"""Phase-2 guardrail: batch runner -> metrics/report consistency.

Tests that:
1. Batch result summaries are accepted by metrics/report unchanged
2. Metrics computed from batch results match what report writes
3. Failed-case manifest stays aligned with run summaries

This guards against changes to RunSummary, compute_metrics, or
write_batch_reports that would silently break cross-module consistency.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pycodeagent.eval.batch_runner import BatchResult, RunSummary
from pycodeagent.eval.metrics import (
    compute_avg_reward,
    compute_avg_tool_calls,
    compute_avg_turns,
    compute_invalid_schema_call_rate,
    compute_metrics,
    compute_pass_at_1,
    compute_patch_apply_success_rate,
    compute_tool_call_parse_error_rate,
)
from pycodeagent.eval.report import (
    load_failed_cases_jsonl,
    load_runs_jsonl,
    load_summary_json,
    write_batch_reports,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "phase2_batch_consistency"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _make_summary(
    *,
    task_id: str = "task_001",
    profile_id: str = "base",
    status: str = "completed",
    reward: float = 1.0,
    passed: bool = True,
    turns: int = 3,
    tool_calls: int = 2,
    output_dir: str = ".",
    failure_reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> RunSummary:
    return RunSummary(
        task_id=task_id,
        profile_id=profile_id,
        status=status,
        reward=reward,
        passed=passed,
        turns=turns,
        tool_calls=tool_calls,
        output_dir=output_dir,
        failure_reason=failure_reason,
        metadata=metadata or {},
    )


class TestMetricsFromRunSummaries:
    """Verify compute_metrics accepts RunSummary and returns correct values."""

    def test_pass_at_1(self):
        summaries = [
            _make_summary(passed=True),
            _make_summary(passed=True),
            _make_summary(passed=False),
        ]
        assert compute_pass_at_1(summaries) == pytest.approx(2 / 3)

    def test_avg_reward(self):
        summaries = [
            _make_summary(reward=1.0),
            _make_summary(reward=0.5),
            _make_summary(reward=0.0),
        ]
        assert compute_avg_reward(summaries) == pytest.approx(0.5)

    def test_avg_turns(self):
        summaries = [
            _make_summary(turns=5),
            _make_summary(turns=3),
        ]
        assert compute_avg_turns(summaries) == pytest.approx(4.0)

    def test_avg_tool_calls(self):
        summaries = [
            _make_summary(tool_calls=4),
            _make_summary(tool_calls=2),
        ]
        assert compute_avg_tool_calls(summaries) == pytest.approx(3.0)

    def test_parse_error_rate(self):
        summaries = [
            _make_summary(metadata={"parse_errors": 1}),
            _make_summary(metadata={"parse_errors": 0}),
            _make_summary(metadata={"parse_errors": 0}),
        ]
        assert compute_tool_call_parse_error_rate(summaries) == pytest.approx(1 / 3)

    def test_invalid_schema_call_rate(self):
        summaries = [
            _make_summary(tool_calls=5, metadata={"schema_errors": 1}),
            _make_summary(tool_calls=3, metadata={"schema_errors": 0}),
        ]
        # 1 schema error out of 8 total tool calls
        assert compute_invalid_schema_call_rate(summaries) == pytest.approx(1 / 8)

    def test_patch_apply_success_rate(self):
        summaries = [
            _make_summary(metadata={"apply_patch_success": True}),
            _make_summary(metadata={"apply_patch_success": False}),
        ]
        assert compute_patch_apply_success_rate(summaries) == pytest.approx(0.5)

    def test_compute_metrics_returns_all_keys(self):
        summaries = [_make_summary()]
        metrics = compute_metrics(summaries)
        expected_keys = {
            "pass_at_1",
            "avg_reward",
            "avg_turns",
            "avg_tool_calls",
            "tool_call_parse_error_rate",
            "invalid_schema_call_rate",
            "patch_apply_success_rate",
        }
        assert set(metrics.keys()) == expected_keys

    def test_empty_summaries(self):
        metrics = compute_metrics([])
        assert metrics["pass_at_1"] == 0.0
        assert metrics["avg_reward"] == 0.0
        assert metrics["invalid_schema_call_rate"] == 0.0


class TestBatchReportConsistency:
    """Verify write_batch_reports + load functions roundtrip correctly."""

    def test_summary_json_contains_metrics(self):
        output_dir = _get_test_dir()
        try:
            summaries = [
                _make_summary(reward=1.0, passed=True, status="completed"),
                _make_summary(reward=0.0, passed=False, status="error"),
            ]
            metrics = compute_metrics(summaries)
            write_batch_reports(output_dir, summaries, metrics)

            loaded = load_summary_json(output_dir)
            assert "metrics" in loaded
            assert loaded["metrics"]["pass_at_1"] == pytest.approx(0.5)
            assert loaded["metrics"]["avg_reward"] == pytest.approx(0.5)
        finally:
            _cleanup(output_dir)

    def test_summary_json_counts(self):
        output_dir = _get_test_dir()
        try:
            summaries = [
                _make_summary(passed=True, status="completed"),
                _make_summary(passed=False, status="error"),
                _make_summary(passed=False, status="timeout"),
            ]
            metrics = compute_metrics(summaries)
            write_batch_reports(output_dir, summaries, metrics)

            loaded = load_summary_json(output_dir)
            assert loaded["total_runs"] == 3
            assert loaded["passed_count"] == 1
            assert loaded["failed_count"] == 2
            # Status counts
            assert loaded["status_counts"]["completed"] == 1
            assert loaded["status_counts"]["error"] == 1
            assert loaded["status_counts"]["timeout"] == 1
        finally:
            _cleanup(output_dir)

    def test_summary_json_profile_counts(self):
        output_dir = _get_test_dir()
        try:
            summaries = [
                _make_summary(profile_id="base"),
                _make_summary(profile_id="base"),
                _make_summary(profile_id="schema_only"),
            ]
            metrics = compute_metrics(summaries)
            write_batch_reports(output_dir, summaries, metrics)

            loaded = load_summary_json(output_dir)
            assert loaded["profile_counts"]["base"] == 2
            assert loaded["profile_counts"]["schema_only"] == 1
        finally:
            _cleanup(output_dir)

    def test_runs_jsonl_roundtrip(self):
        output_dir = _get_test_dir()
        try:
            summaries = [
                _make_summary(task_id="t1", reward=1.0, passed=True),
                _make_summary(task_id="t2", reward=0.5, passed=False),
            ]
            metrics = compute_metrics(summaries)
            write_batch_reports(output_dir, summaries, metrics)

            runs = load_runs_jsonl(output_dir)
            assert len(runs) == 2
            assert runs[0]["task_id"] == "t1"
            assert runs[0]["reward"] == 1.0
            assert runs[1]["task_id"] == "t2"
            assert runs[1]["reward"] == 0.5
        finally:
            _cleanup(output_dir)

    def test_runs_jsonl_has_required_fields(self):
        output_dir = _get_test_dir()
        try:
            summaries = [_make_summary(metadata={"schema_errors": 1})]
            metrics = compute_metrics(summaries)
            write_batch_reports(output_dir, summaries, metrics)

            runs = load_runs_jsonl(output_dir)
            run = runs[0]
            required_fields = {
                "task_id",
                "profile_id",
                "status",
                "reward",
                "passed",
                "turns",
                "tool_calls",
                "output_dir",
                "failure_reason",
                "metadata",
            }
            assert required_fields.issubset(run.keys())
        finally:
            _cleanup(output_dir)


class TestFailedCaseManifest:
    """Verify failed-case manifest alignment with run summaries."""

    def test_failed_cases_only_includes_failures(self):
        output_dir = _get_test_dir()
        try:
            summaries = [
                _make_summary(task_id="t1", passed=True, status="completed"),
                _make_summary(task_id="t2", passed=False, status="completed"),
                _make_summary(task_id="t3", passed=True, status="error"),
            ]
            metrics = compute_metrics(summaries)
            write_batch_reports(output_dir, summaries, metrics)

            failed = load_failed_cases_jsonl(output_dir)
            failed_ids = {c["task_id"] for c in failed}
            assert "t2" in failed_ids  # passed=False
            assert "t3" in failed_ids  # status != completed
            assert "t1" not in failed_ids  # both passed and completed
        finally:
            _cleanup(output_dir)

    def test_failed_cases_fields(self):
        output_dir = _get_test_dir()
        try:
            summaries = [
                _make_summary(
                    task_id="t1",
                    passed=False,
                    status="error",
                    failure_reason="verifier_failed",
                ),
            ]
            metrics = compute_metrics(summaries)
            write_batch_reports(output_dir, summaries, metrics)

            failed = load_failed_cases_jsonl(output_dir)
            assert len(failed) == 1
            case = failed[0]
            assert "task_id" in case
            assert "profile_id" in case
            assert "status" in case
            assert "reward" in case
            assert "failure_reason" in case
            assert "passed" in case
            assert case["failure_reason"] == "verifier_failed"
        finally:
            _cleanup(output_dir)

    def test_no_failed_cases_produces_empty_file(self):
        output_dir = _get_test_dir()
        try:
            summaries = [
                _make_summary(passed=True, status="completed"),
            ]
            metrics = compute_metrics(summaries)
            write_batch_reports(output_dir, summaries, metrics)

            failed = load_failed_cases_jsonl(output_dir)
            assert failed == []
        finally:
            _cleanup(output_dir)


class TestMetricsReportAlignment:
    """Verify metrics computed directly match what's in report."""

    def test_report_metrics_match_compute(self):
        output_dir = _get_test_dir()
        try:
            summaries = [
                _make_summary(reward=1.0, passed=True, turns=5, tool_calls=3, status="completed"),
                _make_summary(reward=0.5, passed=False, turns=8, tool_calls=6, status="completed",
                              metadata={"parse_errors": 1, "schema_errors": 2}),
                _make_summary(reward=0.0, passed=False, turns=2, tool_calls=0, status="error"),
            ]
            metrics = compute_metrics(summaries)
            write_batch_reports(output_dir, summaries, metrics)

            loaded = load_summary_json(output_dir)
            report_metrics = loaded["metrics"]

            # Each metric should match exactly
            for key in metrics:
                assert report_metrics[key] == pytest.approx(metrics[key]), f"Mismatch for {key}"
        finally:
            _cleanup(output_dir)

    def test_report_counts_match_summaries(self):
        output_dir = _get_test_dir()
        try:
            summaries = [
                _make_summary(task_id="t1", profile_id="base", passed=True, status="completed"),
                _make_summary(task_id="t2", profile_id="base", passed=False, status="completed"),
                _make_summary(task_id="t3", profile_id="schema_only", passed=False, status="error"),
            ]
            metrics = compute_metrics(summaries)
            write_batch_reports(output_dir, summaries, metrics)

            loaded = load_summary_json(output_dir)

            # Total runs
            assert loaded["total_runs"] == len(summaries)
            # Pass/fail counts
            assert loaded["passed_count"] == sum(1 for s in summaries if s.passed)
            assert loaded["failed_count"] == sum(1 for s in summaries if not s.passed)
            # Status counts
            for status, count in loaded["status_counts"].items():
                assert count == sum(1 for s in summaries if s.status == status)
            # Profile counts
            for pid, count in loaded["profile_counts"].items():
                assert count == sum(1 for s in summaries if s.profile_id == pid)
        finally:
            _cleanup(output_dir)


class TestBatchResultStructure:
    """Verify BatchResult has correct structure."""

    def test_batch_result_fields(self):
        summaries = [_make_summary(), _make_summary()]
        metrics = compute_metrics(summaries)
        result = BatchResult(
            summaries=summaries,
            metrics=metrics,
            output_dir="/tmp/test",
            num_tasks=1,
            num_profiles=2,
            total_runs=2,
        )

        assert len(result.summaries) == 2
        assert result.num_tasks == 1
        assert result.num_profiles == 2
        assert result.total_runs == 2
        assert "pass_at_1" in result.metrics

    def test_batch_result_metrics_consumable_by_report(self):
        """Metrics from BatchResult should be consumable by write_batch_reports."""
        output_dir = _get_test_dir()
        try:
            summaries = [_make_summary()]
            metrics = compute_metrics(summaries)
            result = BatchResult(
                summaries=summaries,
                metrics=metrics,
                output_dir=str(output_dir),
                num_tasks=1,
                num_profiles=1,
                total_runs=1,
            )

            # Write using result's metrics
            write_batch_reports(output_dir, result.summaries, result.metrics)

            loaded = load_summary_json(output_dir)
            assert loaded["metrics"]["pass_at_1"] == pytest.approx(metrics["pass_at_1"])
        finally:
            _cleanup(output_dir)
