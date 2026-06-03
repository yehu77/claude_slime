"""Tool system: registry, runtime, specs, and built-in tools."""

from pycodeagent.tools.bootstrap import (
    build_base_tool_runtime,
    build_builtin_registry,
)
from pycodeagent.tools.profile_factory import build_base_tool_profile
from pycodeagent.tools.registry import ToolRegistry
from pycodeagent.tools.runtime import ToolRuntime
from pycodeagent.tools.spec import (
    CanonicalTool,
    ToolAdapter,
    ToolArgumentError,
    ToolProfile,
    ToolView,
)

__all__ = [
    # Core types
    "CanonicalTool",
    "ToolAdapter",
    "ToolArgumentError",
    "ToolProfile",
    "ToolView",
    # Registry and runtime
    "ToolRegistry",
    "ToolRuntime",
    # Bootstrap helpers
    "build_builtin_registry",
    "build_base_tool_profile",
    "build_base_tool_runtime",
]
