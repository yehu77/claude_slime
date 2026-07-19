"""Tests for Claude API-trace intermediate extraction."""

from __future__ import annotations

from pathlib import Path

from pycodeagent.auxiliary.claude_api.trace import (
    ClaudeApiRequest,
    ClaudeApiSession,
    ClaudeGatewayEvent,
    ClaudeSseEvent,
)
from pycodeagent.auxiliary.claude_api.trace_extract import (
    extract_claude_request_sample,
    extract_claude_session,
    extract_claude_session_from_path,
)


_REAL_SESSION_PATH = Path(
    "runs/claude_gateway_traces/84f8f6fa-4cb3-480d-8e8a-a80fc035bdcc.jsonl"
)


def _real_session_path() -> Path:
    if not _REAL_SESSION_PATH.exists():
        import pytest

        pytest.skip(f"Missing real Claude session fixture: {_REAL_SESSION_PATH}")
    return _REAL_SESSION_PATH


def _make_request(
    *,
    session_id: str = "session_1",
    request_id: str = "req_1",
    stream_completed: bool = True,
    error: str | None = None,
    sse_events: list[ClaudeSseEvent] | None = None,
    body: dict | None = None,
) -> ClaudeApiRequest:
    request_event = ClaudeGatewayEvent(
        schema_version=1,
        event_type="messages_request",
        request_id=request_id,
        session_id=session_id,
        route="/v1/messages",
        timestamp="2026-05-20T00:00:00+00:00",
        data={
            "body": body
            or {
                "model": "mimo-v2.5-pro",
                "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                "system": [{"type": "text", "text": "system"}],
                "tools": [{"name": "ToolA"}],
                "stream": True,
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": "high"},
            }
        },
    )
    stream_end_event = ClaudeGatewayEvent(
        schema_version=1,
        event_type="messages_stream_end",
        request_id=request_id,
        session_id=session_id,
        route="/v1/messages",
        timestamp="2026-05-20T00:00:01+00:00",
        data={"status_code": 200, "chunk_count": len(sse_events or []), "error": error},
    )
    request = ClaudeApiRequest(
        request_event=request_event,
        stream_end_event=stream_end_event if stream_completed or error is not None else None,
        sse_events=sse_events or [],
    )
    if error is not None:
        request.error_events.append(
            ClaudeGatewayEvent(
                schema_version=1,
                event_type="messages_error",
                request_id=request_id,
                session_id=session_id,
                route="/v1/messages",
                timestamp="2026-05-20T00:00:02+00:00",
                data={"phase": "stream", "error": error},
            )
        )
    return request


class TestClaudeApiTraceExtract:
    def test_real_session_extract_invariants(self) -> None:
        extracted = extract_claude_session_from_path(_real_session_path())

        assert extracted.session_id == "84f8f6fa-4cb3-480d-8e8a-a80fc035bdcc"
        assert extracted.skipped_request_ids == []
        assert len(extracted.samples) == 1

        sample = extracted.samples[0]
        assert sample.model == "mimo-v2.5-pro"
        assert isinstance(sample.request_messages, list)
        assert isinstance(sample.request_system, list)
        assert isinstance(sample.request_tools, list)
        assert sample.stream_completed is True
        assert sample.stop_reason == "end_turn"
        assert sample.usage is not None
        block_types = [block.block_type for block in sample.response_blocks]
        assert "thinking" in block_types
        assert "text" in block_types

    def test_extract_request_rebuilds_multiple_block_types(self) -> None:
        sse_events = [
            ClaudeSseEvent(
                event_name="content_block_start",
                data_raw='{"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}',
                data_json={
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "thinking", "thinking": ""},
                },
                chunk_index=0,
                sequence_in_chunk=0,
            ),
            ClaudeSseEvent(
                event_name="content_block_delta",
                data_raw='{"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"Let me think"},"index":0}',
                data_json={
                    "type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "Let me think"},
                    "index": 0,
                },
                chunk_index=0,
                sequence_in_chunk=1,
            ),
            ClaudeSseEvent(
                event_name="content_block_stop",
                data_raw='{"type":"content_block_stop","index":0}',
                data_json={"type": "content_block_stop", "index": 0},
                chunk_index=0,
                sequence_in_chunk=2,
            ),
            ClaudeSseEvent(
                event_name="content_block_start",
                data_raw='{"type":"content_block_start","index":1,"content_block":{"type":"text","text":""}}',
                data_json={
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {"type": "text", "text": ""},
                },
                chunk_index=1,
                sequence_in_chunk=0,
            ),
            ClaudeSseEvent(
                event_name="content_block_delta",
                data_raw='{"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"},"index":1}',
                data_json={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "Hello"},
                    "index": 1,
                },
                chunk_index=1,
                sequence_in_chunk=1,
            ),
            ClaudeSseEvent(
                event_name="content_block_stop",
                data_raw='{"type":"content_block_stop","index":1}',
                data_json={"type": "content_block_stop", "index": 1},
                chunk_index=1,
                sequence_in_chunk=2,
            ),
            ClaudeSseEvent(
                event_name="content_block_start",
                data_raw='{"type":"content_block_start","index":2,"content_block":{"type":"tool_use","name":"Read","id":"toolu_1"}}',
                data_json={
                    "type": "content_block_start",
                    "index": 2,
                    "content_block": {"type": "tool_use", "name": "Read", "id": "toolu_1"},
                },
                chunk_index=2,
                sequence_in_chunk=0,
            ),
            ClaudeSseEvent(
                event_name="content_block_stop",
                data_raw='{"type":"content_block_stop","index":2}',
                data_json={"type": "content_block_stop", "index": 2},
                chunk_index=2,
                sequence_in_chunk=1,
            ),
            ClaudeSseEvent(
                event_name="message_delta",
                data_raw='{"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":7}}',
                data_json={
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 7},
                },
                chunk_index=3,
                sequence_in_chunk=0,
            ),
        ]

        sample = extract_claude_request_sample(_make_request(sse_events=sse_events))

        assert sample is not None
        assert [block.block_type for block in sample.response_blocks] == [
            "thinking",
            "text",
            "tool_use",
        ]
        assert sample.response_blocks[0].text_fragments == ["Let me think"]
        assert sample.response_blocks[1].text_fragments == ["Hello"]
        assert sample.response_blocks[2].metadata["start_payload"]["content_block"]["name"] == "Read"
        assert sample.stop_reason == "end_turn"
        assert sample.usage == {"output_tokens": 7}
        assert sample.request_metadata["thinking"] == {"type": "adaptive"}
        assert sample.request_metadata["output_config"] == {"effort": "high"}

    def test_extract_request_skips_incomplete_by_default(self) -> None:
        sample = extract_claude_request_sample(_make_request(sse_events=[], stream_completed=False))
        assert sample is None

    def test_extract_request_can_include_incomplete_with_error(self) -> None:
        sample = extract_claude_request_sample(
            _make_request(sse_events=[], stream_completed=False, error="stream failed"),
            include_incomplete=True,
        )

        assert sample is not None
        assert sample.stream_completed is False
        assert sample.error is not None
        assert "stream failed" in sample.error

    def test_extract_session_records_skipped_request_ids(self) -> None:
        session = ClaudeApiSession(
            session_id="session_1",
            message_requests=[
                _make_request(request_id="req_good", sse_events=[
                    ClaudeSseEvent(
                        event_name="message_delta",
                        data_raw='{"type":"message_delta","delta":{"stop_reason":"end_turn"}}',
                        data_json={
                            "type": "message_delta",
                            "delta": {"stop_reason": "end_turn"},
                        },
                        chunk_index=0,
                        sequence_in_chunk=0,
                    )
                ]),
                _make_request(request_id="req_bad", sse_events=[], stream_completed=False),
            ],
            count_token_requests=[],
            orphan_events=[],
            events=[],
        )

        extracted = extract_claude_session(session)
        assert [sample.request_id for sample in extracted.samples] == ["req_good"]
        assert extracted.skipped_request_ids == ["req_bad"]
        assert extracted.metadata["count_token_request_count"] == 0
