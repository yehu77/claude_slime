"""Tests for batch transformed native SFT dataset export."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pycodeagent.rl import (
    build_native_transformed_sft_dataset,
    read_claude_api_sft_jsonl,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.traces import ClaudeGatewayEvent


_TEST_NAMESPACE = "native_transformed_sft_dataset"
_REAL_TOOL_USE_SESSION_PATH = Path("tests/fixtures/claude_api_tool_use_session.jsonl")


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


def _request_event(
    *,
    session_id: str,
    request_id: str,
    tools: list[dict] | None,
) -> ClaudeGatewayEvent:
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
                "messages": [{"role": "user", "content": [{"type": "text", "text": "Inspect the file."}]}],
                "system": [{"type": "text", "text": "system"}],
                "tools": tools if tools is not None else [],
                "stream": True,
            }
        },
    )


def _tool_use_chunk_event(
    *,
    session_id: str,
    request_id: str,
    tool_name: str = "Read",
) -> ClaudeGatewayEvent:
    chunk = (
        "event: content_block_start\n"
        f'data: {{"type":"content_block_start","index":0,"content_block":{{"type":"tool_use","name":"{tool_name}","id":"toolu_1","input":{{"file_path":"README.md"}}}}}}\n\n'
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


def _text_chunk_event(
    *,
    session_id: str,
    request_id: str,
) -> ClaudeGatewayEvent:
    chunk = (
        "event: content_block_start\n"
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"},"index":0}\n\n'
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


def _stream_end_event(*, session_id: str, request_id: str) -> ClaudeGatewayEvent:
    return ClaudeGatewayEvent(
        schema_version=1,
        event_type="messages_stream_end",
        request_id=request_id,
        session_id=session_id,
        route="/v1/messages",
        timestamp="2026-05-20T00:00:02+00:00",
        data={"status_code": 200, "chunk_count": 1, "error": None},
    )


class TestNativeTransformedSFTDataset:
    def test_batch_export_counts_and_target_consistency(self) -> None:
        tmp = _get_test_dir()
        try:
            source = tmp / "source"
            output = tmp / "output"
            read_tool = [
                {
                    "name": "Read",
                    "description": "Read a file.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"file_path": {"type": "string"}},
                        "required": ["file_path"],
                    },
                }
            ]
            _write_session(
                source / "tool_use.jsonl",
                [
                    _request_event(session_id="session_good", request_id="req_good", tools=read_tool),
                    _tool_use_chunk_event(session_id="session_good", request_id="req_good"),
                    _stream_end_event(session_id="session_good", request_id="req_good"),
                ],
            )
            _write_session(
                source / "no_tools.jsonl",
                [
                    _request_event(session_id="session_no_tools", request_id="req_no_tools", tools=[]),
                    _tool_use_chunk_event(session_id="session_no_tools", request_id="req_no_tools"),
                    _stream_end_event(session_id="session_no_tools", request_id="req_no_tools"),
                ],
            )
            _write_session(
                source / "text_only.jsonl",
                [
                    _request_event(session_id="session_text", request_id="req_text", tools=read_tool),
                    _text_chunk_event(session_id="session_text", request_id="req_text"),
                    _stream_end_event(session_id="session_text", request_id="req_text"),
                ],
            )
            (source / "broken.jsonl").write_text("{not-json}\n", encoding="utf-8")

            result = build_native_transformed_sft_dataset(
                source,
                output,
                continue_on_error=True,
            )

            assert result.session_count == 3
            assert result.request_count == 3
            assert result.tool_use_request_count == 1
            assert result.skipped_request_count == 2
            assert result.sample_count == 4
            assert result.mode_counts == {
                "base": 1,
                "name_only": 1,
                "description_only": 1,
                "name_description": 1,
            }
            assert result.mapped_tool_use_count == 4
            assert result.unmapped_tool_use_count == 0
            assert result.dropped_tool_use_count == 0
            assert len(result.failed_files) == 1
            assert result.failed_files[0].path == "broken.jsonl"
            assert result.failed_files[0].stage == "load"

            samples = read_claude_api_sft_jsonl(output / "train.jsonl")
            assert len(samples) == 4
            by_mode = {sample.metadata["transformation_mode"]: sample for sample in samples}
            assert set(by_mode) == {"base", "name_only", "description_only", "name_description"}
            for sample in samples:
                assert sample.metadata["source_trace_path"] == "tool_use.jsonl"
                assert sample.metadata["source_session_id"] == "session_good"
                assert sample.metadata["source_request_id"] == "req_good"
                visible_tool_names = {spec["name"] for spec in sample.tool_specs}
                assert visible_tool_names
                for block in sample.target_blocks:
                    if block.block_type != "tool_use" or block.tool_call is None:
                        continue
                    assert block.tool_call.name in visible_tool_names
                    assert block.tool_call.arguments == {"file_path": "README.md"}

            assert by_mode["base"].target_blocks[0].tool_call.name == "Read"
            assert by_mode["description_only"].target_blocks[0].tool_call.name == "Read"
            assert by_mode["name_only"].target_blocks[0].tool_call.name != "Read"
            assert by_mode["name_description"].target_blocks[0].tool_call.name != "Read"

            manifest = json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))
            assert manifest["primary_sample_input"] == "train.jsonl"
            assert manifest["present_splits"] == ["train"]
            metrics = json.loads((output / "split_metrics.json").read_text(encoding="utf-8"))
            assert metrics["split_counts"] == {"train": 4}
            assert metrics["mode_counts"] == result.mode_counts
            assert metrics["remap_status_counts"] == {"mapped": 4}
        finally:
            _cleanup(tmp)

    def test_real_tool_use_fixture_smoke_export(self) -> None:
        if not _REAL_TOOL_USE_SESSION_PATH.exists():
            pytest.skip(f"Missing real Claude tool-use fixture: {_REAL_TOOL_USE_SESSION_PATH}")
        tmp = _get_test_dir()
        try:
            source = tmp / "source"
            output = tmp / "output"
            source.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_REAL_TOOL_USE_SESSION_PATH, source / _REAL_TOOL_USE_SESSION_PATH.name)

            result = build_native_transformed_sft_dataset(source, output)

            assert result.sample_count >= 4
            assert (output / "train.jsonl").exists()
            assert (output / "dataset_manifest.json").exists()
            assert (output / "split_metrics.json").exists()
            assert all(result.mode_counts[mode] >= 1 for mode in result.mode_counts)

            samples = read_claude_api_sft_jsonl(output / "train.jsonl")
            assert samples
            for sample in samples:
                visible_tool_names = {spec["name"] for spec in sample.tool_specs}
                assert visible_tool_names
                for block in sample.target_blocks:
                    if block.block_type == "tool_use" and block.tool_call is not None:
                        assert block.tool_call.name in visible_tool_names
        finally:
            _cleanup(tmp)
