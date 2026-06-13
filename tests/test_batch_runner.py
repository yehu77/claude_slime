"""Tests for batch runner.

Uses a fake LLM client and toy tasks to verify batch execution,
summary extraction, and output artifacts without requiring a real model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pycodeagent.eval.batch_runner import BatchResult, BatchRunner, RunSummary, run_batch
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.trajectory.schema import (
    Message,
    Role,
    RunStatus,
    ToolCall,
    ToolObservation,
    ToolResult,
    Trajectory,
    VerifyResult,
)


_TEST_NAMESPACE = "batch_runner"


def _get_unique_test_dir() -> Path:
    """Get a unique test directory for the current test."""
    return make_unique_test_dir(_TEST_NAMESPACE)


def _setup_test_dir() -> Path:
    """Create a unique test directory and return it."""
    return _get_unique_test_dir()


def _cleanup_test_dir(path: Path) -> None:
    """Clean up a test directory."""
    cleanup_test_path(path)


# --- Fake LLM Client ---


class FakeLLMClient:
    """LLM client that returns a predefined sequence of responses.

    Each call to generate returns the next response in the sequence.
    The response triggers a 'finish' tool call to end the loop immediately.
    """

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.responses = responses or []
        self._call_count = 0

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if self._call_count < len(self.responses):
            resp = self.responses[self._call_count]
            self._call_count += 1
            return resp
        # Default: finish immediately
        return {
            "content": "Task complete.",
            "tool_calls": [
                {"id": "call_finish", "name": "finish", "arguments": {"summary": "done"}}
            ],
        }


def _make_completed_trajectory(
    task_id: str = "test_task",
    passed: bool = True,
    reward: float = 1.0,
    turns: int = 2,
    tool_calls_count: int = 1,
    has_patch: bool = False,
    apply_patch_ok: bool | None = None,
) -> Trajectory:
    """Build a completed trajectory for testing _extract_summary.

    Args:
        apply_patch_ok: If None, no apply_patch observation. If True/False,
            add an apply_patch observation with that result.
    """
    messages = [
        Message(role=Role.SYSTEM, content="system prompt"),
        Message(role=Role.USER, content="Fix the bug"),
    ]
    for _ in range(turns):
        messages.append(Message(role=Role.ASSISTANT, content="Working on it..."))

    tool_calls = [
        ToolCall(id=f"tc_{i}", name="finish", arguments={"summary": "done"})
        for i in range(tool_calls_count)
    ]

    observations = [
        ToolObservation(
            call=tc,
            result=ToolResult(ok=True, content="Finished"),
            tool_name="finish",
        )
        for tc in tool_calls
    ]

    # Add apply_patch observation if requested
    if apply_patch_ok is not None:
        patch_call = ToolCall(
            id="tc_patch",
            name="apply_patch",
            arguments={"diff": "--- a/f.py\n+++ b/f.py\n"},
            canonical_name="apply_patch",
        )
        patch_result = ToolResult(
            ok=apply_patch_ok,
            content="Patch applied successfully" if apply_patch_ok else "Patch failed",
            is_error=not apply_patch_ok,
            metadata={} if apply_patch_ok else {"error_type": "patch_apply"},
        )
        observations.append(ToolObservation(
            call=patch_call,
            result=patch_result,
            tool_name="apply_patch",
            canonical_name="apply_patch",
        ))

    return Trajectory(
        task_id=task_id,
        repo="examples/test_repo",
        tool_profile_id="base",
        messages=messages,
        tool_calls=tool_calls,
        observations=observations,
        final_diff="--- a/file.py\n+++ b/file.py\n" if has_patch else "",
        verifier=VerifyResult(passed=passed, score=1.0 if passed else 0.0),
        reward=reward,
        status=RunStatus.COMPLETED,
    )


def _make_error_trajectory(
    task_id: str = "test_task",
    failure_type: str = "error",
) -> Trajectory:
    """Build an error trajectory for testing."""
    status_map = {
        "error": RunStatus.ERROR,
        "timeout": RunStatus.TIMEOUT,
        "failed": RunStatus.FAILED,
    }
    return Trajectory(
        task_id=task_id,
        repo="examples/test_repo",
        tool_profile_id="base",
        status=status_map.get(failure_type, RunStatus.ERROR),
        metadata={"setup_error": "something went wrong"} if failure_type == "error" else {},
    )


def _make_completed_trajectory_for_profile(
    *,
    task_id: str,
    profile_mode: str,
    profile_seed: int,
    passed: bool = True,
    reward: float = 1.0,
) -> Trajectory:
    """Build a completed trajectory aligned with the expected sampled profile id."""
    expected_profile = ToolProfileSampler(seed=profile_seed).sample(profile_mode)
    return _make_completed_trajectory(
        task_id=task_id,
        passed=passed,
        reward=reward,
    ).model_copy(update={"tool_profile_id": expected_profile.profile_id})


def _make_parse_error_trajectory(
    task_id: str = "test_task",
) -> Trajectory:
    """Build a trajectory with parse errors in stop_detail."""
    return Trajectory(
        task_id=task_id,
        repo="examples/test_repo",
        tool_profile_id="base",
        status=RunStatus.ERROR,
        metadata={"stop_detail": "Parse errors: ['Invalid JSON in tool call: Expecting value']"},
    )


def _make_schema_error_trajectory(
    task_id: str = "test_task",
    schema_error_type: str = "argument_mapping",
) -> Trajectory:
    """Build a trajectory with schema/argument mapping errors."""
    tool_call = ToolCall(id="tc_1", name="open_source", arguments={"target": "f.py"})
    schema_result = ToolResult(
        ok=False,
        content="Missing required argument: path",
        is_error=True,
        metadata={"error_type": schema_error_type},
    )
    return Trajectory(
        task_id=task_id,
        repo="examples/test_repo",
        tool_profile_id="base",
        messages=[Message(role=Role.ASSISTANT, content="trying...")],
        tool_calls=[tool_call],
        observations=[ToolObservation(
            call=tool_call,
            result=schema_result,
            tool_name="open_source",
        )],
        verifier=VerifyResult(passed=False, score=0.0),
        reward=0.0,
        status=RunStatus.COMPLETED,
    )


def _write_tasks_jsonl(path: Path, task_ids: list[str]) -> None:
    """Write a minimal tasks JSONL file."""
    lines = []
    for tid in task_ids:
        lines.append(json.dumps({
            "task_id": tid,
            "repo_path": "examples/test_repo",
            "prompt": "Fix the bug",
            "test_command": "pytest -q",
            "max_turns": 10,
            "allowed_files": ["*.py"],
            "forbidden_files": [],
            "metadata": {},
        }))
    path.write_text("\n".join(lines) + "\n")


# --- Test RunSummary ---


class TestRunSummary:
    """Tests for RunSummary dataclass."""

    def test_creation(self):
        """Should create with required fields."""
        s = RunSummary(
            task_id="t1",
            profile_id="base",
            status="completed",
            reward=1.0,
            passed=True,
            turns=5,
            tool_calls=10,
            output_dir="runs/t1",
        )
        assert s.task_id == "t1"
        assert s.passed is True
        assert s.failure_reason == ""
        assert s.metadata == {}

    def test_with_optional_fields(self):
        """Should accept optional fields."""
        s = RunSummary(
            task_id="t1",
            profile_id="base",
            status="error",
            reward=0.0,
            passed=False,
            turns=0,
            tool_calls=0,
            output_dir="runs/t1",
            failure_reason="timeout",
            metadata={"has_patch": False},
        )
        assert s.failure_reason == "timeout"
        assert s.metadata["has_patch"] is False


# --- Test BatchResult ---


class TestBatchResult:
    """Tests for BatchResult dataclass."""

    def test_creation(self):
        """Should create with all fields."""
        summaries = [RunSummary(
            task_id="t1", profile_id="base", status="completed",
            reward=1.0, passed=True, turns=5, tool_calls=10, output_dir="runs/t1",
        )]
        result = BatchResult(
            summaries=summaries,
            metrics={"pass_at_1": 1.0},
            output_dir="runs/batch_001",
            num_tasks=1,
            num_profiles=1,
            total_runs=1,
        )
        assert result.total_runs == 1
        assert result.metrics["pass_at_1"] == 1.0


# --- Test _extract_summary ---


class TestExtractSummary:
    """Tests for BatchRunner._extract_summary."""

    def setup_method(self):
        self.runner = BatchRunner(client_factory=lambda: FakeLLMClient())

    def test_completed_passed(self):
        """Should extract correct summary for a completed, passing trajectory."""
        traj = _make_completed_trajectory(passed=True, reward=1.0, turns=3, tool_calls_count=2)
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.task_id == "t1"
        assert summary.profile_id == "base"
        assert summary.status == "completed"
        assert summary.reward == 1.0
        assert summary.passed is True
        assert summary.turns == 3
        assert summary.tool_calls == 2
        assert summary.failure_reason == ""

    def test_completed_failed_verification(self):
        """Should set failure_reason to verifier_failed when verifier fails."""
        traj = _make_completed_trajectory(passed=False, reward=0.0)
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.passed is False
        assert summary.failure_reason == "verifier_failed"

    def test_error_trajectory(self):
        """Should set failure_reason from status for error trajectory."""
        traj = _make_error_trajectory(failure_type="error")
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.status == "error"
        # setup_error takes priority over generic status
        assert summary.failure_reason == "something went wrong"

    def test_timeout_trajectory(self):
        """Should set failure_reason from status for timeout."""
        traj = _make_error_trajectory(failure_type="timeout")
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.status == "timeout"
        assert summary.failure_reason == "timeout"

    def test_metadata_extracted(self):
        """Should extract metadata correctly."""
        traj = _make_completed_trajectory(passed=True, has_patch=True)
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.metadata["has_patch"] is True
        assert summary.metadata["verifier_score"] == 1.0
        assert summary.metadata["parse_errors"] == 0

    def test_no_verifier(self):
        """Should handle trajectory with no verifier."""
        traj = _make_completed_trajectory()
        traj.verifier = None
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.passed is False
        assert summary.metadata["verifier_score"] == 0.0

    def test_setup_error_in_failure_reason(self):
        """Should prefer setup_error from metadata as failure_reason."""
        traj = _make_completed_trajectory()
        traj.metadata["setup_error"] = "workspace_copy_failed"
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.failure_reason == "workspace_copy_failed"

    def test_setup_error_overrides_generic_error(self):
        """setup_error should take priority over generic status like 'error'."""
        traj = _make_error_trajectory(failure_type="error")
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        # The error trajectory has setup_error="something went wrong"
        # This should appear as failure_reason, not just "error"
        assert summary.failure_reason == "something went wrong"
        assert summary.failure_reason != "error"

    def test_parse_error_in_failure_reason(self):
        """Should detect parse_error from stop_detail and set failure_reason."""
        traj = _make_parse_error_trajectory()
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.failure_reason == "parse_error"
        assert summary.metadata["parse_errors"] == 1

    def test_parse_error_in_metadata_count(self):
        """Should detect parse_errors from trajectory metadata."""
        traj = _make_completed_trajectory()
        traj.metadata["parse_errors"] = 2
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.metadata["parse_errors"] == 1
        assert summary.failure_reason == "parse_error"

    def test_patch_metadata(self):
        """Should correctly set has_patch from final_diff."""
        traj_with_patch = _make_completed_trajectory(has_patch=True)
        summary_with = self.runner._extract_summary(traj_with_patch, "t1", "base", "runs/t1")
        assert summary_with.metadata["has_patch"] is True

        traj_no_patch = _make_completed_trajectory(has_patch=False)
        summary_without = self.runner._extract_summary(traj_no_patch, "t1", "base", "runs/t1")
        assert summary_without.metadata["has_patch"] is False

    def test_apply_patch_success(self):
        """Should detect successful apply_patch from observations."""
        traj = _make_completed_trajectory(apply_patch_ok=True)
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.metadata["apply_patch_attempted"] is True
        assert summary.metadata["apply_patch_success"] is True

    def test_apply_patch_failure(self):
        """Should detect failed apply_patch from observations."""
        traj = _make_completed_trajectory(apply_patch_ok=False)
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.metadata["apply_patch_attempted"] is True
        assert summary.metadata["apply_patch_success"] is False

    def test_no_apply_patch(self):
        """No apply_patch call should show not attempted."""
        traj = _make_completed_trajectory(apply_patch_ok=None)
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.metadata["apply_patch_attempted"] is False
        assert summary.metadata["apply_patch_success"] is False

    def test_schema_errors_counted(self):
        """Should count schema/argument mapping errors from observations."""
        traj = _make_schema_error_trajectory(schema_error_type="argument_mapping")
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.metadata["schema_errors"] == 1

    def test_schema_errors_unexpected_counted(self):
        """Should count argument_mapping_unexpected errors."""
        traj = _make_schema_error_trajectory(schema_error_type="argument_mapping_unexpected")
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.metadata["schema_errors"] == 1

    def test_other_errors_not_counted_as_schema(self):
        """Handler exceptions should not count as schema errors."""
        traj = _make_schema_error_trajectory(schema_error_type="handler_exception")
        summary = self.runner._extract_summary(traj, "t1", "base", "runs/t1")

        assert summary.metadata["schema_errors"] == 0
        # But still counted as tool_errors
        assert summary.metadata["tool_errors"] == 1


# --- Test run_batch convenience function ---


class TestRunBatchFunction:
    """Tests for run_batch convenience function."""

    def test_creates_batch_runner(self):
        """run_batch should create a BatchRunner and call run()."""
        # Just verify it's callable with expected signature
        import inspect
        sig = inspect.signature(run_batch)
        param_names = list(sig.parameters)
        assert "tasks_path" in param_names
        assert "profile_modes" in param_names
        assert "seed" in param_names
        assert "output_dir" in param_names
        assert "client_factory" in param_names


# --- Integration-style tests using mocked run_coding_task ---


class TestBatchRunnerWithMockedTask:
    """Tests for BatchRunner.run with mocked run_coding_task."""

    def test_single_task_single_profile(self, monkeypatch):
        """Should run 1 task × 1 profile = 1 run."""
        import pycodeagent.env.coding_env as coding_env

        captured_kwargs = []

        def mock_run_coding_task(
            task,
            client,
            output_dir,
            *,
            profile=None,
            runtime=None,
            profile_mode=None,
            profile_seed=0,
        ):
            captured_kwargs.append(
                {
                    "profile": profile,
                    "runtime": runtime,
                    "profile_mode": profile_mode,
                    "profile_seed": profile_seed,
                }
            )
            return _make_completed_trajectory_for_profile(
                task_id="t1",
                profile_mode=profile_mode,
                profile_seed=profile_seed,
                passed=True,
                reward=1.0,
            )

        monkeypatch.setattr(coding_env, "run_coding_task", mock_run_coding_task)

        test_dir = _setup_test_dir()
        try:
            tasks_path = test_dir / "tasks.jsonl"
            _write_tasks_jsonl(tasks_path, ["t1"])

            output_dir = test_dir / "batch_output"
            runner = BatchRunner(client_factory=lambda: FakeLLMClient())
            result = runner.run(
                tasks_path=tasks_path,
                profile_modes=["base"],
                seed=42,
                output_dir=output_dir,
            )

            assert result.total_runs == 1
            assert result.num_tasks == 1
            assert result.num_profiles == 1
            assert len(result.summaries) == 1
            assert result.summaries[0].passed is True
            assert len(captured_kwargs) == 1
            assert captured_kwargs[0]["profile"] is None
            assert captured_kwargs[0]["runtime"] is not None
            assert captured_kwargs[0]["profile_mode"] == "base"
            assert captured_kwargs[0]["profile_seed"] == 42
        finally:
            _cleanup_test_dir(test_dir)

    def test_single_task_multiple_profiles(self, monkeypatch):
        """Should run 1 task × 2 profiles = 2 runs."""
        import pycodeagent.env.coding_env as coding_env

        def mock_run_coding_task(
            task,
            client,
            output_dir,
            *,
            profile=None,
            runtime=None,
            profile_mode=None,
            profile_seed=0,
        ):
            return _make_completed_trajectory_for_profile(
                task_id="t1",
                profile_mode=profile_mode,
                profile_seed=profile_seed,
                passed=True,
            )

        monkeypatch.setattr(coding_env, "run_coding_task", mock_run_coding_task)

        test_dir = _setup_test_dir()
        try:
            tasks_path = test_dir / "tasks.jsonl"
            _write_tasks_jsonl(tasks_path, ["t1"])

            output_dir = test_dir / "batch_output"
            runner = BatchRunner(client_factory=lambda: FakeLLMClient())
            result = runner.run(
                tasks_path=tasks_path,
                profile_modes=["base", "schema_only"],
                seed=42,
                output_dir=output_dir,
            )

            assert result.total_runs == 2
            assert result.num_profiles == 2
        finally:
            _cleanup_test_dir(test_dir)

    def test_multiple_tasks_single_profile(self, monkeypatch):
        """Should run 2 tasks × 1 profile = 2 runs."""
        import pycodeagent.env.coding_env as coding_env

        def mock_run_coding_task(
            task,
            client,
            output_dir,
            *,
            profile=None,
            runtime=None,
            profile_mode=None,
            profile_seed=0,
        ):
            return _make_completed_trajectory_for_profile(
                task_id=task.task_id,
                profile_mode=profile_mode,
                profile_seed=profile_seed,
            )

        monkeypatch.setattr(coding_env, "run_coding_task", mock_run_coding_task)

        test_dir = _setup_test_dir()
        try:
            tasks_path = test_dir / "tasks.jsonl"
            _write_tasks_jsonl(tasks_path, ["t0", "t1"])

            output_dir = test_dir / "batch_output"
            runner = BatchRunner(client_factory=lambda: FakeLLMClient())
            result = runner.run(
                tasks_path=tasks_path,
                profile_modes=["base"],
                seed=42,
                output_dir=output_dir,
            )

            assert result.total_runs == 2
            assert result.num_tasks == 2
        finally:
            _cleanup_test_dir(test_dir)

    def test_max_tasks_limit(self, monkeypatch):
        """Should respect max_tasks limit."""
        import pycodeagent.env.coding_env as coding_env

        def mock_run_coding_task(
            task,
            client,
            output_dir,
            *,
            profile=None,
            runtime=None,
            profile_mode=None,
            profile_seed=0,
        ):
            return _make_completed_trajectory_for_profile(
                task_id=task.task_id,
                profile_mode=profile_mode,
                profile_seed=profile_seed,
            )

        monkeypatch.setattr(coding_env, "run_coding_task", mock_run_coding_task)

        test_dir = _setup_test_dir()
        try:
            tasks_path = test_dir / "tasks.jsonl"
            _write_tasks_jsonl(tasks_path, [f"t{i}" for i in range(5)])

            output_dir = test_dir / "batch_output"
            runner = BatchRunner(client_factory=lambda: FakeLLMClient())
            result = runner.run(
                tasks_path=tasks_path,
                profile_modes=["base"],
                seed=42,
                output_dir=output_dir,
                max_tasks=2,
            )

            assert result.num_tasks == 2
            assert result.total_runs == 2
        finally:
            _cleanup_test_dir(test_dir)

    def test_output_artifacts_created(self, monkeypatch):
        """Should create report files in output directory."""
        import pycodeagent.env.coding_env as coding_env

        def mock_run_coding_task(
            task,
            client,
            output_dir,
            *,
            profile=None,
            runtime=None,
            profile_mode=None,
            profile_seed=0,
        ):
            return _make_completed_trajectory_for_profile(
                task_id=task.task_id,
                profile_mode=profile_mode,
                profile_seed=profile_seed,
            )

        monkeypatch.setattr(coding_env, "run_coding_task", mock_run_coding_task)

        test_dir = _setup_test_dir()
        try:
            tasks_path = test_dir / "tasks.jsonl"
            _write_tasks_jsonl(tasks_path, ["t1"])

            output_dir = test_dir / "batch_output"
            runner = BatchRunner(client_factory=lambda: FakeLLMClient())
            runner.run(
                tasks_path=tasks_path,
                profile_modes=["base"],
                seed=42,
                output_dir=output_dir,
            )

            assert (output_dir / "summary.json").exists()
            assert (output_dir / "runs.jsonl").exists()
            assert (output_dir / "failed_cases.jsonl").exists()
        finally:
            _cleanup_test_dir(test_dir)

    def test_metrics_in_result(self, monkeypatch):
        """Should compute and include metrics in result."""
        import pycodeagent.env.coding_env as coding_env

        def mock_run_coding_task(
            task,
            client,
            output_dir,
            *,
            profile=None,
            runtime=None,
            profile_mode=None,
            profile_seed=0,
        ):
            return _make_completed_trajectory_for_profile(
                task_id=task.task_id,
                profile_mode=profile_mode,
                profile_seed=profile_seed,
                passed=True,
                reward=1.0,
            )

        monkeypatch.setattr(coding_env, "run_coding_task", mock_run_coding_task)

        test_dir = _setup_test_dir()
        try:
            tasks_path = test_dir / "tasks.jsonl"
            _write_tasks_jsonl(tasks_path, ["t1"])

            output_dir = test_dir / "batch_output"
            runner = BatchRunner(client_factory=lambda: FakeLLMClient())
            result = runner.run(
                tasks_path=tasks_path,
                profile_modes=["base"],
                seed=42,
                output_dir=output_dir,
            )

            assert "pass_at_1" in result.metrics
            assert "avg_reward" in result.metrics
            assert result.metrics["pass_at_1"] == 1.0
        finally:
            _cleanup_test_dir(test_dir)

    def test_client_factory_called_per_run(self, monkeypatch):
        """Should create a fresh client for each run."""
        import pycodeagent.env.coding_env as coding_env

        call_count = 0

        def client_factory():
            nonlocal call_count
            call_count += 1
            return FakeLLMClient()

        def mock_run_coding_task(
            task,
            client,
            output_dir,
            *,
            profile=None,
            runtime=None,
            profile_mode=None,
            profile_seed=0,
        ):
            return _make_completed_trajectory_for_profile(
                task_id=task.task_id,
                profile_mode=profile_mode,
                profile_seed=profile_seed,
            )

        monkeypatch.setattr(coding_env, "run_coding_task", mock_run_coding_task)

        test_dir = _setup_test_dir()
        try:
            tasks_path = test_dir / "tasks.jsonl"
            _write_tasks_jsonl(tasks_path, ["t0", "t1"])

            output_dir = test_dir / "batch_output"
            runner = BatchRunner(client_factory=client_factory)
            runner.run(
                tasks_path=tasks_path,
                profile_modes=["base"],
                seed=42,
                output_dir=output_dir,
            )

            assert call_count == 2
        finally:
            _cleanup_test_dir(test_dir)

    def test_run_dirs_created(self, monkeypatch):
        """Should create output directories for each run."""
        import pycodeagent.env.coding_env as coding_env

        def mock_run_coding_task(
            task,
            client,
            output_dir,
            *,
            profile=None,
            runtime=None,
            profile_mode=None,
            profile_seed=0,
        ):
            return _make_completed_trajectory_for_profile(
                task_id=task.task_id,
                profile_mode=profile_mode,
                profile_seed=profile_seed,
            )

        monkeypatch.setattr(coding_env, "run_coding_task", mock_run_coding_task)

        test_dir = _setup_test_dir()
        try:
            tasks_path = test_dir / "tasks.jsonl"
            _write_tasks_jsonl(tasks_path, ["t1"])

            output_dir = test_dir / "batch_output"
            runner = BatchRunner(client_factory=lambda: FakeLLMClient())
            result = runner.run(
                tasks_path=tasks_path,
                profile_modes=["base"],
                seed=42,
                output_dir=output_dir,
            )

            # Check that run dir path is in the summary
            assert result.summaries[0].output_dir
        finally:
            _cleanup_test_dir(test_dir)
