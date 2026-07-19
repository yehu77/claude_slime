"""Tests for MutationStudyRunner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.eval.study_config import StudyConfig
from pycodeagent.eval.study_runner import MutationStudyRunner, StudyResult
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


pytestmark = [pytest.mark.slow, pytest.mark.integration]


_TEST_NAMESPACE = "study_runner"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    """Clean up a specific test directory, but preserve the test root."""
    cleanup_test_path(path)


def _make_source_repo(test_root: Path, name: str, files: dict[str, str]) -> Path:
    """Create a source repo directory with files."""
    repo = test_root / "source" / name
    repo.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return repo


def _make_tasks_jsonl(test_root: Path, tasks: list[dict]) -> Path:
    """Create a JSONL file with task definitions."""
    tasks_path = test_root / "tasks.jsonl"
    with open(tasks_path, "w", encoding="utf-8") as f:
        for task in tasks:
            f.write(json.dumps(task) + "\n")
    return tasks_path


def _make_fake_client_factory(responses: list[str]):
    """Create a factory that produces FakeLLMClients with given responses."""

    def factory():
        return FakeLLMClient(responses=responses)

    return factory


class TestMutationStudyRunnerMinimal:
    """Tests for minimal study runs."""

    def test_minimal_study_with_single_mode(self):
        """Should run a study with a single mode (baseline only)."""
        test_dir = _get_test_dir()
        try:
            # Create a simple task
            source = _make_source_repo(test_dir, "simple", {"test.py": "def test_ok(): pass"})
            tasks_path = _make_tasks_jsonl(
                test_dir,
                [
                    {
                        "task_id": "task_001",
                        "repo_path": str(source),
                        "prompt": "Run tests",
                        "max_turns": 2,
                    }
                ],
            )

            config = StudyConfig(
                study_id="minimal_study",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(test_dir / "studies"),
            )

            # Fake client just finishes
            client_factory = _make_fake_client_factory(
                [
                    """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
                ]
            )

            runner = MutationStudyRunner(client_factory)
            result = runner.run(config)

            assert result.config.study_id == "minimal_study"
            assert result.task_count == 1
            assert len(result.experiment_results) == 1
            assert "base" in result.experiment_results
        finally:
            _cleanup(test_dir)

    def test_study_with_baseline_and_mutated_mode(self):
        """Should run study with baseline and one mutated mode."""
        test_dir = _get_test_dir()
        try:
            source = _make_source_repo(test_dir, "two_modes", {"test.py": "def test_ok(): pass"})
            tasks_path = _make_tasks_jsonl(
                test_dir,
                [
                    {
                        "task_id": "task_001",
                        "repo_path": str(source),
                        "prompt": "Run tests",
                        "max_turns": 2,
                    }
                ],
            )

            config = StudyConfig(
                study_id="two_mode_study",
                tasks_path=str(tasks_path),
                profile_modes=["base", "schema_only"],
                baseline_mode="base",
                seeds=[0],
                output_root=str(test_dir / "studies"),
            )

            client_factory = _make_fake_client_factory(
                [
                    """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
                ]
            )

            runner = MutationStudyRunner(client_factory)
            result = runner.run(config)

            # Should have both experiments
            assert len(result.experiment_results) == 2
            assert "base" in result.experiment_results
            assert "schema_only" in result.experiment_results

            # Mode comparisons should include both
            assert len(result.mode_comparisons) == 2
            modes = {c.mode for c in result.mode_comparisons}
            assert modes == {"base", "schema_only"}
        finally:
            _cleanup(test_dir)


class TestModeComparison:
    """Tests for mode comparison calculations."""

    def test_baseline_delta_is_zero(self):
        """Baseline mode should have zero delta vs itself."""
        test_dir = _get_test_dir()
        try:
            source = _make_source_repo(test_dir, "baseline_delta", {"test.py": "def test_ok(): pass"})
            tasks_path = _make_tasks_jsonl(
                test_dir,
                [
                    {
                        "task_id": "task_001",
                        "repo_path": str(source),
                        "prompt": "Run tests",
                        "max_turns": 2,
                    }
                ],
            )

            config = StudyConfig(
                study_id="delta_zero_study",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(test_dir / "studies"),
            )

            client_factory = _make_fake_client_factory(
                [
                    """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
                ]
            )

            runner = MutationStudyRunner(client_factory)
            result = runner.run(config)

            # Find baseline comparison
            baseline_comp = next(c for c in result.mode_comparisons if c.mode == "base")
            assert baseline_comp.delta_pass_at_1 == 0.0
            assert baseline_comp.delta_avg_reward == 0.0
        finally:
            _cleanup(test_dir)

    def test_mutated_mode_delta_computed(self):
        """Mutated mode should have delta computed vs baseline."""
        test_dir = _get_test_dir()
        try:
            source = _make_source_repo(test_dir, "mutated_delta", {"test.py": "def test_ok(): pass"})
            tasks_path = _make_tasks_jsonl(
                test_dir,
                [
                    {
                        "task_id": "task_001",
                        "repo_path": str(source),
                        "prompt": "Run tests",
                        "max_turns": 2,
                    }
                ],
            )

            config = StudyConfig(
                study_id="mutated_delta_study",
                tasks_path=str(tasks_path),
                profile_modes=["base", "schema_only"],
                baseline_mode="base",
                seeds=[0],
                output_root=str(test_dir / "studies"),
            )

            client_factory = _make_fake_client_factory(
                [
                    """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
                ]
            )

            runner = MutationStudyRunner(client_factory)
            result = runner.run(config)

            # Both modes have same results (same fake client), so delta should be 0
            schema_comp = next(c for c in result.mode_comparisons if c.mode == "schema_only")
            # With same fake client responses, deltas should be 0
            assert schema_comp.delta_pass_at_1 == 0.0
            assert schema_comp.delta_avg_reward == 0.0
        finally:
            _cleanup(test_dir)


class TestSeedComparison:
    """Tests for seed comparisons."""

    def test_multiple_seeds(self):
        """Should compute metrics per seed."""
        test_dir = _get_test_dir()
        try:
            source = _make_source_repo(test_dir, "multi_seed", {"test.py": "def test_ok(): pass"})
            tasks_path = _make_tasks_jsonl(
                test_dir,
                [
                    {
                        "task_id": "task_001",
                        "repo_path": str(source),
                        "prompt": "Run tests",
                        "max_turns": 2,
                    }
                ],
            )

            config = StudyConfig(
                study_id="multi_seed_study",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0, 42],
                output_root=str(test_dir / "studies"),
            )

            client_factory = _make_fake_client_factory(
                [
                    """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
                ]
            )

            runner = MutationStudyRunner(client_factory)
            result = runner.run(config)

            # Should have seed comparisons for both seeds
            assert len(result.seed_comparisons) == 2
            seeds = {c.seed for c in result.seed_comparisons}
            assert seeds == {0, 42}
        finally:
            _cleanup(test_dir)


class TestSeedVariability:
    """Tests for seed variability calculations."""

    def test_seed_variability_computed(self):
        """Should compute variability across seeds for each mode."""
        test_dir = _get_test_dir()
        try:
            source = _make_source_repo(test_dir, "seed_var", {"test.py": "def test_ok(): pass"})
            tasks_path = _make_tasks_jsonl(
                test_dir,
                [
                    {
                        "task_id": "task_001",
                        "repo_path": str(source),
                        "prompt": "Run tests",
                        "max_turns": 2,
                    }
                ],
            )

            config = StudyConfig(
                study_id="seed_var_study",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0, 42, 123],
                output_root=str(test_dir / "studies"),
            )

            client_factory = _make_fake_client_factory(
                [
                    """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
                ]
            )

            runner = MutationStudyRunner(client_factory)
            result = runner.run(config)

            # Should have seed variability for base mode
            assert len(result.seed_variability) == 1
            sv = result.seed_variability[0]
            assert sv.mode == "base"
            assert sv.seed_count == 3
            # With same fake client, variability should be 0
            assert sv.pass_at_1_range == 0.0
        finally:
            _cleanup(test_dir)


class TestDeterminism:
    """Tests for deterministic behavior."""

    def test_same_config_same_outputs(self):
        """Same config + same client should produce same results."""
        test_dir = _get_test_dir()
        try:
            source = _make_source_repo(test_dir, "determinism", {"test.py": "def test_ok(): pass"})
            tasks_path = _make_tasks_jsonl(
                test_dir,
                [
                    {
                        "task_id": "task_001",
                        "repo_path": str(source),
                        "prompt": "Run tests",
                        "max_turns": 2,
                    }
                ],
            )

            config = StudyConfig(
                study_id="determinism_study",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(test_dir / "studies"),
            )

            client_factory = _make_fake_client_factory(
                [
                    """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
                ]
            )

            runner = MutationStudyRunner(client_factory)
            result1 = runner.run(config)

            # Run again (but need different output dir to avoid conflicts)
            config2 = StudyConfig(
                study_id="determinism_study_2",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(test_dir / "studies_2"),
            )
            result2 = runner.run(config2)

            # Results should match
            assert result1.task_count == result2.task_count
            assert result1.baseline_metrics == result2.baseline_metrics
        finally:
            _cleanup(test_dir)


class TestExperimentOutputsCreated:
    """Tests that underlying experiment outputs are created."""

    def test_experiment_output_dirs_exist(self):
        """Experiment output directories should be created."""
        test_dir = _get_test_dir()
        try:
            source = _make_source_repo(test_dir, "exp_outputs", {"test.py": "def test_ok(): pass"})
            tasks_path = _make_tasks_jsonl(
                test_dir,
                [
                    {
                        "task_id": "task_001",
                        "repo_path": str(source),
                        "prompt": "Run tests",
                        "max_turns": 2,
                    }
                ],
            )

            config = StudyConfig(
                study_id="exp_output_study",
                tasks_path=str(tasks_path),
                profile_modes=["base", "schema_only"],
                seeds=[0],
                output_root=str(test_dir / "studies"),
            )

            client_factory = _make_fake_client_factory(
                [
                    """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
                ]
            )

            runner = MutationStudyRunner(client_factory)
            result = runner.run(config)

            # Check experiment output dirs exist
            for mode, exp_result in result.experiment_results.items():
                exp_dir = Path(exp_result.output_dir)
                assert exp_dir.exists(), f"Experiment dir for {mode} should exist"
        finally:
            _cleanup(test_dir)

    def test_completed_experiment_outputs_are_reused(self):
        """Re-running a study should skip complete per-mode experiments."""
        test_dir = _get_test_dir()
        try:
            source = _make_source_repo(test_dir, "resume", {"test.py": "def test_ok(): pass"})
            tasks_path = _make_tasks_jsonl(
                test_dir,
                [
                    {
                        "task_id": "task_001",
                        "repo_path": str(source),
                        "prompt": "Run tests",
                        "max_turns": 2,
                    }
                ],
            )

            config = StudyConfig(
                study_id="resume_study",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(test_dir / "studies"),
            )

            client_factory = _make_fake_client_factory(
                [
                    """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
                ]
            )
            first = MutationStudyRunner(client_factory).run(config)

            def fail_if_called():
                raise AssertionError("client_factory should not be called for completed experiments")

            second = MutationStudyRunner(fail_if_called).run(config)

            assert second.baseline_metrics == first.baseline_metrics
            assert len(second.experiment_results["base"].summaries) == 1
        finally:
            _cleanup(test_dir)
