"""Extract auxiliary samples from Claude gateway API traces."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from pycodeagent.auxiliary.claude_api.trace import (
    ClaudeApiRequest,
    ClaudeApiSession,
    ClaudeSseEvent,
)
from pycodeagent.auxiliary.claude_api.trace_loader import read_claude_api_session

ClaudeExtractedBlockType = Literal["thinking", "text", "tool_use", "tool_result", "unknown"]


class ClaudeExtractedBlock(BaseModel):
    """One structured response block extracted from Claude SSE events."""

    block_type: ClaudeExtractedBlockType
    index: int | None = None
    text_fragments: list[str] = Field(default_factory=list)
    raw_sse_events: list[ClaudeSseEvent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClaudeExtractedRequestSample(BaseModel):
    """Intermediate extracted sample from one Claude messages request."""

    sample_id: str
    session_id: str
    request_id: str
    source_type: Literal["claude_api_trace"] = "claude_api_trace"
    model: str | None = None
    request_messages: list[dict[str, Any]] = Field(default_factory=list)
    request_system: list[dict[str, Any]] = Field(default_factory=list)
    request_tools: list[dict[str, Any]] = Field(default_factory=list)
    request_metadata: dict[str, Any] = Field(default_factory=dict)
    response_blocks: list[ClaudeExtractedBlock] = Field(default_factory=list)
    stop_reason: str | None = None
    usage: dict[str, Any] | None = None
    stream_completed: bool = False
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClaudeExtractedSession(BaseModel):
    """Intermediate extracted samples for one Claude gateway session."""

    session_id: str
    samples: list[ClaudeExtractedRequestSample] = Field(default_factory=list)
    skipped_request_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _get_request_metadata(body: dict[str, Any]) -> dict[str, Any]:
    excluded = {"model", "messages", "system", "tools"}
    return {key: value for key, value in body.items() if key not in excluded}


def _get_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _get_block_type(event: ClaudeSseEvent) -> ClaudeExtractedBlockType:
    data = event.data_json or {}
    if event.event_name == "content_block_start":
        content_block = data.get("content_block")
        if isinstance(content_block, dict):
            block_type = content_block.get("type")
            if block_type in {"thinking", "text", "tool_use", "tool_result"}:
                return block_type
    return "unknown"


def _build_delta_text(event: ClaudeSseEvent) -> str | None:
    data = event.data_json or {}
    if event.event_name != "content_block_delta":
        return None
    delta = data.get("delta")
    if not isinstance(delta, dict):
        return None
    delta_type = delta.get("type")
    if delta_type == "thinking_delta":
        thinking = delta.get("thinking")
        return thinking if isinstance(thinking, str) else None
    if delta_type == "text_delta":
        text = delta.get("text")
        return text if isinstance(text, str) else None
    return None


def get_claude_request_error(request: ClaudeApiRequest) -> str | None:
    """Return a normalized request-level error string, if any."""
    errors: list[str] = []
    if request.stream_end_event is not None:
        end_error = request.stream_end_event.data.get("error")
        if isinstance(end_error, str) and end_error:
            errors.append(end_error)
    for event in request.error_events:
        payload_error = event.data.get("error")
        if isinstance(payload_error, str) and payload_error:
            errors.append(payload_error)
        else:
            errors.append(event.event_type)
    if not request.stream_completed and not errors:
        errors.append("incomplete_stream")
    if not request.sse_events and not errors:
            errors.append("missing_sse_events")
    if not errors:
        return None
    return "; ".join(errors)


def _extract_response_blocks(request: ClaudeApiRequest) -> list[ClaudeExtractedBlock]:
    blocks: list[ClaudeExtractedBlock] = []
    current: ClaudeExtractedBlock | None = None

    def finalize_current() -> None:
        nonlocal current
        if current is not None:
            blocks.append(current)
            current = None

    for event in request.sse_events:
        data = event.data_json or {}
        if event.event_name == "content_block_start":
            finalize_current()
            current = ClaudeExtractedBlock(
                block_type=_get_block_type(event),
                index=_get_int(data.get("index")),
                raw_sse_events=[event],
                metadata={"start_payload": data},
            )
            continue

        if event.event_name == "content_block_delta":
            if current is None:
                current = ClaudeExtractedBlock(
                    block_type="unknown",
                    index=_get_int(data.get("index")),
                    metadata={"synthetic_open": True},
                )
            current.raw_sse_events.append(event)
            current.metadata.setdefault("delta_payloads", []).append(data)
            text = _build_delta_text(event)
            if text is not None:
                current.text_fragments.append(text)
            continue

        if event.event_name == "content_block_stop":
            if current is None:
                current = ClaudeExtractedBlock(
                    block_type="unknown",
                    index=_get_int(data.get("index")),
                    metadata={"synthetic_open": True},
                )
            current.raw_sse_events.append(event)
            current.metadata["stop_payload"] = data
            finalize_current()
            continue

        if current is not None:
            current.raw_sse_events.append(event)

    finalize_current()
    return blocks


def extract_claude_request_sample(
    request: ClaudeApiRequest,
    *,
    include_incomplete: bool = False,
) -> ClaudeExtractedRequestSample | None:
    """Extract one intermediate sample from a Claude messages request."""
    error = get_claude_request_error(request)
    if error is not None and not include_incomplete:
        return None

    body = request.request_body
    messages = body.get("messages")
    system = body.get("system")
    tools = body.get("tools")

    return ClaudeExtractedRequestSample(
        sample_id=f"{request.request_event.session_id}:{request.request_id}",
        session_id=request.request_event.session_id,
        request_id=request.request_id,
        model=body.get("model") if isinstance(body.get("model"), str) else None,
        request_messages=messages if isinstance(messages, list) else [],
        request_system=system if isinstance(system, list) else [],
        request_tools=tools if isinstance(tools, list) else [],
        request_metadata=_get_request_metadata(body),
        response_blocks=_extract_response_blocks(request),
        stop_reason=request.stop_reason,
        usage=request.usage,
        stream_completed=request.stream_completed,
        error=error,
        metadata={
            "response_status_code": request.response_status_code,
            "agent_id": request.request_event.agent_id,
            "parent_agent_id": request.request_event.parent_agent_id,
            "error_event_count": len(request.error_events),
        },
    )


def extract_claude_session(
    session: ClaudeApiSession,
    *,
    include_incomplete: bool = False,
) -> ClaudeExtractedSession:
    """Extract intermediate samples from one loaded Claude session."""
    samples: list[ClaudeExtractedRequestSample] = []
    skipped_request_ids: list[str] = []
    for request in session.message_requests:
        sample = extract_claude_request_sample(
            request,
            include_incomplete=include_incomplete,
        )
        if sample is None:
            skipped_request_ids.append(request.request_id)
            continue
        samples.append(sample)

    return ClaudeExtractedSession(
        session_id=session.session_id,
        samples=samples,
        skipped_request_ids=skipped_request_ids,
        metadata={
            "message_request_count": len(session.message_requests),
            "count_token_request_count": len(session.count_token_requests),
            "orphan_event_count": len(session.orphan_events),
            "error_request_count": sum(
                1 for request in session.message_requests if get_claude_request_error(request) is not None
            ),
            "incomplete_request_count": sum(
                1 for request in session.message_requests if not request.stream_completed
            ),
        },
    )


def extract_claude_session_from_path(
    path: str,
    *,
    strict: bool = True,
    include_incomplete: bool = False,
) -> ClaudeExtractedSession:
    """Load and extract one Claude gateway session JSONL."""
    session = read_claude_api_session(path, strict=strict)
    extracted = extract_claude_session(session, include_incomplete=include_incomplete)
    extracted.metadata["source_trace_path"] = str(path)
    return extracted
