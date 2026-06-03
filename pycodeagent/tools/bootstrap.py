"""Bootstrap layer for the tool system.

Provides convenience functions to assemble a ready-to-use tool runtime
from builtin canonical tools and a base profile.
"""

from __future__ import annotations

from pycodeagent.tools.builtin import ALL_BUILTIN_TOOLS
from pycodeagent.tools.profile_factory import build_base_tool_profile
from pycodeagent.tools.registry import ToolRegistry
from pycodeagent.tools.runtime import ToolRuntime
from pycodeagent.tools.spec import ToolProfile


def build_builtin_registry() -> ToolRegistry:
    """Create a fresh ToolRegistry with all builtin canonical tools.

    Each call returns a new independent instance — no shared mutable state.

    Returns:
        A ToolRegistry containing all Phase 1-2 builtin tools.
    """
    registry = ToolRegistry()
    for tool in ALL_BUILTIN_TOOLS:
        registry.register(tool)
    return registry


def build_base_tool_runtime(
    *,
    profile_id: str = "base",
) -> tuple[ToolRegistry, ToolProfile, ToolRuntime]:
    """Assemble a complete base tooling stack.

    Convenience entry point that builds:
    - A ToolRegistry with all builtin tools
    - A base ToolProfile (identity mapping)
    - A ToolRuntime wired to the registry

    Args:
        profile_id: Identifier for the profile. Defaults to "base".

    Returns:
        A (registry, profile, runtime) triple ready for use.
    """
    registry = build_builtin_registry()
    profile = build_base_tool_profile(profile_id=profile_id)
    runtime = ToolRuntime(registry)
    return registry, profile, runtime
