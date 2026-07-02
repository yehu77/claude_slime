"""LLM client interfaces and provider-response protocol contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from pycodeagent.tools.contracts import (
    ExposedToolSpec,
    ToolPayloadKind,
)


RequestKind = Literal["agent_turn", "context_compaction"]


class StructuredOutputSchema(BaseModel):
    """Structured output contract requested from the provider."""

    name: str
    schema: dict[str, Any]
    strict: bool = True


class GenerateRequest(BaseModel):
    """Input to the LLM generate call."""

    messages: list[dict[str, Any]]
    tools: list[ExposedToolSpec]
    request_kind: RequestKind = "agent_turn"
    structured_output_schema: StructuredOutputSchema | None = None

    @field_validator("tools", mode="before")
    @classmethod
    def _normalize_tools(cls, value: Any) -> list[ExposedToolSpec]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("GenerateRequest.tools must be a list")
        return [ExposedToolSpec.model_validate(spec) for spec in value]


RuntimeProtocolMode = Literal["native_tool_calling"]
StructuredFinishMode = Literal["finish_tool_call", "assistant_completion"]


class RuntimeClientCapabilities(BaseModel):
    """Stable runtime-protocol capabilities exposed by one LLM client.

    These capabilities define how the runtime should shape prompts,
    interpret provider responses, and record protocol provenance.
    """

    protocol_mode: RuntimeProtocolMode = "native_tool_calling"
    supports_native_tools: bool = True
    text_fallback_allowed: bool = False
    structured_finish_mode: StructuredFinishMode = "finish_tool_call"
    supports_structured_output: bool = False
    supports_model_backed_compaction: bool = False
    provider_family: str = "generic"
    provider_name: str = "unknown"


class ToolCallCandidate(BaseModel):
    """Provider-level candidate tool call before runtime dispatch."""

    call_id: str | None = None
    name: str = ""
    arguments_raw: str | None = None
    arguments_obj: dict[str, Any] | None = None
    input_text: str | None = None
    arguments_parse_error: str | None = None
    source: str = "text_parsed"

    @property
    def payload_kind(self) -> ToolPayloadKind | None:
        if self.input_text is not None:
            return ToolPayloadKind.INPUT_TEXT
        if self.arguments_obj is not None:
            return ToolPayloadKind.ARGUMENTS_OBJECT
        return None

    @model_validator(mode="after")
    def _validate_payload_shape(self) -> "ToolCallCandidate":
        if self.input_text is not None and self.arguments_obj is not None:
            raise ValueError(
                "ToolCallCandidate cannot contain both input_text and arguments_obj"
            )
        return self

    def model_dump(self, *args, **kwargs) -> dict[str, Any]:  # type: ignore[override]
        data = super().model_dump(*args, **kwargs)
        if data.get("input_text") is None:
            data.pop("input_text", None)
        return data


class GenerateResponse(BaseModel):
    """Structured provider response envelope consumed by the runtime."""

    transport_mode: str = "native_tool_calling"
    text: str = ""
    assistant_text: str = ""
    reasoning_content: str | None = None
    tool_calls: list[ToolCallCandidate] = Field(default_factory=list)
    finish_reason: str | None = None
    response_id: str | None = None
    raw_text: str | None = None
    raw_provider_payload: dict[str, Any] | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    request_kind: RequestKind = "agent_turn"
    structured_output: dict[str, Any] | None = None
    structured_output_parse_error: str | None = None

    @model_validator(mode="after")
    def _sync_text_fields(self) -> "GenerateResponse":
        if not self.assistant_text and self.text:
            self.assistant_text = self.text
        if not self.text and self.assistant_text:
            self.text = self.assistant_text
        return self

    @classmethod
    def from_native_tool_calling(
        cls,
        *,
        assistant_text: str = "",
        tool_calls: list[ToolCallCandidate] | None = None,
        reasoning_content: str | None = None,
        finish_reason: str | None = None,
        response_id: str | None = None,
        raw_provider_payload: dict[str, Any] | None = None,
        provider_metadata: dict[str, Any] | None = None,
        request_kind: RequestKind = "agent_turn",
        structured_output: dict[str, Any] | None = None,
        structured_output_parse_error: str | None = None,
    ) -> "GenerateResponse":
        return cls(
            transport_mode="native_tool_calling",
            text=assistant_text,
            assistant_text=assistant_text,
            tool_calls=list(tool_calls or []),
            reasoning_content=reasoning_content,
            finish_reason=finish_reason,
            response_id=response_id,
            raw_text=None,
            raw_provider_payload=raw_provider_payload,
            provider_metadata=provider_metadata or {},
            request_kind=request_kind,
            structured_output=structured_output,
            structured_output_parse_error=structured_output_parse_error,
        )


class BaseLLMClient(ABC):
    """Abstract base class for runtime LLM clients."""

    @abstractmethod
    def generate(self, request: GenerateRequest) -> GenerateResponse:
        """Generate a text response given messages and tool specs."""
        ...

    def runtime_provenance(self) -> dict[str, Any]:
        """Return non-secret provider/runtime provenance for artifacts.

        The default is empty so deterministic test clients do not force
        artifact churn unless a concrete provider wants to expose metadata.
        """
        return {}

    def runtime_capabilities(self) -> RuntimeClientCapabilities:
        """Return runtime protocol capabilities for prompt/response handling.

        The default follows the native-tools runtime mainline. Legacy text-mode
        clients should override this explicitly instead of inheriting a text-first
        fallback contract.
        """
        return RuntimeClientCapabilities()


class FakeLLMClient(BaseLLMClient):
    """A fake LLM client that returns predetermined responses.

    Used for deterministic testing. Each call to generate() returns the
    next response from the queue, or repeats the last response if the
    queue is exhausted.
    """

    def __init__(
        self,
        responses: list[GenerateResponse | dict[str, Any]],
        *,
        capabilities: RuntimeClientCapabilities | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> None:
        """Initialize with predetermined structured responses.

        Args:
            responses: List of GenerateResponse envelopes or payload dicts
                accepted by GenerateResponse.
        """
        self._responses = list(responses)
        self._call_count = 0
        self._capabilities = capabilities or self._infer_capabilities_from_responses()
        self._provenance = dict(provenance or {})

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        """Return the next predetermined response."""
        if not self._responses:
            raise RuntimeError("FakeLLMClient has no responses configured")

        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        response = self._responses[idx]
        if isinstance(response, GenerateResponse):
            return response
        if isinstance(response, dict):
            return GenerateResponse.model_validate(response)
        raise RuntimeError(
            "FakeLLMClient only supports GenerateResponse or dict payloads under the "
            "native-tools runtime mainline."
        )

    @property
    def call_count(self) -> int:
        """Number of times generate() has been called."""
        return self._call_count

    def runtime_capabilities(self) -> RuntimeClientCapabilities:
        return self._capabilities

    def runtime_provenance(self) -> dict[str, Any]:
        return dict(self._provenance)

    def _infer_capabilities_from_responses(self) -> RuntimeClientCapabilities:
        if not self._responses:
            return RuntimeClientCapabilities()

        first = self._responses[0]
        if isinstance(first, GenerateResponse):
            return RuntimeClientCapabilities(
                protocol_mode="native_tool_calling",
                supports_native_tools=True,
                text_fallback_allowed=False,
                structured_finish_mode="finish_tool_call",
                supports_structured_output=True,
                supports_model_backed_compaction=True,
                provider_family="fake",
                provider_name="fake_native",
            )

        if isinstance(first, dict):
            return RuntimeClientCapabilities(
                protocol_mode="native_tool_calling",
                supports_native_tools=True,
                text_fallback_allowed=False,
                structured_finish_mode="finish_tool_call",
                supports_structured_output=True,
                supports_model_backed_compaction=True,
                provider_family="fake",
                provider_name="fake_native",
            )

        return RuntimeClientCapabilities(
            protocol_mode="native_tool_calling",
            supports_native_tools=True,
            text_fallback_allowed=False,
            structured_finish_mode="finish_tool_call",
            supports_structured_output=True,
            supports_model_backed_compaction=True,
            provider_family="fake",
            provider_name="fake_native",
        )
