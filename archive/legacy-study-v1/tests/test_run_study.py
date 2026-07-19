"""Tests for run_study entrypoint and first mutation sensitivity study config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.agent.mimo_native_client import MimoNativeToolClient
from pycodeagent.eval.run_study import (
    run_study,
    run_study_from_config,
    run_study_from_provider_config,
)
from pycodeagent.eval.study_config import StudyConfig
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


pytestmark = [pytest.mark.slow, pytest.mark.integration]


_TEST_NAMESPACE = "run_study"

# Path to the checked-in first study config
_FIRST_STUDY_CONFIG = Path(__file__).parent.parent / "configs/studies/first_mutation_sensitivity.json"


def _get_test_dir() -> Path:
    """Get a unique test output directory."""
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    """Clean up a specific test directory."""
    cleanup_test_path(path)


def _make_fake_client_factory() -> callable:
    """Create a fake client factory with a simple finish response."""
    responses = [
        {
            "transport_mode": "native_tool_calling",
            "assistant_text": "",
            "tool_calls": [
                {
                    "call_id": "c1",
                    "name": "finish",
                    "arguments_raw": '{"answer":"Task completed"}',
                    "arguments_obj": {"answer": "Task completed"},
                    "source": "native",
                }
            ],
            "finish_reason": "tool_calls",
        }
    ]
    return lambda: FakeLLMClient(responses=responses)


class TestFirstStudyConfigSanity:
    """Tests for the checked-in first mutation sensitivity study config."""

    def test_config_file_exists(self):
        """The first study config file should exist."""
        assert _FIRST_STUDY_CONFIG.exists(), f"Config file not found: {_FIRST_STUDY_CONFIG}"

    def test_config_loads_successfully(self):
        """The config should load through StudyConfig."""
        config = StudyConfig.load(_FIRST_STUDY_CONFIG)
        assert config.study_id == "first_mutation_sensitivity"

    def test_config_points_to_existing_tasks(self):
        """The tasks_path should point to an existing file."""
        config = StudyConfig.load(_FIRST_STUDY_CONFIG)
        repo_root = _FIRST_STUDY_CONFIG.parent.parent.parent
        tasks_path = repo_root / config.tasks_path
        assert tasks_path.exists(), f"Tasks file not found: {tasks_path}"

    def test_baseline_in_profile_modes(self):
        """The baseline_mode should be in profile_modes."""
        config = StudyConfig.load(_FIRST_STUDY_CONFIG)
        assert config.baseline_mode in config.profile_modes

    def test_has_mutated_modes(self):
        """There should be at least one non-baseline mode."""
        config = StudyConfig.load(_FIRST_STUDY_CONFIG)
        mutated = config.get_mutated_modes()
        assert len(mutated) >= 1, "Expected at least one mutated mode"
        assert "base" not in mutated, "base should not be in mutated modes"

    def test_has_multiple_seeds(self):
        """The config should have multiple seeds for variability analysis."""
        config = StudyConfig.load(_FIRST_STUDY_CONFIG)
        assert len(config.seeds) >= 2, "Expected at least 2 seeds for variability"

    def test_has_multiple_profile_modes(self):
        """The config should have multiple profile modes."""
        config = StudyConfig.load(_FIRST_STUDY_CONFIG)
        assert len(config.profile_modes) >= 3, "Expected at least 3 profile modes"


class TestRunStudyEntrypoint:
    """Tests for the run_study entrypoint functions."""

    def test_run_study_from_config_with_fake_client(self):
        """Should run study from config file with fake client."""
        test_dir = _get_test_dir()
        try:
            config = StudyConfig.load(_FIRST_STUDY_CONFIG)
            # Override output to test dir, limit tasks for speed
            config.output_root = str(test_dir / "studies")
            config.max_tasks = 1  # Just one task for speed
            config.seeds = [0]  # Just one seed for speed
            config.profile_modes = ["base", "schema_only"]  # Just two modes for speed

            result = run_study(config, client_factory=_make_fake_client_factory())

            # Check result
            assert result.config.study_id == config.study_id
            assert result.task_count == 1
            assert len(result.experiment_results) == 2  # base + schema_only
            assert len(result.mode_comparisons) == 2

        finally:
            _cleanup(test_dir)

    def test_run_study_from_config_path(self):
        """Should run study from config file path."""
        test_dir = _get_test_dir()
        try:
            # Load config but minimize for speed and path length
            config = StudyConfig.load(_FIRST_STUDY_CONFIG)
            config.output_root = str(test_dir / "studies")
            config.max_tasks = 1
            config.seeds = [0]
            config.profile_modes = ["base", "schema_only"]

            result = run_study(config, client_factory=_make_fake_client_factory())

            assert result is not None
            assert result.config.study_id == "first_mutation_sensitivity"

        finally:
            _cleanup(test_dir)

    def test_output_files_exist(self):
        """Study report files should be written."""
        test_dir = _get_test_dir()
        try:
            config = StudyConfig.load(_FIRST_STUDY_CONFIG)
            config.output_root = str(test_dir / "studies")
            config.max_tasks = 1
            config.seeds = [0]
            config.profile_modes = ["base"]

            result = run_study(config, client_factory=_make_fake_client_factory())

            output_dir = Path(result.output_dir)

            # Check expected report files
            assert (output_dir / "study_config.json").exists()
            assert (output_dir / "study_summary.json").exists()
            assert (output_dir / "mode_comparison.json").exists()
            assert (output_dir / "seed_comparison.json").exists()
            assert (output_dir / "seed_variability.json").exists()

        finally:
            _cleanup(test_dir)

    def test_study_summary_contents(self):
        """Study summary should contain expected fields."""
        test_dir = _get_test_dir()
        try:
            config = StudyConfig.load(_FIRST_STUDY_CONFIG)
            config.output_root = str(test_dir / "studies")
            config.max_tasks = 1
            config.seeds = [0]
            config.profile_modes = ["base", "schema_only"]

            result = run_study(config, client_factory=_make_fake_client_factory())

            # Load the summary
            summary_path = Path(result.output_dir) / "study_summary.json"
            with open(summary_path, encoding="utf-8") as f:
                summary = json.load(f)

            assert summary["study_id"] == config.study_id
            assert "task_count" in summary
            assert "baseline_metrics" in summary
            assert "per_mode_deltas" in summary
            assert "experiment_output_dirs" in summary

        finally:
            _cleanup(test_dir)

    def test_run_study_from_provider_config_builds_real_client_factory(self, monkeypatch):
        """Provider-config study wrapper should dispatch through a real client factory."""
        test_dir = _get_test_dir()
        try:
            captured: dict[str, object] = {}
            provider_config_path = test_dir / "real_provider_runtime.local.json"
            provider_config_path.write_text(
                json.dumps(
                    {
                        "client_mode": "mimo_native_tools",
                        "model": "mimo-v2.5-pro",
                        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                        "api_key_env": "PYCODEAGENT_API_KEY",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            def fake_run_study_from_config(config_path, client_factory, output_dir=None):
                captured["config_path"] = config_path
                captured["output_dir"] = output_dir
                captured["client_factory"] = client_factory
                return _fake_result(output_dir=str(output_dir or "runs/out"))

            monkeypatch.setattr(
                "pycodeagent.eval.run_study.run_study_from_config",
                fake_run_study_from_config,
            )

            result = run_study_from_provider_config(
                _FIRST_STUDY_CONFIG,
                provider_config_path,
                output_dir=test_dir / "study_output",
            )

            client = captured["client_factory"]()
            assert isinstance(client, MimoNativeToolClient)
            assert client.runtime_provenance()["base_url"] == "https://token-plan-cn.xiaomimimo.com/v1"
            assert captured["config_path"] == _FIRST_STUDY_CONFIG
            assert Path(result.output_dir) == test_dir / "study_output"
        finally:
            _cleanup(test_dir)


class TestStudyIntegration:
    """End-to-end integration tests."""

    def test_full_study_smoke(self):
        """Smoke test: load the real config and run a minimal study end-to-end."""
        test_dir = _get_test_dir()
        try:
            config = StudyConfig.load(_FIRST_STUDY_CONFIG)
            config.output_root = str(test_dir / "studies")
            # Minimal study for speed
            config.max_tasks = 2
            config.seeds = [0]
            config.profile_modes = ["base", "name_only", "schema_only"]

            result = run_study(config, client_factory=_make_fake_client_factory())

            # Verify result structure
            assert result.task_count == 2
            assert len(result.experiment_results) == 3

            # Verify each experiment has summaries
            for mode, exp_result in result.experiment_results.items():
                assert len(exp_result.summaries) == 2  # 2 tasks * 1 seed * 1 mode

            # Verify mode comparisons have deltas
            baseline_comp = next(c for c in result.mode_comparisons if c.mode == "base")
            assert baseline_comp.delta_pass_at_1 == 0.0  # Baseline delta is zero

            mutated_comps = [c for c in result.mode_comparisons if c.mode != "base"]
            assert len(mutated_comps) == 2  # name_only and schema_only

        finally:
            _cleanup(test_dir)

    def test_deterministic_with_same_fake_responses(self):
        """Running twice with same fake responses should give same results."""
        test_dir = _get_test_dir()
        try:
            config = StudyConfig.load(_FIRST_STUDY_CONFIG)
            config.output_root = str(test_dir / "studies")
            config.max_tasks = 1
            config.seeds = [0]
            config.profile_modes = ["base"]

            # Run twice
            result1 = run_study(config, client_factory=_make_fake_client_factory())

            # Clean and reconfigure for second run
            config.study_id = "first_mutation_sensitivity_v2"
            result2 = run_study(config, client_factory=_make_fake_client_factory())

            # Results should be identical (same fake responses)
            assert result1.task_count == result2.task_count
            assert len(result1.mode_comparisons) == len(result2.mode_comparisons)
            for c1, c2 in zip(result1.mode_comparisons, result2.mode_comparisons):
                assert c1.mode == c2.mode
                assert c1.pass_at_1 == c2.pass_at_1
                assert c1.avg_reward == c2.avg_reward

        finally:
            _cleanup(test_dir)


class TestStudyReportRoundtrip:
    """Tests for study report load/save roundtrip."""

    def test_config_roundtrip(self):
        """Study config should survive roundtrip."""
        test_dir = _get_test_dir()
        try:
            config = StudyConfig.load(_FIRST_STUDY_CONFIG)
            config.output_root = str(test_dir / "studies")
            config.max_tasks = 1
            config.seeds = [0]
            config.profile_modes = ["base"]

            result = run_study(config, client_factory=_make_fake_client_factory())

            # Load the saved config
            saved_config_path = Path(result.output_dir) / "study_config.json"
            loaded_config = StudyConfig.load(saved_config_path)

            assert loaded_config.study_id == config.study_id
            assert loaded_config.tasks_path == config.tasks_path
            assert loaded_config.profile_modes == config.profile_modes
            assert loaded_config.seeds == config.seeds

        finally:
            _cleanup(test_dir)


class TestOutputDirOverride:
    """Tests for output_dir override behavior in run_study_from_config."""

    def test_output_dir_override_exact_path(self):
        """output_dir should be the exact output directory, not nested."""
        test_dir = _get_test_dir()
        try:
            # Define the exact output path we want
            exact_output = test_dir / "my_custom_output"

            result = run_study_from_config(
                _FIRST_STUDY_CONFIG,
                client_factory=_make_fake_client_factory(),
                output_dir=exact_output,
            )

            # Result output_dir should match exactly
            assert Path(result.output_dir) == exact_output

            # Study report files should exist in exact_output
            assert (exact_output / "study_config.json").exists()
            assert (exact_output / "study_summary.json").exists()

        finally:
            _cleanup(test_dir)

    def test_output_dir_override_preserves_study_id(self):
        """output_dir override must NOT change study_id."""
        test_dir = _get_test_dir()
        try:
            # Load config to get original study_id
            original_config = StudyConfig.load(_FIRST_STUDY_CONFIG)
            original_study_id = original_config.study_id

            # Use a custom output path with different name
            custom_output = test_dir / "custom_output_name"

            result = run_study_from_config(
                _FIRST_STUDY_CONFIG,
                client_factory=_make_fake_client_factory(),
                output_dir=custom_output,
            )

            # study_id must remain unchanged
            assert result.config.study_id == original_study_id
            assert result.config.study_id == "first_mutation_sensitivity"
            assert Path(result.output_dir) == custom_output

        finally:
            _cleanup(test_dir)

    def test_saved_config_preserves_study_id(self):
        """Saved study_config.json must preserve original study_id."""
        test_dir = _get_test_dir()
        try:
            custom_output = test_dir / "my_output"

            result = run_study_from_config(
                _FIRST_STUDY_CONFIG,
                client_factory=_make_fake_client_factory(),
                output_dir=custom_output,
            )

            # Load the saved config
            saved_config_path = custom_output / "study_config.json"
            saved_config = StudyConfig.load(saved_config_path)

            # study_id must be the original, not derived from output path
            assert saved_config.study_id == "first_mutation_sensitivity"

        finally:
            _cleanup(test_dir)

    def test_saved_summary_preserves_study_id(self):
        """Saved study_summary.json must preserve original study_id."""
        test_dir = _get_test_dir()
        try:
            custom_output = test_dir / "my_summary_output"

            result = run_study_from_config(
                _FIRST_STUDY_CONFIG,
                client_factory=_make_fake_client_factory(),
                output_dir=custom_output,
            )

            # Load the summary
            summary_path = custom_output / "study_summary.json"
            with open(summary_path, encoding="utf-8") as f:
                summary = json.load(f)

            # study_id must be the original
            assert summary["study_id"] == "first_mutation_sensitivity"

        finally:
            _cleanup(test_dir)

    def test_output_dir_not_nested_under_study_id(self):
        """output_dir should not create extra nesting under study_id."""
        test_dir = _get_test_dir()
        try:
            exact_output = test_dir / "direct_output"

            result = run_study_from_config(
                _FIRST_STUDY_CONFIG,
                client_factory=_make_fake_client_factory(),
                output_dir=exact_output,
            )

            # Files should be in exact_output, not exact_output/study_id
            assert (exact_output / "study_config.json").exists()
            # Should NOT exist under a nested study_id directory
            nested_path = exact_output / "first_mutation_sensitivity"
            assert not (nested_path / "study_config.json").exists()

        finally:
            _cleanup(test_dir)

    def test_default_behavior_no_override(self):
        """Without output_dir, default behavior should work (output_root / study_id)."""
        test_dir = _get_test_dir()
        try:
            config = StudyConfig.load(_FIRST_STUDY_CONFIG)
            config.output_root = str(test_dir / "studies")
            config.max_tasks = 1
            config.seeds = [0]
            config.profile_modes = ["base"]

            result = run_study(config, client_factory=_make_fake_client_factory())

            # Output should be at output_root / study_id
            expected_output = test_dir / "studies" / config.study_id
            assert Path(result.output_dir) == expected_output

        finally:
            _cleanup(test_dir)
