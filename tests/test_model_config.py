"""Tests for ModelConfig."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from pycodeagent.agent.model_config import ModelConfig, ModelConfigError


class TestModelConfigCreation:
    """Tests for ModelConfig instantiation."""

    def test_minimal_config(self):
        """Should create config with required fields only."""
        config = ModelConfig(provider="openai", model="gpt-4o-mini")
        assert config.provider == "openai"
        assert config.model == "gpt-4o-mini"
        assert config.api_key_env == "OPENAI_API_KEY"
        assert config.base_url is None
        assert config.timeout_seconds == 120.0
        assert config.max_retries == 3
        assert config.temperature is None
        assert config.max_output_tokens is None
        assert config.extra_headers == {}
        assert config.metadata == {}

    def test_full_config(self):
        """Should accept all fields."""
        config = ModelConfig(
            provider="openai",
            model="gpt-4o",
            api_key_env="MY_API_KEY",
            base_url="https://my-proxy.example.com/v1",
            timeout_seconds=60.0,
            max_retries=5,
            temperature=0.7,
            max_output_tokens=4096,
            extra_headers={"X-Custom": "value"},
            metadata={"run_id": "run_001"},
        )
        assert config.provider == "openai"
        assert config.model == "gpt-4o"
        assert config.api_key_env == "MY_API_KEY"
        assert config.base_url == "https://my-proxy.example.com/v1"
        assert config.timeout_seconds == 60.0
        assert config.max_retries == 5
        assert config.temperature == 0.7
        assert config.max_output_tokens == 4096
        assert config.extra_headers == {"X-Custom": "value"}
        assert config.metadata == {"run_id": "run_001"}

class TestResolveAPIKey:
    """Tests for API key resolution."""

    def test_resolve_existing_key(self):
        """Should resolve key from environment."""
        config = ModelConfig(provider="openai", model="gpt-4o", api_key_env="TEST_KEY_123")
        with patch.dict(os.environ, {"TEST_KEY_123": "sk-test-key"}):
            key = config.resolve_api_key()
            assert key == "sk-test-key"

    @pytest.mark.parametrize(
        ("env_name", "env_value"),
        [("NONEXISTENT_KEY_XYZ", None), ("EMPTY_KEY_123", "")],
    )
    def test_resolve_missing_or_empty_key(self, env_name: str, env_value: str | None):
        """Missing and empty API keys should both fail clearly."""
        config = ModelConfig(provider="openai", model="gpt-4o", api_key_env=env_name)
        os.environ.pop(env_name, None)
        env_patch = {} if env_value is None else {env_name: env_value}
        with patch.dict(os.environ, env_patch, clear=False):
            with pytest.raises(ModelConfigError, match="API key not found"):
                config.resolve_api_key()


class TestFromEnv:
    """Tests for ModelConfig.from_env class method."""

    def test_from_env_success(self):
        """Should create config and validate key exists."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}):
            config = ModelConfig.from_env()
            assert config.provider == "openai"
            assert config.model == "gpt-4o-mini"
            assert config.api_key_env == "OPENAI_API_KEY"

    def test_from_env_missing_key(self):
        """Should raise if key is missing."""
        os.environ.pop("NONEXISTENT_KEY_FOR_TEST", None)
        with pytest.raises(ModelConfigError, match="API key not found"):
            ModelConfig.from_env(api_key_env="NONEXISTENT_KEY_FOR_TEST")

    def test_from_env_with_kwargs(self):
        """Should pass through additional kwargs."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}):
            config = ModelConfig.from_env(
                temperature=0.5,
                max_output_tokens=2048,
                timeout_seconds=30.0,
            )
            assert config.temperature == 0.5
            assert config.max_output_tokens == 2048
            assert config.timeout_seconds == 30.0


class TestSerialization:
    """Tests for serialization and roundtrip."""

    def test_roundtrip_and_json_serialization(self):
        """Structured and JSON serialization should preserve all fields."""
        original = ModelConfig(
            provider="openai",
            model="gpt-4o",
            api_key_env="TEST_KEY",
            base_url="https://proxy.example.com/v1",
            timeout_seconds=45.0,
            max_retries=2,
            temperature=0.8,
            max_output_tokens=1024,
            extra_headers={"X-Test": "yes"},
            metadata={"experiment": "exp_001"},
        )
        data = original.model_dump()
        restored = ModelConfig.model_validate(data)

        assert restored.provider == original.provider
        assert restored.model == original.model
        assert restored.api_key_env == original.api_key_env
        assert restored.base_url == original.base_url
        assert restored.timeout_seconds == original.timeout_seconds
        assert restored.max_retries == original.max_retries
        assert restored.temperature == original.temperature
        assert restored.max_output_tokens == original.max_output_tokens
        assert restored.extra_headers == original.extra_headers
        assert restored.metadata == original.metadata

        json_str = original.model_dump_json()
        json_restored = ModelConfig.model_validate_json(json_str)
        assert json_restored.model == original.model
        assert json_restored.metadata == original.metadata
