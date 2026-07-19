"""Tests for ExperimentConfig."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.eval.experiment_config import ExperimentConfig
from pycodeagent.eval.layout import mode_dir_name
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "experiment_config"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


class TestExperimentConfigCreation:
    """Tests for config creation."""

    def test_minimal_config_defaults_and_no_timestamp(self):
        """Minimal config should expose stable defaults and no runtime timestamp."""
        config = ExperimentConfig(
            experiment_id="exp_001",
            tasks_path="tasks.jsonl",
        )
        assert config.experiment_id == "exp_001"
        assert config.tasks_path == "tasks.jsonl"
        assert config.profile_modes == ["base"]
        assert config.seeds == [0]
        assert config.output_root == "experiments"
        assert config.max_tasks is None
        assert config.task_ids is None
        assert config.notes == ""
        assert config.metadata == {}
        assert not hasattr(config, "created_at")

    def test_full_config_accepts_optional_fields(self):
        """Optional fields should be stored without additional normalization."""
        config = ExperimentConfig(
            experiment_id="exp_002",
            tasks_path="datasets/tasks/toy_tasks.jsonl",
            profile_modes=["base", "schema_only", "name_description_schema"],
            seeds=[0, 42, 123],
            output_root="experiments",
            max_tasks=10,
            task_ids=["task_001", "task_002"],
            notes="Testing schema mutation",
            metadata={"author": "test", "purpose": "research"},
        )
        assert config.experiment_id == "exp_002"
        assert len(config.profile_modes) == 3
        assert len(config.seeds) == 3
        assert config.max_tasks == 10
        assert len(config.task_ids) == 2
        assert "author" in config.metadata


class TestExperimentConfigSaveLoad:
    """Tests for config save/load roundtrip."""

    def test_roundtrip_preserves_all_fields(self):
        """Save/load should preserve all fields exactly."""
        output_dir = _get_test_dir()
        try:
            original = ExperimentConfig(
                experiment_id="exp_roundtrip",
                tasks_path="path/to/tasks.jsonl",
                profile_modes=["base", "name_only", "schema_only"],
                seeds=[0, 1, 2],
                output_root="custom_output",
                max_tasks=20,
                task_ids=["a", "b", "c"],
                notes="complex config",
                metadata={"key": "value", "number": 42},
            )
            path = output_dir / "config.json"
            original.save(path)
            loaded = ExperimentConfig.load(path)

            assert loaded.experiment_id == original.experiment_id
            assert loaded.tasks_path == original.tasks_path
            assert loaded.profile_modes == original.profile_modes
            assert loaded.seeds == original.seeds
            assert loaded.output_root == original.output_root
            assert loaded.max_tasks == original.max_tasks
            assert loaded.task_ids == original.task_ids
            assert loaded.notes == original.notes
            assert loaded.metadata == original.metadata
        finally:
            _cleanup(output_dir)

    def test_deterministic_across_instances(self):
        """Two configs with same fields should produce identical JSON.

        This is the key reproducibility guarantee: the same logical config
        created at different times should serialize identically.
        """
        output_dir = _get_test_dir()
        try:
            # Create two configs with identical fields at different times
            config1 = ExperimentConfig(
                experiment_id="exp_same",
                tasks_path="tasks.jsonl",
                profile_modes=["base", "schema_only"],
                seeds=[0, 42],
                notes="test",
            )
            config2 = ExperimentConfig(
                experiment_id="exp_same",
                tasks_path="tasks.jsonl",
                profile_modes=["base", "schema_only"],
                seeds=[0, 42],
                notes="test",
            )

            path1 = output_dir / "config1.json"
            path2 = output_dir / "config2.json"
            config1.save(path1)
            config2.save(path2)

            assert path1.read_text() == path2.read_text()
        finally:
            _cleanup(output_dir)

    def test_no_timestamp_in_serialized_json(self):
        """Serialized config should not contain timestamp noise."""
        output_dir = _get_test_dir()
        try:
            config = ExperimentConfig(
                experiment_id="exp_no_ts",
                tasks_path="tasks.jsonl",
            )
            path = output_dir / "config.json"
            config.save(path)

            data = json.loads(path.read_text())
            assert "created_at" not in data
            assert "timestamp" not in data
        finally:
            _cleanup(output_dir)


class TestExperimentConfigDirectories:
    """Tests for directory path helpers."""

    def test_directory_helpers(self):
        """Directory helper methods should compose into a stable layout."""
        config = ExperimentConfig(
            experiment_id="my_exp",
            tasks_path="tasks.jsonl",
            output_root="experiments",
        )
        assert config.get_output_dir() == Path("experiments/my_exp")
        assert config.get_runs_dir() == Path("experiments/my_exp/runs")
        assert config.get_seed_dir(42) == Path("experiments/my_exp/runs/seed_42")
        assert config.get_mode_dir(42, "schema_only") == Path(
            "experiments/my_exp/runs/seed_42/schema"
        )
        assert config.get_mode_dir(42, "schema_only").name == mode_dir_name("schema_only")
        assert config.get_mode_dir(42, "argument_rename").name == "arg"
        assert config.get_mode_dir(42, "schema_flat_to_nested").name == "nested"
        assert config.get_mode_dir(42, "tool_reorder").name == "order"


class TestExperimentConfigCombinations:
    """Tests for combination counting."""

    def test_count_combinations(self):
        """Combination counting should scale with tasks, modes, and seeds."""
        single = ExperimentConfig(
            experiment_id="exp_single",
            tasks_path="tasks.jsonl",
            profile_modes=["base"],
            seeds=[0],
        )
        multiple = ExperimentConfig(
            experiment_id="exp_multi",
            tasks_path="tasks.jsonl",
            profile_modes=["base", "schema_only"],
            seeds=[0, 42],
        )
        empty_seeds = ExperimentConfig(
            experiment_id="exp_empty",
            tasks_path="tasks.jsonl",
            profile_modes=["base"],
            seeds=[],
        )
        assert single.count_combinations(task_count=1) == 1
        assert multiple.count_combinations(task_count=3) == 12
        assert empty_seeds.count_combinations(task_count=5) == 0
