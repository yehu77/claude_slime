"""Tests for TrainConfig."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.rl.train_config import TrainConfig
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "train_config"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


class TestTrainConfigCreation:
    """Tests for TrainConfig instantiation."""

    def test_minimal_config(self):
        """Should create config with required fields only."""
        config = TrainConfig(
            run_id="test_001",
            dataset_path="/data/train.jsonl",
            output_dir="/output/test_001",
        )
        assert config.run_id == "test_001"
        assert config.dataset_path == "/data/train.jsonl"
        assert config.output_dir == "/output/test_001"
        assert config.max_steps == 1000
        assert config.batch_size == 8
        assert config.learning_rate == 1e-4
        assert config.seed == 42
        assert config.log_every == 10
        assert config.allow_empty_dataset is False
        assert config.metadata == {}

    def test_full_config(self):
        """Should accept all fields."""
        config = TrainConfig(
            run_id="exp_002",
            dataset_path="/data/train.jsonl",
            output_dir="/output/exp_002",
            max_steps=5000,
            batch_size=16,
            learning_rate=5e-5,
            seed=123,
            log_every=50,
            allow_empty_dataset=True,
            metadata={"experiment": "v1"},
        )
        assert config.run_id == "exp_002"
        assert config.max_steps == 5000
        assert config.batch_size == 16
        assert config.learning_rate == 5e-5
        assert config.seed == 123
        assert config.log_every == 50
        assert config.allow_empty_dataset is True
        assert config.metadata == {"experiment": "v1"}


class TestSaveLoad:
    """Tests for config save/load roundtrip."""

    def test_roundtrip_preserves_all_fields_and_creates_parent_dirs(self):
        """Roundtrip should preserve all active fields and create parent dirs."""
        test_dir = _get_test_dir()
        try:
            original = TrainConfig(
                run_id="full_test",
                dataset_path="/data/train.jsonl",
                output_dir="/output/full",
                max_steps=2000,
                batch_size=32,
                learning_rate=3e-4,
                seed=99,
                log_every=25,
                allow_empty_dataset=True,
                metadata={"key": "value"},
            )
            path = test_dir / "nested" / "config.json"
            original.save(path)
            loaded = TrainConfig.load(path)

            assert loaded.run_id == original.run_id
            assert loaded.dataset_path == original.dataset_path
            assert loaded.output_dir == original.output_dir
            assert loaded.max_steps == original.max_steps
            assert loaded.batch_size == original.batch_size
            assert loaded.learning_rate == original.learning_rate
            assert loaded.seed == original.seed
            assert loaded.log_every == original.log_every
            assert loaded.allow_empty_dataset == original.allow_empty_dataset
            assert loaded.metadata == original.metadata
        finally:
            _cleanup(test_dir)


class TestSerialization:
    """Tests for serialization determinism."""

    def test_serialization_is_json_friendly_and_deterministic(self):
        """Config serialization should be JSON friendly and deterministic."""
        config = TrainConfig(
            run_id="test",
            dataset_path="/data/train.jsonl",
            output_dir="/output/test",
            metadata={"key": "val"},
        )
        data = config.model_dump()
        assert data["run_id"] == "test"
        assert data["max_steps"] == 1000
        assert data["allow_empty_dataset"] is False

        json1 = config.model_dump_json()
        json2 = config.model_dump_json()
        assert json1 == json2
        assert json.loads(json1)["metadata"] == {"key": "val"}
