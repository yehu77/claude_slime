"""Tool registry for canonical backend tools.

Only manages canonical tool implementations — never exposed schemas or profiles.
"""

from __future__ import annotations

from pycodeagent.tools.spec import CanonicalTool


class ToolRegistryError(Exception):
    """Raised on invalid registry operations."""


class ToolRegistry:
    """A simple name-keyed registry of canonical tool backends."""

    def __init__(self) -> None:
        self._tools: dict[str, CanonicalTool] = {}

    def register(self, tool: CanonicalTool) -> None:
        if tool.canonical_name in self._tools:
            raise ToolRegistryError(
                f"Duplicate canonical tool: {tool.canonical_name!r}"
            )
        self._tools[tool.canonical_name] = tool

    def get(self, canonical_name: str) -> CanonicalTool:
        try:
            return self._tools[canonical_name]
        except KeyError:
            raise ToolRegistryError(
                f"Unknown canonical tool: {canonical_name!r}"
            )

    def list(self) -> list[CanonicalTool]:
        return list(self._tools.values())

    def has(self, canonical_name: str) -> bool:
        return canonical_name in self._tools
