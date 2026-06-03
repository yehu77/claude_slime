"""Tests for MiMo-specific client behavior."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from pycodeagent.agent.llm_client import GenerateRequest
from pycodeagent.agent.mimo_client import MimoTextClient
from pycodeagent.agent.model_config import ModelConfig


def make_config(**overrides) -> ModelConfig:
    defaults = {
        "provider": "mimo",
        "model": "mimo-v2.5-pro",
        "api_key_env": "TEST_MIMO_API_KEY",
        "timeout_seconds": 10.0,
        "max_retries": 1,
    }
    defaults.update(overrides)
    return ModelConfig(**defaults)


def make_response(content: str, reasoning: str | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": reasoning,
                }
            }
        ]
    }
    return response


class TestMimoMessageSanitization:
    def test_sanitizes_assistant_and_tool_history(self):
        client = MimoTextClient(make_config())
        client._assistant_reasoning_history = ["previous chain"]
        request = GenerateRequest(
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "task"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "c1", "name": "read_file", "arguments": {"path": "a.py"}}
                    ],
                },
                {
                    "role": "tool",
                    "content": "file contents",
                    "tool_call_id": "c1",
                    "tool_name": "read_file",
                },
            ],
            tools=[],
        )

        sanitized = client._sanitize_messages(request.messages)

        assert sanitized[0] == {"role": "system", "content": "sys"}
        assert sanitized[1] == {"role": "user", "content": "task"}
        assert sanitized[2]["role"] == "assistant"
        assert sanitized[2]["reasoning_content"] == "previous chain"
        assert "<|tool|>" in sanitized[2]["content"]
        assert '"name": "read_file"' in sanitized[2]["content"]
        assert sanitized[3]["role"] == "user"
        assert "<tool_result" in sanitized[3]["content"]
        assert "file contents" in sanitized[3]["content"]

    def test_uses_tail_of_reasoning_history_for_truncated_context(self):
        client = MimoTextClient(make_config())
        client._assistant_reasoning_history = ["old chain", "new chain"]
        request = GenerateRequest(
            messages=[
                {"role": "user", "content": "task"},
                {"role": "assistant", "content": "latest assistant turn"},
            ],
            tools=[],
        )

        sanitized = client._sanitize_messages(request.messages)

        assert sanitized[1]["reasoning_content"] == "new chain"


class TestMimoReasoningReplay:
    def test_replays_reasoning_content_on_followup_turn(self):
        client = MimoTextClient(make_config())
        first_request = GenerateRequest(
            messages=[{"role": "user", "content": "Say hi"}],
            tools=[],
        )

        with patch.dict(os.environ, {"TEST_MIMO_API_KEY": "tp-test"}):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.side_effect = [
                    make_response("<|tool|>\n{}\n<|end|>", "reason-1"),
                    make_response("done", "reason-2"),
                ]
                mock_client_class.return_value = mock_client

                client.generate(first_request)

                second_request = GenerateRequest(
                    messages=[
                        {"role": "user", "content": "Say hi"},
                        {"role": "assistant", "content": "previous tool call"},
                        {"role": "tool", "content": "result", "tool_call_id": "c1", "tool_name": "x"},
                        {"role": "user", "content": "continue"},
                    ],
                    tools=[],
                )
                client.generate(second_request)

                second_body = mock_client.post.call_args.kwargs["json"]
                assistant_messages = [m for m in second_body["messages"] if m["role"] == "assistant"]
                assert assistant_messages[0]["reasoning_content"] == "reason-1"


class TestMimoParsing:
    def test_stores_reasoning_content_from_response(self):
        client = MimoTextClient(make_config())
        response = make_response("OK", "trace")
        parsed = client._parse_response(response)
        assert parsed.text == "OK"
        assert client._assistant_reasoning_history == ["trace"]

    def test_new_conversation_clears_stale_reasoning_history(self):
        client = MimoTextClient(make_config(base_url="https://example.com/v1"))
        client._assistant_reasoning_history = ["stale-trace"]
        request = GenerateRequest(
            messages=[{"role": "user", "content": "Hello"}],
            tools=[],
        )

        with patch.dict(os.environ, {"TEST_MIMO_API_KEY": "tp-test"}):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.post.return_value = make_response("OK", "fresh-trace")
                mock_client_class.return_value = mock_client

                result = client.generate(request)

                assert result.text == "OK"
                assert client._assistant_reasoning_history == ["fresh-trace"]

    def test_generate_uses_openai_transport_shape(self):
        client = MimoTextClient(make_config(base_url="https://example.com/v1"))
        request = GenerateRequest(
            messages=[{"role": "user", "content": "Hello"}],
            tools=[],
        )

        with patch.dict(os.environ, {"TEST_MIMO_API_KEY": "tp-test"}):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = make_response("OK", "trace")
                mock_client_class.return_value = mock_client

                result = client.generate(request)

                assert result.text == "OK"
                args = mock_client.post.call_args
                assert args.args[0] == "https://example.com/v1/chat/completions"
                assert args.kwargs["json"]["model"] == "mimo-v2.5-pro"

    def test_reuses_persistent_http_client(self):
        client = MimoTextClient(make_config(base_url="https://example.com/v1"))
        request = GenerateRequest(
            messages=[{"role": "user", "content": "Hello"}],
            tools=[],
        )

        with patch.dict(os.environ, {"TEST_MIMO_API_KEY": "tp-test"}):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.post.side_effect = [
                    make_response("one", "r1"),
                    make_response("two", "r2"),
                ]
                mock_client_class.return_value = mock_client

                client.generate(request)
                client.generate(request)

                assert mock_client_class.call_count == 1
                assert mock_client.post.call_count == 2

    def test_drops_persistent_client_on_http_error(self):
        client = MimoTextClient(make_config(base_url="https://example.com/v1"))
        request = GenerateRequest(
            messages=[{"role": "user", "content": "Hello"}],
            tools=[],
        )

        with patch.dict(os.environ, {"TEST_MIMO_API_KEY": "tp-test"}):
            with patch("httpx.Client") as mock_client_class:
                first_client = MagicMock()
                first_client.post.side_effect = httpx.RemoteProtocolError("disconnect")
                second_client = MagicMock()
                second_client.post.return_value = make_response("OK", "trace")
                mock_client_class.side_effect = [first_client, second_client]

                result = client.generate(request)

                assert result.text == "OK"
                assert mock_client_class.call_count == 2
