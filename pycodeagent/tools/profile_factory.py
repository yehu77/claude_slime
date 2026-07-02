"""Tool profile factories for strict native family stacks."""

from __future__ import annotations

from copy import deepcopy
from typing import Iterable

from pycodeagent.tools.families import (
    build_claude_canonical_tools,
    build_codex_canonical_tools,
)
from pycodeagent.tools.spec import ToolAdapter, ToolProfile, ToolView

_NATIVE_IDENTITY_STATUS = "native_identity_not_canonicalized"


def build_native_claude_profile(
    profile_id: str = "native_claude",
) -> ToolProfile:
    """Build the strict native Claude family profile."""
    return _build_native_family_profile(
        canonical_tools=build_claude_canonical_tools(),
        profile_id=profile_id,
        family="claude",
        native_profile_kind="native_claude",
    )


def build_native_codex_profile(
    profile_id: str = "native_codex",
) -> ToolProfile:
    """Build the strict native Codex family profile."""
    return _build_native_family_profile(
        canonical_tools=build_codex_canonical_tools(),
        profile_id=profile_id,
        family="codex",
        native_profile_kind="native_codex",
    )


def _build_native_family_profile(
    *,
    canonical_tools: Iterable,
    profile_id: str,
    family: str,
    native_profile_kind: str,
) -> ToolProfile:
    tools: list[ToolView] = []
    adapters: dict[str, ToolAdapter] = {}

    for index, canonical_tool in enumerate(canonical_tools):
        native_name = str(
            canonical_tool.metadata.get(
                "native_tool_name",
                canonical_tool.canonical_name,
            )
        )
        metadata = dict(canonical_tool.metadata)
        metadata.update(
            {
                "family": family,
                "native_name": native_name,
                "native_profile_kind": native_profile_kind,
                "mutation_source_family": family,
                "canonical_mapping_status": _NATIVE_IDENTITY_STATUS,
                "transformation_mode": "base",
                "name_mutated": False,
                "description_mutated": False,
                "schema_mutated": False,
                "tool_order_index_base": index,
                "tool_order_index_exposed": index,
                "tool_reordered": False,
                "name_variant_id": f"{native_name}_name_native_base",
                "description_variant_id": f"{native_name}_description_native_base",
                "schema_variant_id": f"{native_name}_schema_native_base",
                "schema_variant_category": None,
            }
        )
        view = ToolView(
            canonical_name=canonical_tool.canonical_name,
            exposed_name=canonical_tool.canonical_name,
            description=canonical_tool.description
            or f"Tool: {canonical_tool.canonical_name}",
            input_schema=deepcopy(canonical_tool.canonical_schema),
            contract_kind=canonical_tool.contract_kind,
            input_format=deepcopy(canonical_tool.input_format),
            version=canonical_tool.version,
            metadata=metadata,
        )
        tools.append(view)
        adapters[view.exposed_name] = ToolAdapter()

    return ToolProfile(
        profile_id=profile_id,
        tools=tools,
        adapters=adapters,
        metadata={
            "family": family,
            "native_profile_kind": native_profile_kind,
            "mutation_source_family": family,
            "profile_origin": "strict_family_canonical_tools",
            "transformation_mode": "base",
            "native_schema_snapshot": True,
            "canonical_mapping_status": _NATIVE_IDENTITY_STATUS,
            "tool_order_preserved": True,
            "mode": "native_family_base",
            "seed": 0,
            "mutation_manifest_version": 1,
            "mutation_axes": [],
            "compat_mode": None,
            "reorder_anchor_policy": "preserve_source_order",
            "tool_order_seed": None,
            "schema_variant_categories": {
                tool.canonical_name: tool.metadata["schema_variant_category"]
                for tool in tools
            },
            "selected_variant_ids": {
                tool.canonical_name: {
                    "name_variant_id": tool.metadata["name_variant_id"],
                    "description_variant_id": tool.metadata[
                        "description_variant_id"
                    ],
                    "schema_variant_id": tool.metadata["schema_variant_id"],
                }
                for tool in tools
            },
        },
    )
