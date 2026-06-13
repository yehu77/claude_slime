"""Managed paths for local-only configs, weights, and caches."""

from __future__ import annotations

import os
from pathlib import Path


LOCAL_DATA_DIR_ENV = "PYCODEAGENT_LOCAL_DATA_DIR"
LOCAL_CONFIG_DIR_ENV = "PYCODEAGENT_LOCAL_CONFIG_DIR"
MODEL_DIR_ENV = "PYCODEAGENT_MODEL_DIR"
HF_CACHE_DIR_ENV = "PYCODEAGENT_HF_CACHE_DIR"


def default_local_data_dir(*, home: Path | None = None) -> Path:
    """Return the preferred machine-local storage root."""
    override = os.environ.get(LOCAL_DATA_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()

    user_home = (home or Path.home()).expanduser()
    if os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        if local_appdata:
            return Path(local_appdata) / "pycodeagent"
        return user_home / "AppData" / "Local" / "pycodeagent"
    return user_home / ".cache" / "pycodeagent"


def default_local_config_dir(*, home: Path | None = None) -> Path:
    """Return the preferred directory for machine-local config files."""
    override = os.environ.get(LOCAL_CONFIG_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return default_local_data_dir(home=home) / "configs"


def default_model_dir(*, home: Path | None = None) -> Path:
    """Return the preferred directory for local model weights."""
    override = os.environ.get(MODEL_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return default_local_data_dir(home=home) / "models"


def default_hf_cache_dir(*, home: Path | None = None) -> Path:
    """Return the preferred directory for Hugging Face cache data."""
    override = os.environ.get(HF_CACHE_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return default_local_data_dir(home=home) / "huggingface"


def resolve_local_config_path(
    filename: str,
    *,
    repo_fallback: Path | str | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve a machine-local config path, keeping a repo fallback for compatibility."""
    candidate = default_local_config_dir(home=home) / filename
    if candidate.exists():
        return candidate

    if repo_fallback is not None:
        fallback = Path(repo_fallback)
        if fallback.exists():
            return fallback

    return candidate
