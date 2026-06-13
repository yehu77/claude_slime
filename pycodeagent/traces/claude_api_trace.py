"""Claude gateway API-trace contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ClaudeGatewayEvent(BaseModel):
    """One event row emitted by ``claude_gateway_proxy.py``."""

    schema_version: int
    event_type: str
    request_id: str
    session_id: str
    agent_id: str | None = None
    parent_agent_id: str | None = None
    route: str
    timestamp: str
    data: dict[str, Any] = Field(default_factory=dict)


class ClaudeSseEvent(BaseModel):
    """One SSE event reconstructed from a streamed messages chunk."""

    event_name: str
    data_raw: str
    data_json: dict[str, Any] | None = None
    chunk_index: int
    sequence_in_chunk: int


class ClaudeApiRequest(BaseModel):
    """One grouped ``/v1/messages`` request."""

    request_event: ClaudeGatewayEvent
    response_headers_event: ClaudeGatewayEvent | None = None
    stream_chunk_events: list[ClaudeGatewayEvent] = Field(default_factory=list)
    stream_end_event: ClaudeGatewayEvent | None = None
    error_events: list[ClaudeGatewayEvent] = Field(default_factory=list)
    sse_events: list[ClaudeSseEvent] = Field(default_factory=list)

    @property
    def request_id(self) -> str:
        return self.request_event.request_id

    @property
    def request_body(self) -> dict[str, Any]:
        body = self.request_event.data.get("body")
        return body if isinstance(body, dict) else {}

    @property
    def response_status_code(self) -> int | None:
        if self.response_headers_event is None:
            return None
        value = self.response_headers_event.data.get("status_code")
        return int(value) if isinstance(value, int | float) else None

    @property
    def stream_text(self) -> str:
        ordered = sorted(
            self.stream_chunk_events,
            key=lambda event: int(event.data.get("index", 0)),
        )
        return "".join(str(event.data.get("text", "")) for event in ordered)

    @property
    def stream_completed(self) -> bool:
        return self.stream_end_event is not None and self.stream_end_event.data.get("error") is None

    @property
    def sse_event_names(self) -> list[str]:
        return [event.event_name for event in self.sse_events]

    @property
    def text_delta_fragments(self) -> list[str]:
        fragments: list[str] = []
        for event in self.sse_events:
            data = event.data_json or {}
            if event.event_name != "content_block_delta":
                continue
            delta = data.get("delta")
            if not isinstance(delta, dict):
                continue
            if delta.get("type") == "text_delta":
                text = delta.get("text")
                if isinstance(text, str):
                    fragments.append(text)
        return fragments

    @property
    def thinking_delta_fragments(self) -> list[str]:
        fragments: list[str] = []
        for event in self.sse_events:
            data = event.data_json or {}
            if event.event_name != "content_block_delta":
                continue
            delta = data.get("delta")
            if not isinstance(delta, dict):
                continue
            if delta.get("type") == "thinking_delta":
                thinking = delta.get("thinking")
                if isinstance(thinking, str):
                    fragments.append(thinking)
        return fragments

    @property
    def stop_reason(self) -> str | None:
        for event in reversed(self.sse_events):
            if event.event_name != "message_delta":
                continue
            data = event.data_json or {}
            delta = data.get("delta")
            if not isinstance(delta, dict):
                continue
            reason = delta.get("stop_reason")
            if isinstance(reason, str):
                return reason
        return None

    @property
    def usage(self) -> dict[str, Any] | None:
        for event in reversed(self.sse_events):
            if event.event_name != "message_delta":
                continue
            data = event.data_json or {}
            usage = data.get("usage")
            if isinstance(usage, dict):
                return usage
        return None


class ClaudeCountTokensRequest(BaseModel):
    """One grouped ``/v1/messages/count_tokens`` request."""

    request_event: ClaudeGatewayEvent
    response_event: ClaudeGatewayEvent | None = None
    error_events: list[ClaudeGatewayEvent] = Field(default_factory=list)

    @property
    def request_id(self) -> str:
        return self.request_event.request_id

    @property
    def request_body(self) -> dict[str, Any]:
        body = self.request_event.data.get("body")
        return body if isinstance(body, dict) else {}

    @property
    def response_status_code(self) -> int | None:
        if self.response_event is None:
            return None
        value = self.response_event.data.get("status_code")
        return int(value) if isinstance(value, int | float) else None

    @property
    def response_body(self) -> dict[str, Any] | None:
        if self.response_event is None:
            return None
        body = self.response_event.data.get("body")
        return body if isinstance(body, dict) else None


class ClaudeApiSession(BaseModel):
    """One loaded Claude gateway session trace."""

    session_id: str
    events: list[ClaudeGatewayEvent] = Field(default_factory=list)
    message_requests: list[ClaudeApiRequest] = Field(default_factory=list)
    count_token_requests: list[ClaudeCountTokensRequest] = Field(default_factory=list)
    orphan_events: list[ClaudeGatewayEvent] = Field(default_factory=list)

    @property
    def message_requests_by_id(self) -> dict[str, ClaudeApiRequest]:
        return {request.request_id: request for request in self.message_requests}

    @property
    def count_token_requests_by_id(self) -> dict[str, ClaudeCountTokensRequest]:
        return {request.request_id: request for request in self.count_token_requests}
