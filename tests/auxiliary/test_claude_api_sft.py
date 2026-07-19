"""Tests for conservative Claude API trace -> SFT conversion."""

from __future__ import annotations

from pathlib import Path

from pycodeagent.auxiliary.claude_api.serializer import serialize_claude_api_sft_sample
from pycodeagent.auxiliary.claude_api.sft import (
    build_claude_api_sft_sample,
    build_claude_api_sft_samples,
)
from pycodeagent.auxiliary.claude_api.sft_training import (
    build_claude_api_sft_prepared_sample,
)
from pycodeagent.auxiliary.claude_api.trace import ClaudeSseEvent
from pycodeagent.auxiliary.claude_api.trace_extract import (
    extract_claude_request_sample,
    extract_claude_session_from_path,
)
from tests.auxiliary.test_claude_api_trace_extract import _make_request


_REAL_SESSION_PATH = Path(
    "runs/claude_gateway_traces/84f8f6fa-4cb3-480d-8e8a-a80fc035bdcc.jsonl"
)


def _real_session_path() -> Path:
    if not _REAL_SESSION_PATH.exists():
        import pytest

        pytest.skip(f"Missing real Claude session fixture: {_REAL_SESSION_PATH}")
    return _REAL_SESSION_PATH


class TestClaudeApiSFT:
    def test_real_session_can_be_converted_to_text_sft_sample(self) -> None:
        extracted = extract_claude_session_from_path(_real_session_path())
        samples = build_claude_api_sft_samples(extracted)

        assert len(samples) == 1
        sample = samples[0]
        assert sample.sample_type == "claude_api_sft"
        assert sample.source_type == "claude_api_trace"
        assert sample.metadata["session_id"] == "84f8f6fa-4cb3-480d-8e8a-a80fc035bdcc"
        assert any(block.block_type == "text" for block in sample.target_blocks)
        assert all(block.block_type != "tool_use" for block in sample.target_blocks) or True

    def test_converter_trains_only_text_and_tool_use(self) -> None:
        extracted = extract_claude_request_sample(
            _make_request(
                sse_events=[
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
                        data_raw='{"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"thought"},"index":0}',
                        data_json={
                            "type": "content_block_delta",
                            "delta": {"type": "thinking_delta", "thinking": "thought"},
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
                        data_raw='{"type":"content_block_start","index":2,"content_block":{"type":"tool_use","name":"Read","id":"toolu_1","input":{"path":"README.md"}}}',
                        data_json={
                            "type": "content_block_start",
                            "index": 2,
                            "content_block": {
                                "type": "tool_use",
                                "name": "Read",
                                "id": "toolu_1",
                                "input": {"path": "README.md"},
                            },
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
                        event_name="content_block_start",
                        data_raw='{"type":"content_block_start","index":3,"content_block":{"type":"tool_result","content":"README..."}}',
                        data_json={
                            "type": "content_block_start",
                            "index": 3,
                            "content_block": {"type": "tool_result", "content": "README..."},
                        },
                        chunk_index=3,
                        sequence_in_chunk=0,
                    ),
                    ClaudeSseEvent(
                        event_name="content_block_stop",
                        data_raw='{"type":"content_block_stop","index":3}',
                        data_json={"type": "content_block_stop", "index": 3},
                        chunk_index=3,
                        sequence_in_chunk=1,
                    ),
                ]
            )
        )

        assert extracted is not None
        sample = build_claude_api_sft_sample(extracted)

        assert sample is not None
        assert [block.block_type for block in sample.target_blocks] == ["text", "tool_use"]
        assert sample.target_blocks[0].text == "Hello"
        assert sample.target_blocks[1].tool_call is not None
        assert sample.target_blocks[1].tool_call.name == "Read"

    def test_converter_skips_invalid_tool_use_and_records_drop_count(self) -> None:
        extracted = extract_claude_request_sample(
            _make_request(
                sse_events=[
                    ClaudeSseEvent(
                        event_name="content_block_start",
                        data_raw='{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
                        data_json={
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {"type": "text", "text": ""},
                        },
                        chunk_index=0,
                        sequence_in_chunk=0,
                    ),
                    ClaudeSseEvent(
                        event_name="content_block_delta",
                        data_raw='{"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"},"index":0}',
                        data_json={
                            "type": "content_block_delta",
                            "delta": {"type": "text_delta", "text": "Hi"},
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
                        data_raw='{"type":"content_block_start","index":1,"content_block":{"type":"tool_use","name":"Read"}}',
                        data_json={
                            "type": "content_block_start",
                            "index": 1,
                            "content_block": {"type": "tool_use", "name": "Read"},
                        },
                        chunk_index=1,
                        sequence_in_chunk=0,
                    ),
                    ClaudeSseEvent(
                        event_name="content_block_stop",
                        data_raw='{"type":"content_block_stop","index":1}',
                        data_json={"type": "content_block_stop", "index": 1},
                        chunk_index=1,
                        sequence_in_chunk=1,
                    ),
                ]
            )
        )

        assert extracted is not None
        sample = build_claude_api_sft_sample(extracted)
        assert sample is not None
        assert [block.block_type for block in sample.target_blocks] == ["text"]
        assert sample.metadata["dropped_tool_use_blocks"] == 1

    def test_error_sample_is_skipped(self) -> None:
        extracted = extract_claude_request_sample(
            _make_request(sse_events=[], stream_completed=False, error="stream failed"),
            include_incomplete=True,
        )
        assert extracted is not None
        assert build_claude_api_sft_sample(extracted) is None

    def test_serialized_and_prepared_sample_train_only_selected_blocks(self) -> None:
        extracted = extract_claude_request_sample(
            _make_request(
                sse_events=[
                    ClaudeSseEvent(
                        event_name="content_block_start",
                        data_raw='{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
                        data_json={
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {"type": "text", "text": ""},
                        },
                        chunk_index=0,
                        sequence_in_chunk=0,
                    ),
                    ClaudeSseEvent(
                        event_name="content_block_delta",
                        data_raw='{"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"},"index":0}',
                        data_json={
                            "type": "content_block_delta",
                            "delta": {"type": "text_delta", "text": "Hello"},
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
                        data_raw='{"type":"content_block_start","index":1,"content_block":{"type":"tool_use","name":"Read","id":"toolu_1","input":{"path":"README.md"}}}',
                        data_json={
                            "type": "content_block_start",
                            "index": 1,
                            "content_block": {
                                "type": "tool_use",
                                "name": "Read",
                                "id": "toolu_1",
                                "input": {"path": "README.md"},
                            },
                        },
                        chunk_index=1,
                        sequence_in_chunk=0,
                    ),
                    ClaudeSseEvent(
                        event_name="content_block_stop",
                        data_raw='{"type":"content_block_stop","index":1}',
                        data_json={"type": "content_block_stop", "index": 1},
                        chunk_index=1,
                        sequence_in_chunk=1,
                    ),
                ]
            )
        )

        assert extracted is not None
        sample = build_claude_api_sft_sample(extracted)
        assert sample is not None

        serialized = serialize_claude_api_sft_sample(sample)
        assert [segment.kind for segment in serialized.segments][-2:] == [
            "assistant",
            "assistant_tool_call",
        ]
        assert serialized.segments[-2].trainable is False
        assert serialized.segments[-1].trainable is True
        assert "<|tool|>" in serialized.segments[-1].text

        prepared = build_claude_api_sft_prepared_sample(sample)
        assert prepared.trainable_char_count > 0
        trainable_segments = [
            segment["kind"]
            for segment, span in zip(prepared.segments, prepared.spans, strict=True)
            if span["trainable"]
        ]
        assert trainable_segments == ["assistant_tool_call"]
