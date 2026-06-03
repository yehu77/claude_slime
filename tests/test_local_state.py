"""Tests for local-only storage path helpers."""

from __future__ import annotations

from pathlib import Path

from pycodeagent.dev.local_state import (
    default_hf_cache_dir,
    default_local_config_dir,
    default_model_dir,
    resolve_local_config_path,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


def _get_test_dir() -> Path:
    return make_unique_test_dir("local_state")


def test_default_subdirs_follow_local_data_dir_env(monkeypatch):
    tmp = _get_test_dir()
    try:
        local_root = tmp / "local_root"
        monkeypatch.setenv("PYCODEAGENT_LOCAL_DATA_DIR", str(local_root))
        monkeypatch.delenv("PYCODEAGENT_LOCAL_CONFIG_DIR", raising=False)
        monkeypatch.delenv("PYCODEAGENT_MODEL_DIR", raising=False)
        monkeypatch.delenv("PYCODEAGENT_HF_CACHE_DIR", raising=False)

        assert default_local_config_dir() == local_root / "configs"
        assert default_model_dir() == local_root / "models"
        assert default_hf_cache_dir() == local_root / "huggingface"
    finally:
        cleanup_test_path(tmp)


def test_resolve_local_config_path_prefers_external_candidate(monkeypatch):
    tmp = _get_test_dir()
    try:
        config_dir = tmp / "external_configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        external_path = config_dir / "mimo_v25pro.local.json"
        external_path.write_text("{}", encoding="utf-8")
        repo_fallback = tmp / "repo" / "configs" / "local" / "mimo_v25pro.local.json"
        repo_fallback.parent.mkdir(parents=True, exist_ok=True)
        repo_fallback.write_text("{}", encoding="utf-8")

        monkeypatch.setenv("PYCODEAGENT_LOCAL_CONFIG_DIR", str(config_dir))

        resolved = resolve_local_config_path(
            "mimo_v25pro.local.json",
            repo_fallback=repo_fallback,
        )

        assert resolved == external_path
    finally:
        cleanup_test_path(tmp)


def test_resolve_local_config_path_falls_back_to_repo_path(monkeypatch):
    tmp = _get_test_dir()
    try:
        repo_fallback = tmp / "repo" / "configs" / "local" / "mimo_v25pro.local.json"
        repo_fallback.parent.mkdir(parents=True, exist_ok=True)
        repo_fallback.write_text("{}", encoding="utf-8")

        monkeypatch.setenv("PYCODEAGENT_LOCAL_CONFIG_DIR", str(tmp / "missing_external"))

        resolved = resolve_local_config_path(
            "mimo_v25pro.local.json",
            repo_fallback=repo_fallback,
        )

        assert resolved == repo_fallback
    finally:
        cleanup_test_path(tmp)
