"""Phase-2 end-to-end smoke test.

A compact but meaningful smoke test that:
1. Loads a toy task
2. Runs a tiny batch with fake client and different profile modes
3. Builds rollout records from trajectories
4. Exports them
5. Verifies final outputs are structurally valid and deterministic

This is not a comprehensive test suite — it's a quick sanity check
that the full phase-2 pipeline doesn't crash and produces valid output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.env.task import CodingTask
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.rl.export import export_batch_rollouts, read_rollouts_jsonl
from pycodeagent.rl.slime_rollout import trajectory_to_slime_rollout
from pycodeagent.tools.bootstrap import build_base_tool_runtime
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.runtime import ToolRuntime
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.trajectory.schema import RunStatus, Trajectory
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "phase2_smoke"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _make_minimal_task(workspace: Path) -> CodingTask:
    """Create a minimal task for smoke testing."""
    return CodingTask(
        task_id="smoke_test_task",
        repo_path=workspace,
        prompt="Fix the bug in the code.",
        test_command="echo 'no tests'",
        max_turns=2,
    )


def _make_fake_responses() -> list[str]:
    """Create fake LLM responses that trigger tool calls then finish."""
    return [
        # First response: call finish immediately
        """<assistant>
I will complete the task.
</assistant>
<|tool|>
{"id": "call_finish", "name": "finish", "arguments": {"answer": "Task completed"}}
<|end|>
""",
    ]


class TestPhase2SmokeEndToEnd:
    """Minimal end-to-end smoke test of the phase-2 pipeline."""

    def test_smoke_pipeline_runs_without_crash(self):
        """The full pipeline should run without crashing."""
        output_dir = _get_test_dir()
        workspace = output_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        # Create a minimal file for the task
        (workspace / "main.py").write_text("print('hello')\n")

        try:
            # Create task
            task = _make_minimal_task(workspace)

            # Create tool runtime
            registry, profile, runtime = build_base_tool_runtime()

            # Create fake client
            responses = _make_fake_responses()
            client = FakeLLMClient(responses)

            # Create context
            ctx = ToolContext(workspace_root=workspace, task=task)

            # Run agent manually (not through run_coding_task to avoid verifier)
            from pycodeagent.agent.runner import run_agent_task

            trajectory = run_agent_task(task, client, runtime, profile, ctx)

            # Build rollout
            rollout = trajectory_to_slime_rollout(trajectory)

            # Export
            jsonl_path = export_batch_rollouts(output_dir, [rollout])

            # Verify output exists
            assert jsonl_path.exists()
            assert (output_dir / "rollout_summary.json").exists()

        finally:
            _cleanup(output_dir)

    def test_smoke_pipeline_produces_valid_rollout(self):
        """Pipeline should produce structurally valid rollouts."""
        output_dir = _get_test_dir()
        workspace = output_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "main.py").write_text("print('hello')\n")

        try:
            task = _make_minimal_task(workspace)
            registry, profile, runtime = build_base_tool_runtime()
            client = FakeLLMClient(_make_fake_responses())
            ctx = ToolContext(workspace_root=workspace, task=task)

            from pycodeagent.agent.runner import run_agent_task

            trajectory = run_agent_task(task, client, runtime, profile, ctx)
            rollout = trajectory_to_slime_rollout(trajectory)

            # Verify rollout structure
            assert rollout.task_id == task.task_id
            assert rollout.tool_profile_id == profile.profile_id
            assert len(rollout.text) > 0
            assert len(rollout.character_mask) == len(rollout.text)
            assert len(rollout.segments) > 0
            assert rollout.total_char_count == len(rollout.text)

        finally:
            _cleanup(output_dir)

    def test_smoke_pipeline_with_mutated_profile(self):
        """Pipeline should work with mutated profiles."""
        output_dir = _get_test_dir()
        workspace = output_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "main.py").write_text("print('hello')\n")

        try:
            task = _make_minimal_task(workspace)
            registry, _, runtime = build_base_tool_runtime()

            # Use schema_only profile
            sampler = ToolProfileSampler(seed=0)
            profile = sampler.sample("schema_only")

            # Create response that uses mutated tool name
            # Find the finish tool's exposed name
            finish_exposed = None
            for tool in profile.tools:
                if tool.canonical_name == "finish":
                    finish_exposed = tool.exposed_name
                    break

            # Create response with correct exposed name
            response = f"""<assistant>
Completing task.
</assistant>
<|tool|>
{{"id": "call_finish", "name": "{finish_exposed}", "arguments": {{"answer": "Done"}}}}
<|end|>
"""
            client = FakeLLMClient([response])
            ctx = ToolContext(workspace_root=workspace, task=task)

            from pycodeagent.agent.runner import run_agent_task

            trajectory = run_agent_task(task, client, runtime, profile, ctx)
            rollout = trajectory_to_slime_rollout(trajectory)

            # Verify rollout is valid
            assert rollout.task_id == task.task_id
            assert len(rollout.text) > 0
            assert rollout.tool_profile_id == profile.profile_id

        finally:
            _cleanup(output_dir)


class TestPhase2SmokeBatch:
    """Smoke test for batch execution."""

    def test_tiny_batch_produces_valid_outputs(self):
        """A tiny batch should produce valid batch outputs."""
        output_dir = _get_test_dir()
        workspace = output_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "main.py").write_text("print('hello')\n")

        try:
            task = _make_minimal_task(workspace)
            registry, profile, runtime = build_base_tool_runtime()
            client = FakeLLMClient(_make_fake_responses())
            ctx = ToolContext(workspace_root=workspace, task=task)

            from pycodeagent.agent.runner import run_agent_task

            # Run 3 trajectories
            trajectories = []
            for i in range(3):
                client = FakeLLMClient(_make_fake_responses())
                task_i = CodingTask(
                    task_id=f"task_{i}",
                    repo_path=workspace,
                    prompt=f"Task {i}",
                    test_command="echo ok",
                    max_turns=2,
                )
                traj = run_agent_task(task_i, client, runtime, profile, ctx)
                trajectories.append(traj)

            # Build rollouts
            rollouts = [trajectory_to_slime_rollout(t) for t in trajectories]

            # Export
            jsonl_path = export_batch_rollouts(output_dir, rollouts)

            # Verify
            records = read_rollouts_jsonl(jsonl_path)
            assert len(records) == 3
            for i, rec in enumerate(records):
                assert rec["task_id"] == f"task_{i}"

            # Verify summary
            summary = json.loads((output_dir / "rollout_summary.json").read_text())
            assert summary["total_count"] == 3

        finally:
            _cleanup(output_dir)


class TestPhase2SmokeDeterminism:
    """Smoke test for determinism."""

    def test_same_input_same_output(self):
        """Same input should produce same output."""
        output_dir = _get_test_dir()
        workspace = output_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "main.py").write_text("print('hello')\n")

        try:
            task = _make_minimal_task(workspace)
            registry, profile, runtime = build_base_tool_runtime()
            ctx = ToolContext(workspace_root=workspace, task=task)

            from pycodeagent.agent.runner import run_agent_task

            # Run twice with same client responses
            responses = _make_fake_responses()

            client1 = FakeLLMClient(responses)
            traj1 = run_agent_task(task, client1, runtime, profile, ctx)
            rollout1 = trajectory_to_slime_rollout(traj1)

            client2 = FakeLLMClient(responses)
            traj2 = run_agent_task(task, client2, runtime, profile, ctx)
            rollout2 = trajectory_to_slime_rollout(traj2)

            # Should be identical
            assert rollout1.text == rollout2.text
            assert rollout1.character_mask == rollout2.character_mask
            assert rollout1.model_dump_json() == rollout2.model_dump_json()

        finally:
            _cleanup(output_dir)

    def test_profile_sampling_deterministic(self):
        """Profile sampling with same seed should produce same profile."""
        sampler1 = ToolProfileSampler(seed=42)
        sampler2 = ToolProfileSampler(seed=42)

        for mode in ["base", "name_only", "schema_only"]:
            p1 = sampler1.sample(mode)
            p2 = sampler2.sample(mode)
            assert p1.profile_id == p2.profile_id
            assert [t.exposed_name for t in p1.tools] == [t.exposed_name for t in p2.tools]


class TestPhase2SmokeCrossModuleContract:
    """Smoke tests for cross-module contracts."""

    def test_trajectory_repo_and_diff_preserved_in_rollout(self):
        """Trajectory repo and final_diff should be preserved in rollout metadata."""
        output_dir = _get_test_dir()
        workspace = output_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "main.py").write_text("print('hello')\n")

        try:
            task = _make_minimal_task(workspace)
            registry, profile, runtime = build_base_tool_runtime()
            client = FakeLLMClient(_make_fake_responses())
            ctx = ToolContext(workspace_root=workspace, task=task)

            from pycodeagent.agent.runner import run_agent_task

            trajectory = run_agent_task(task, client, runtime, profile, ctx)

            # Set final_diff to test preservation
            trajectory.final_diff = "--- a/main.py\n+++ b/main.py\n@@\n-hello\n+world"

            rollout = trajectory_to_slime_rollout(trajectory)

            # Check repo and final_diff are in metadata
            assert "repo" in rollout.metadata
            assert "final_diff" in rollout.metadata
            assert rollout.metadata["repo"] == trajectory.repo
            assert rollout.metadata["final_diff"] == trajectory.final_diff

        finally:
            _cleanup(output_dir)

    def test_tool_profile_id_preserved(self):
        """Tool profile ID should be preserved throughout pipeline."""
        output_dir = _get_test_dir()
        workspace = output_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "main.py").write_text("print('hello')\n")

        try:
            task = _make_minimal_task(workspace)
            registry, _, runtime = build_base_tool_runtime()

            # Use a specific profile
            sampler = ToolProfileSampler(seed=123)
            profile = sampler.sample("schema_only")

            # Find finish tool
            finish_exposed = None
            for tool in profile.tools:
                if tool.canonical_name == "finish":
                    finish_exposed = tool.exposed_name
                    break

            response = f"""<assistant>
Done.
</assistant>
<|tool|>
{{"id": "c1", "name": "{finish_exposed}", "arguments": {{"answer": "ok"}}}}
<|end|>
"""
            client = FakeLLMClient([response])
            ctx = ToolContext(workspace_root=workspace, task=task)

            from pycodeagent.agent.runner import run_agent_task

            trajectory = run_agent_task(task, client, runtime, profile, ctx)
            rollout = trajectory_to_slime_rollout(trajectory)

            # Profile ID should be preserved
            assert trajectory.tool_profile_id == profile.profile_id
            assert rollout.tool_profile_id == profile.profile_id

        finally:
            _cleanup(output_dir)


class TestPhase2SmokeToyDataset:
    """Smoke test using actual toy dataset."""

    def test_can_load_toy_tasks(self):
        """Should be able to load toy tasks from dataset."""
        dataset_path = Path(__file__).parent.parent / "datasets" / "tasks" / "toy_tasks.jsonl"
        if not dataset_path.exists():
            pytest.skip("toy_tasks.jsonl not found")

        tasks = CodingTask.from_jsonl(dataset_path)
        assert len(tasks) > 0

        # Each task should have required fields
        for task in tasks:
            assert task.task_id
            assert task.repo_path
            assert task.prompt

    def test_toy_task_rollout_pipeline(self):
        """Should be able to process a toy task through the pipeline."""
        dataset_path = Path(__file__).parent.parent / "datasets" / "tasks" / "toy_tasks.jsonl"
        if not dataset_path.exists():
            pytest.skip("toy_tasks.jsonl not found")

        output_dir = _get_test_dir()

        try:
            tasks = CodingTask.from_jsonl(dataset_path)
            task = tasks[0]  # Just use first task

            # Ensure workspace exists
            if not task.repo_path.exists():
                pytest.skip(f"Task repo not found: {task.repo_path}")

            # Create a simple workspace copy for testing
            workspace = output_dir / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copytree(task.repo_path, workspace, dirs_exist_ok=True)

            # Create modified task pointing to workspace
            test_task = CodingTask(
                task_id=task.task_id,
                repo_path=workspace,
                prompt=task.prompt,
                test_command="echo ok",
                max_turns=2,
            )

            registry, profile, runtime = build_base_tool_runtime()
            client = FakeLLMClient(_make_fake_responses())
            ctx = ToolContext(workspace_root=workspace, task=test_task)

            from pycodeagent.agent.runner import run_agent_task

            trajectory = run_agent_task(test_task, client, runtime, profile, ctx)
            rollout = trajectory_to_slime_rollout(trajectory)

            # Verify basic structure
            assert rollout.task_id == task.task_id
            assert len(rollout.text) > 0

        finally:
            _cleanup(output_dir)
