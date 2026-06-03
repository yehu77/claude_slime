"""OpenAI-compatible text-mode client.

Implements the BaseLLMClient contract using the OpenAI Chat Completions API.
Text mode only - tool schemas are injected into the prompt, not sent via
native tool-calling. The parser extracts tool calls from model output.
"""

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
    """Error response from the API.

    Attributes:
        status_code: HTTP status code (if available).
        message: Error message from the API or client.
    """

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


class OpenAITextClient(BaseLLMClient):
    """OpenAI-compatible text-mode client."""

    def __init__(self, config: ModelConfig) -> None:
        """Initialize the client with a configuration.

        Args:
            config: ModelConfig instance with provider, model, and credentials.
        """
        self._config = config
        self._api_key: str | None = None
        self._base_url = config.base_url or "https://api.openai.com/v1"
        self._call_count = 0

    def _ensure_api_key(self) -> str:
        """Lazily resolve and cache the API key."""
        if self._api_key is None:
            try:
                self._api_key = self._config.resolve_api_key()
            except ModelConfigError as e:
                raise MissingAPIKeyError(str(e)) from e
        return self._api_key

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        """Generate a text response using the OpenAI Chat Completions API.

        Args:
            request: GenerateRequest with messages and tools. Tool specs are not
                sent to the API; they should already be rendered into the prompt.
        """
        api_key = self._ensure_api_key()

        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                return self._make_request(api_key, request)
            except (TimeoutError, EmptyResponseError):
                raise
            except APIError as e:
                last_error = e
                if e.status_code not in _RETRYABLE_STATUS_CODES:
                    raise
                if attempt < self._config.max_retries:
                    delay = min(_BASE_RETRY_DELAY * (2 ** attempt), _MAX_RETRY_DELAY)
                    time.sleep(delay)
                continue
            except httpx.TimeoutException as e:
                last_error = TimeoutError(f"Request timed out after {self._config.timeout_seconds}s")
                raise last_error from e
            except httpx.HTTPError as e:
                last_error = APIError(f"HTTP error: {e}")
                if attempt < self._config.max_retries:
                    delay = min(_BASE_RETRY_DELAY * (2 ** attempt), _MAX_RETRY_DELAY)
                    time.sleep(delay)
                continue

        if last_error is None:
            raise RetryExhaustedError(self._config.max_retries + 1, RuntimeError("unknown error"))
        raise RetryExhaustedError(self._config.max_retries + 1, last_error)

    def _make_request(
        self,
        api_key: str,
        request: GenerateRequest,
    ) -> GenerateResponse:
        """Make a single HTTP request to the API."""
        url = f"{self._base_url}/chat/completions"

        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": request.messages,
        }

        if self._config.temperature is not None:
            body["temperature"] = self._config.temperature
        if self._config.max_output_tokens is not None:
            body["max_tokens"] = self._config.max_output_tokens

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self._config.extra_headers)

        self._call_count += 1

        with httpx.Client(timeout=self._config.timeout_seconds) as client:
            response = client.post(url, json=body, headers=headers)

        if response.status_code != 200:
            self._raise_api_error(response)

        return self._parse_response(response)

    def _raise_api_error(self, response: httpx.Response) -> None:
        """Raise an appropriate APIError from the response."""
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

    def _parse_response(self, response: httpx.Response) -> GenerateResponse:
        """Parse a successful response into GenerateResponse."""
        try:
            data = response.json()
        except Exception as e:
            raise EmptyResponseError(f"Failed to parse response JSON: {e}") from e

        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise EmptyResponseError("Response missing 'choices' array")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise EmptyResponseError(f"Invalid choice: {first_choice}")

        message = first_choice.get("message")
        if not message or not isinstance(message, dict):
            raise EmptyResponseError("Choice missing 'message' object")

        content = message.get("content")
        if content is None:
            raise EmptyResponseError("Model returned empty content (possibly filtered)")

        return GenerateResponse(text=str(content))

    @property
    def call_count(self) -> int:
        """Number of times generate() has made HTTP requests."""
        return self._call_count
