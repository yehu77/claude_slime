"""Shared OpenAI-compatible native client transport and exceptions."""

from __future__ import annotations

import time
from typing import Any

import httpx

from pycodeagent.agent.llm_client import BaseLLMClient, GenerateRequest, GenerateResponse
from pycodeagent.agent.model_config import ModelConfig, ModelConfigError


class ModelClientError(Exception):
    """Base exception for model client errors."""


class MissingAPIKeyError(ModelClientError):
    """API key is missing or invalid."""


class APIError(ModelClientError):
    """Error response from the API."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class TimeoutError(ModelClientError):
    """Request timed out."""


class EmptyResponseError(ModelClientError):
    """Model returned an empty or invalid response."""


class RetryExhaustedError(ModelClientError):
    """All retry attempts failed."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        super().__init__(f"All {attempts} retry attempts failed. Last error: {last_error}")
        self.attempts = attempts
        self.last_error = last_error


_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_BASE_RETRY_DELAY = 1.0
_MAX_RETRY_DELAY = 30.0


class OpenAICompatibleClientBase(BaseLLMClient):
    """Shared HTTP transport for OpenAI-compatible native-tool clients."""

    def __init__(self, config: ModelConfig) -> None:
        self._config = config
        self._api_key: str | None = None
        self._base_url = config.base_url or "https://api.openai.com/v1"
        self._call_count = 0

    def _ensure_api_key(self) -> str:
        if self._api_key is None:
            try:
                self._api_key = self._config.resolve_api_key()
            except ModelConfigError as exc:
                raise MissingAPIKeyError(str(exc)) from exc
        return self._api_key

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        api_key = self._ensure_api_key()

        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                return self._make_request(api_key, request)
            except (TimeoutError, EmptyResponseError):
                raise
            except APIError as exc:
                last_error = exc
                if exc.status_code not in _RETRYABLE_STATUS_CODES:
                    raise
                if attempt < self._config.max_retries:
                    delay = min(_BASE_RETRY_DELAY * (2**attempt), _MAX_RETRY_DELAY)
                    time.sleep(delay)
                continue
            except httpx.TimeoutException as exc:
                last_error = TimeoutError(
                    f"Request timed out after {self._config.timeout_seconds}s"
                )
                raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = APIError(f"HTTP error: {exc}")
                if attempt < self._config.max_retries:
                    delay = min(_BASE_RETRY_DELAY * (2**attempt), _MAX_RETRY_DELAY)
                    time.sleep(delay)
                continue

        if last_error is None:
            raise RetryExhaustedError(
                self._config.max_retries + 1,
                RuntimeError("unknown error"),
            )
        raise RetryExhaustedError(self._config.max_retries + 1, last_error)

    def runtime_provenance(self) -> dict[str, Any]:
        return {
            "provider_kind": str(self._config.provider),
            "model": self._config.model,
            "base_url": self._base_url,
            "api_key_env": self._config.api_key_env,
            "timeout_seconds": self._config.timeout_seconds,
            "max_retries": self._config.max_retries,
            "temperature": self._config.temperature,
            "max_output_tokens": self._config.max_output_tokens,
        }

    def _raise_api_error(self, response: httpx.Response) -> None:
        status_code = response.status_code
        try:
            error_body = response.json()
            if isinstance(error_body, dict):
                error_obj = error_body.get("error", {})
                if isinstance(error_obj, dict):
                    message = error_obj.get("message", response.text)
                else:
                    message = str(error_obj)
            else:
                message = response.text
        except Exception:
            message = response.text or f"HTTP {status_code}"

        raise APIError(message, status_code=status_code)

    @property
    def call_count(self) -> int:
        return self._call_count

    def _make_request(
        self,
        api_key: str,
        request: GenerateRequest,
    ) -> GenerateResponse:
        raise NotImplementedError
