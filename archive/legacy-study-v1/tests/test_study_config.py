"""Tests for StudyConfig."""

from __future__ import annotations

from pathlib import Path

import pytest

from pycodeagent.eval.study_config import StudyConfig
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "study_config"
_PROJECT_ROOT = Path(__file__).parent.parent
_SCHEMA_ATTRIBUTION_CONFIG = _PROJECT_ROOT / "configs" / "studies" / "schema_failure_attribution_v1.json"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


class TestStudyConfigCreation:
    """Tests for StudyConfig instantiation."""

    def test_minimal_config_defaults(self):
        """Minimal config should expose the expected defaults."""
        config = StudyConfig(
            study_id="study_001",
            tasks_path="/data/tasks.jsonl",
        )
        assert config.study_id == "study_001"
        assert config.tasks_path == "/data/tasks.jsonl"
        assert config.profile_modes == ["base"]
        assert config.baseline_mode == "base"
        assert config.seeds == [0]
        assert config.output_root == "studies"
        assert config.max_tasks is None
        assert config.task_ids is None
        assert config.notes == ""
        assert config.metadata == {}

class TestSaveLoad:
    """Tests for config save/load roundtrip."""

    def test_roundtrip_preserves_all_fields(self):
        """Should preserve all fields through save/load."""
        test_dir = _get_test_dir()
        try:
            original = StudyConfig(
                study_id="full_roundtrip",
                tasks_path="/data/tasks.jsonl",
                profile_modes=["base", "name_only"],
                baseline_mode="base",
                seeds=[1, 2, 3],
                output_root="custom_studies",
                max_tasks=5,
                task_ids=["a", "b"],
                notes="Test notes",
                metadata={"key": "value"},
            )
            path = test_dir / "config.json"
            original.save(path)
            loaded = StudyConfig.load(path)

            assert loaded.study_id == original.study_id
            assert loaded.tasks_path == original.tasks_path
            assert loaded.profile_modes == original.profile_modes
            assert loaded.baseline_mode == original.baseline_mode
            assert loaded.seeds == original.seeds
            assert loaded.output_root == original.output_root
            assert loaded.max_tasks == original.max_tasks
            assert loaded.task_ids == original.task_ids
            assert loaded.notes == original.notes
            assert loaded.metadata == original.metadata
        finally:
            _cleanup(test_dir)


class TestValidation:
    """Tests for config validation."""

    def test_validate_baseline_enforces_membership(self):
        """Baseline validation should accept valid configs and reject invalid ones."""
        valid = StudyConfig(
            study_id="valid_baseline",
            tasks_path="/data/tasks.jsonl",
            profile_modes=["base", "schema_only"],
            baseline_mode="base",
        )
        valid.validate_baseline()

        invalid = StudyConfig(
            study_id="invalid_baseline",
            tasks_path="/data/tasks.jsonl",
            profile_modes=["schema_only", "name_only"],
            baseline_mode="base",
        )
        with pytest.raises(ValueError, match="baseline_mode"):
            invalid.validate_baseline()


class TestUtilityMethods:
    """Tests for utility methods."""

    def test_output_paths(self):
        """Path helpers should derive stable output locations."""
        config = StudyConfig(
            study_id="my_study",
            tasks_path="/data/tasks.jsonl",
            output_root="studies",
        )
        assert config.get_output_dir() == Path("studies/my_study")
        assert config.get_experiments_dir() == Path("studies/my_study/experiments")

    def test_get_mutated_modes(self):
        """Mutated-mode helper should exclude baseline and preserve order."""
        config = StudyConfig(
            study_id="mutation_test",
            tasks_path="/data/tasks.jsonl",
            profile_modes=["base", "schema_only", "name_only"],
            baseline_mode="base",
        )
        baseline_only = StudyConfig(
            study_id="only_baseline",
            tasks_path="/data/tasks.jsonl",
            profile_modes=["base"],
            baseline_mode="base",
        )
        assert config.get_mutated_modes() == ["schema_only", "name_only"]
        assert baseline_only.get_mutated_modes() == []


class TestDeterminism:
    """Tests for deterministic serialization."""

    def test_deterministic_json(self):
        """Same config should produce same JSON."""
        config = StudyConfig(
            study_id="determinism_test",
            tasks_path="/data/tasks.jsonl",
            profile_modes=["base", "schema_only"],
            seeds=[0, 42],
        )
        json1 = config.model_dump_json()
        json2 = config.model_dump_json()
        assert json1 == json2


class TestCheckedInStudyConfigs:
    """Tests for checked-in study config files."""

    def test_schema_failure_attribution_config_loads(self):
        """schema_failure_attribution_v1 should load with expected modes and seeds."""
        config = StudyConfig.load(_SCHEMA_ATTRIBUTION_CONFIG)
        assert config.study_id == "schema_failure_attribution_v1"
        assert config.profile_modes == [
            "base",
            "description_only",
            "schema_only",
            "name_description_schema",
        ]
        assert config.baseline_mode == "base"
        assert config.seeds == [0, 1, 2, 3, 4]
