"""Bridges native tool-schema snapshots into existing catalog/profile types."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycodeagent.tools.contracts import (
    ToolContractKind,
    tool_spec_input_format,
    tool_spec_input_schema,
    tool_spec_kind,
)
from pycodeagent.tools.spec import ToolAdapter, ToolProfile, ToolView
from pycodeagent.traces.claude_api_trace import ClaudeApiRequest
from pycodeagent.traces.tool_catalog import AgentToolCatalog, CatalogToolEntry


_NATIVE_IDENTITY_STATUS = "native_identity_not_canonicalized"


def build_catalog_from_claude_request_tools(
    request: ClaudeApiRequest,
    *,
    source_trace_path: str | Path | None = None,
) -> AgentToolCatalog | None:
    """Build a request-scoped catalog from Claude request-body tools.

    Returns ``None`` when the request did not expose any tools.
    """
    body = request.request_body
    raw_tools = body.get("tools")
    if not isinstance(raw_tools, list) or len(raw_tools) == 0:
        return None

    tools: list[CatalogToolEntry] = []
    for index, entry in enumerate(raw_tools):
        if not isinstance(entry, dict):
            raise ValueError(f"Claude tool entry at index {index} must be a mapping")

        raw_tool_name = entry.get("name")
        if not isinstance(raw_tool_name, str) or not raw_tool_name:
            raise ValueError(f"Claude tool entry at index {index} is missing a string name")

        description = entry.get("description", "")
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise ValueError(
                f"Claude tool entry {raw_tool_name!r} has non-string description"
            )

        contract_kind = tool_spec_kind(entry)
        input_schema = tool_spec_input_schema(entry) or {}
        input_format = tool_spec_input_format(entry)
        if contract_kind == ToolContractKind.FUNCTION and not isinstance(
            input_schema, dict
        ):
            raise ValueError(
                f"Claude tool entry {raw_tool_name!r} has non-mapping input_schema"
            )
        if contract_kind == ToolContractKind.FREEFORM and input_format is not None and not isinstance(
            input_format, dict
        ):
            raise ValueError(
                f"Claude tool entry {raw_tool_name!r} has non-mapping input_format"
            )

        tools.append(
            CatalogToolEntry(
                raw_tool_name=raw_tool_name,
                description=description,
                input_schema=input_schema,
                contract_kind=contract_kind,
                input_format=input_format,
                metadata={
                    "native_name": raw_tool_name,
                    "original_index": index,
                    "schema_source": "model_visible_api_request",
                    "canonical_mapping_status": _NATIVE_IDENTITY_STATUS,
                },
            )
        )

    model_name = body.get("model") if isinstance(body.get("model"), str) else None
    source_path = str(source_trace_path) if source_trace_path is not None else None
    return AgentToolCatalog(
        catalog_id=(
            f"claude_api::{request.request_event.session_id}::"
            f"{request.request_id}::native_catalog"
        ),
        agent_name="claude_code",
        agent_version="api_trace_v1",
        capture_mode="api_trace_observed",
        source_kind="claude_api_trace",
        tools=tools,
        metadata={
            "schema_source": "model_visible_api_request",
            "model_visible_confirmed": True,
            "snapshot_scope": "request",
            "tool_order_preserved": True,
            "source_trace_path": source_path,
            "source_session_id": request.request_event.session_id,
            "source_request_id": request.request_id,
            "model_name": model_name,
            "agent_instance_id": request.request_event.agent_id,
            "parent_agent_id": request.request_event.parent_agent_id,
        },
    )


def catalog_to_base_tool_profile(catalog: AgentToolCatalog) -> ToolProfile:
    """Project a native snapshot catalog into a base identity ToolProfile."""
    tools: list[ToolView] = []
    adapters: dict[str, ToolAdapter] = {}

    for entry in catalog.tools:
        tool_metadata = dict(entry.metadata)
        tool_metadata["native_name"] = entry.raw_tool_name
        tool_metadata["canonical_mapping_status"] = _NATIVE_IDENTITY_STATUS
        tools.append(
            ToolView(
                canonical_name=entry.raw_tool_name,
                exposed_name=entry.raw_tool_name,
                description=entry.description,
                input_schema=entry.input_schema,
                contract_kind=entry.contract_kind,
                input_format=entry.input_format,
                version=entry.version or "native_snapshot",
                metadata=tool_metadata,
            )
        )
        adapters[entry.raw_tool_name] = ToolAdapter()

    profile_metadata = dict(catalog.metadata)
    profile_metadata.update(
        {
            "source_catalog_id": catalog.catalog_id,
            "source_agent_name": catalog.agent_name,
            "source_agent_version": catalog.agent_version,
            "capture_mode": catalog.capture_mode,
            "source_kind": catalog.source_kind,
            "native_schema_snapshot": True,
            "canonical_mapping_status": _NATIVE_IDENTITY_STATUS,
        }
    )
    return ToolProfile(
        profile_id=f"native::{catalog.catalog_id}",
        tools=tools,
        adapters=adapters,
        metadata=profile_metadata,
    )
