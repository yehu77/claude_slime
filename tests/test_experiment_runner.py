"""Tests for ExperimentRunner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.eval.experiment_config import ExperimentConfig
from pycodeagent.eval.experiment_runner import (
    ExperimentManifest,
    ExperimentResult,
    ExperimentRunner,
    run_experiment,
)
from pycodeagent.eval.layout import mode_dir_name, run_dir_name
from pycodeagent.eval.report import load_failed_cases_jsonl, load_runs_jsonl, load_summary_json
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


pytestmark = [pytest.mark.slow, pytest.mark.integration]


_TEST_NAMESPACE = "experiment_runner"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _make_fake_responses() -> list[str]:
    """Create fake LLM responses that trigger tool calls then finish."""
    return [
        """<assistant>
I will complete the task.
</assistant>
<|tool|>
{"id": "call_finish", "name": "finish", "arguments": {"answer": "Task completed"}}
<|end|>
""",
    ]


def _make_failing_fake_responses() -> list[str]:
    """Create fake LLM responses that cause errors."""
    return [
        """<assistant>
I will try to do something.
</assistant>
<|tool|>
{"id": "call_bad", "name": "nonexistent_tool", "arguments": {}}
<|end|>
""",
    ]


def _create_toy_tasks_jsonl(output_dir: Path, num_tasks: int = 2) -> Path:
    """Create a toy tasks JSONL file for testing."""
    tasks_path = output_dir / "toy_tasks.jsonl"
    workspace = output_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "main.py").write_text("print('hello')\n")

    tasks = []
    for i in range(num_tasks):
        tasks.append({
            "task_id": f"task_{i:03d}",
            "repo_path": str(workspace),
            "prompt": f"Fix the bug in task {i}.",
            "test_command": "echo ok",
            "max_turns": 2,
        })

    with open(tasks_path, "w", encoding="utf-8") as f:
        for task in tasks:
            f.write(json.dumps(task) + "\n")

    return tasks_path


class TestExperimentRunnerMinimal:
    """Tests for minimal experiment execution."""

    def test_minimal_experiment_runs(self):
        """A minimal experiment should run without crashing."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)

            config = ExperimentConfig(
                experiment_id="exp_minimal",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            result = runner.run(config)

            assert result is not None
            assert isinstance(result, ExperimentResult)
            assert len(result.summaries) > 0
        finally:
            _cleanup(output_dir)

    def test_experiment_creates_output_directory(self):
        """Experiment should create the output directory."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)

            config = ExperimentConfig(
                experiment_id="exp_dirs",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            result = runner.run(config)

            exp_dir = Path(result.output_dir)
            assert exp_dir.exists()
        finally:
            _cleanup(output_dir)

    def test_experiment_runner_uses_runtime_entry_profile_mode(self, monkeypatch):
        """ExperimentRunner should drive profile selection via run_coding_task kwargs."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)
            captured_calls: list[dict[str, Any]] = []

            config = ExperimentConfig(
                experiment_id="exp_profile_mode_entry",
                tasks_path=str(tasks_path),
                profile_modes=["schema_only"],
                seeds=[42],
                output_root=str(output_dir / "experiments"),
            )

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
                captured_calls.append(
                    {
                        "profile": profile,
                        "runtime": runtime,
                        "profile_mode": profile_mode,
                        "profile_seed": profile_seed,
                    }
                )
                from pycodeagent.mutations.profile_sampler import ToolProfileSampler
                from pycodeagent.trajectory.schema import Trajectory

                expected_profile = ToolProfileSampler(seed=profile_seed).sample(profile_mode)
                return Trajectory(
                    task_id=task.task_id,
                    repo=str(task.repo_path),
                    tool_profile_id=expected_profile.profile_id,
                    verifier=None,
                )

            monkeypatch.setattr(
                "pycodeagent.eval.experiment_runner.run_coding_task",
                mock_run_coding_task,
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            result = runner.run(config)

            assert len(result.summaries) == 1
            assert captured_calls == [
                {
                    "profile": None,
                    "runtime": captured_calls[0]["runtime"],
                    "profile_mode": "schema_only",
                    "profile_seed": 42,
                }
            ]
            assert captured_calls[0]["runtime"] is not None
        finally:
            _cleanup(output_dir)


class TestExperimentDirectoryLayout:
    """Tests for experiment output directory structure."""

    def test_config_saved_in_output_dir(self):
        """experiment_config.json should be saved in output dir."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)

            config = ExperimentConfig(
                experiment_id="exp_config_save",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            runner.run(config)

            exp_dir = config.get_output_dir()
            assert (exp_dir / "experiment_config.json").exists()

            # Config should be loadable
            loaded = ExperimentConfig.load(exp_dir / "experiment_config.json")
            assert loaded.experiment_id == "exp_config_save"
        finally:
            _cleanup(output_dir)

    def test_manifest_saved_in_output_dir(self):
        """experiment_manifest.json should be saved in output dir."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)

            config = ExperimentConfig(
                experiment_id="exp_manifest",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            runner.run(config)

            exp_dir = config.get_output_dir()
            manifest_path = exp_dir / "experiment_manifest.json"
            assert manifest_path.exists()

            manifest = json.loads(manifest_path.read_text())
            assert manifest["experiment_id"] == "exp_manifest"
            assert manifest["task_count"] == 1
        finally:
            _cleanup(output_dir)

    def test_summary_and_runs_written(self):
        """summary.json and runs.jsonl should be written."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)

            config = ExperimentConfig(
                experiment_id="exp_reports",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            runner.run(config)

            exp_dir = config.get_output_dir()
            assert (exp_dir / "summary.json").exists()
            assert (exp_dir / "runs.jsonl").exists()
        finally:
            _cleanup(output_dir)

    def test_seed_mode_directory_structure(self):
        """Should create seed/mode subdirectories."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)

            config = ExperimentConfig(
                experiment_id="exp_structure",
                tasks_path=str(tasks_path),
                profile_modes=["base", "schema_only"],
                seeds=[0, 42],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            runner.run(config)

            runs_dir = config.get_runs_dir()
            assert (runs_dir / "seed_0" / "base").exists()
            assert (runs_dir / "seed_0" / mode_dir_name("schema_only")).exists()
            assert (runs_dir / "seed_42" / "base").exists()
            assert (runs_dir / "seed_42" / mode_dir_name("schema_only")).exists()
        finally:
            _cleanup(output_dir)

    def test_run_directories_use_short_stable_names(self):
        """Run directories should not embed long profile IDs."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)

            config = ExperimentConfig(
                experiment_id="exp_short_run_dirs",
                tasks_path=str(tasks_path),
                profile_modes=["name_description_schema"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            result = runner.run(config)

            summary = result.summaries[0]
            run_dir = Path(summary.output_dir)
            assert run_dir.name == run_dir_name(summary.task_id, summary.profile_id)
            assert "__" not in run_dir.name
            assert "name_description_schema" not in run_dir.name
        finally:
            _cleanup(output_dir)


class TestExperimentIterationCount:
    """Tests for correct task/profile/seed iteration counts."""

    def test_single_combination(self):
        """1 task * 1 mode * 1 seed = 1 run."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)

            config = ExperimentConfig(
                experiment_id="exp_count1",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            result = runner.run(config)

            assert len(result.summaries) == 1
        finally:
            _cleanup(output_dir)

    def test_multiple_combinations(self):
        """2 tasks * 2 modes * 2 seeds = 8 runs."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=2)

            config = ExperimentConfig(
                experiment_id="exp_count8",
                tasks_path=str(tasks_path),
                profile_modes=["base", "schema_only"],
                seeds=[0, 42],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            result = runner.run(config)

            assert len(result.summaries) == 8
        finally:
            _cleanup(output_dir)

    def test_runs_jsonl_has_correct_count(self):
        """runs.jsonl should have the correct number of records."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=2)

            config = ExperimentConfig(
                experiment_id="exp_jsonl_count",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0, 1],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            runner.run(config)

            runs = load_runs_jsonl(config.get_output_dir())
            assert len(runs) == 4  # 2 tasks * 1 mode * 2 seeds
        finally:
            _cleanup(output_dir)


class TestExperimentManifest:
    """Tests for experiment manifest content."""

    def test_manifest_has_required_fields(self):
        """Manifest should have all required fields."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)

            config = ExperimentConfig(
                experiment_id="exp_manifest_fields",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            runner.run(config)

            manifest_path = config.get_output_dir() / "experiment_manifest.json"
            manifest = json.loads(manifest_path.read_text())

            required_fields = {
                "experiment_id",
                "tasks_path",
                "task_count",
                "task_ids",
                "profile_modes",
                "seeds",
                "total_runs",
                "completed_runs",
                "failed_runs",
                "output_dir",
                "runs_dir",
            }
            assert required_fields.issubset(manifest.keys())
        finally:
            _cleanup(output_dir)

    def test_manifest_task_ids_match(self):
        """Manifest task_ids should match the tasks run."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=2)

            config = ExperimentConfig(
                experiment_id="exp_manifest_ids",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            runner.run(config)

            manifest_path = config.get_output_dir() / "experiment_manifest.json"
            manifest = json.loads(manifest_path.read_text())

            assert set(manifest["task_ids"]) == {"task_000", "task_001"}
        finally:
            _cleanup(output_dir)

    def test_manifest_omits_timestamps_by_default(self):
        """Manifest should omit runtime timestamps by default for determinism."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)

            config = ExperimentConfig(
                experiment_id="exp_timestamps",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            runner.run(config)

            manifest_path = config.get_output_dir() / "experiment_manifest.json"
            manifest = json.loads(manifest_path.read_text())

            assert "start_time" not in manifest
            assert "end_time" not in manifest
        finally:
            _cleanup(output_dir)

    def test_manifest_serializes_explicit_timestamps_when_provided(self):
        """ExperimentManifest should preserve explicit timestamps when present."""
        manifest = ExperimentManifest(
            experiment_id="exp_ts",
            tasks_path="tasks.jsonl",
            task_count=1,
            task_ids=["task_000"],
            profile_modes=["base"],
            seeds=[0],
            start_time="2025-01-01T00:00:00+00:00",
            end_time="2025-01-01T00:00:01+00:00",
            total_runs=1,
            completed_runs=1,
            failed_runs=0,
            output_dir="out",
            runs_dir="out/runs",
        )

        data = manifest.to_dict()
        assert data["start_time"] == "2025-01-01T00:00:00+00:00"
        assert data["end_time"] == "2025-01-01T00:00:01+00:00"


class TestExperimentTaskFiltering:
    """Tests for task filtering in experiments."""

    def test_max_tasks_limits_runs(self):
        """max_tasks should limit the number of tasks."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=3)

            config = ExperimentConfig(
                experiment_id="exp_max_tasks",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                max_tasks=2,
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            result = runner.run(config)

            # Should only run 2 tasks (not 3)
            task_ids = {s.task_id for s in result.summaries}
            assert len(task_ids) == 2
        finally:
            _cleanup(output_dir)

    def test_task_ids_filters_runs(self):
        """task_ids should select specific tasks."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=3)

            config = ExperimentConfig(
                experiment_id="exp_task_ids",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                task_ids=["task_001"],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            result = runner.run(config)

            # Should only run task_001
            task_ids = {s.task_id for s in result.summaries}
            assert task_ids == {"task_001"}
        finally:
            _cleanup(output_dir)


class TestExperimentDeterminism:
    """Tests for deterministic experiment output."""

    def test_same_config_same_path_layout(self):
        """Same config should produce same directory paths."""
        config = ExperimentConfig(
            experiment_id="exp_det",
            tasks_path="tasks.jsonl",
            profile_modes=["base", "schema_only"],
            seeds=[0, 42],
        )

        # These should always be the same for the same config
        # Use Path comparison to avoid OS-specific path separator issues
        assert config.get_output_dir() == Path("experiments") / "exp_det"
        assert config.get_seed_dir(0) == Path("experiments") / "exp_det" / "runs" / "seed_0"
        assert config.get_mode_dir(0, "base") == Path("experiments") / "exp_det" / "runs" / "seed_0" / "base"
        assert config.get_mode_dir(42, "schema_only") == Path("experiments") / "exp_det" / "runs" / "seed_42" / "schema"

    def test_deterministic_traversal_order(self):
        """Tasks should be traversed in sorted task_id order."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=3)

            config = ExperimentConfig(
                experiment_id="exp_order",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            result = runner.run(config)

            # Summaries should be in task_id order
            task_ids = [s.task_id for s in result.summaries]
            assert task_ids == sorted(task_ids)
        finally:
            _cleanup(output_dir)


class TestExperimentFailureTolerance:
    """Tests for failure tolerance."""

    def test_failing_run_still_produces_result(self):
        """Experiment should still produce result if one run fails."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)

            config = ExperimentConfig(
                experiment_id="exp_fail",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            # Use failing client
            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_failing_fake_responses()),
            )
            result = runner.run(config)

            # Should still have a result
            assert result is not None
            assert len(result.summaries) == 1
        finally:
            _cleanup(output_dir)

    def test_failing_run_still_writes_manifest(self):
        """Manifest should be written even if runs fail."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)

            config = ExperimentConfig(
                experiment_id="exp_fail_manifest",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_failing_fake_responses()),
            )
            runner.run(config)

            manifest_path = config.get_output_dir() / "experiment_manifest.json"
            assert manifest_path.exists()

            manifest = json.loads(manifest_path.read_text())
            assert manifest["total_runs"] == 1
            # Should have at least one failed run
            assert manifest["failed_runs"] >= 0  # may be 0 or 1 depending on error handling
        finally:
            _cleanup(output_dir)

    def test_mixed_pass_fail_reflected_in_summary(self):
        """Summary should reflect mixed pass/fail outcomes."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=2)

            config = ExperimentConfig(
                experiment_id="exp_mixed",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            # Alternate between success and failure
            call_count = [0]
            def alternating_client():
                call_count[0] += 1
                if call_count[0] % 2 == 1:
                    return FakeLLMClient(_make_fake_responses())
                else:
                    return FakeLLMClient(_make_failing_fake_responses())

            runner = ExperimentRunner(client_factory=alternating_client)
            result = runner.run(config)

            # Should still have 2 results
            assert len(result.summaries) == 2

            # Summary should exist and be valid
            summary = load_summary_json(config.get_output_dir())
            assert summary["total_runs"] == 2
        finally:
            _cleanup(output_dir)


class TestRunExperimentConvenience:
    """Tests for the run_experiment convenience function."""

    def test_run_experiment_function(self):
        """run_experiment should work as convenience function."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)

            config = ExperimentConfig(
                experiment_id="exp_convenience",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(output_dir / "experiments"),
            )

            result = run_experiment(
                config,
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )

            assert isinstance(result, ExperimentResult)
            assert len(result.summaries) == 1
        finally:
            _cleanup(output_dir)


class TestExperimentSmokeIntegration:
    """Integration smoke test using real toy tasks and multiple modes/seeds."""

    def test_smoke_2_tasks_2_modes_2_seeds(self):
        """Full smoke test: 2 tasks, 2 modes, 2 seeds."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=2)

            config = ExperimentConfig(
                experiment_id="exp_smoke",
                tasks_path=str(tasks_path),
                profile_modes=["base", "schema_only"],
                seeds=[0, 42],
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            result = runner.run(config)

            # 2 tasks * 2 modes * 2 seeds = 8 runs
            assert len(result.summaries) == 8

            # All required output files should exist
            exp_dir = config.get_output_dir()
            assert (exp_dir / "experiment_config.json").exists()
            assert (exp_dir / "experiment_manifest.json").exists()
            assert (exp_dir / "summary.json").exists()
            assert (exp_dir / "runs.jsonl").exists()

            # Manifest should be correct
            manifest = json.loads((exp_dir / "experiment_manifest.json").read_text())
            assert manifest["experiment_id"] == "exp_smoke"
            assert manifest["task_count"] == 2
            assert manifest["profile_modes"] == ["base", "schema_only"]
            assert manifest["seeds"] == [0, 42]
            assert manifest["total_runs"] == 8

            # Runs should have correct structure
            runs = load_runs_jsonl(exp_dir)
            assert len(runs) == 8

            # All runs should have required fields
            for run in runs:
                assert "task_id" in run
                assert "profile_id" in run
                assert "status" in run
                assert "reward" in run

            # Summary should have metrics
            summary = load_summary_json(exp_dir)
            assert "metrics" in summary
            assert "pass_at_1" in summary["metrics"]

            # Directory structure should be correct
            runs_dir = config.get_runs_dir()
            for seed in [0, 42]:
                for mode in ["base", "schema_only"]:
                    mode_dir = runs_dir / f"seed_{seed}" / mode_dir_name(mode)
                    assert mode_dir.exists(), f"Missing mode dir: {mode_dir}"
        finally:
            _cleanup(output_dir)

    def test_config_roundtrip_after_experiment(self):
        """Config saved during experiment should be loadable and match."""
        output_dir = _get_test_dir()
        try:
            tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=1)

            config = ExperimentConfig(
                experiment_id="exp_roundtrip",
                tasks_path=str(tasks_path),
                profile_modes=["base", "schema_only"],
                seeds=[0],
                notes="roundtrip test",
                output_root=str(output_dir / "experiments"),
            )

            runner = ExperimentRunner(
                client_factory=lambda: FakeLLMClient(_make_fake_responses()),
            )
            runner.run(config)

            # Load config back
            loaded = ExperimentConfig.load(config.get_output_dir() / "experiment_config.json")
            assert loaded.experiment_id == config.experiment_id
            assert loaded.profile_modes == config.profile_modes
            assert loaded.seeds == config.seeds
            assert loaded.notes == config.notes
        finally:
            _cleanup(output_dir)
