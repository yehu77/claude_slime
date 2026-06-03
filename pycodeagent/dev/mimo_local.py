"""Helpers for local MIMO/OpenAI-compatible study configuration."""

from __future__ import annotations

import json
import os
import warnings
from pathlib import Path
from typing import Any

from pycodeagent.agent import ModelConfig
from pycodeagent.dev.local_state import default_local_config_dir


def load_mimo_local_config(
    path: Path | str,
    *,
    example_path: Path | str | None = None,
    default_api_key_env: str = "MIMO_API_KEY",
) -> dict[str, Any]:
    """Load a local config file and resolve the API key safely.

    The config may either:
    - provide ``api_key`` inline, or
    - provide ``api_key_env`` and rely on an environment variable.
    """
    path = Path(path)
    if not path.exists():
        message = f"Local config not found: {path}."
        if example_path is not None:
            message += f" Copy {example_path} to {path} and fill the non-secret fields."
        raise FileNotFoundError(message)

    _warn_if_repo_local_config(path)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Local config must be a JSON object: {path}")

    config = dict(data)
    config["base_url"] = _require_string_field(config, "base_url", path=path)
    resolved_api_key, api_key_env = _resolve_secret(
        config,
        value_key="api_key",
        env_key="api_key_env",
        default_env=default_api_key_env,
        path=path,
    )
    config["resolved_api_key"] = resolved_api_key
    config["api_key_env"] = api_key_env
    return config


def build_openai_compatible_model_config(
    local_config: dict[str, Any],
    *,
    model_name: str,
) -> ModelConfig:
    """Build a ModelConfig from a resolved local config dict."""
    api_key_env = str(local_config["api_key_env"]).strip()
    os.environ[api_key_env] = str(local_config["resolved_api_key"]).strip()
    return ModelConfig(
        provider="openai",
        model=model_name,
        api_key_env=api_key_env,
        base_url=str(local_config["base_url"]).strip(),
        timeout_seconds=float(local_config.get("timeout_seconds", 120)),
        max_retries=int(local_config.get("max_retries", 3)),
        temperature=local_config.get("temperature"),
        max_output_tokens=local_config.get("max_output_tokens"),
    )


def _require_string_field(
    config: dict[str, Any],
    key: str,
    *,
    path: Path,
) -> str:
    value = str(config.get(key, "")).strip()
    if not value:
        raise ValueError(f"Missing {key} in {path}. Fill the {key} field before running.")
    return value


def _resolve_secret(
    config: dict[str, Any],
    *,
    value_key: str,
    env_key: str,
    default_env: str,
    path: Path,
) -> tuple[str, str]:
    inline_value = str(config.get(value_key, "")).strip()
    env_name = str(config.get(env_key, "")).strip() or default_env

    if inline_value:
        warnings.warn(
            f"{path} contains inline {value_key}. Prefer environment variable "
            f"{env_name} and keep secrets out of local JSON files.",
            stacklevel=2,
        )
        return inline_value, env_name

    env_value = os.environ.get(env_name, "").strip()
    if env_value:
        return env_value, env_name

    raise ValueError(
        f"Missing {value_key} for {path}. Set {value_key} inline, or set {env_key} "
        f"and export environment variable {env_name}."
    )


def _warn_if_repo_local_config(path: Path) -> None:
    repo_root = _repo_root_from()
    try:
        path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return

    preferred_path = default_local_config_dir() / path.name
    warnings.warn(
        f"{path} lives inside the source tree. Prefer a machine-local path such as "
        f"{preferred_path} and keep runtime config outside the repo.",
        stacklevel=3,
    )


def _repo_root_from(module_path: Path | None = None) -> Path:
    base = module_path or Path(__file__).resolve()
    return base.parents[2]
