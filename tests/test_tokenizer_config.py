"""Tests for TokenizerConfig."""

from __future__ import annotations

from pathlib import Path

import pytest

from pycodeagent.rl.tokenizer_config import IGNORE_INDEX, FakeTokenizerConfig, TokenizerConfig
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "tokenizer_config"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


class TestTokenizerConfigCreation:
    """Tests for TokenizerConfig instantiation."""

    def test_minimal_config_defaults(self):
        """Minimal config should expose the expected defaults."""
        config = TokenizerConfig(tokenizer_name="gpt2")
        assert config.tokenizer_name == "gpt2"
        assert config.max_length == 2048
        assert config.truncation is True
        assert config.padding == "do_not_pad"
        assert config.bos_token_id is None
        assert config.eos_token_id is None
        assert config.pad_token_id is None
        assert config.add_special_tokens is True
        assert config.metadata == {}

    def test_full_config(self):
        """Should accept all fields."""
        config = TokenizerConfig(
            tokenizer_name="Qwen/Qwen2-0.5B",
            max_length=4096,
            truncation=False,
            padding="max_length",
            bos_token_id=1,
            eos_token_id=2,
            pad_token_id=0,
            add_special_tokens=False,
            metadata={"source": "experiment_v1"},
        )
        assert config.tokenizer_name == "Qwen/Qwen2-0.5B"
        assert config.max_length == 4096
        assert config.truncation is False
        assert config.padding == "max_length"
        assert config.bos_token_id == 1
        assert config.eos_token_id == 2
        assert config.pad_token_id == 0
        assert config.add_special_tokens is False
        assert config.metadata == {"source": "experiment_v1"}

class TestIgnoreIndex:
    """Tests for IGNORE_INDEX constant."""

    def test_ignore_index_is_negative_pytorch_convention(self):
        """IGNORE_INDEX should be the standard negative ignore label."""
        assert IGNORE_INDEX == -100
        assert IGNORE_INDEX < 0


class TestSaveLoad:
    """Tests for config save/load roundtrip."""

    def test_roundtrip_preserves_all_fields_and_creates_parent_dirs(self):
        """Save/load should preserve all fields and create parent dirs."""
        test_dir = _get_test_dir()
        try:
            original = TokenizerConfig(
                tokenizer_name="test-model",
                max_length=8192,
                truncation=False,
                padding="max_length",
                bos_token_id=10,
                eos_token_id=11,
                pad_token_id=12,
                add_special_tokens=False,
                metadata={"key": "value"},
            )
            path = test_dir / "sub" / "dir" / "config.yaml"
            original.save(path)
            loaded = TokenizerConfig.load(path)

            assert loaded.tokenizer_name == original.tokenizer_name
            assert loaded.max_length == original.max_length
            assert loaded.truncation == original.truncation
            assert loaded.padding == original.padding
            assert loaded.bos_token_id == original.bos_token_id
            assert loaded.eos_token_id == original.eos_token_id
            assert loaded.pad_token_id == original.pad_token_id
            assert loaded.add_special_tokens == original.add_special_tokens
            assert loaded.metadata == original.metadata
        finally:
            _cleanup(test_dir)


class TestSerialization:
    """Tests for serialization determinism."""

    def test_serialization_outputs_are_stable(self):
        """Config should have stable dict, YAML, and JSON representations."""
        config = TokenizerConfig(tokenizer_name="gpt2", max_length=512)
        data = config.model_dump()
        assert data["tokenizer_name"] == "gpt2"
        assert data["max_length"] == 512

        yaml1 = config.model_dump_yaml()
        yaml2 = config.model_dump_yaml()
        assert yaml1 == yaml2

        import json

        json_str = TokenizerConfig(tokenizer_name="gpt2", metadata={"key": "val"}).model_dump_json()
        data = json.loads(json_str)
        assert data["tokenizer_name"] == "gpt2"


class TestFakeTokenizerConfig:
    """Tests for FakeTokenizerConfig."""

    def test_defaults_and_custom_values(self):
        """Fake tokenizer config should expose stable defaults and overrides."""
        defaults = FakeTokenizerConfig()
        custom = FakeTokenizerConfig(vocab_size=500, chars_per_token=2)
        assert defaults.vocab_size == 1000
        assert defaults.bos_token_id == 1
        assert defaults.eos_token_id == 2
        assert defaults.pad_token_id == 0
        assert defaults.unk_token_id == 3
        assert defaults.chars_per_token == 4
        assert custom.vocab_size == 500
        assert custom.chars_per_token == 2
