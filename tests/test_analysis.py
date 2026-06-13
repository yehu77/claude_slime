"""Tests for experiment analysis: slicing, grouping, and aggregation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.eval.analysis import (
    ExperimentAnalysis,
    RunRecord,
    load_experiment_analysis,
    load_experiment_runs,
)
from pycodeagent.eval.experiment_config import ExperimentConfig
from pycodeagent.eval.experiment_runner import ExperimentRunner
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


pytestmark = [pytest.mark.slow, pytest.mark.integration]


_TEST_NAMESPACE = "analysis"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _make_fake_responses() -> list[str]:
    return [
        """<assistant>
I will complete the task.
</assistant>
<|tool|>
{"id": "call_finish", "name": "finish", "arguments": {"answer": "Task completed"}}
<|end|>
""",
    ]


def _create_toy_tasks_jsonl(output_dir: Path, num_tasks: int = 2) -> Path:
    """Create a toy tasks JSONL file for testing."""
    tasks_path = output_dir / "toy_tasks.jsonl"
    workspace = output_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "main.py").write_text("print('hello')\n")

    categories = ["bugfix", "feature", "refactor"]
    difficulties = ["easy", "medium", "hard"]

    tasks = []
    for i in range(num_tasks):
        tasks.append({
            "task_id": f"task_{i:03d}",
            "repo_path": str(workspace),
            "prompt": f"Fix the bug in task {i}.",
            "test_command": "echo ok",
            "max_turns": 2,
            "metadata": {
                "category": categories[i % len(categories)],
                "difficulty": difficulties[i % len(difficulties)],
            },
        })

    with open(tasks_path, "w", encoding="utf-8") as f:
        for task in tasks:
            f.write(json.dumps(task) + "\n")

    return tasks_path


def _run_mini_experiment(output_dir: Path, num_tasks: int = 2) -> Path:
    """Run a minimal experiment and return its output directory."""
    tasks_path = _create_toy_tasks_jsonl(output_dir, num_tasks=num_tasks)

    config = ExperimentConfig(
        experiment_id="test_exp",
        tasks_path=str(tasks_path),
        profile_modes=["base", "schema_only"],
        seeds=[0, 42],
        output_root=str(output_dir / "experiments"),
    )

    runner = ExperimentRunner(
        client_factory=lambda: FakeLLMClient(_make_fake_responses()),
    )
    runner.run(config)

    return config.get_output_dir()


# ─── RunRecord tests ───


class TestRunRecord:
    """Tests for RunRecord data class."""

    def test_run_record_properties(self):
        """RunRecord should provide property accessors for metadata fields."""
        record = RunRecord(
            task_id="t1",
            profile_id="base_001",
            status="completed",
            reward=1.0,
            passed=True,
            turns=2,
            tool_calls=1,
            output_dir="/tmp",
            failure_reason="",
            metadata={
                "seed": 42,
                "mode": "schema_only",
                "category": "bugfix",
                "difficulty": "easy",
                "verifier_score": 0.9,
                "has_patch": True,
                "parse_errors": 0,
                "schema_errors": 1,
                "tool_errors": 0,
                "apply_patch_success": True,
                "apply_patch_attempted": True,
            },
        )
        assert record.seed == 42
        assert record.mode == "schema_only"
        assert record.category == "bugfix"
        assert record.difficulty == "easy"
        assert record.verifier_score == 0.9
        assert record.has_patch is True
        assert record.parse_errors == 0
        assert record.schema_errors == 1
        assert record.apply_patch_success is True
        assert record.entered_execution is False
        assert record.clean_run is False
        assert record.verifier_failed is False

    def test_run_record_defaults(self):
        """RunRecord should default gracefully for missing metadata."""
        record = RunRecord(
            task_id="t1",
            profile_id="p1",
            status="completed",
            reward=0.5,
            passed=False,
            turns=3,
            tool_calls=2,
            output_dir="/tmp",
            failure_reason="verifier_failed",
            metadata={},
        )
        assert record.seed == 0
        assert record.mode == "unknown"
        assert record.category == ""
        assert record.difficulty == ""
        assert record.verifier_score == 0.0
        assert record.has_patch is False
        assert record.parse_errors == 0
        assert record.schema_errors == 0
        assert record.entered_execution is False
        assert record.clean_run is True
        assert record.verifier_failed is True


# ─── Loading tests ───


class TestLoadExperimentAnalysis:
    """Tests for loading experiment analysis from outputs."""

    def test_load_from_experiment_output(self):
        """Should load analysis from a real experiment output directory."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=1)
            analysis = load_experiment_analysis(exp_dir)

            assert analysis.count() > 0
            assert analysis.manifest["experiment_id"] == "test_exp"
        finally:
            _cleanup(output_dir)

    def test_load_missing_directory_raises(self):
        """Should raise FileNotFoundError for missing runs.jsonl."""
        with pytest.raises(FileNotFoundError):
            load_experiment_analysis("/nonexistent/path")

    def test_load_experiment_runs(self):
        """load_experiment_runs should return list of RunRecord."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=1)
            runs = load_experiment_runs(exp_dir)

            assert len(runs) > 0
            assert all(isinstance(r, RunRecord) for r in runs)
        finally:
            _cleanup(output_dir)


# ─── Overall metrics tests ───


class TestOverallMetrics:
    """Tests for overall metrics computation."""

    def test_overall_metrics_keys(self):
        """Overall metrics should have expected keys."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)
            overall = analysis.overall()

            expected_keys = {
                "count", "pass_at_1", "avg_reward", "avg_turns",
                "avg_tool_calls", "parse_error_rate",
                "schema_error_rate", "patch_apply_success_rate",
                "entered_execution_rate", "clean_run_count",
                "clean_run_pass_at_1", "verifier_failed_rate",
            }
            assert expected_keys.issubset(overall.keys())
        finally:
            _cleanup(output_dir)

    def test_overall_count_matches_runs(self):
        """Overall count should match the number of runs."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)
            overall = analysis.overall()

            # 2 tasks * 2 modes * 2 seeds = 8 runs
            assert overall["count"] == 8
            assert analysis.count() == 8
        finally:
            _cleanup(output_dir)


# ─── Grouping tests ───


class TestGroupBy:
    """Tests for grouping runs by field."""

    def test_group_by_mode(self):
        """Should group by mode."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)
            by_mode = analysis.group_by("mode")

            assert "base" in by_mode
            assert "schema_only" in by_mode
            # Each mode should have 4 runs (2 tasks * 2 seeds)
            assert by_mode["base"]["count"] == 4
            assert by_mode["schema_only"]["count"] == 4
        finally:
            _cleanup(output_dir)

    def test_group_by_seed(self):
        """Should group by seed."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)
            by_seed = analysis.group_by("seed")

            assert "0" in by_seed
            assert "42" in by_seed
            # Each seed should have 4 runs (2 tasks * 2 modes)
            assert by_seed["0"]["count"] == 4
            assert by_seed["42"]["count"] == 4
        finally:
            _cleanup(output_dir)

    def test_group_by_profile_id(self):
        """Should group by profile_id."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=1)
            analysis = load_experiment_analysis(exp_dir)
            by_profile = analysis.group_by("profile_id")

            # Should have at least 2 profile_ids (one per mode)
            assert len(by_profile) >= 2
            total_count = sum(g["count"] for g in by_profile.values())
            assert total_count == analysis.count()
        finally:
            _cleanup(output_dir)

    def test_group_by_task_id(self):
        """Should group by task_id."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)
            by_task = analysis.group_by("task_id")

            assert "task_000" in by_task
            assert "task_001" in by_task
            # Each task should have 4 runs (2 modes * 2 seeds)
            assert by_task["task_000"]["count"] == 4
            assert by_task["task_001"]["count"] == 4
        finally:
            _cleanup(output_dir)

    def test_group_by_status(self):
        """Should group by status."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=1)
            analysis = load_experiment_analysis(exp_dir)
            by_status = analysis.group_by("status")

            assert len(by_status) > 0
            total_count = sum(g["count"] for g in by_status.values())
            assert total_count == analysis.count()
        finally:
            _cleanup(output_dir)

    def test_group_keys_sorted(self):
        """Group keys should be sorted for determinism."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)
            by_task = analysis.group_by("task_id")

            keys = list(by_task.keys())
            assert keys == sorted(keys)
        finally:
            _cleanup(output_dir)


# ─── Filtering tests ───


class TestFiltering:
    """Tests for filtering runs before grouping."""

    def test_filter_by_mode(self):
        """Should filter to only schema_only runs."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)
            filtered = analysis.filter_by(mode="schema_only")

            assert filtered.count() == 4  # 2 tasks * 2 seeds
            # All runs should be schema_only
            for run in filtered.runs:
                assert run.mode == "schema_only"
        finally:
            _cleanup(output_dir)

    def test_filter_by_seed(self):
        """Should filter to only seed=42 runs."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)
            filtered = analysis.filter_by(seed=42)

            assert filtered.count() == 4  # 2 tasks * 2 modes
            for run in filtered.runs:
                assert run.seed == 42
        finally:
            _cleanup(output_dir)

    def test_filter_method_works(self):
        """analysis.filter() should work the same as filter_by()."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)

            # filter() should work with keyword arguments
            filtered = analysis.filter(mode="base")
            assert filtered.count() == 4  # 2 tasks * 2 seeds
            for run in filtered.runs:
                assert run.mode == "base"
        finally:
            _cleanup(output_dir)

    def test_filter_multiple_criteria(self):
        """analysis.filter() with multiple criteria should intersect."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)

            # Filter by both seed and mode
            filtered = analysis.filter(seed=42, mode="schema_only")
            assert filtered.count() == 2  # 2 tasks * 1 seed * 1 mode
            for run in filtered.runs:
                assert run.seed == 42
                assert run.mode == "schema_only"
        finally:
            _cleanup(output_dir)

    def test_filter_and_filter_by_consistent(self):
        """filter() and filter_by() should produce identical results."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)

            by_filter = analysis.filter(mode="schema_only", seed=0)
            by_filter_by = analysis.filter_by(mode="schema_only", seed=0)

            assert by_filter.count() == by_filter_by.count()
            assert by_filter.overall() == by_filter_by.overall()
        finally:
            _cleanup(output_dir)

    def test_filter_by_list_value(self):
        """filter_by() should support list/tuple/set values for membership tests."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)

            # Filter with list of seeds
            filtered = analysis.filter_by(seed=[0, 42])
            assert filtered.count() == 8  # 2 tasks * 2 modes * 2 seeds

            # Filter with set of modes
            filtered = analysis.filter_by(mode={"base", "schema_only"})
            assert filtered.count() == 8

            # Filter with list via filter() alias
            filtered = analysis.filter(seed=[0])
            assert filtered.count() == 4  # 2 tasks * 2 modes * 1 seed
        finally:
            _cleanup(output_dir)

    def test_filter_then_group(self):
        """Should be able to filter then group."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)

            # Filter to seed=0, then group by mode
            filtered = analysis.filter_by(seed=0)
            by_mode = filtered.group_by("mode")

            assert by_mode["base"]["count"] == 2  # 2 tasks
            assert by_mode["schema_only"]["count"] == 2
        finally:
            _cleanup(output_dir)

    def test_filter_by_category(self):
        """Should filter by category from task metadata."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=3)
            analysis = load_experiment_analysis(exp_dir)

            # task_000 is category=bugfix (index 0)
            filtered = analysis.filter_by(category="bugfix")
            assert filtered.count() > 0
            for run in filtered.runs:
                assert run.category == "bugfix"
        finally:
            _cleanup(output_dir)

    def test_filter_empty_result(self):
        """Should return empty analysis if no matches."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=1)
            analysis = load_experiment_analysis(exp_dir)
            filtered = analysis.filter_by(mode="nonexistent_mode")

            assert filtered.count() == 0
            assert filtered.overall()["count"] == 0
        finally:
            _cleanup(output_dir)


# ─── Category-aware slicing tests ───


class TestCategorySlicing:
    """Tests for category-aware slicing when metadata exists."""

    def test_group_by_category(self):
        """Should group by category from metadata."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=3)
            analysis = load_experiment_analysis(exp_dir)
            by_category = analysis.group_by("category")

            # At least bugfix category should exist
            assert "bugfix" in by_category
            assert by_category["bugfix"]["count"] > 0
        finally:
            _cleanup(output_dir)

    def test_group_by_difficulty(self):
        """Should group by difficulty from metadata."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=3)
            analysis = load_experiment_analysis(exp_dir)
            by_difficulty = analysis.group_by("difficulty")

            assert "easy" in by_difficulty
            assert by_difficulty["easy"]["count"] > 0
        finally:
            _cleanup(output_dir)


# ─── Determinism tests ───


class TestDeterminism:
    """Tests for deterministic analysis outputs."""

    def test_overall_deterministic(self):
        """Same data should produce same overall metrics."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=1)
            analysis1 = load_experiment_analysis(exp_dir)
            analysis2 = load_experiment_analysis(exp_dir)

            assert analysis1.overall() == analysis2.overall()
        finally:
            _cleanup(output_dir)

    def test_grouping_deterministic(self):
        """Same data should produce same grouped metrics."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis1 = load_experiment_analysis(exp_dir)
            analysis2 = load_experiment_analysis(exp_dir)

            assert analysis1.group_by("mode") == analysis2.group_by("mode")
            assert analysis1.group_by("seed") == analysis2.group_by("seed")
        finally:
            _cleanup(output_dir)

    def test_run_order_deterministic(self):
        """Runs should be sorted deterministically."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis1 = load_experiment_analysis(exp_dir)
            analysis2 = load_experiment_analysis(exp_dir)

            ids1 = [(r.seed, r.mode, r.task_id) for r in analysis1.runs]
            ids2 = [(r.seed, r.mode, r.task_id) for r in analysis2.runs]
            assert ids1 == ids2
        finally:
            _cleanup(output_dir)


# ─── Unique values and failed runs tests ───


class TestUniqueValuesAndFailed:
    """Tests for unique_values and failed_runs."""

    def test_unique_values(self):
        """Should return sorted unique values for a field."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)

            modes = analysis.unique_values("mode")
            assert modes == sorted(modes)
            assert "base" in modes
            assert "schema_only" in modes
        finally:
            _cleanup(output_dir)

    def test_failed_runs(self):
        """Should return runs that are not passed or not completed."""
        # Create analysis with some failed runs
        runs = [
            RunRecord("t1", "p1", "completed", 1.0, True, 2, 1, "", "", {"seed": 0, "mode": "base"}),
            RunRecord("t2", "p1", "completed", 0.0, False, 3, 2, "", "verifier_failed", {"seed": 0, "mode": "base"}),
            RunRecord("t3", "p2", "error", 0.0, False, 1, 0, "", "setup_error", {"seed": 1, "mode": "schema_only"}),
        ]
        analysis = ExperimentAnalysis(runs, {})
        failed = analysis.failed_runs()

        assert len(failed) == 2
        failed_ids = {r.task_id for r in failed}
        assert "t2" in failed_ids  # not passed
        assert "t3" in failed_ids  # not completed


# ─── Metrics alignment tests ───


class TestMetricsAlignment:
    """Tests that analysis metrics align with compute_metrics."""

    def test_pass_at_1_aligned(self):
        """pass_at_1 should match compute_pass_at_1 definition."""
        runs = [
            RunRecord("t1", "p1", "completed", 1.0, True, 2, 1, "", "", {"seed": 0, "mode": "base"}),
            RunRecord("t2", "p1", "completed", 0.0, False, 3, 2, "", "", {"seed": 0, "mode": "base"}),
            RunRecord("t3", "p2", "completed", 1.0, True, 1, 1, "", "", {"seed": 0, "mode": "schema_only"}),
        ]
        analysis = ExperimentAnalysis(runs, {})
        overall = analysis.overall()

        # 2 of 3 passed
        assert overall["pass_at_1"] == pytest.approx(2 / 3)

    def test_avg_reward_aligned(self):
        """avg_reward should match simple mean of rewards."""
        runs = [
            RunRecord("t1", "p1", "completed", 1.0, True, 2, 1, "", "", {"seed": 0, "mode": "base"}),
            RunRecord("t2", "p1", "completed", 0.5, False, 3, 2, "", "", {"seed": 0, "mode": "base"}),
        ]
        analysis = ExperimentAnalysis(runs, {})
        overall = analysis.overall()

        assert overall["avg_reward"] == pytest.approx(0.75)

    def test_empty_analysis(self):
        """Empty analysis should return zero metrics."""
        analysis = ExperimentAnalysis([], {})
        overall = analysis.overall()

        assert overall["count"] == 0
        assert overall["pass_at_1"] == 0.0
        assert overall["avg_reward"] == 0.0

    def test_clean_run_pass_rate_and_entered_execution_rate(self):
        """Should compute clean-run and entered-execution metrics correctly."""
        runs = [
            RunRecord(
                "t1", "p1", "completed", 1.0, True, 2, 2, "", "",
                {"seed": 0, "mode": "base", "entered_execution": True, "parse_errors": 0, "schema_errors": 0},
            ),
            RunRecord(
                "t2", "p1", "completed", 0.0, False, 2, 1, "", "verifier_failed",
                {"seed": 0, "mode": "base", "entered_execution": False, "parse_errors": 1, "schema_errors": 0},
            ),
            RunRecord(
                "t3", "p1", "completed", 0.0, False, 2, 2, "", "verifier_failed",
                {"seed": 0, "mode": "base", "entered_execution": True, "parse_errors": 0, "schema_errors": 0},
            ),
        ]
        analysis = ExperimentAnalysis(runs, {})
        overall = analysis.overall()

        assert overall["entered_execution_rate"] == pytest.approx(2 / 3)
        assert overall["clean_run_count"] == 2
        assert overall["clean_run_pass_at_1"] == pytest.approx(0.5)
        assert overall["verifier_failed_rate"] == pytest.approx(2 / 3)
