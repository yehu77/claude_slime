"""Native tool-calling response interpretation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.agent.llm_client import GenerateResponse, RuntimeClientCapabilities
from pycodeagent.tools.contracts import ToolPayloadKind
from pycodeagent.trajectory.schema import ToolCall


class ParseResult(BaseModel):
    """Structured result of interpreting a provider response."""

    ok: bool
    assistant_content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    parse_status: str = "ok"
    format_family: str = "native_tool_calling"
    fatal_errors: list[str] = Field(default_factory=list)
    recovery_warnings: list[str] = Field(default_factory=list)
    normalization_actions: list[str] = Field(default_factory=list)
    normalized_text: str = ""
    transport_mode: str = "native_tool_calling"
    finish_reason: str | None = None
    provider_response_id: str | None = None
    protocol_errors: list[str] = Field(default_factory=list)
    protocol_error_kind: str | None = None
    fallback_parser_used: bool = False
    protocol_decision: str = "accept_native"
    text_fallback_used: bool = False
    fallback_reason: str | None = None
    fallback_allowed: bool = False
    tool_call_candidate_count: int = 0
    accepted_tool_call_count: int = 0
    rejected_tool_call_candidate_count: int = 0
    raw_provider_payload: dict[str, Any] | None = None

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def has_parse_errors(self) -> bool:
        return len(self.parse_errors) > 0


def interpret_model_response(
    response: GenerateResponse,
    runtime_capabilities: RuntimeClientCapabilities | None = None,
) -> ParseResult:
    """Interpret one structured native provider response."""
    if response.transport_mode != "native_tool_calling":
        return ParseResult(
            ok=False,
            assistant_content=response.assistant_text,
            parse_errors=[
                f"Unsupported transport mode for runtime mainline: {response.transport_mode}"
            ],
            parse_status="fatal",
            fatal_errors=[
                f"Unsupported transport mode for runtime mainline: {response.transport_mode}"
            ],
            normalized_text=response.assistant_text,
            transport_mode=response.transport_mode,
            finish_reason=response.finish_reason,
            provider_response_id=response.response_id,
            protocol_errors=[
                f"Unsupported transport mode for runtime mainline: {response.transport_mode}"
            ],
            protocol_error_kind="unsupported_transport_contract",
            protocol_decision="protocol_error",
            tool_call_candidate_count=len(response.tool_calls),
            rejected_tool_call_candidate_count=len(response.tool_calls),
            raw_provider_payload=response.raw_provider_payload,
        )

    if (
        runtime_capabilities is not None
        and (
            runtime_capabilities.protocol_mode != "native_tool_calling"
            or not runtime_capabilities.supports_native_tools
        )
    ):
        return ParseResult(
            ok=False,
            assistant_content=response.assistant_text,
            parse_errors=[
                "Native provider response received under non-native runtime capabilities"
            ],
            parse_status="fatal",
            fatal_errors=[
                "Native provider response received under non-native runtime capabilities"
            ],
            normalized_text=response.assistant_text,
            transport_mode=response.transport_mode,
            finish_reason=response.finish_reason,
            provider_response_id=response.response_id,
            protocol_errors=[
                "Native provider response received under non-native runtime capabilities"
            ],
            protocol_error_kind="unsupported_transport_contract",
            protocol_decision="protocol_error",
            tool_call_candidate_count=len(response.tool_calls),
            rejected_tool_call_candidate_count=len(response.tool_calls),
            raw_provider_payload=response.raw_provider_payload,
        )

    return _interpret_native_tool_calling_response(response)


def _interpret_native_tool_calling_response(response: GenerateResponse) -> ParseResult:
    tool_calls: list[ToolCall] = []
    protocol_errors: list[str] = []
    accepted_tool_call_count = 0
    rejected_tool_call_candidate_count = 0

    for index, candidate in enumerate(response.tool_calls, start=1):
        call_id = candidate.call_id or f"native_call_{index}"
        name = str(candidate.name or "").strip()
        if not name:
            protocol_errors.append(f"Native tool call {call_id} missing name")
            rejected_tool_call_candidate_count += 1
            continue
        if candidate.arguments_parse_error is not None:
            protocol_errors.append(
                f"Native tool call {call_id} arguments parse error: {candidate.arguments_parse_error}"
            )
            rejected_tool_call_candidate_count += 1
            continue
        payload_kind = candidate.payload_kind
        if payload_kind == ToolPayloadKind.INPUT_TEXT:
            if not isinstance(candidate.input_text, str):
                protocol_errors.append(
                    f"Native tool call {call_id} missing freeform input text"
                )
                rejected_tool_call_candidate_count += 1
                continue
            tool_calls.append(
                ToolCall(
                    id=call_id,
                    name=name,
                    input_text=candidate.input_text,
                )
            )
        else:
            if candidate.arguments_obj is None:
                protocol_errors.append(
                    f"Native tool call {call_id} missing parsed arguments object"
                )
                rejected_tool_call_candidate_count += 1
                continue
            if not isinstance(candidate.arguments_obj, dict):
                protocol_errors.append(
                    f"Native tool call {call_id} arguments must be an object, got "
                    f"{type(candidate.arguments_obj).__name__}"
                )
                rejected_tool_call_candidate_count += 1
                continue
            tool_calls.append(
                ToolCall(
                    id=call_id,
                    name=name,
                    arguments=candidate.arguments_obj,
                )
            )
        accepted_tool_call_count += 1

    protocol_error_kind: str | None = None
    if protocol_errors:
        protocol_error_kind = "candidate_validation_error"
        tool_calls = []
    elif response.finish_reason == "tool_calls" and not tool_calls:
        protocol_errors.append(
            "Native response declared tool_calls finish_reason but provided no usable native tool calls"
        )
        protocol_error_kind = "finish_reason_contract_error"

    parse_errors = list(protocol_errors)
    parse_status = "fatal" if parse_errors else "ok"
    return ParseResult(
        ok=not parse_errors,
        assistant_content=response.assistant_text,
        tool_calls=tool_calls,
        parse_errors=parse_errors,
        parse_status=parse_status,
        format_family="native_tool_calling",
        fatal_errors=list(parse_errors),
        recovery_warnings=[],
        normalization_actions=[],
        normalized_text=response.assistant_text,
        transport_mode=response.transport_mode,
        finish_reason=response.finish_reason,
        provider_response_id=response.response_id,
        protocol_errors=protocol_errors,
        protocol_error_kind=protocol_error_kind,
        fallback_parser_used=False,
        protocol_decision="protocol_error" if parse_errors else "accept_native",
        text_fallback_used=False,
        fallback_reason=None,
        fallback_allowed=False,
        tool_call_candidate_count=len(response.tool_calls),
        accepted_tool_call_count=accepted_tool_call_count,
        rejected_tool_call_candidate_count=rejected_tool_call_candidate_count,
        raw_provider_payload=response.raw_provider_payload,
    )
