"""Tests for StudyReport."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.eval.study_config import StudyConfig
from pycodeagent.eval.study_report import StudyReport, write_study_report
from pycodeagent.eval.study_runner import MutationStudyRunner
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


pytestmark = [pytest.mark.slow, pytest.mark.integration]


_TEST_NAMESPACE = "study_report"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
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


def _run_minimal_study(test_dir: Path) -> tuple[Path, dict]:
    """Run a minimal study and return output dir and result data."""
    source = _make_source_repo(test_dir, "report_test", {"test.py": "def test_ok(): pass"})
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
        study_id="report_study",
        tasks_path=str(tasks_path),
        profile_modes=["base", "schema_only"],
        baseline_mode="base",
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

    return test_dir / "studies" / "report_study", result


class TestStudyReportFiles:
    """Tests for study report file writing."""

    def test_write_config(self):
        """Should write study_config.json."""
        test_dir = _get_test_dir()
        try:
            output_dir, result = _run_minimal_study(test_dir)

            report = StudyReport(output_dir)
            report.write_config(result.config)

            config_path = output_dir / "study_config.json"
            assert config_path.exists()

            # Verify it's valid JSON
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            assert data["study_id"] == "report_study"
        finally:
            _cleanup(test_dir)

    def test_write_summary(self):
        """Should write study_summary.json."""
        test_dir = _get_test_dir()
        try:
            output_dir, result = _run_minimal_study(test_dir)

            report = StudyReport(output_dir)
            report.write_summary(result)

            summary_path = output_dir / "study_summary.json"
            assert summary_path.exists()

            with open(summary_path, encoding="utf-8") as f:
                data = json.load(f)

            assert data["study_id"] == "report_study"
            assert "task_count" in data
            assert "profile_modes" in data
            assert "baseline_mode" in data
            assert "seeds" in data
            assert "baseline_metrics" in data
            assert "per_mode_deltas" in data
        finally:
            _cleanup(test_dir)

    def test_write_mode_comparison(self):
        """Should write mode_comparison.json."""
        test_dir = _get_test_dir()
        try:
            output_dir, result = _run_minimal_study(test_dir)

            report = StudyReport(output_dir)
            report.write_mode_comparison(result)

            path = output_dir / "mode_comparison.json"
            assert path.exists()

            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            assert isinstance(data, list)
            assert len(data) == 2  # base and schema_only

            # Each entry should have expected fields
            for entry in data:
                assert "mode" in entry
                assert "count" in entry
                assert "pass_at_1" in entry
                assert "avg_reward" in entry
                assert "entered_execution_rate" in entry
                assert "clean_run_pass_at_1" in entry
                assert "verifier_failed_rate" in entry
                assert "delta_pass_at_1" in entry
                assert "delta_avg_reward" in entry
        finally:
            _cleanup(test_dir)

    def test_write_seed_comparison(self):
        """Should write seed_comparison.json."""
        test_dir = _get_test_dir()
        try:
            output_dir, result = _run_minimal_study(test_dir)

            report = StudyReport(output_dir)
            report.write_seed_comparison(result)

            path = output_dir / "seed_comparison.json"
            assert path.exists()

            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            assert isinstance(data, list)
            assert len(data) == 2  # 2 seeds

            for entry in data:
                assert "seed" in entry
                assert "count" in entry
                assert "pass_at_1" in entry
                assert "avg_reward" in entry
                assert "entered_execution_rate" in entry
                assert "clean_run_pass_at_1" in entry
                assert "verifier_failed_rate" in entry
        finally:
            _cleanup(test_dir)

    def test_write_seed_variability(self):
        """Should write seed_variability.json."""
        test_dir = _get_test_dir()
        try:
            output_dir, result = _run_minimal_study(test_dir)

            report = StudyReport(output_dir)
            report.write_seed_variability(result)

            path = output_dir / "seed_variability.json"
            assert path.exists()

            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            assert isinstance(data, list)

            for entry in data:
                assert "mode" in entry
                assert "seed_count" in entry
                assert "pass_at_1_range" in entry
                assert "avg_reward_range" in entry
        finally:
            _cleanup(test_dir)

    def test_write_all(self):
        """Should write all report files."""
        test_dir = _get_test_dir()
        try:
            output_dir, result = _run_minimal_study(test_dir)

            report = StudyReport(output_dir)
            report.write_all(result)

            assert (output_dir / "study_config.json").exists()
            assert (output_dir / "study_summary.json").exists()
            assert (output_dir / "mode_comparison.json").exists()
            assert (output_dir / "seed_comparison.json").exists()
            assert (output_dir / "seed_variability.json").exists()
        finally:
            _cleanup(test_dir)


class TestWriteStudyReportConvenience:
    """Tests for write_study_report convenience function."""

    def test_write_study_report(self):
        """write_study_report should write all files."""
        test_dir = _get_test_dir()
        try:
            output_dir, result = _run_minimal_study(test_dir)

            report = write_study_report(result)

            assert (output_dir / "study_config.json").exists()
            assert (output_dir / "study_summary.json").exists()
            assert (output_dir / "mode_comparison.json").exists()
        finally:
            _cleanup(test_dir)


class TestLoadMethods:
    """Tests for load methods."""

    def test_load_config(self):
        """Should load config from study_config.json."""
        test_dir = _get_test_dir()
        try:
            output_dir, result = _run_minimal_study(test_dir)

            report = StudyReport(output_dir)
            report.write_config(result.config)

            loaded = report.load_config()
            assert loaded.study_id == result.config.study_id
        finally:
            _cleanup(test_dir)

    def test_load_summary(self):
        """Should load summary from study_summary.json."""
        test_dir = _get_test_dir()
        try:
            output_dir, result = _run_minimal_study(test_dir)

            report = StudyReport(output_dir)
            report.write_summary(result)

            loaded = report.load_summary()
            assert loaded["study_id"] == "report_study"
        finally:
            _cleanup(test_dir)

    def test_load_mode_comparison(self):
        """Should load mode comparison from mode_comparison.json."""
        test_dir = _get_test_dir()
        try:
            output_dir, result = _run_minimal_study(test_dir)

            report = StudyReport(output_dir)
            report.write_mode_comparison(result)

            loaded = report.load_mode_comparison()
            assert len(loaded) == 2
        finally:
            _cleanup(test_dir)

    def test_load_seed_comparison(self):
        """Should load seed comparison from seed_comparison.json."""
        test_dir = _get_test_dir()
        try:
            output_dir, result = _run_minimal_study(test_dir)

            report = StudyReport(output_dir)
            report.write_seed_comparison(result)

            loaded = report.load_seed_comparison()
            assert len(loaded) == 2
        finally:
            _cleanup(test_dir)


class TestBaselineComparison:
    """Tests for baseline comparison fields."""

    def test_summary_has_per_mode_deltas(self):
        """Summary should include per_mode_deltas for mutated modes."""
        test_dir = _get_test_dir()
        try:
            output_dir, result = _run_minimal_study(test_dir)

            report = StudyReport(output_dir)
            report.write_summary(result)

            summary = report.load_summary()

            assert "per_mode_deltas" in summary
            # Baseline should NOT be in per_mode_deltas (only mutated modes)
            assert "base" not in summary["per_mode_deltas"]
            # Mutated mode should be present
            assert "schema_only" in summary["per_mode_deltas"]

            # Check delta fields exist
            deltas = summary["per_mode_deltas"]["schema_only"]
            assert "delta_pass_at_1" in deltas
            assert "delta_avg_reward" in deltas
            assert "delta_entered_execution_rate" in deltas
            assert "delta_clean_run_pass_at_1" in deltas
            assert "delta_verifier_failed_rate" in deltas
        finally:
            _cleanup(test_dir)

    def test_mode_comparison_baseline_delta_zero(self):
        """Baseline mode should have zero delta vs itself."""
        test_dir = _get_test_dir()
        try:
            output_dir, result = _run_minimal_study(test_dir)

            report = StudyReport(output_dir)
            report.write_mode_comparison(result)

            comparisons = report.load_mode_comparison()

            baseline = next(c for c in comparisons if c["mode"] == "base")
            assert baseline["delta_pass_at_1"] == 0.0
            assert baseline["delta_avg_reward"] == 0.0
        finally:
            _cleanup(test_dir)


class TestRoundtrip:
    """Tests for roundtrip consistency."""

    def test_config_roundtrip(self):
        """Config should survive roundtrip."""
        test_dir = _get_test_dir()
        try:
            output_dir, result = _run_minimal_study(test_dir)

            report = StudyReport(output_dir)
            report.write_config(result.config)

            loaded = report.load_config()
            assert loaded.study_id == result.config.study_id
            assert loaded.profile_modes == result.config.profile_modes
            assert loaded.baseline_mode == result.config.baseline_mode
            assert loaded.seeds == result.config.seeds
        finally:
            _cleanup(test_dir)
