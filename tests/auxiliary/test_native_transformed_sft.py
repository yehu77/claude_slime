"""Tests for transformed native SFT samples built from real Claude tool-use traces."""

from __future__ import annotations

from pathlib import Path

import pytest

from pycodeagent.auxiliary.claude_api.serializer import serialize_claude_api_sft_sample
from pycodeagent.auxiliary.claude_api.sft_training import build_claude_api_sft_prepared_sample
from pycodeagent.auxiliary.claude_api.tool_catalog_snapshot import (
    build_catalog_from_claude_request_tools,
)
from pycodeagent.auxiliary.claude_api.trace import ClaudeSseEvent
from pycodeagent.auxiliary.claude_api.trace_extract import extract_claude_request_sample
from pycodeagent.auxiliary.claude_api.trace_loader import read_claude_api_session
from pycodeagent.auxiliary.native_transformed.sft import build_transformed_native_sft_sample
from pycodeagent.tools.spec import ToolAdapter, ToolProfile, ToolView
from pycodeagent.traces import (
    build_native_transformed_profile,
    catalog_to_base_tool_profile,
)
from tests.auxiliary.test_claude_api_trace_extract import _make_request


_REAL_TOOL_USE_SESSION_PATH = Path("tests/fixtures/claude_api_tool_use_session.jsonl")


def _real_tool_use_session_path() -> Path:
    if not _REAL_TOOL_USE_SESSION_PATH.exists():
        pytest.skip(f"Missing real Claude tool-use fixture: {_REAL_TOOL_USE_SESSION_PATH}")
    return _REAL_TOOL_USE_SESSION_PATH


def _find_first_tool_use_request(session_path: Path):
    session = read_claude_api_session(session_path, strict=False)
    for request in session.message_requests:
        extracted = extract_claude_request_sample(request, include_incomplete=True)
        if extracted is None:
            continue
        if any(block.block_type == "tool_use" for block in extracted.response_blocks):
            return session, request, extracted
    raise AssertionError("Expected at least one request with tool_use in real fixture")


class TestNativeTransformedSFT:
    def test_real_fixture_contains_request_tools_tool_use_and_followup_tool_result(self) -> None:
        session, request, extracted = _find_first_tool_use_request(_real_tool_use_session_path())

        assert isinstance(request.request_body.get("tools"), list)
        assert len(request.request_body["tools"]) > 0
        assert any(block.block_type == "tool_use" for block in extracted.response_blocks)

        tool_use_ids = [
            block.metadata["start_payload"]["content_block"]["id"]
            for block in extracted.response_blocks
            if block.block_type == "tool_use"
        ]
        request_ids = [item.request_id for item in session.message_requests]
        request_index = request_ids.index(request.request_id)

        matched_tool_results = []
        for later in session.message_requests[request_index + 1 :]:
            for message in later.request_body.get("messages", []):
                if not isinstance(message, dict) or message.get("role") != "user":
                    continue
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    tool_use_id = block.get("tool_use_id")
                    if tool_use_id in tool_use_ids:
                        matched_tool_results.append((later.request_id, tool_use_id))

        assert matched_tool_results, "Expected a later request carrying tool_result for the tool_use"

    def test_transformed_builder_rewrites_visible_tool_specs_and_tool_name(self) -> None:
        session, request, extracted = _find_first_tool_use_request(_real_tool_use_session_path())
        catalog = build_catalog_from_claude_request_tools(
            request,
            source_trace_path=_real_tool_use_session_path(),
        )
        assert catalog is not None
        base_profile = catalog_to_base_tool_profile(catalog)
        target_profile = build_native_transformed_profile(
            base_profile,
            mode="name_only",
            seed=7,
        )

        result = build_transformed_native_sft_sample(
            extracted,
            source_catalog=catalog,
            base_profile=base_profile,
            target_profile=target_profile,
            session=session,
        )

        assert result.sample is not None
        assert result.sample.tool_specs == target_profile.get_exposed_specs()
        assert result.sample.metadata["source_catalog_id"] == catalog.catalog_id
        assert result.sample.metadata["tool_use_remap_report"]["unmapped_tool_uses"] == 0
        assert result.audit["matched_tool_result_count"] >= 1

        target_tool_names = [
            block.tool_call.name
            for block in result.sample.target_blocks
            if block.block_type == "tool_use" and block.tool_call is not None
        ]
        assert target_tool_names
        source_tool_names = [
            block.metadata["start_payload"]["content_block"]["name"]
            for block in extracted.response_blocks
            if block.block_type == "tool_use"
        ]
        assert target_tool_names != source_tool_names
        assert all(name in {spec["name"] for spec in result.sample.tool_specs} for name in target_tool_names)

    def test_description_only_keeps_tool_use_name_but_swaps_visible_tool_specs(self) -> None:
        session, request, extracted = _find_first_tool_use_request(_real_tool_use_session_path())
        catalog = build_catalog_from_claude_request_tools(request)
        assert catalog is not None
        base_profile = catalog_to_base_tool_profile(catalog)
        target_profile = build_native_transformed_profile(
            base_profile,
            mode="description_only",
            seed=7,
        )

        result = build_transformed_native_sft_sample(
            extracted,
            source_catalog=catalog,
            base_profile=base_profile,
            target_profile=target_profile,
            session=session,
        )
        assert result.sample is not None

        tool_use_names = [
            block.tool_call.name
            for block in result.sample.target_blocks
            if block.block_type == "tool_use" and block.tool_call is not None
        ]
        source_tool_names = [
            block.metadata["start_payload"]["content_block"]["name"]
            for block in extracted.response_blocks
            if block.block_type == "tool_use"
        ]
        assert tool_use_names == source_tool_names
        assert result.sample.tool_specs == target_profile.get_exposed_specs()

    def test_unmapped_tool_use_is_dropped_and_reported(self) -> None:
        extracted = extract_claude_request_sample(
            _make_request(
                sse_events=[
                    ClaudeSseEvent(
                        event_name="content_block_start",
                        data_raw='{"type":"content_block_start","index":0,"content_block":{"type":"tool_use","name":"Read","id":"toolu_1","input":{"file_path":"README.md"}}}',
                        data_json={
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {
                                "type": "tool_use",
                                "name": "Read",
                                "id": "toolu_1",
                                "input": {"file_path": "README.md"},
                            },
                        },
                        chunk_index=0,
                        sequence_in_chunk=0,
                    ),
                    ClaudeSseEvent(
                        event_name="content_block_stop",
                        data_raw='{"type":"content_block_stop","index":0}',
                        data_json={"type": "content_block_stop", "index": 0},
                        chunk_index=0,
                        sequence_in_chunk=1,
                    ),
                ],
                body={
                    "model": "mimo-v2.5-pro",
                    "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                    "system": [{"type": "text", "text": "system"}],
                    "tools": [
                        {
                            "name": "Read",
                            "description": "Read a file.",
                            "input_schema": {
                                "type": "object",
                                "properties": {"file_path": {"type": "string"}},
                                "required": ["file_path"],
                            },
                        }
                    ],
                },
            )
        )
        assert extracted is not None
        # Use a target profile that intentionally lacks the native name mapping.
        source_catalog = build_catalog_from_claude_request_tools(
            _make_request(
                body={
                    "model": "mimo-v2.5-pro",
                    "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                    "system": [{"type": "text", "text": "system"}],
                    "tools": [
                        {
                            "name": "Read",
                            "description": "Read a file.",
                            "input_schema": {
                                "type": "object",
                                "properties": {"file_path": {"type": "string"}},
                                "required": ["file_path"],
                            },
                        }
                    ],
                }
            )
        )
        assert source_catalog is not None
        base_profile = catalog_to_base_tool_profile(source_catalog)
        target_profile = ToolProfile(
            profile_id="native::other",
            tools=[
                ToolView(
                    canonical_name="Write",
                    exposed_name="WriteTool",
                    description="Write a file.",
                    input_schema={
                        "type": "object",
                        "properties": {"file_path": {"type": "string"}},
                        "required": ["file_path"],
                    },
                    metadata={
                        "native_name": "Write",
                        "canonical_mapping_status": "native_identity_not_canonicalized",
                    },
                )
            ],
            adapters={"WriteTool": ToolAdapter()},
            metadata={"transformation_mode": "name_only"},
        )

        result = build_transformed_native_sft_sample(
            extracted,
            source_catalog=source_catalog,
            base_profile=base_profile,
            target_profile=target_profile,
            session=None,
        )

        assert result.sample is None
        assert result.remap_report.unmapped_tool_uses == 1
        assert result.remap_report.dropped_tool_uses == 1
        assert result.remap_report.entries[0].native_tool_name == "Read"
        assert result.remap_report.entries[0].transformed_tool_name is None

    def test_transformed_sample_serializes_with_target_tool_specs_and_prepared_path(self) -> None:
        session, request, extracted = _find_first_tool_use_request(_real_tool_use_session_path())
        catalog = build_catalog_from_claude_request_tools(
            request,
            source_trace_path=_real_tool_use_session_path(),
        )
        assert catalog is not None
        base_profile = catalog_to_base_tool_profile(catalog)
        target_profile = build_native_transformed_profile(
            base_profile,
            mode="name_only",
            seed=7,
        )

        result = build_transformed_native_sft_sample(
            extracted,
            source_catalog=catalog,
            base_profile=base_profile,
            target_profile=target_profile,
            session=session,
        )
        assert result.sample is not None

        serialized = serialize_claude_api_sft_sample(result.sample)
        tool_spec_segments = [segment for segment in serialized.segments if segment.metadata.get("source") == "tool_specs"]
        assert len(tool_spec_segments) == 1
        assert "<tools>" in tool_spec_segments[0].text
        tool_call_segments = [segment for segment in serialized.segments if segment.kind == "assistant_tool_call"]
        assert tool_call_segments
        transformed_names = {spec["name"] for spec in result.sample.tool_specs}
        assert all(segment.metadata["tool_name"] in transformed_names for segment in tool_call_segments)

        prepared = build_claude_api_sft_prepared_sample(result.sample)
        assert prepared.trainable_char_count > 0
