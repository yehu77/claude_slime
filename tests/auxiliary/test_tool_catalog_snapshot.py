"""Tests for request-scoped native tool schema snapshots."""

from __future__ import annotations

from pathlib import Path

import pytest

from pycodeagent.mutations import load_tool_profile_from_dict
from pycodeagent.auxiliary.claude_api.tool_catalog_snapshot import (
    build_catalog_from_claude_request_tools,
)
from pycodeagent.auxiliary.claude_api.trace import ClaudeApiRequest, ClaudeGatewayEvent
from pycodeagent.auxiliary.claude_api.trace_loader import read_claude_api_session
from pycodeagent.traces import (
    catalog_to_base_tool_profile,
)


_REAL_SESSION_PATH = Path(
    "runs/claude_gateway_traces/84f8f6fa-4cb3-480d-8e8a-a80fc035bdcc.jsonl"
)


def _real_session_path() -> Path:
    if not _REAL_SESSION_PATH.exists():
        pytest.skip(f"Missing real Claude session fixture: {_REAL_SESSION_PATH}")
    return _REAL_SESSION_PATH


def _make_request(*, tools: list[dict] | None) -> ClaudeApiRequest:
    return ClaudeApiRequest(
        request_event=ClaudeGatewayEvent(
            schema_version=1,
            event_type="messages_request",
            request_id="req_1",
            session_id="session_1",
            agent_id="agent_inst_1",
            parent_agent_id="parent_1",
            route="/v1/messages",
            timestamp="2026-05-20T00:00:00+00:00",
            data={
                "body": {
                    "model": "mimo-v2.5-pro",
                    "messages": [],
                    "system": [],
                    "tools": tools,
                }
            },
        )
    )


def _profile_to_loader_dict(profile) -> dict:
    return {
        "profile_id": profile.profile_id,
        "tools": [
            {
                "canonical": tool.canonical_name,
                "exposed_name": tool.exposed_name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "version": tool.version,
                "adapter": {
                    "exposed_to_canonical": profile.adapters[tool.exposed_name].exposed_to_canonical,
                    "defaults": profile.adapters[tool.exposed_name].defaults,
                },
            }
            for tool in profile.tools
        ],
    }


class TestToolCatalogSnapshot:
    def test_real_claude_request_tools_build_catalog(self) -> None:
        session = read_claude_api_session(_real_session_path())
        request = session.message_requests[0]

        catalog = build_catalog_from_claude_request_tools(
            request,
            source_trace_path=_real_session_path(),
        )

        assert catalog is not None
        assert catalog.agent_name == "claude_code"
        assert catalog.agent_version == "api_trace_v1"
        assert catalog.capture_mode == "api_trace_observed"
        assert catalog.source_kind == "claude_api_trace"
        assert catalog.metadata["schema_source"] == "model_visible_api_request"
        assert catalog.metadata["model_visible_confirmed"] is True
        assert catalog.metadata["snapshot_scope"] == "request"
        assert catalog.metadata["tool_order_preserved"] is True
        assert catalog.metadata["source_trace_path"] == str(_real_session_path())
        assert catalog.metadata["source_session_id"] == request.request_event.session_id
        assert catalog.metadata["source_request_id"] == request.request_id
        assert catalog.catalog_id == (
            f"claude_api::{request.request_event.session_id}::{request.request_id}::native_catalog"
        )
        assert len(catalog.tools) == len(request.request_body["tools"])
        assert catalog.tools[0].raw_tool_name == request.request_body["tools"][0]["name"]
        assert catalog.tools[1].raw_tool_name == request.request_body["tools"][1]["name"]
        assert catalog.tools[0].metadata["canonical_mapping_status"] == (
            "native_identity_not_canonicalized"
        )

    def test_returns_none_when_request_has_no_tools(self) -> None:
        request = _make_request(tools=[])
        assert build_catalog_from_claude_request_tools(request) is None

        request = _make_request(tools=None)
        assert build_catalog_from_claude_request_tools(request) is None

    def test_catalog_projects_to_base_native_tool_profile(self) -> None:
        request = _make_request(
            tools=[
                {
                    "name": "Read",
                    "description": "Read a file.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"file_path": {"type": "string"}},
                        "required": ["file_path"],
                    },
                },
                {
                    "name": "Bash",
                    "description": "Run shell commands.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"command": {"type": "string"}},
                        "required": ["command"],
                    },
                },
            ]
        )
        catalog = build_catalog_from_claude_request_tools(
            request,
            source_trace_path="runs/claude_gateway_traces/session_1.jsonl",
        )
        assert catalog is not None

        profile = catalog_to_base_tool_profile(catalog)

        assert profile.profile_id == f"native::{catalog.catalog_id}"
        assert [tool.exposed_name for tool in profile.tools] == ["Read", "Bash"]
        assert [tool.canonical_name for tool in profile.tools] == ["Read", "Bash"]
        assert profile.tools[0].description == "Read a file."
        assert profile.tools[0].input_schema["required"] == ["file_path"]
        assert profile.tools[0].metadata["native_name"] == "Read"
        assert profile.tools[0].metadata["canonical_mapping_status"] == (
            "native_identity_not_canonicalized"
        )
        assert profile.adapters["Read"].exposed_to_canonical == {}
        assert profile.adapters["Read"].defaults == {}
        assert profile.metadata["source_catalog_id"] == catalog.catalog_id
        assert profile.metadata["native_schema_snapshot"] is True
        assert profile.metadata["canonical_mapping_status"] == (
            "native_identity_not_canonicalized"
        )

    def test_base_profile_can_roundtrip_through_profile_loader_smoke(self) -> None:
        request = _make_request(
            tools=[
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
        )
        catalog = build_catalog_from_claude_request_tools(request)
        assert catalog is not None
        profile = catalog_to_base_tool_profile(catalog)

        loaded = load_tool_profile_from_dict(_profile_to_loader_dict(profile))

        assert loaded.profile_id == profile.profile_id
        assert [tool.exposed_name for tool in loaded.tools] == ["Read"]
        assert loaded.adapters["Read"].exposed_to_canonical == {}
