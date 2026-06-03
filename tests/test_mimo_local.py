"""Tests for local MIMO config helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pycodeagent.dev.mimo_local import (
    build_openai_compatible_model_config,
    load_mimo_local_config,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


def _get_test_dir() -> Path:
    return make_unique_test_dir("mimo_local")


def test_load_local_config_accepts_inline_api_key():
    tmp = _get_test_dir()
    try:
        config_path = tmp / "mimo.local.json"
        config_path.write_text(
            """
            {
              "api_key": "inline-secret",
              "base_url": "https://example.invalid/v1"
            }
            """.strip(),
            encoding="utf-8",
        )

        with pytest.warns(UserWarning, match="contains inline api_key"):
            config = load_mimo_local_config(
                config_path,
                default_api_key_env="MIMO_API_KEY",
            )

        assert config["resolved_api_key"] == "inline-secret"
        assert config["api_key_env"] == "MIMO_API_KEY"
        assert config["base_url"] == "https://example.invalid/v1"
    finally:
        cleanup_test_path(tmp)


def test_load_local_config_accepts_env_backed_secret(monkeypatch: pytest.MonkeyPatch):
    tmp = _get_test_dir()
    try:
        config_path = tmp / "mimo.local.json"
        config_path.write_text(
            """
            {
              "api_key_env": "CUSTOM_MIMO_KEY",
              "base_url": "https://example.invalid/v1"
            }
            """.strip(),
            encoding="utf-8",
        )
        monkeypatch.setenv("CUSTOM_MIMO_KEY", "env-secret")

        config = load_mimo_local_config(config_path, default_api_key_env="MIMO_API_KEY")

        assert config["resolved_api_key"] == "env-secret"
        assert config["api_key_env"] == "CUSTOM_MIMO_KEY"
    finally:
        cleanup_test_path(tmp)


def test_load_local_config_requires_secret_and_base_url():
    tmp = _get_test_dir()
    try:
        config_path = tmp / "mimo.local.json"
        config_path.write_text("{}", encoding="utf-8")

        with pytest.raises(ValueError, match="Missing base_url"):
            load_mimo_local_config(config_path)
    finally:
        cleanup_test_path(tmp)


def test_build_model_config_uses_resolved_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MIMO_API_KEY", raising=False)

    model_config = build_openai_compatible_model_config(
        {
            "resolved_api_key": "resolved-secret",
            "api_key_env": "MIMO_API_KEY",
            "base_url": "https://example.invalid/v1",
            "timeout_seconds": 30,
            "max_retries": 2,
        },
        model_name="mimo-v2.5-pro",
    )

    assert os.environ["MIMO_API_KEY"] == "resolved-secret"
    assert model_config.api_key_env == "MIMO_API_KEY"
    assert model_config.base_url == "https://example.invalid/v1"
    assert model_config.model == "mimo-v2.5-pro"


def test_load_local_config_warns_for_repo_local_path(monkeypatch: pytest.MonkeyPatch):
    tmp = _get_test_dir()
    try:
        repo_root = tmp / "repo_root"
        config_path = repo_root / "configs" / "local" / "mimo_v25pro.local.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            """
            {
              "api_key_env": "CUSTOM_MIMO_KEY",
              "base_url": "https://example.invalid/v1"
            }
            """.strip(),
            encoding="utf-8",
        )
        monkeypatch.setenv("CUSTOM_MIMO_KEY", "env-secret")
        monkeypatch.setattr("pycodeagent.dev.mimo_local._repo_root_from", lambda: repo_root)

        with pytest.warns(UserWarning, match="lives inside the source tree"):
            config = load_mimo_local_config(config_path)

        assert config["resolved_api_key"] == "env-secret"
    finally:
        cleanup_test_path(tmp)
