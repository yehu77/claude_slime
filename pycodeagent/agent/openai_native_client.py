"""OpenAI-compatible native tool-calling client."""

from __future__ import annotations

import json
from typing import Any

import httpx

from pycodeagent.agent.llm_client import (
    GenerateRequest,
    GenerateResponse,
    RuntimeClientCapabilities,
    ToolCallCandidate,
)
from pycodeagent.agent.openai_client import (
    EmptyResponseError,
    OpenAICompatibleClientBase,
)


def _to_openai_tool_spec(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec["name"],
            "description": spec.get("description", ""),
            "parameters": spec.get("input_schema", {"type": "object", "properties": {}}),
        },
    }


class OpenAINativeToolClient(OpenAICompatibleClientBase):
    """OpenAI-compatible client using native Chat Completions tool calling."""

    def runtime_provenance(self) -> dict[str, Any]:
        provenance = super().runtime_provenance()
        provenance["client_mode"] = "openai_native_tools"
        return provenance

    def runtime_capabilities(self) -> RuntimeClientCapabilities:
        return RuntimeClientCapabilities(
            protocol_mode="native_tool_calling",
            supports_native_tools=True,
            text_fallback_allowed=False,
            structured_finish_mode="finish_tool_call",
            supports_structured_output=True,
            supports_model_backed_compaction=True,
            provider_family="openai_chat_completions",
            provider_name=str(self._config.provider),
        )

    def _make_request(
        self,
        api_key: str,
        request: GenerateRequest,
    ) -> GenerateResponse:
        url = f"{self._base_url}/chat/completions"

        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": request.messages,
        }
        if request.tools:
            body["tools"] = [_to_openai_tool_spec(spec) for spec in request.tools]
            body["tool_choice"] = "auto"
        if request.structured_output_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.structured_output_schema.name,
                    "strict": request.structured_output_schema.strict,
                    "schema": request.structured_output_schema.schema,
                },
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

        return self._parse_response(response, request)

    def _parse_response(
        self,
        response: httpx.Response,
        request: GenerateRequest,
    ) -> GenerateResponse:
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

        assistant_text = _message_content_to_text(message.get("content"))
        tool_calls = _extract_tool_call_candidates(message.get("tool_calls"))
        structured_output, structured_output_parse_error = _parse_structured_output(
            assistant_text,
            request,
        )
        return GenerateResponse.from_native_tool_calling(
            assistant_text=assistant_text,
            tool_calls=tool_calls,
            finish_reason=first_choice.get("finish_reason"),
            response_id=data.get("id"),
            raw_provider_payload=data if isinstance(data, dict) else None,
            provider_metadata={"choice_index": 0},
            request_kind=request.request_kind,
            structured_output=structured_output,
            structured_output_parse_error=structured_output_parse_error,
        )


def _extract_tool_call_candidates(raw_tool_calls: Any) -> list[ToolCallCandidate]:
    if not isinstance(raw_tool_calls, list):
        return []

    candidates: list[ToolCallCandidate] = []
    for raw_call in raw_tool_calls:
        if not isinstance(raw_call, dict):
            continue
        function = raw_call.get("function")
        if not isinstance(function, dict):
            continue
        arguments_raw = function.get("arguments")
        arguments_obj: dict[str, Any] | None = None
        parse_error: str | None = None
        if arguments_raw is None:
            parse_error = "missing_arguments"
        elif not isinstance(arguments_raw, str):
            parse_error = f"expected string arguments, got {type(arguments_raw).__name__}"
        else:
            try:
                parsed = json.loads(arguments_raw)
            except json.JSONDecodeError as exc:
                parse_error = str(exc)
            else:
                if isinstance(parsed, dict):
                    arguments_obj = parsed
                else:
                    parse_error = (
                        f"arguments must decode to object, got {type(parsed).__name__}"
                    )

        candidates.append(
            ToolCallCandidate(
                call_id=raw_call.get("id"),
                name=str(function.get("name") or ""),
                arguments_raw=arguments_raw if isinstance(arguments_raw, str) else None,
                arguments_obj=arguments_obj,
                arguments_parse_error=parse_error,
                source="native",
            )
        )
    return candidates


def _message_content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        fragments: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                fragments.append(item["text"])
        return "\n".join(fragment for fragment in fragments if fragment).strip()
    return str(content)


def _parse_structured_output(
    assistant_text: str,
    request: GenerateRequest,
) -> tuple[dict[str, Any] | None, str | None]:
    if request.structured_output_schema is None:
        return None, None
    if not assistant_text.strip():
        return None, "empty_structured_output"
    try:
        parsed = json.loads(assistant_text)
    except json.JSONDecodeError as exc:
        return None, str(exc)
    if not isinstance(parsed, dict):
        return None, f"structured output must decode to object, got {type(parsed).__name__}"
    return parsed, None
