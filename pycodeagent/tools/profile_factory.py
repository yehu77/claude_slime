"""Tool profile factories.

Provides builders for ToolProfile instances. The base profile uses identity
mapping (exposed_name == canonical_name) without any schema mutation.
"""

from __future__ import annotations

from copy import deepcopy

from pycodeagent.tools.builtin import ALL_BUILTIN_TOOLS
from pycodeagent.tools.spec import ToolAdapter, ToolProfile, ToolView


def build_base_tool_profile(
    profile_id: str = "base",
) -> ToolProfile:
    """Build the base ToolProfile with identity mapping.

    The base profile exposes each builtin tool with:
    - exposed_name == canonical_name
    - description from canonical tool metadata
    - input_schema directly from canonical tool
    - empty adapter (identity argument mapping)

    Args:
        profile_id: Identifier for the profile. Defaults to "base".

    Returns:
        A ToolProfile ready for use with ToolRuntime.
    """
    tools: list[ToolView] = []
    adapters: dict[str, ToolAdapter] = {}

    for index, canonical_tool in enumerate(ALL_BUILTIN_TOOLS):
        view = ToolView(
            canonical_name=canonical_tool.canonical_name,
            exposed_name=canonical_tool.canonical_name,
            description=canonical_tool.description or f"Tool: {canonical_tool.canonical_name}",
            input_schema=deepcopy(canonical_tool.canonical_schema),
            version=canonical_tool.version,
            metadata={
                "name_variant_id": f"{canonical_tool.canonical_name}_name_base",
                "description_variant_id": f"{canonical_tool.canonical_name}_description_base",
                "schema_variant_id": f"{canonical_tool.canonical_name}_schema_base",
                "schema_variant_category": None,
                "name_mutated": False,
                "description_mutated": False,
                "schema_mutated": False,
                "tool_order_index_base": index,
                "tool_order_index_exposed": index,
                "tool_reordered": False,
            },
        )
        tools.append(view)
        # Empty adapter = identity mapping (exposed args pass through unchanged)
        adapters[view.exposed_name] = ToolAdapter()

    return ToolProfile(
        profile_id=profile_id,
        tools=tools,
        adapters=adapters,
        metadata={
            "mode": "base",
            "seed": 0,
            "mutation_manifest_version": 1,
            "mutation_axes": [],
            "compat_mode": None,
            "reorder_anchor_policy": "finish_last",
            "tool_order_seed": None,
            "schema_variant_categories": {
                tool.canonical_name: None for tool in tools
            },
            "selected_variant_ids": {
                tool.canonical_name: {
                    "name_variant_id": tool.metadata["name_variant_id"],
                    "description_variant_id": tool.metadata["description_variant_id"],
                    "schema_variant_id": tool.metadata["schema_variant_id"],
                }
                for tool in tools
            },
        },
    )
