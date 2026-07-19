"""Load and group auxiliary Claude gateway API-trace JSONL sessions."""

from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.auxiliary.claude_api.trace import (
    ClaudeApiRequest,
    ClaudeApiSession,
    ClaudeCountTokensRequest,
    ClaudeGatewayEvent,
    ClaudeSseEvent,
)


_MESSAGES_ROUTE = "/v1/messages"
_COUNT_TOKENS_ROUTE = "/v1/messages/count_tokens"


def read_claude_gateway_events(path: str | Path) -> list[ClaudeGatewayEvent]:
    """Load Claude gateway JSONL events."""
    source = Path(path)
    events: list[ClaudeGatewayEvent] = []
    with open(source, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            payload = line.strip()
            if not payload:
                continue
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid Claude gateway JSON on line {line_number}: {exc}"
                ) from exc
            try:
                events.append(ClaudeGatewayEvent.model_validate(data))
            except Exception as exc:
                raise ValueError(
                    f"Invalid Claude gateway event on line {line_number}: {exc}"
                ) from exc
    return events


def parse_messages_sse_events(text: str, *, chunk_index: int) -> list[ClaudeSseEvent]:
    """Parse one streamed chunk payload into one or more SSE events."""
    normalized = text.replace("\r\n", "\n")
    blocks = [block for block in normalized.split("\n\n") if block.strip()]
    parsed: list[ClaudeSseEvent] = []
    for sequence_in_chunk, block in enumerate(blocks):
        event_name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if not line:
                continue
            if line.startswith("event:"):
                event_name = line.partition(":")[2].strip() or "message"
                continue
            if line.startswith("data:"):
                data_lines.append(line.partition(":")[2].lstrip())
        if not data_lines:
            raise ValueError(f"SSE block missing data payload: {block!r}")
        data_raw = "\n".join(data_lines)
        data_json = None
        try:
            loaded = json.loads(data_raw)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            data_json = loaded
        parsed.append(
            ClaudeSseEvent(
                event_name=event_name,
                data_raw=data_raw,
                data_json=data_json,
                chunk_index=chunk_index,
                sequence_in_chunk=sequence_in_chunk,
            )
        )
    return parsed


def group_claude_api_session(
    events: list[ClaudeGatewayEvent],
    *,
    strict: bool = True,
) -> ClaudeApiSession:
    """Group Claude gateway events into request-level session objects."""
    if not events:
        raise ValueError("Claude gateway session cannot be empty")

    session_ids = {event.session_id for event in events}
    if len(session_ids) != 1:
        raise ValueError(f"Expected one session_id per file, got {sorted(session_ids)}")
    session_id = next(iter(session_ids))

    message_requests: dict[str, ClaudeApiRequest] = {}
    message_order: list[str] = []
    count_token_requests: dict[str, ClaudeCountTokensRequest] = {}
    count_token_order: list[str] = []
    orphan_events: list[ClaudeGatewayEvent] = []

    def _orphan_or_raise(event: ClaudeGatewayEvent) -> None:
        if strict:
            raise ValueError(
                f"Found {event.event_type} without anchor request_id={event.request_id}"
            )
        orphan_events.append(event)

    for event in events:
        if event.route == _MESSAGES_ROUTE:
            if event.event_type == "messages_request":
                request = ClaudeApiRequest(request_event=event)
                message_requests[event.request_id] = request
                message_order.append(event.request_id)
                continue
            request = message_requests.get(event.request_id)
            if request is None:
                _orphan_or_raise(event)
                continue
            if event.event_type == "messages_response_headers":
                request.response_headers_event = event
            elif event.event_type == "messages_stream_chunk":
                request.stream_chunk_events.append(event)
                chunk_index = int(event.data.get("index", len(request.stream_chunk_events) - 1))
                chunk_text = str(event.data.get("text", ""))
                request.sse_events.extend(
                    parse_messages_sse_events(chunk_text, chunk_index=chunk_index)
                )
            elif event.event_type == "messages_stream_end":
                request.stream_end_event = event
            elif event.event_type == "messages_error":
                request.error_events.append(event)
            else:
                _orphan_or_raise(event)
            continue

        if event.route == _COUNT_TOKENS_ROUTE:
            if event.event_type == "count_tokens_request":
                request = ClaudeCountTokensRequest(request_event=event)
                count_token_requests[event.request_id] = request
                count_token_order.append(event.request_id)
                continue
            request = count_token_requests.get(event.request_id)
            if request is None:
                _orphan_or_raise(event)
                continue
            if event.event_type == "count_tokens_response":
                request.response_event = event
            elif event.event_type == "count_tokens_error":
                request.error_events.append(event)
            else:
                _orphan_or_raise(event)
            continue

        _orphan_or_raise(event)

    return ClaudeApiSession(
        session_id=session_id,
        events=events,
        message_requests=[message_requests[request_id] for request_id in message_order],
        count_token_requests=[
            count_token_requests[request_id] for request_id in count_token_order
        ],
        orphan_events=orphan_events,
    )


def read_claude_api_session(path: str | Path, *, strict: bool = True) -> ClaudeApiSession:
    """Read and group one Claude gateway session JSONL."""
    events = read_claude_gateway_events(path)
    return group_claude_api_session(events, strict=strict)
