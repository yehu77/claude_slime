"""Tests for batch Claude API SFT dataset export."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pycodeagent.rl import (
    build_claude_api_sft_dataset,
    read_claude_api_sft_jsonl,
    validate_claude_api_sft_jsonl,
    write_claude_api_sft_jsonl,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.traces import ClaudeGatewayEvent


_TEST_NAMESPACE = "claude_api_sft_dataset"
_REAL_SESSION_PATH = Path(
    "runs/claude_gateway_traces/84f8f6fa-4cb3-480d-8e8a-a80fc035bdcc.jsonl"
)


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _write_session(path: Path, events: list[ClaudeGatewayEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False))
            handle.write("\n")


def _request_event(*, session_id: str, request_id: str) -> ClaudeGatewayEvent:
    return ClaudeGatewayEvent(
        schema_version=1,
        event_type="messages_request",
        request_id=request_id,
        session_id=session_id,
        route="/v1/messages",
        timestamp="2026-05-20T00:00:00+00:00",
        data={
            "body": {
                "model": "mimo-v2.5-pro",
                "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                "system": [{"type": "text", "text": "system"}],
                "tools": [],
                "stream": True,
            }
        },
    )


def _text_chunk_event(*, session_id: str, request_id: str, text: str) -> ClaudeGatewayEvent:
    chunk = (
        "event: content_block_start\n"
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
        "event: content_block_delta\n"
        f'data: {{"type":"content_block_delta","delta":{{"type":"text_delta","text":"{text}"}},"index":0}}\n\n'
        "event: content_block_stop\n"
        'data: {"type":"content_block_stop","index":0}\n\n'
        "event: message_delta\n"
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":1}}\n\n'
    )
    return ClaudeGatewayEvent(
        schema_version=1,
        event_type="messages_stream_chunk",
        request_id=request_id,
        session_id=session_id,
        route="/v1/messages",
        timestamp="2026-05-20T00:00:01+00:00",
        data={"index": 0, "text": chunk},
    )


def _thinking_chunk_event(*, session_id: str, request_id: str) -> ClaudeGatewayEvent:
    chunk = (
        "event: content_block_start\n"
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}\n\n'
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"thought"},"index":0}\n\n'
        "event: content_block_stop\n"
        'data: {"type":"content_block_stop","index":0}\n\n'
        "event: message_delta\n"
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":1}}\n\n'
    )
    return ClaudeGatewayEvent(
        schema_version=1,
        event_type="messages_stream_chunk",
        request_id=request_id,
        session_id=session_id,
        route="/v1/messages",
        timestamp="2026-05-20T00:00:01+00:00",
        data={"index": 0, "text": chunk},
    )


def _stream_end_event(*, session_id: str, request_id: str, error: str | None = None) -> ClaudeGatewayEvent:
    return ClaudeGatewayEvent(
        schema_version=1,
        event_type="messages_stream_end",
        request_id=request_id,
        session_id=session_id,
        route="/v1/messages",
        timestamp="2026-05-20T00:00:02+00:00",
        data={"status_code": 200, "chunk_count": 1, "error": error},
    )


class TestClaudeApiSFTDataset:
    def test_batch_export_counts_and_failed_files(self) -> None:
        tmp = _get_test_dir()
        try:
            source = tmp / "source"
            output = tmp / "output"
            _write_session(
                source / "good.jsonl",
                [
                    _request_event(session_id="session_good", request_id="req_good"),
                    _text_chunk_event(session_id="session_good", request_id="req_good", text="Hello"),
                    _stream_end_event(session_id="session_good", request_id="req_good"),
                ],
            )
            _write_session(
                source / "no_target.jsonl",
                [
                    _request_event(session_id="session_no_target", request_id="req_no_target"),
                    _thinking_chunk_event(session_id="session_no_target", request_id="req_no_target"),
                    _stream_end_event(session_id="session_no_target", request_id="req_no_target"),
                ],
            )
            _write_session(
                source / "incomplete.jsonl",
                [
                    _request_event(session_id="session_incomplete", request_id="req_incomplete"),
                    _text_chunk_event(
                        session_id="session_incomplete",
                        request_id="req_incomplete",
                        text="Partial",
                    ),
                ],
            )
            (source / "broken.jsonl").write_text("{not-json}\n", encoding="utf-8")

            result = build_claude_api_sft_dataset(
                source,
                output,
                continue_on_error=True,
            )

            assert result.session_count == 3
            assert result.request_count == 3
            assert result.sample_count == 1
            assert result.extractor_skipped_request_count == 1
            assert result.converter_skipped_sample_count == 1
            assert result.error_request_count == 1
            assert result.incomplete_request_count == 1
            assert result.no_trainable_target_count == 1
            assert len(result.failed_files) == 1
            assert result.failed_files[0].path == "broken.jsonl"
            assert result.failed_files[0].stage == "load"

            samples = read_claude_api_sft_jsonl(output / "train.jsonl")
            assert len(samples) == 1
            metadata = samples[0].metadata
            assert metadata["source_trace_path"] == "good.jsonl"
            assert metadata["source_session_id"] == "session_good"
            assert metadata["source_request_id"] == "req_good"

            manifest = json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))
            assert manifest["present_splits"] == ["train"]
            assert manifest["failed_files"][0]["path"] == "broken.jsonl"
            metrics = json.loads((output / "split_metrics.json").read_text(encoding="utf-8"))
            assert metrics["split_counts"] == {"train": 1}
        finally:
            _cleanup(tmp)

    def test_batch_export_fail_fast_by_default(self) -> None:
        tmp = _get_test_dir()
        try:
            source = tmp / "source"
            output = tmp / "output"
            (source / "broken.jsonl").parent.mkdir(parents=True, exist_ok=True)
            (source / "broken.jsonl").write_text("{not-json}\n", encoding="utf-8")

            with pytest.raises(ValueError, match="Invalid Claude gateway JSON"):
                build_claude_api_sft_dataset(source, output)
        finally:
            _cleanup(tmp)

    def test_real_session_smoke_export(self) -> None:
        if not _REAL_SESSION_PATH.exists():
            pytest.skip(f"Missing real Claude session fixture: {_REAL_SESSION_PATH}")
        tmp = _get_test_dir()
        try:
            source = tmp / "source"
            output = tmp / "output"
            source.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_REAL_SESSION_PATH, source / _REAL_SESSION_PATH.name)

            result = build_claude_api_sft_dataset(source, output)

            assert result.sample_count >= 1
            assert (output / "train.jsonl").exists()
            assert (output / "dataset_manifest.json").exists()
            assert (output / "split_metrics.json").exists()
            manifest = json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))
            assert manifest["present_splits"] == ["train"]
        finally:
            _cleanup(tmp)

    def test_claude_api_sft_jsonl_roundtrip(self) -> None:
        tmp = _get_test_dir()
        try:
            source = tmp / "source"
            output = tmp / "output"
            _write_session(
                source / "good.jsonl",
                [
                    _request_event(session_id="session_good", request_id="req_good"),
                    _text_chunk_event(session_id="session_good", request_id="req_good", text="Hello"),
                    _stream_end_event(session_id="session_good", request_id="req_good"),
                ],
            )

            result = build_claude_api_sft_dataset(source, output)
            assert result.sample_count == 1
            validate_claude_api_sft_jsonl(output / "train.jsonl")
            samples = read_claude_api_sft_jsonl(output / "train.jsonl")
            roundtrip_path = output / "roundtrip.jsonl"
            write_claude_api_sft_jsonl(samples, roundtrip_path)
            validate_claude_api_sft_jsonl(roundtrip_path)
        finally:
            _cleanup(tmp)
