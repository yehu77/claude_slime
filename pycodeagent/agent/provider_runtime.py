"""Formal real-provider runtime config and client factory helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from pycodeagent.agent.llm_client import BaseLLMClient
from pycodeagent.agent.mimo_native_client import MimoNativeToolClient
from pycodeagent.agent.model_config import ModelConfig, ModelConfigError
from pycodeagent.agent.openai_native_client import OpenAINativeToolClient
from pycodeagent.dev.local_state import default_local_config_dir


ClientMode = Literal[
    "mimo_native_tools",
    "openai_native_tools",
]

DEFAULT_CLIENT_MODE: ClientMode = "mimo_native_tools"
NATIVE_MAINLINE_CLIENT_MODES: frozenset[str] = frozenset(
    {"mimo_native_tools", "openai_native_tools"}
)
DEFAULT_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
DEFAULT_API_KEY_ENV = "PYCODEAGENT_API_KEY"

CLIENT_MODE_ENV = "PYCODEAGENT_CLIENT_MODE"
MODEL_ENV = "PYCODEAGENT_MODEL"
BASE_URL_ENV = "PYCODEAGENT_BASE_URL"
API_KEY_ENV_NAME_ENV = "PYCODEAGENT_API_KEY_ENV"
ENV_FILE_ENV = "PYCODEAGENT_ENV_FILE"


class RuntimeProviderConfig(BaseModel):
    """Formal runtime config for OpenAI-compatible real providers."""

    model_config = ConfigDict(extra="forbid")

    client_mode: ClientMode = DEFAULT_CLIENT_MODE
    model: str
    base_url: str
    api_key_env: str = DEFAULT_API_KEY_ENV
    timeout_seconds: float = 120.0
    max_retries: int = 3
    temperature: float | None = None
    max_output_tokens: int | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _reject_inline_api_key(cls, data: Any) -> Any:
        if isinstance(data, dict) and "api_key" in data:
            raise ValueError(
                "Inline api_key is not allowed in RuntimeProviderConfig; "
                "set api_key_env and export the secret via the environment."
            )
        return data

    @field_validator("model", "base_url", "api_key_env", mode="before")
    @classmethod
    def _require_non_empty_string(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Field must be a non-empty string")
        return text

    @property
    def provider_kind(self) -> str:
        if self.client_mode == "mimo_native_tools":
            return "mimo"
        return "openai_compatible"

    @property
    def is_native_mainline(self) -> bool:
        return self.client_mode in NATIVE_MAINLINE_CLIENT_MODES

    def to_model_config(self) -> ModelConfig:
        """Convert the runtime config into the lower-level model config."""
        return ModelConfig(
            provider=self.provider_kind,
            model=self.model,
            api_key_env=self.api_key_env,
            base_url=self.base_url,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            extra_headers=dict(self.extra_headers),
            metadata=dict(self.metadata),
        )

    def runtime_provenance(self) -> dict[str, Any]:
        """Structured non-secret provider provenance for runtime artifacts."""
        return {
            "provider_kind": self.provider_kind,
            "client_mode": self.client_mode,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
        }

    @classmethod
    def load(
        cls,
        path: Path | str,
        *,
        example_path: Path | str | None = None,
    ) -> "RuntimeProviderConfig":
        """Load and validate a runtime provider config from JSON."""
        path = Path(path)
        if not path.exists():
            message = f"Runtime provider config not found: {path}."
            if example_path is not None:
                message += (
                    f" Copy {example_path} to {path} and fill the non-secret fields."
                )
            raise FileNotFoundError(message)

        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError(f"Runtime provider config must be a JSON object: {path}")
        return cls.model_validate(data)


def load_runtime_provider_config(
    path: Path | str,
    *,
    example_path: Path | str | None = None,
) -> RuntimeProviderConfig:
    """Load a checked-in or machine-local runtime provider config."""
    return RuntimeProviderConfig.load(path, example_path=example_path)


def _env_override_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {}
    client_mode = os.environ.get(CLIENT_MODE_ENV, "").strip()
    if client_mode:
        payload["client_mode"] = client_mode

    model = os.environ.get(MODEL_ENV, "").strip()
    if model:
        payload["model"] = model

    base_url = os.environ.get(BASE_URL_ENV, "").strip()
    if base_url:
        payload["base_url"] = base_url

    api_key_env = os.environ.get(API_KEY_ENV_NAME_ENV, "").strip()
    if api_key_env:
        payload["api_key_env"] = api_key_env

    return payload


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _dotenv_candidates(env_path: Path | str | None = None) -> list[Path]:
    candidates: list[Path] = []
    if env_path is not None:
        candidates.append(Path(env_path))

    explicit_env_file = os.environ.get(ENV_FILE_ENV, "").strip()
    if explicit_env_file:
        candidates.append(Path(explicit_env_file).expanduser())

    candidates.append(Path.cwd() / ".env")
    candidates.append(_repo_root() / ".env")
    candidates.append(default_local_config_dir() / ".env")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved_key = str(candidate.expanduser().resolve(strict=False)).lower()
        except Exception:
            resolved_key = str(candidate).lower()
        if resolved_key in seen:
            continue
        seen.add(resolved_key)
        unique.append(candidate.expanduser())
    return unique


def _parse_dotenv_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        inner = value[1:-1]
        if value[0] == '"':
            return inner.encode("utf-8").decode("unicode_escape")
        return inner
    return value


def _load_dotenv_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_key = key.strip()
        if not env_key or env_key in os.environ:
            continue
        os.environ[env_key] = _parse_dotenv_value(value)


def load_runtime_provider_env(env_path: Path | str | None = None) -> Path | None:
    """Best-effort auto-load of a minimal `.env` file.

    Existing environment variables always win over `.env` values.
    The loader intentionally supports only a small `.env` subset:
    - blank lines
    - comments
    - optional `export`
    - `KEY=VALUE`
    - single-quoted or double-quoted values
    """
    for candidate in _dotenv_candidates(env_path):
        if candidate.exists() and candidate.is_file():
            _load_dotenv_file(candidate)
            return candidate
    return None


def runtime_provider_env_present() -> bool:
    """Whether any formal runtime-provider env overrides are present."""
    return bool(_env_override_payload() or os.environ.get(DEFAULT_API_KEY_ENV, "").strip())


def resolve_runtime_provider_config(
    path: Path | str | None = None,
    *,
    example_path: Path | str | None = None,
    env_path: Path | str | None = None,
) -> RuntimeProviderConfig:
    """Resolve provider config from defaults, optional local JSON, and env.

    Precedence:
    1. hard defaults
    2. optional local JSON config, if present
    3. explicit environment-variable overrides

    This makes the local JSON file optional. A minimal env-only setup is:
    - ``PYCODEAGENT_API_KEY``
    - ``PYCODEAGENT_MODEL``
    """
    load_runtime_provider_env(env_path)

    payload: dict[str, Any] = {
        "client_mode": DEFAULT_CLIENT_MODE,
        "base_url": DEFAULT_BASE_URL,
        "api_key_env": DEFAULT_API_KEY_ENV,
    }

    config_path: Path | None = None
    config_path_exists = False
    if path is not None:
        config_path = Path(path)
        config_path_exists = config_path.exists()
        if config_path_exists:
            with open(config_path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict):
                raise ValueError(f"Runtime provider config must be a JSON object: {config_path}")
            if "api_key" in loaded:
                raise ValueError(
                    "Inline api_key is not allowed in RuntimeProviderConfig; "
                    "set api_key_env and export the secret via the environment."
                )
            payload.update(loaded)

    payload.update(_env_override_payload())
    try:
        config = RuntimeProviderConfig.model_validate(payload)
    except ValidationError as exc:
        message = (
            "Unable to resolve runtime provider config. "
            f"Set at least {MODEL_ENV} and {DEFAULT_API_KEY_ENV}, "
            "or provide a local runtime config JSON."
        )
        if config_path is not None and not config_path_exists:
            message += f" Missing fallback config: {config_path}."
        if example_path is not None:
            message += f" Example config: {example_path}."
        raise ValueError(message) from exc
    try:
        config.to_model_config().resolve_api_key()
    except ModelConfigError as exc:
        raise ValueError(
            f"Missing API key for runtime provider config. "
            f"Export environment variable {config.api_key_env}."
        ) from exc
    return config


def build_llm_client(provider_config: RuntimeProviderConfig) -> BaseLLMClient:
    """Build an LLM client from a formal runtime provider config."""
    model_config = provider_config.to_model_config()
    if provider_config.client_mode == "mimo_native_tools":
        return MimoNativeToolClient(model_config)
    if provider_config.client_mode == "openai_native_tools":
        return OpenAINativeToolClient(model_config)
    raise ValueError(f"Unsupported native client mode: {provider_config.client_mode}")


def build_llm_client_factory(provider_config: RuntimeProviderConfig):
    """Build a reusable fresh-client factory from a runtime provider config."""
    return lambda: build_llm_client(provider_config)


def build_llm_client_factory_from_path(
    path: Path | str,
    *,
    example_path: Path | str | None = None,
):
    """Load a runtime provider config from disk and return a client factory."""
    provider_config = resolve_runtime_provider_config(
        path,
        example_path=example_path,
    )
    return build_llm_client_factory(provider_config)
