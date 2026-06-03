"""Tests for Claude gateway API-trace loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from pycodeagent.traces import (
    ClaudeGatewayEvent,
    group_claude_api_session,
    parse_messages_sse_events,
    read_claude_api_session,
)


_REAL_SESSION_PATH = Path(
    "runs/claude_gateway_traces/84f8f6fa-4cb3-480d-8e8a-a80fc035bdcc.jsonl"
)


def _real_session_path() -> Path:
    if not _REAL_SESSION_PATH.exists():
        pytest.skip(f"Missing real Claude session fixture: {_REAL_SESSION_PATH}")
    return _REAL_SESSION_PATH


class TestClaudeApiTraceLoader:
    def test_real_session_invariants(self) -> None:
        session = read_claude_api_session(_real_session_path())

        assert session.session_id == "84f8f6fa-4cb3-480d-8e8a-a80fc035bdcc"
        assert len(session.message_requests) == 1
        assert len(session.count_token_requests) == 0
        assert session.orphan_events == []

        request = session.message_requests[0]
        body = request.request_body
        assert body["model"] == "mimo-v2.5-pro"
        assert isinstance(body["messages"], list)
        assert isinstance(body["system"], list)
        assert isinstance(body.get("tools", []), list)
        assert body["stream"] is True

        event_names = request.sse_event_names
        assert "message_start" in event_names
        assert "content_block_start" in event_names
        assert "content_block_delta" in event_names
        assert "message_delta" in event_names
        assert "message_stop" in event_names

        assert request.stop_reason == "end_turn"
        usage = request.usage
        assert usage is not None
        assert usage["output_tokens"] == 21
        assert request.response_status_code == 200
        assert request.stream_completed is True

    def test_parse_messages_sse_events_extracts_fragments_from_multi_event_chunk(self) -> None:
        chunk = (
            "event: content_block_start\n"
            'data: {"type":"content_block_start","index":1,"content_block":{"type":"text","text":""}}\n\n'
            "event: content_block_delta\n"
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi there"},"index":1}\n\n'
            "event: content_block_delta\n"
            'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"Let me think"},"index":0}\n\n'
        )

        sse_events = parse_messages_sse_events(chunk, chunk_index=6)
        assert [event.event_name for event in sse_events] == [
            "content_block_start",
            "content_block_delta",
            "content_block_delta",
        ]
        assert sse_events[0].sequence_in_chunk == 0
        assert sse_events[1].sequence_in_chunk == 1
        assert sse_events[2].sequence_in_chunk == 2
        assert sse_events[1].data_json["delta"]["text"] == "Hi there"
        assert sse_events[2].data_json["delta"]["thinking"] == "Let me think"

        request = group_claude_api_session(
            [
                ClaudeGatewayEvent(
                    schema_version=1,
                    event_type="messages_request",
                    request_id="req_1",
                    session_id="session_1",
                    route="/v1/messages",
                    timestamp="2026-05-20T00:00:00+00:00",
                    data={"body": {"model": "mimo-v2.5-pro", "messages": [], "system": []}},
                ),
                ClaudeGatewayEvent(
                    schema_version=1,
                    event_type="messages_stream_chunk",
                    request_id="req_1",
                    session_id="session_1",
                    route="/v1/messages",
                    timestamp="2026-05-20T00:00:01+00:00",
                    data={"index": 6, "text": chunk},
                ),
                ClaudeGatewayEvent(
                    schema_version=1,
                    event_type="messages_stream_end",
                    request_id="req_1",
                    session_id="session_1",
                    route="/v1/messages",
                    timestamp="2026-05-20T00:00:02+00:00",
                    data={"status_code": 200, "chunk_count": 1, "error": None},
                ),
            ]
        ).message_requests[0]

        assert request.text_delta_fragments == ["Hi there"]
        assert request.thinking_delta_fragments == ["Let me think"]

    def test_parse_messages_sse_events_preserves_non_json_data(self) -> None:
        sse_events = parse_messages_sse_events(
            "event: ping\ndata: not-json\n\n",
            chunk_index=0,
        )

        assert len(sse_events) == 1
        assert sse_events[0].event_name == "ping"
        assert sse_events[0].data_raw == "not-json"
        assert sse_events[0].data_json is None

    def test_grouping_raises_on_orphan_messages_event_in_strict_mode(self) -> None:
        orphan = ClaudeGatewayEvent(
            schema_version=1,
            event_type="messages_stream_chunk",
            request_id="req_orphan",
            session_id="session_1",
            route="/v1/messages",
            timestamp="2026-05-20T00:00:00+00:00",
            data={"index": 0, "text": "event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n"},
        )

        with pytest.raises(ValueError, match="without anchor"):
            group_claude_api_session([orphan], strict=True)

    def test_grouping_collects_orphan_messages_event_in_non_strict_mode(self) -> None:
        orphan = ClaudeGatewayEvent(
            schema_version=1,
            event_type="messages_stream_chunk",
            request_id="req_orphan",
            session_id="session_1",
            route="/v1/messages",
            timestamp="2026-05-20T00:00:00+00:00",
            data={"index": 0, "text": "event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n"},
        )

        session = group_claude_api_session([orphan], strict=False)
        assert session.message_requests == []
        assert session.orphan_events == [orphan]

    def test_count_tokens_are_grouped_by_request_id(self) -> None:
        events = [
            ClaudeGatewayEvent(
                schema_version=1,
                event_type="count_tokens_request",
                request_id="count_req_1",
                session_id="session_1",
                route="/v1/messages/count_tokens",
                timestamp="2026-05-20T00:00:00+00:00",
                data={"body": {"model": "mimo-v2.5-pro", "messages": []}},
            ),
            ClaudeGatewayEvent(
                schema_version=1,
                event_type="count_tokens_response",
                request_id="count_req_1",
                session_id="session_1",
                route="/v1/messages/count_tokens",
                timestamp="2026-05-20T00:00:01+00:00",
                data={"status_code": 200, "body": {"input_tokens": 42}},
            ),
            ClaudeGatewayEvent(
                schema_version=1,
                event_type="count_tokens_request",
                request_id="count_req_2",
                session_id="session_1",
                route="/v1/messages/count_tokens",
                timestamp="2026-05-20T00:00:02+00:00",
                data={"body": {"model": "mimo-v2.5-pro", "messages": []}},
            ),
            ClaudeGatewayEvent(
                schema_version=1,
                event_type="count_tokens_error",
                request_id="count_req_2",
                session_id="session_1",
                route="/v1/messages/count_tokens",
                timestamp="2026-05-20T00:00:03+00:00",
                data={"phase": "response", "status_code": 429, "body": {"error": "rate_limited"}},
            ),
        ]

        session = group_claude_api_session(events)

        assert [request.request_id for request in session.count_token_requests] == [
            "count_req_1",
            "count_req_2",
        ]
        assert session.count_token_requests_by_id["count_req_1"].response_body == {
            "input_tokens": 42
        }
        assert session.count_token_requests_by_id["count_req_2"].response_event is None
        assert len(session.count_token_requests_by_id["count_req_2"].error_events) == 1
