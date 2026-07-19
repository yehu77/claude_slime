"""Bridges native tool-schema snapshots into existing catalog/profile types."""

from __future__ import annotations

from pycodeagent.tools.spec import ToolAdapter, ToolProfile, ToolView
from pycodeagent.traces.tool_catalog import AgentToolCatalog


_NATIVE_IDENTITY_STATUS = "native_identity_not_canonicalized"


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
