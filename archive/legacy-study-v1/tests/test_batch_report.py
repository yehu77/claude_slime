"""Tests for batch report writing and loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.eval.batch_runner import RunSummary
from pycodeagent.eval.report import (
    load_failed_cases_jsonl,
    load_runs_jsonl,
    load_summary_json,
    write_batch_reports,
    write_failed_cases_jsonl,
    write_runs_jsonl,
    write_summary_json,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "batch_report"


def _get_unique_test_dir() -> Path:
    """Get a unique test directory for the current test."""
    return make_unique_test_dir(_TEST_NAMESPACE)


def _setup_test_dir() -> Path:
    """Create a unique test directory and return it."""
    return _get_unique_test_dir()


def _cleanup_test_dir(path: Path) -> None:
    """Clean up a test directory."""
    cleanup_test_path(path)


def make_summary(
    *,
    task_id: str = "task_001",
    profile_id: str = "base",
    status: str = "completed",
    reward: float = 1.0,
    passed: bool = True,
    turns: int = 5,
    tool_calls: int = 10,
    output_dir: str = "runs/task_001__base",
    failure_reason: str = "",
    has_patch: bool = True,
    parse_errors: int = 0,
    tool_errors: int = 0,
    schema_errors: int = 0,
    apply_patch_attempted: bool = False,
    apply_patch_success: bool = False,
) -> RunSummary:
    """Helper to create a RunSummary with sensible defaults."""
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
        metadata={
            "has_patch": has_patch,
            "parse_errors": parse_errors,
            "tool_errors": tool_errors,
            "schema_errors": schema_errors,
            "apply_patch_attempted": apply_patch_attempted,
            "apply_patch_success": apply_patch_success,
        },
    )


def sample_summaries() -> list[RunSummary]:
    """Provide a sample list of RunSummary objects."""
    return [
        make_summary(
            task_id="task_001",
            profile_id="base",
            reward=1.0,
            passed=True,
        ),
        make_summary(
            task_id="task_001",
            profile_id="schema_only",
            reward=0.5,
            passed=False,
            failure_reason="verifier_failed",
            status="completed",
        ),
        make_summary(
            task_id="task_002",
            profile_id="base",
            reward=0.0,
            passed=False,
            status="error",
            failure_reason="timeout",
        ),
    ]


def sample_metrics() -> dict[str, float]:
    """Provide sample metrics."""
    return {
        "pass_at_1": 1 / 3,
        "avg_reward": 0.5,
        "avg_turns": 5.0,
        "avg_tool_calls": 10.0,
        "tool_call_parse_error_rate": 0.0,
        "invalid_schema_call_rate": 0.0,
        "patch_apply_success_rate": 1.0,
    }


class TestWriteSummaryJson:
    """Tests for write_summary_json."""

    def test_writes_file(self):
        """Should create summary.json."""
        output_dir = _setup_test_dir()
        try:
            write_summary_json(output_dir, sample_summaries(), sample_metrics())
            assert (output_dir / "summary.json").exists()
        finally:
            _cleanup_test_dir(output_dir)

    def test_json_structure(self):
        """Should have correct JSON structure."""
        output_dir = _setup_test_dir()
        try:
            write_summary_json(output_dir, sample_summaries(), sample_metrics())
            data = json.loads((output_dir / "summary.json").read_text())

            assert "timestamp" not in data
            assert data["total_runs"] == 3
            assert "metrics" in data
            assert data["metrics"]["pass_at_1"] == pytest.approx(1 / 3)
            assert "status_counts" in data
            assert "profile_counts" in data
        finally:
            _cleanup_test_dir(output_dir)

    def test_explicit_timestamp_preserved(self):
        """Explicit timestamps should still be serializable when requested."""
        output_dir = _setup_test_dir()
        try:
            write_summary_json(
                output_dir,
                sample_summaries(),
                sample_metrics(),
                timestamp="2025-01-01T00:00:00+00:00",
            )
            data = json.loads((output_dir / "summary.json").read_text())

            assert data["timestamp"] == "2025-01-01T00:00:00+00:00"
        finally:
            _cleanup_test_dir(output_dir)

    def test_status_counts(self):
        """Should count statuses correctly."""
        output_dir = _setup_test_dir()
        try:
            write_summary_json(output_dir, sample_summaries(), sample_metrics())
            data = json.loads((output_dir / "summary.json").read_text())

            # 2 completed, 1 error
            assert data["status_counts"]["completed"] == 2
            assert data["status_counts"]["error"] == 1
        finally:
            _cleanup_test_dir(output_dir)

    def test_profile_counts(self):
        """Should count profiles correctly."""
        output_dir = _setup_test_dir()
        try:
            write_summary_json(output_dir, sample_summaries(), sample_metrics())
            data = json.loads((output_dir / "summary.json").read_text())

            assert data["profile_counts"]["base"] == 2
            assert data["profile_counts"]["schema_only"] == 1
        finally:
            _cleanup_test_dir(output_dir)

    def test_passed_failed_counts(self):
        """Should count passed/failed correctly."""
        output_dir = _setup_test_dir()
        try:
            write_summary_json(output_dir, sample_summaries(), sample_metrics())
            data = json.loads((output_dir / "summary.json").read_text())

            assert data["passed_count"] == 1
            assert data["failed_count"] == 2
        finally:
            _cleanup_test_dir(output_dir)

    def test_empty_summaries(self):
        """Should handle empty summaries."""
        output_dir = _setup_test_dir()
        try:
            write_summary_json(output_dir, [], sample_metrics())
            data = json.loads((output_dir / "summary.json").read_text())

            assert data["total_runs"] == 0
            assert data["passed_count"] == 0
            assert data["failed_count"] == 0
        finally:
            _cleanup_test_dir(output_dir)


class TestWriteRunsJsonl:
    """Tests for write_runs_jsonl."""

    def test_writes_file(self):
        """Should create runs.jsonl."""
        output_dir = _setup_test_dir()
        try:
            write_runs_jsonl(output_dir, sample_summaries())
            assert (output_dir / "runs.jsonl").exists()
        finally:
            _cleanup_test_dir(output_dir)

    def test_line_count(self):
        """Should have one line per summary."""
        output_dir = _setup_test_dir()
        try:
            write_runs_jsonl(output_dir, sample_summaries())
            lines = (output_dir / "runs.jsonl").read_text().strip().split("\n")
            assert len(lines) == 3
        finally:
            _cleanup_test_dir(output_dir)

    def test_record_fields(self):
        """Each record should have the expected fields."""
        output_dir = _setup_test_dir()
        try:
            write_runs_jsonl(output_dir, sample_summaries())
            lines = (output_dir / "runs.jsonl").read_text().strip().split("\n")
            first = json.loads(lines[0])

            assert "task_id" in first
            assert "profile_id" in first
            assert "status" in first
            assert "reward" in first
            assert "passed" in first
            assert "turns" in first
            assert "tool_calls" in first
            assert "output_dir" in first
            assert "failure_reason" in first
            assert "metadata" in first
        finally:
            _cleanup_test_dir(output_dir)

    def test_record_values(self):
        """Record values should match summary."""
        output_dir = _setup_test_dir()
        try:
            write_runs_jsonl(output_dir, sample_summaries())
            lines = (output_dir / "runs.jsonl").read_text().strip().split("\n")
            first = json.loads(lines[0])

            assert first["task_id"] == "task_001"
            assert first["profile_id"] == "base"
            assert first["status"] == "completed"
            assert first["reward"] == 1.0
            assert first["passed"] is True
        finally:
            _cleanup_test_dir(output_dir)

    def test_empty_summaries(self):
        """Should handle empty summaries."""
        output_dir = _setup_test_dir()
        try:
            write_runs_jsonl(output_dir, [])
            content = (output_dir / "runs.jsonl").read_text()
            assert content == ""
        finally:
            _cleanup_test_dir(output_dir)


class TestWriteFailedCasesJsonl:
    """Tests for write_failed_cases_jsonl."""

    def test_writes_file(self):
        """Should create failed_cases.jsonl."""
        output_dir = _setup_test_dir()
        try:
            write_failed_cases_jsonl(output_dir, sample_summaries())
            assert (output_dir / "failed_cases.jsonl").exists()
        finally:
            _cleanup_test_dir(output_dir)

    def test_only_failed_cases(self):
        """Should only include failed cases."""
        output_dir = _setup_test_dir()
        try:
            write_failed_cases_jsonl(output_dir, sample_summaries())
            lines = (output_dir / "failed_cases.jsonl").read_text().strip().split("\n")
            # 2 failed: task_001/schema_only (not passed) and task_002/base (error status)
            assert len(lines) == 2
        finally:
            _cleanup_test_dir(output_dir)

    def test_failed_case_fields(self):
        """Failed case records should have expected fields."""
        output_dir = _setup_test_dir()
        try:
            write_failed_cases_jsonl(output_dir, sample_summaries())
            lines = (output_dir / "failed_cases.jsonl").read_text().strip().split("\n")
            first = json.loads(lines[0])

            assert "task_id" in first
            assert "profile_id" in first
            assert "status" in first
            assert "reward" in first
            assert "output_dir" in first
            assert "failure_reason" in first
            assert "passed" in first
        finally:
            _cleanup_test_dir(output_dir)

    def test_all_passed(self):
        """Should produce empty file when all pass."""
        output_dir = _setup_test_dir()
        try:
            summaries = [
                make_summary(task_id="t1", passed=True, status="completed"),
                make_summary(task_id="t2", passed=True, status="completed"),
            ]
            write_failed_cases_jsonl(output_dir, summaries)
            content = (output_dir / "failed_cases.jsonl").read_text()
            assert content == ""
        finally:
            _cleanup_test_dir(output_dir)

    def test_all_failed(self):
        """Should include all when all fail."""
        output_dir = _setup_test_dir()
        try:
            summaries = [
                make_summary(task_id="t1", passed=False, status="error"),
                make_summary(task_id="t2", passed=False, status="error"),
            ]
            write_failed_cases_jsonl(output_dir, summaries)
            lines = (output_dir / "failed_cases.jsonl").read_text().strip().split("\n")
            assert len(lines) == 2
        finally:
            _cleanup_test_dir(output_dir)

    def test_error_status_included_even_if_passed(self):
        """Runs with non-completed status should be included even if passed."""
        output_dir = _setup_test_dir()
        try:
            summaries = [
                make_summary(task_id="t1", passed=True, status="timeout"),
            ]
            write_failed_cases_jsonl(output_dir, summaries)
            lines = (output_dir / "failed_cases.jsonl").read_text().strip().split("\n")
            assert len(lines) == 1
        finally:
            _cleanup_test_dir(output_dir)


class TestWriteBatchReports:
    """Tests for write_batch_reports (full pipeline)."""

    def test_writes_all_files(self):
        """Should write all three report files."""
        output_dir = _setup_test_dir()
        try:
            write_batch_reports(output_dir, sample_summaries(), sample_metrics())
            assert (output_dir / "summary.json").exists()
            assert (output_dir / "runs.jsonl").exists()
            assert (output_dir / "failed_cases.jsonl").exists()
        finally:
            _cleanup_test_dir(output_dir)

    def test_creates_output_dir(self):
        """Should create output directory if it doesn't exist."""
        output_dir = _get_unique_test_dir()
        try:
            write_batch_reports(output_dir, sample_summaries(), sample_metrics())
            assert output_dir.exists()
        finally:
            _cleanup_test_dir(output_dir)


class TestLoadSummaryJson:
    """Tests for load_summary_json."""

    def test_load_from_file(self):
        """Should load from explicit file path."""
        output_dir = _setup_test_dir()
        try:
            write_summary_json(output_dir, sample_summaries(), sample_metrics())
            data = load_summary_json(output_dir / "summary.json")
            assert data["total_runs"] == 3
        finally:
            _cleanup_test_dir(output_dir)

    def test_load_from_dir(self):
        """Should load from directory (appending summary.json)."""
        output_dir = _setup_test_dir()
        try:
            write_summary_json(output_dir, sample_summaries(), sample_metrics())
            data = load_summary_json(output_dir)
            assert data["total_runs"] == 3
        finally:
            _cleanup_test_dir(output_dir)


class TestLoadRunsJsonl:
    """Tests for load_runs_jsonl."""

    def test_load_from_file(self):
        """Should load from explicit file path."""
        output_dir = _setup_test_dir()
        try:
            write_runs_jsonl(output_dir, sample_summaries())
            runs = load_runs_jsonl(output_dir / "runs.jsonl")
            assert len(runs) == 3
        finally:
            _cleanup_test_dir(output_dir)

    def test_load_from_dir(self):
        """Should load from directory (appending runs.jsonl)."""
        output_dir = _setup_test_dir()
        try:
            write_runs_jsonl(output_dir, sample_summaries())
            runs = load_runs_jsonl(output_dir)
            assert len(runs) == 3
        finally:
            _cleanup_test_dir(output_dir)

    def test_roundtrip(self):
        """Write then load should preserve data."""
        output_dir = _setup_test_dir()
        try:
            write_runs_jsonl(output_dir, sample_summaries())
            runs = load_runs_jsonl(output_dir)

            assert runs[0]["task_id"] == "task_001"
            assert runs[0]["reward"] == 1.0
            assert runs[0]["passed"] is True
            assert runs[1]["reward"] == 0.5
            assert runs[1]["passed"] is False
        finally:
            _cleanup_test_dir(output_dir)


class TestLoadFailedCasesJsonl:
    """Tests for load_failed_cases_jsonl."""

    def test_load_from_file(self):
        """Should load from explicit file path."""
        output_dir = _setup_test_dir()
        try:
            write_failed_cases_jsonl(output_dir, sample_summaries())
            cases = load_failed_cases_jsonl(output_dir / "failed_cases.jsonl")
            assert len(cases) == 2
        finally:
            _cleanup_test_dir(output_dir)

    def test_load_from_dir(self):
        """Should load from directory (appending failed_cases.jsonl)."""
        output_dir = _setup_test_dir()
        try:
            write_failed_cases_jsonl(output_dir, sample_summaries())
            cases = load_failed_cases_jsonl(output_dir)
            assert len(cases) == 2
        finally:
            _cleanup_test_dir(output_dir)

    def test_roundtrip(self):
        """Write then load should preserve data."""
        output_dir = _setup_test_dir()
        try:
            write_failed_cases_jsonl(output_dir, sample_summaries())
            cases = load_failed_cases_jsonl(output_dir)

            assert all(not c["passed"] or c["status"] != "completed" for c in cases)
        finally:
            _cleanup_test_dir(output_dir)
