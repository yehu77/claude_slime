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

    for canonical_tool in ALL_BUILTIN_TOOLS:
        view = ToolView(
            canonical_name=canonical_tool.canonical_name,
            exposed_name=canonical_tool.canonical_name,
            description=canonical_tool.description or f"Tool: {canonical_tool.canonical_name}",
            input_schema=deepcopy(canonical_tool.canonical_schema),
            version=canonical_tool.version,
        )
        tools.append(view)
        # Empty adapter = identity mapping (exposed args pass through unchanged)
        adapters[view.exposed_name] = ToolAdapter()

    return ToolProfile(
        profile_id=profile_id,
        tools=tools,
        adapters=adapters,
    )
