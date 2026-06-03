"""Tests for OpenAITextClient.

All tests use mocked HTTP transport — no real network calls.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from pycodeagent.agent.llm_client import GenerateRequest, GenerateResponse
from pycodeagent.agent.model_config import ModelConfig, ModelConfigError
from pycodeagent.agent.openai_client import (
    APIError,
    EmptyResponseError,
    MissingAPIKeyError,
    OpenAITextClient,
    RetryExhaustedError,
    TimeoutError,
)


def make_config(**overrides) -> ModelConfig:
    """Create a test ModelConfig."""
    defaults = {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key_env": "TEST_API_KEY_123",
        "timeout_seconds": 10.0,
        "max_retries": 2,
    }
    defaults.update(overrides)
    return ModelConfig(**defaults)


def make_request(messages: list | None = None) -> GenerateRequest:
    """Create a test GenerateRequest."""
    return GenerateRequest(
        messages=messages or [{"role": "user", "content": "Hello"}],
        tools=[],
    )


def make_success_response(content: str) -> httpx.Response:
    """Create a mock successful HTTP response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {
        "choices": [
            {"message": {"content": content, "role": "assistant"}}
        ]
    }
    return response


def make_error_response(status_code: int, message: str) -> httpx.Response:
    """Create a mock error HTTP response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = message
    response.json.return_value = {"error": {"message": message}}
    return response


class TestOpenAITextClientSuccess:
    """Tests for successful response path."""

    def test_basic_text_response(self):
        """Should return text from successful API call."""
        config = make_config()
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            with patch.object(client, "_make_request") as mock_request:
                mock_request.return_value = GenerateResponse(text="Hello, world!")

                request = make_request()
                response = client.generate(request)

                assert response.text == "Hello, world!"

    def test_request_body_structure(self):
        """Should send correct request body."""
        config = make_config(temperature=0.7, max_output_tokens=100)
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            # Mock httpx.Client
            mock_response = make_success_response("Test response")

            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_class.return_value = mock_client

                request = make_request(
                    messages=[{"role": "user", "content": "Say hi"}]
                )
                response = client.generate(request)

                assert response.text == "Test response"

                # Verify request was made correctly
                call_args = mock_client.post.call_args
                body = call_args.kwargs["json"]
                assert body["model"] == "gpt-4o-mini"
                assert body["messages"] == [{"role": "user", "content": "Say hi"}]
                assert body["temperature"] == 0.7
                assert body["max_tokens"] == 100

    def test_request_headers(self):
        """Should send correct headers including API key."""
        config = make_config(extra_headers={"X-Custom": "value"})
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-my-key"}):
            mock_response = make_success_response("OK")

            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_class.return_value = mock_client

                request = make_request()
                client.generate(request)

                call_args = mock_client.post.call_args
                headers = call_args.kwargs["headers"]
                assert headers["Authorization"] == "Bearer sk-my-key"
                assert headers["Content-Type"] == "application/json"
                assert headers["X-Custom"] == "value"

    def test_call_count_incremented(self):
        """Should increment call_count on each HTTP request."""
        config = make_config()
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            mock_response = make_success_response("OK")

            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_class.return_value = mock_client

                assert client.call_count == 0
                client.generate(make_request())
                assert client.call_count == 1
                client.generate(make_request())
                assert client.call_count == 2

    def test_custom_base_url(self):
        """Should use custom base URL if provided."""
        config = make_config(base_url="https://my-proxy.example.com/v1")
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            mock_response = make_success_response("OK")

            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_class.return_value = mock_client

                client.generate(make_request())

                call_args = mock_client.post.call_args
                url = call_args.args[0]
                assert url == "https://my-proxy.example.com/v1/chat/completions"


class TestMissingAPIKey:
    """Tests for missing API key handling."""

    def test_missing_key_raises(self):
        """Should raise MissingAPIKeyError if key is missing."""
        config = make_config(api_key_env="NONEXISTENT_KEY_FOR_TEST")
        client = OpenAITextClient(config)

        os.environ.pop("NONEXISTENT_KEY_FOR_TEST", None)

        with pytest.raises(MissingAPIKeyError, match="API key not found"):
            client.generate(make_request())

    def test_empty_key_raises(self):
        """Should raise MissingAPIKeyError if key is empty."""
        config = make_config(api_key_env="EMPTY_KEY_FOR_TEST")
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"EMPTY_KEY_FOR_TEST": ""}):
            with pytest.raises(MissingAPIKeyError, match="API key not found"):
                client.generate(make_request())


class TestTimeoutHandling:
    """Tests for timeout handling."""

    def test_timeout_raises(self):
        """Should raise TimeoutError on timeout."""
        config = make_config(timeout_seconds=5.0)
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.side_effect = httpx.TimeoutException("timeout")
                mock_client_class.return_value = mock_client

                with pytest.raises(TimeoutError, match="timed out"):
                    client.generate(make_request())


class TestAPIErrorHandling:
    """Tests for API error responses."""

    def test_400_error_raises(self):
        """Should raise APIError for 400 status."""
        config = make_config()
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            mock_response = make_error_response(400, "Bad request")

            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_class.return_value = mock_client

                with pytest.raises(APIError) as exc_info:
                    client.generate(make_request())

                assert exc_info.value.status_code == 400
                assert "Bad request" in str(exc_info.value)

    def test_401_error_raises(self):
        """Should raise APIError for 401 status (invalid key)."""
        config = make_config()
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            mock_response = make_error_response(401, "Invalid API key")

            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_class.return_value = mock_client

                with pytest.raises(APIError) as exc_info:
                    client.generate(make_request())

                assert exc_info.value.status_code == 401


class TestRetryBehavior:
    """Tests for retry behavior."""

    def test_retry_on_429(self):
        """Should retry on rate limit (429)."""
        config = make_config(max_retries=2)
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            error_response = make_error_response(429, "Rate limited")
            success_response = make_success_response("OK after retry")

            call_count = [0]

            def post_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return error_response
                return success_response

            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.side_effect = post_side_effect
                mock_client_class.return_value = mock_client

                # Patch time.sleep to avoid delays
                with patch("time.sleep"):
                    response = client.generate(make_request())

                assert response.text == "OK after retry"
                assert call_count[0] == 2

    def test_retry_on_500(self):
        """Should retry on server error (500)."""
        config = make_config(max_retries=2)
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            error_response = make_error_response(500, "Internal error")
            success_response = make_success_response("OK")

            call_count = [0]

            def post_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return error_response
                return success_response

            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.side_effect = post_side_effect
                mock_client_class.return_value = mock_client

                with patch("time.sleep"):
                    response = client.generate(make_request())

                assert response.text == "OK"

    def test_retry_exhausted(self):
        """Should raise RetryExhaustedError when all retries fail."""
        config = make_config(max_retries=2)
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            error_response = make_error_response(429, "Rate limited")

            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = error_response
                mock_client_class.return_value = mock_client

                with patch("time.sleep"):
                    with pytest.raises(RetryExhaustedError) as exc_info:
                        client.generate(make_request())

                    # max_retries=2 means 3 total attempts
                    assert exc_info.value.attempts == 3

    def test_no_retry_on_400(self):
        """Should NOT retry on 400 (client error)."""
        config = make_config(max_retries=3)
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            error_response = make_error_response(400, "Bad request")

            call_count = [0]

            def post_side_effect(*args, **kwargs):
                call_count[0] += 1
                return error_response

            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.side_effect = post_side_effect
                mock_client_class.return_value = mock_client

                with pytest.raises(APIError):
                    client.generate(make_request())

                # Should only be called once (no retries)
                assert call_count[0] == 1


class TestEmptyInvalidResponse:
    """Tests for empty/invalid response handling."""

    def test_empty_content_raises(self):
        """Should raise EmptyResponseError if content is None."""
        config = make_config()
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "choices": [{"message": {"content": None}}]
            }

            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_class.return_value = mock_client

                with pytest.raises(EmptyResponseError, match="empty content"):
                    client.generate(make_request())

    def test_missing_choices_raises(self):
        """Should raise EmptyResponseError if choices is missing."""
        config = make_config()
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.json.return_value = {}

            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_class.return_value = mock_client

                with pytest.raises(EmptyResponseError, match="choices"):
                    client.generate(make_request())

    def test_empty_choices_raises(self):
        """Should raise EmptyResponseError if choices is empty."""
        config = make_config()
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.json.return_value = {"choices": []}

            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_class.return_value = mock_client

                with pytest.raises(EmptyResponseError, match="choices"):
                    client.generate(make_request())

    def test_invalid_json_raises(self):
        """Should raise EmptyResponseError if response is not valid JSON."""
        config = make_config()
        client = OpenAITextClient(config)

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.json.side_effect = ValueError("not json")

            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_class.return_value = mock_client

                with pytest.raises(EmptyResponseError, match="parse response JSON"):
                    client.generate(make_request())


class TestIntegrationWithParser:
    """Integration tests verifying output is usable by parser."""

    def test_parser_can_parse_response(self):
        """Response text should be parseable by parse_assistant_response."""
        from pycodeagent.agent.parser import parse_assistant_response

        config = make_config()
        client = OpenAITextClient(config)

        # Simulated model output with tool call
        model_output = """<assistant>
I will help you fix the bug.
</assistant>
<|tool|>
{"id": "call_001", "name": "read_file", "arguments": {"path": "main.py"}}
<|end|>"""

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            with patch.object(client, "_make_request") as mock_request:
                mock_request.return_value = GenerateResponse(text=model_output)

                response = client.generate(make_request())
                parsed = parse_assistant_response(response.text)

                assert parsed.ok
                assert "I will help you fix the bug" in parsed.assistant_content
                assert len(parsed.tool_calls) == 1
                assert parsed.tool_calls[0].name == "read_file"

    def test_parser_handles_plain_text(self):
        """Plain text response should also be parseable."""
        from pycodeagent.agent.parser import parse_assistant_response

        config = make_config()
        client = OpenAITextClient(config)

        model_output = "I cannot help with that request."

        with patch.dict(os.environ, {"TEST_API_KEY_123": "sk-test"}):
            with patch.object(client, "_make_request") as mock_request:
                mock_request.return_value = GenerateResponse(text=model_output)

                response = client.generate(make_request())
                parsed = parse_assistant_response(response.text)

                assert parsed.ok
                assert parsed.assistant_content == model_output
                assert len(parsed.tool_calls) == 0
