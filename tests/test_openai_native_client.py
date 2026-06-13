from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import httpx

from pycodeagent.agent.llm_client import GenerateRequest, StructuredOutputSchema
from pycodeagent.agent.model_config import ModelConfig
from pycodeagent.agent.openai_native_client import OpenAINativeToolClient


def make_config(**overrides) -> ModelConfig:
    defaults = {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key_env": "TEST_API_KEY_NATIVE",
        "timeout_seconds": 10.0,
        "max_retries": 1,
    }
    defaults.update(overrides)
    return ModelConfig(**defaults)


def make_request() -> GenerateRequest:
    return GenerateRequest(
        messages=[{"role": "user", "content": "Read main.py"}],
        tools=[
            {
                "name": "read_file",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            }
        ],
    )


def make_native_response() -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {
        "id": "resp_native_1",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "I will inspect the file.",
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path":"main.py"}',
                            },
                        }
                    ],
                },
            }
        ],
    }
    return response


def test_native_client_sends_tools_and_returns_structured_envelope() -> None:
    client = OpenAINativeToolClient(make_config(base_url="https://example.com/v1"))

    with patch.dict(os.environ, {"TEST_API_KEY_NATIVE": "sk-test"}):
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = make_native_response()
            mock_client_class.return_value = mock_client

            response = client.generate(make_request())

            assert response.transport_mode == "native_tool_calling"
            assert response.assistant_text == "I will inspect the file."
            assert response.finish_reason == "tool_calls"
            assert response.response_id == "resp_native_1"
            assert len(response.tool_calls) == 1
            assert response.tool_calls[0].call_id == "call_123"
            assert response.tool_calls[0].name == "read_file"
            assert response.tool_calls[0].arguments_raw == '{"path":"main.py"}'
            assert response.tool_calls[0].arguments_obj == {"path": "main.py"}
            assert response.tool_calls[0].arguments_parse_error is None

            body = mock_client.post.call_args.kwargs["json"]
            assert body["tools"][0]["type"] == "function"
            assert body["tools"][0]["function"]["name"] == "read_file"
            assert body["tool_choice"] == "auto"


def test_native_client_preserves_argument_parse_error() -> None:
    client = OpenAINativeToolClient(make_config(base_url="https://example.com/v1"))
    bad_response = MagicMock(spec=httpx.Response)
    bad_response.status_code = 200
    bad_response.json.return_value = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_bad",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path":}',
                            },
                        }
                    ],
                },
            }
        ],
    }

    with patch.dict(os.environ, {"TEST_API_KEY_NATIVE": "sk-test"}):
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = bad_response
            mock_client_class.return_value = mock_client

            response = client.generate(make_request())

            assert response.transport_mode == "native_tool_calling"
            assert len(response.tool_calls) == 1
            assert response.finish_reason == "tool_calls"
            assert response.tool_calls[0].arguments_obj is None
            assert response.tool_calls[0].arguments_parse_error is not None


def test_native_client_preserves_finish_reason_when_tool_calls_missing() -> None:
    client = OpenAINativeToolClient(make_config(base_url="https://example.com/v1"))
    missing_tools_response = MagicMock(spec=httpx.Response)
    missing_tools_response.status_code = 200
    missing_tools_response.json.return_value = {
        "id": "resp_missing_tools",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "I should call a tool.",
                },
            }
        ],
    }

    with patch.dict(os.environ, {"TEST_API_KEY_NATIVE": "sk-test"}):
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = missing_tools_response
            mock_client_class.return_value = mock_client

            response = client.generate(make_request())

            assert response.transport_mode == "native_tool_calling"
            assert response.finish_reason == "tool_calls"
            assert response.response_id == "resp_missing_tools"
            assert response.tool_calls == []


def test_native_client_returns_empty_candidates_for_non_list_tool_calls() -> None:
    client = OpenAINativeToolClient(make_config(base_url="https://example.com/v1"))
    bad_shape_response = MagicMock(spec=httpx.Response)
    bad_shape_response.status_code = 200
    bad_shape_response.json.return_value = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": {"id": "not_a_list"},
                },
            }
        ],
    }

    with patch.dict(os.environ, {"TEST_API_KEY_NATIVE": "sk-test"}):
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = bad_shape_response
            mock_client_class.return_value = mock_client

            response = client.generate(make_request())

            assert response.transport_mode == "native_tool_calling"
            assert response.finish_reason == "tool_calls"
            assert response.tool_calls == []


def test_native_client_skips_wrong_function_shape_but_keeps_transport() -> None:
    client = OpenAINativeToolClient(make_config(base_url="https://example.com/v1"))
    wrong_function_response = MagicMock(spec=httpx.Response)
    wrong_function_response.status_code = 200
    wrong_function_response.json.return_value = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "Broken tool call.",
                    "tool_calls": [
                        {
                            "id": "call_bad_shape",
                            "type": "function",
                            "function": "not_a_dict",
                        }
                    ],
                },
            }
        ],
    }

    with patch.dict(os.environ, {"TEST_API_KEY_NATIVE": "sk-test"}):
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = wrong_function_response
            mock_client_class.return_value = mock_client

            response = client.generate(make_request())

            assert response.transport_mode == "native_tool_calling"
            assert response.finish_reason == "tool_calls"
            assert response.tool_calls == []


def test_native_client_sends_response_format_for_structured_output() -> None:
    client = OpenAINativeToolClient(make_config(base_url="https://example.com/v1"))
    structured_response = MagicMock(spec=httpx.Response)
    structured_response.status_code = 200
    structured_response.json.return_value = {
        "id": "resp_structured",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": '{"summary_text":"compact","carried_forward_state":{"pending_issue_kind":null,"pending_issue_detail":"","completion_evidence_status":"not_required","validation_phase":"idle","last_successful_validation_turn":null,"last_validation_attempt_turn":null,"last_validation_failure_turn":null,"last_mutation_turn":null,"recent_compacted_tool_outcomes":[],"carried_notes":[]},"compacted_span":{"source_message_indices":[2,3,4,5],"source_turn_indices":[1,2],"pinned_message_indices":[0,1],"replacement_summary_kind":"model_backed_compaction"}}',
                },
            }
        ],
    }

    request = GenerateRequest(
        messages=[{"role": "user", "content": "compact this history"}],
        tools=[],
        request_kind="context_compaction",
        structured_output_schema=StructuredOutputSchema(
            name="runtime_compaction_output",
            schema={"type": "object"},
            strict=True,
        ),
    )

    with patch.dict(os.environ, {"TEST_API_KEY_NATIVE": "sk-test"}):
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = structured_response
            mock_client_class.return_value = mock_client

            response = client.generate(request)

            body = mock_client.post.call_args.kwargs["json"]
            assert body["response_format"]["type"] == "json_schema"
            assert body["response_format"]["json_schema"]["name"] == "runtime_compaction_output"
            assert response.request_kind == "context_compaction"
            assert response.structured_output is not None
            assert response.structured_output["summary_text"] == "compact"
            assert response.structured_output["compacted_span"]["source_turn_indices"] == [1, 2]
