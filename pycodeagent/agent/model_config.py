"""Structured configuration for model client instantiation.

All important runtime knobs live here — no hidden global config assumptions.
Env var handling is explicit via `api_key_env`.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """Configuration for a model client.

    Attributes:
        provider: Provider identifier (e.g. "openai").
        model: Model name (e.g. "gpt-4o-mini").
        api_key_env: Name of the environment variable holding the API key.
        base_url: Optional override for the API base URL.
        timeout_seconds: Per-request timeout in seconds.
        max_retries: Maximum number of retry attempts for transient errors.
        temperature: Sampling temperature (None = provider default).
        max_output_tokens: Maximum tokens in the model response.
        extra_headers: Additional HTTP headers to send with each request.
        metadata: Arbitrary metadata for logging/tracking.
    """

    provider: str
    model: str
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None
    timeout_seconds: float = 120.0
    max_retries: int = 3
    temperature: float | None = None
    max_output_tokens: int | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def resolve_api_key(self) -> str:
        """Resolve the API key from the environment.

        Returns:
            The API key string.

        Raises:
            ModelConfigError: If the environment variable is not set.
        """
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ModelConfigError(
                f"API key not found: environment variable '{self.api_key_env}' is not set or empty"
            )
        return key

    @classmethod
    def from_env(
        cls,
        *,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        api_key_env: str = "OPENAI_API_KEY",
        **kwargs: Any,
    ) -> ModelConfig:
        """Create a config, resolving the API key from the environment.

        This validates that the key exists at construction time rather than
        deferring the failure to first API call.

        Args:
            provider: Provider identifier.
            model: Model name.
            api_key_env: Environment variable name for the API key.
            **kwargs: Additional ModelConfig fields.

        Returns:
            A ModelConfig instance.

        Raises:
            ModelConfigError: If the API key is not available.
        """
        config = cls(provider=provider, model=model, api_key_env=api_key_env, **kwargs)
        config.resolve_api_key()  # Validate key exists
        return config


class ModelConfigError(Exception):
    """Error in model configuration (e.g. missing API key)."""
