"""MiMo-specific native tool-calling client."""

from __future__ import annotations

from typing import Any

import httpx

from pycodeagent.agent.llm_client import (
    GenerateRequest,
    GenerateResponse,
    RuntimeClientCapabilities,
)
from pycodeagent.agent.openai_client import EmptyResponseError
from pycodeagent.agent.openai_native_client import (
    OpenAINativeToolClient,
    _extract_tool_call_candidates,
    _message_content_to_text,
    _parse_structured_output,
)


class MimoNativeToolClient(OpenAINativeToolClient):
    """MiMo-compatible native tool-calling client."""

    def runtime_provenance(self) -> dict[str, Any]:
        provenance = super().runtime_provenance()
        provenance["client_mode"] = "mimo_native_tools"
        provenance["provider_kind"] = "mimo"
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
            provider_name="mimo",
        )

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
        reasoning_content = message.get("reasoning_content")
        structured_output, structured_output_parse_error = _parse_structured_output(
            assistant_text,
            request,
        )
        return GenerateResponse.from_native_tool_calling(
            assistant_text=assistant_text,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content if isinstance(reasoning_content, str) else None,
            finish_reason=first_choice.get("finish_reason"),
            response_id=data.get("id"),
            raw_provider_payload=data if isinstance(data, dict) else None,
            provider_metadata={
                "choice_index": 0,
                "reasoning_content_present": isinstance(reasoning_content, str)
                and bool(reasoning_content),
            },
            request_kind=request.request_kind,
            structured_output=structured_output,
            structured_output_parse_error=structured_output_parse_error,
        )
