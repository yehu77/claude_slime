"""Tests for comparison table builders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.eval.analysis import RunRecord, load_experiment_analysis
from pycodeagent.eval.experiment_config import ExperimentConfig
from pycodeagent.eval.experiment_runner import ExperimentRunner
from pycodeagent.eval.tables import (
    build_category_profile_table,
    build_error_breakdown_table,
    build_profile_comparison_table,
    build_seed_comparison_table,
    table_to_csv,
    table_to_markdown,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


pytestmark = [pytest.mark.slow, pytest.mark.integration]


_TEST_NAMESPACE = "tables"


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


# ─── Profile comparison table tests ───


class TestProfileComparisonTable:
    """Tests for build_profile_comparison_table."""

    def test_table_has_expected_keys(self):
        """Table should have mode and all metric keys."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            runs = load_experiment_analysis(exp_dir).runs
            table = build_profile_comparison_table(runs, group_key="mode")

            assert len(table) > 0
            expected_keys = {
                "mode", "count", "pass_at_1", "avg_reward",
                "avg_turns", "avg_tool_calls", "parse_error_rate",
                "schema_error_rate", "patch_apply_success_rate",
                "entered_execution_rate", "clean_run_count",
                "clean_run_pass_at_1", "verifier_failed_rate",
            }
            for row in table:
                assert expected_keys.issubset(row.keys())
        finally:
            _cleanup(output_dir)

    def test_table_groups_by_mode(self):
        """Table should group by mode."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            runs = load_experiment_analysis(exp_dir).runs
            table = build_profile_comparison_table(runs, group_key="mode")

            modes = {row["mode"] for row in table}
            assert "base" in modes
            assert "schema_only" in modes
        finally:
            _cleanup(output_dir)

    def test_table_sorted_by_key(self):
        """Table should be sorted by group key."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            runs = load_experiment_analysis(exp_dir).runs
            table = build_profile_comparison_table(runs, group_key="mode")

            modes = [row["mode"] for row in table]
            assert modes == sorted(modes)
        finally:
            _cleanup(output_dir)

    def test_table_counts_sum_to_total(self):
        """Counts should sum to total run count."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            runs = load_experiment_analysis(exp_dir).runs
            table = build_profile_comparison_table(runs, group_key="mode")

            total = sum(row["count"] for row in table)
            assert total == len(runs)
        finally:
            _cleanup(output_dir)

    def test_table_with_profile_id_key(self):
        """Should also work grouping by profile_id."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=1)
            runs = load_experiment_analysis(exp_dir).runs
            table = build_profile_comparison_table(runs, group_key="profile_id")

            assert len(table) >= 2  # At least 2 profile_ids
            for row in table:
                assert "profile_id" in row
                assert "count" in row
        finally:
            _cleanup(output_dir)


# ─── Seed comparison table tests ───


class TestSeedComparisonTable:
    """Tests for build_seed_comparison_table."""

    def test_table_has_expected_keys(self):
        """Table should have seed and all metric keys."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            runs = load_experiment_analysis(exp_dir).runs
            table = build_seed_comparison_table(runs)

            assert len(table) > 0
            for row in table:
                assert "seed" in row
                assert "count" in row
                assert "pass_at_1" in row
                assert "avg_reward" in row
        finally:
            _cleanup(output_dir)

    def test_table_groups_by_seed(self):
        """Table should group by seed."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            runs = load_experiment_analysis(exp_dir).runs
            table = build_seed_comparison_table(runs)

            seeds = {row["seed"] for row in table}
            assert 0 in seeds
            assert 42 in seeds
        finally:
            _cleanup(output_dir)

    def test_table_sorted_by_seed(self):
        """Table should be sorted by seed."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            runs = load_experiment_analysis(exp_dir).runs
            table = build_seed_comparison_table(runs)

            seeds = [row["seed"] for row in table]
            assert seeds == sorted(seeds)
        finally:
            _cleanup(output_dir)


# ─── Category × Profile table tests ───


class TestCategoryProfileTable:
    """Tests for build_category_profile_table."""

    def test_table_has_expected_keys(self):
        """Table should have category, mode, and key metrics."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=3)
            runs = load_experiment_analysis(exp_dir).runs
            table = build_category_profile_table(runs, profile_key="mode")

            assert len(table) > 0
            for row in table:
                assert "category" in row
                assert "mode" in row
                assert "count" in row
                assert "pass_at_1" in row
                assert "avg_reward" in row
                assert "entered_execution_rate" in row
                assert "clean_run_pass_at_1" in row
        finally:
            _cleanup(output_dir)

    def test_table_cross_product(self):
        """Table should have entries for (category, mode) combinations."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=3)
            runs = load_experiment_analysis(exp_dir).runs
            table = build_category_profile_table(runs, profile_key="mode")

            # Should have entries for category × mode
            keys = {(row["category"], row["mode"]) for row in table}
            assert len(keys) > 0

            # Each category should appear with each mode
            categories = {row["category"] for row in table}
            modes = {row["mode"] for row in table}
            assert len(categories) >= 1
            assert len(modes) >= 2  # base and schema_only
        finally:
            _cleanup(output_dir)

    def test_table_sorted_by_category_mode(self):
        """Table should be sorted by (category, mode)."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=3)
            runs = load_experiment_analysis(exp_dir).runs
            table = build_category_profile_table(runs, profile_key="mode")

            keys = [(row["category"], row["mode"]) for row in table]
            assert keys == sorted(keys)
        finally:
            _cleanup(output_dir)

    def test_uncategorized_for_missing_category(self):
        """Runs without category should be labeled 'uncategorized'."""
        runs = [
            RunRecord("t1", "p1", "completed", 1.0, True, 2, 1, "", "", {"seed": 0, "mode": "base"}),
            RunRecord("t2", "p2", "completed", 1.0, True, 2, 1, "", "", {"seed": 0, "mode": "schema_only"}),
        ]
        table = build_category_profile_table(runs)

        categories = {row["category"] for row in table}
        assert "uncategorized" in categories


# ─── Error breakdown table tests ───


class TestErrorBreakdownTable:
    """Tests for build_error_breakdown_table."""

    def test_table_has_expected_keys(self):
        """Table should have mode and all error count/rate keys."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            runs = load_experiment_analysis(exp_dir).runs
            table = build_error_breakdown_table(runs, group_key="mode")

            assert len(table) > 0
            expected_keys = {
                "mode", "count",
                "parse_error_count", "parse_error_rate",
                "schema_error_count", "schema_error_rate",
                "verifier_failed_count", "verifier_failed_rate",
                "tool_error_count", "tool_error_rate",
                "patch_failure_count", "patch_failure_rate",
            }
            for row in table:
                assert expected_keys.issubset(row.keys())
        finally:
            _cleanup(output_dir)

    def test_error_rates_in_valid_range(self):
        """Error rates should be in [0, 1]."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            runs = load_experiment_analysis(exp_dir).runs
            table = build_error_breakdown_table(runs, group_key="mode")

            for row in table:
                assert 0.0 <= row["parse_error_rate"] <= 1.0
                assert 0.0 <= row["schema_error_rate"] <= 1.0
                assert 0.0 <= row["verifier_failed_rate"] <= 1.0
                assert 0.0 <= row["tool_error_rate"] <= 1.0
                assert 0.0 <= row["patch_failure_rate"] <= 1.0
        finally:
            _cleanup(output_dir)

    def test_table_with_errors(self):
        """Table should correctly count errors."""
        runs = [
            RunRecord(
                "t1", "p1", "completed", 0.0, False, 2, 5, "", "verifier_failed",
                {"seed": 0, "mode": "base", "parse_errors": 1, "schema_errors": 2, "tool_errors": 1},
            ),
            RunRecord(
                "t2", "p1", "completed", 1.0, True, 2, 3, "", "",
                {"seed": 0, "mode": "base", "parse_errors": 0, "schema_errors": 0, "tool_errors": 0},
            ),
        ]
        table = build_error_breakdown_table(runs, group_key="mode")

        assert len(table) == 1
        row = table[0]
        assert row["count"] == 2
        assert row["parse_error_count"] == 1
        assert row["schema_error_count"] == 2
        assert row["verifier_failed_count"] == 1
        assert row["tool_error_count"] == 1


# ─── Output format tests ───


class TestTableOutputFormats:
    """Tests for table_to_markdown and table_to_csv."""

    def test_markdown_output(self):
        """Should produce valid Markdown table."""
        table = [
            {"mode": "base", "count": 4, "pass_at_1": 0.75},
            {"mode": "schema_only", "count": 4, "pass_at_1": 0.50},
        ]
        md = table_to_markdown(table)

        assert "|" in md
        assert "mode" in md
        assert "count" in md
        assert "pass_at_1" in md

    def test_csv_output(self):
        """Should produce valid CSV."""
        table = [
            {"mode": "base", "count": 4, "pass_at_1": 0.75},
            {"mode": "schema_only", "count": 4, "pass_at_1": 0.50},
        ]
        csv = table_to_csv(table)

        assert "mode,count,pass_at_1" in csv
        assert "base" in csv
        assert "schema_only" in csv

    def test_empty_table(self):
        """Empty table should return empty string."""
        assert table_to_markdown([]) == ""
        assert table_to_csv([]) == ""

    def test_float_formatting(self):
        """Floats should be formatted as specified."""
        table = [{"value": 0.123456789}]
        md = table_to_markdown(table, float_format=".2f")
        assert "0.12" in md

        csv = table_to_csv(table, float_format=".3f")
        assert "0.123" in csv


# ─── Integration smoke test ───


class TestTablesIntegration:
    """Integration tests building tables from real experiment outputs."""

    def test_build_all_tables_from_experiment(self):
        """Should build all tables from a real experiment output."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            runs = load_experiment_analysis(exp_dir).runs

            # Build all table types
            profile_table = build_profile_comparison_table(runs, group_key="mode")
            seed_table = build_seed_comparison_table(runs)
            category_table = build_category_profile_table(runs, profile_key="mode")
            error_table = build_error_breakdown_table(runs, group_key="mode")

            # Verify all tables have data
            assert len(profile_table) >= 2  # 2 modes
            assert len(seed_table) == 2  # 2 seeds
            assert len(category_table) >= 1  # At least one category
            assert len(error_table) >= 1

            # Verify counts align
            total_in_profile = sum(r["count"] for r in profile_table)
            total_in_seed = sum(r["count"] for r in seed_table)
            assert total_in_profile == total_in_seed == len(runs)
        finally:
            _cleanup(output_dir)

    def test_metrics_align_with_analysis(self):
        """Table metrics should align with analysis group_by results."""
        output_dir = _get_test_dir()
        try:
            exp_dir = _run_mini_experiment(output_dir, num_tasks=2)
            analysis = load_experiment_analysis(exp_dir)
            runs = analysis.runs

            # Compare table to analysis results
            profile_table = build_profile_comparison_table(runs, group_key="mode")
            by_mode = analysis.group_by("mode")

            for row in profile_table:
                mode = row["mode"]
                assert mode in by_mode
                assert row["count"] == by_mode[mode]["count"]
                assert row["pass_at_1"] == pytest.approx(by_mode[mode]["pass_at_1"])
                assert row["avg_reward"] == pytest.approx(by_mode[mode]["avg_reward"])
        finally:
            _cleanup(output_dir)
