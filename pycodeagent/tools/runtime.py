"""Tool runtime — executes ToolCalls through the profile → registry → handler chain.

The runtime never touches exposed schemas directly; it delegates lookup and
argument mapping to ToolProfile, then dispatches to the canonical handler.
"""

from __future__ import annotations

import inspect

from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.registry import ToolRegistry, ToolRegistryError
from pycodeagent.tools.spec import (
    CanonicalTool,
    ToolArgumentError,
    ToolProfile,
)
from pycodeagent.trajectory.schema import ToolCall, ToolResult


def _handler_accepts_ctx(handler) -> bool:
    """Check if handler signature accepts a 'ctx' keyword argument."""
    try:
        sig = inspect.signature(handler)
        return "ctx" in sig.parameters
    except (ValueError, TypeError):
        # If we can't inspect, assume it doesn't accept ctx
        return False


class ToolRuntime:
    """Execute tool calls through the canonical-tool abstraction layer."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def execute(
        self,
        call: ToolCall,
        profile: ToolProfile,
        ctx: ToolContext | None = None,
    ) -> ToolResult:
        """Resolve *call* against *profile*, map arguments, and run the handler.

        Returns a structured ``ToolResult`` in every case — exceptions from the
        lookup / mapping / handler stages are caught and turned into error
        results so the caller never has to deal with raw exceptions.
        """
        # --- 1. Resolve exposed name → ToolView ---
        resolved = profile.get_tool(call.name)
        if resolved is None:
            return ToolResult(
                ok=False,
                content=f"Tool not found in profile: {call.name!r}",
                is_error=True,
            )
        view, adapter = resolved

        # Back-fill canonical_name on the call for trajectory logging.
        call.canonical_name = view.canonical_name

        # --- 2. Look up the canonical backend ---
        try:
            canonical_tool = self._registry.get(view.canonical_name)
        except ToolRegistryError as exc:
            return ToolResult(ok=False, content=str(exc), is_error=True)

        # --- 3. Map exposed args → canonical args ---
        try:
            canonical_args = adapter.map_arguments(
                call.arguments,
                exposed_schema=view.input_schema,
                canonical_schema=canonical_tool.canonical_schema,
            )
        except ToolArgumentError as exc:
            return ToolResult(
                ok=False,
                content=f"Argument mapping failed: {exc}",
                is_error=True,
                metadata={"error_type": "argument_mapping"},
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                content=f"Unexpected argument mapping error: {exc}",
                is_error=True,
                metadata={"error_type": "argument_mapping_unexpected"},
            )

        # --- 4. Execute the canonical handler ---
        try:
            handler_kwargs = dict(canonical_args)
            if ctx is not None and _handler_accepts_ctx(canonical_tool.handler):
                handler_kwargs["ctx"] = ctx
            result = canonical_tool.handler(**handler_kwargs)
        except Exception as exc:
            exception_type = type(exc).__name__
            summary = f"Handler raised {exception_type}"
            if str(exc):
                summary += f": {exc}"
            return ToolResult(
                ok=False,
                content=summary,
                is_error=True,
                metadata={
                    "error_type": "handler_exception",
                    "exception_type": exception_type,
                },
            )

        # --- 5. Normalise return value ---
        if isinstance(result, ToolResult):
            return result

        # Allow handlers to return plain strings for convenience.
        if isinstance(result, str):
            return ToolResult(ok=True, content=result)

        return ToolResult(ok=True, content=str(result))
