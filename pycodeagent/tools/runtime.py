"""Tool runtime for canonical-tool dispatch.

Executes ToolCalls through the profile -> registry -> handler chain.

The runtime never touches exposed schemas directly; it delegates lookup and
argument mapping to ToolProfile, then dispatches to the canonical handler.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.contracts import ToolContractKind
from pycodeagent.tools.registry import ToolRegistry, ToolRegistryError
from pycodeagent.tools.spec import (
    CanonicalTool,
    ToolAdapter,
    ToolArgumentError,
    ToolProfile,
    ToolView,
    validate_json_schema,
)
from pycodeagent.trajectory.schema import ToolCall, ToolResult


def _handler_accepts_ctx(handler) -> bool:
    """Check if handler signature accepts a 'ctx' keyword argument."""
    try:
        sig = inspect.signature(handler)
        return "ctx" in sig.parameters
    except (ValueError, TypeError):
        return False


def _runtime_error_result(
    *,
    error_type: str,
    stage: str,
    content: str,
    extra_metadata: dict[str, Any] | None = None,
) -> ToolResult:
    """Build a stable runtime-generated error result."""
    metadata: dict[str, Any] = {
        "error_type": error_type,
        "stage": stage,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return ToolResult(
        ok=False,
        content=content,
        is_error=True,
        metadata=metadata,
    )


@dataclass
class ToolExecutionInspection:
    """Structured pre-execution inspection of one tool call."""

    call: ToolCall
    view: ToolView | None
    adapter: ToolAdapter | None
    canonical_tool: CanonicalTool | None
    canonical_args: dict[str, Any] | None
    canonical_input_text: str | None
    schema_valid: bool
    mapping_valid: bool
    error_type: str | None
    error_message: str | None
    error_result: ToolResult | None

    @classmethod
    def from_error(
        cls,
        *,
        call: ToolCall,
        error_result: ToolResult,
    ) -> "ToolExecutionInspection":
        return cls(
            call=call,
            view=None,
            adapter=None,
            canonical_tool=None,
            canonical_args=None,
            canonical_input_text=None,
            schema_valid=False,
            mapping_valid=False,
            error_type=str(error_result.metadata.get("error_type") or ""),
            error_message=error_result.content,
            error_result=error_result,
        )


class ToolRuntime:
    """Execute tool calls through the canonical-tool abstraction layer."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def inspect_call(
        self,
        call: ToolCall,
        profile: ToolProfile,
    ) -> ToolExecutionInspection:
        """Resolve and validate a tool call without invoking the handler."""
        resolved = self._resolve_exposed_call(call, profile)
        if isinstance(resolved, ToolResult):
            return ToolExecutionInspection.from_error(
                call=call,
                error_result=resolved,
            )
        view, adapter = resolved
        call.canonical_name = view.canonical_name

        schema_error = self._validate_exposed_payload(call, view)
        if schema_error is not None:
            return ToolExecutionInspection(
                call=call,
                view=view,
                adapter=adapter,
                canonical_tool=None,
                canonical_args=None,
                canonical_input_text=None,
                schema_valid=False,
                mapping_valid=False,
                error_type=str(schema_error.metadata.get("error_type") or ""),
                error_message=schema_error.content,
                error_result=schema_error,
            )

        canonical = self._resolve_canonical_tool(view)
        if isinstance(canonical, ToolResult):
            return ToolExecutionInspection(
                call=call,
                view=view,
                adapter=adapter,
                canonical_tool=None,
                canonical_args=None,
                canonical_input_text=None,
                schema_valid=True,
                mapping_valid=False,
                error_type=str(canonical.metadata.get("error_type") or ""),
                error_message=canonical.content,
                error_result=canonical,
            )
        canonical_tool = canonical

        mapped = self._map_payload(call, view, adapter, canonical_tool)
        if isinstance(mapped, ToolResult):
            return ToolExecutionInspection(
                call=call,
                view=view,
                adapter=adapter,
                canonical_tool=canonical_tool,
                canonical_args=None,
                canonical_input_text=None,
                schema_valid=True,
                mapping_valid=False,
                error_type=str(mapped.metadata.get("error_type") or ""),
                error_message=mapped.content,
                error_result=mapped,
            )

        return ToolExecutionInspection(
            call=call,
            view=view,
            adapter=adapter,
            canonical_tool=canonical_tool,
            canonical_args=(
                mapped if isinstance(mapped, dict) else None
            ),
            canonical_input_text=(
                mapped if isinstance(mapped, str) else None
            ),
            schema_valid=True,
            mapping_valid=True,
            error_type=None,
            error_message=None,
            error_result=None,
        )

    def execute(
        self,
        call: ToolCall,
        profile: ToolProfile,
        ctx: ToolContext | None = None,
    ) -> ToolResult:
        """Resolve *call* against *profile*, map arguments, and run the handler.

        Returns a structured ``ToolResult`` in every case. Exceptions from the
        lookup, mapping, and handler stages are caught and turned into error
        results so the caller never has to deal with raw exceptions.
        """
        inspection = self.inspect_call(call, profile)
        if not inspection.mapping_valid:
            return inspection.error_result or _runtime_error_result(
                error_type="inspection_failed",
                stage="map_arguments",
                content="Tool execution inspection failed",
            )
        return self._invoke_handler(
            inspection.canonical_tool,
            inspection.canonical_args or {},
            inspection.canonical_input_text,
            ctx,
        )

    def _resolve_exposed_call(
        self,
        call: ToolCall,
        profile: ToolProfile,
    ) -> tuple[ToolView, ToolAdapter] | ToolResult:
        resolved = profile.get_tool(call.name)
        if resolved is None:
            return _runtime_error_result(
                error_type="unknown_tool",
                stage="resolve_exposed_call",
                content=f"Tool not found in profile: {call.name!r}",
            )
        return resolved

    def _validate_exposed_payload(
        self,
        call: ToolCall,
        view: ToolView,
    ) -> ToolResult | None:
        if view.contract_kind == ToolContractKind.FREEFORM:
            if call.input_text is None:
                return _runtime_error_result(
                    error_type="schema_validation",
                    stage="validate_exposed_payload",
                    content=(
                        "Exposed freeform tool payload is missing input_text"
                    ),
                )
            if call.arguments:
                return _runtime_error_result(
                    error_type="schema_validation",
                    stage="validate_exposed_payload",
                    content=(
                        "Exposed freeform tool payload must not contain object arguments"
                    ),
                )
            return None

        if call.input_text is not None:
            return _runtime_error_result(
                error_type="schema_validation",
                stage="validate_exposed_payload",
                content="Function tool payload must not include input_text",
            )

        try:
            validate_json_schema(
                call.arguments,
                view.input_schema,
                schema_name="exposed",
            )
        except ToolArgumentError as exc:
            return _runtime_error_result(
                error_type="schema_validation",
                stage="validate_exposed_payload",
                content=f"Exposed schema validation failed: {exc}",
            )
        return None

    def _resolve_canonical_tool(
        self,
        view: ToolView,
    ) -> CanonicalTool | ToolResult:
        try:
            return self._registry.get(view.canonical_name)
        except ToolRegistryError as exc:
            return _runtime_error_result(
                error_type="canonical_tool_lookup",
                stage="resolve_canonical_tool",
                content=str(exc),
            )

    def _map_payload(
        self,
        call: ToolCall,
        view: ToolView,
        adapter: ToolAdapter,
        canonical_tool: CanonicalTool,
    ) -> dict[str, Any] | str | ToolResult:
        if view.contract_kind != canonical_tool.contract_kind:
            return _runtime_error_result(
                error_type="contract_kind_mismatch",
                stage="map_arguments",
                content=(
                    "Exposed and canonical tool contract kinds do not match: "
                    f"{view.contract_kind.value} vs {canonical_tool.contract_kind.value}"
                ),
            )

        if view.contract_kind == ToolContractKind.FREEFORM:
            if call.input_text is None:
                return _runtime_error_result(
                    error_type="argument_mapping",
                    stage="map_arguments",
                    content="Freeform tool call is missing input_text",
                )
            return call.input_text

        try:
            return adapter.map_arguments(
                call.arguments,
                exposed_schema=view.input_schema,
                canonical_schema=canonical_tool.canonical_schema,
            )
        except ToolArgumentError as exc:
            return _runtime_error_result(
                error_type="argument_mapping",
                stage="map_arguments",
                content=f"Argument mapping failed: {exc}",
            )
        except Exception as exc:
            return _runtime_error_result(
                error_type="argument_mapping_unexpected",
                stage="map_arguments",
                content=f"Unexpected argument mapping error: {exc}",
            )

    def _invoke_handler(
        self,
        canonical_tool: CanonicalTool | None,
        canonical_args: dict[str, Any],
        canonical_input_text: str | None = None,
        ctx: ToolContext | None = None,
    ) -> ToolResult:
        if canonical_tool is None:
            return _runtime_error_result(
                error_type="missing_canonical_tool",
                stage="invoke_handler",
                content="Canonical tool is required for handler invocation",
            )
        try:
            handler_kwargs = dict(canonical_args)
            if canonical_tool.contract_kind == ToolContractKind.FREEFORM:
                if canonical_input_text is None:
                    return _runtime_error_result(
                        error_type="missing_freeform_input",
                        stage="invoke_handler",
                        content="Freeform tool handler invocation requires input_text",
                    )
                handler_kwargs = {"input_text": canonical_input_text}
            if ctx is not None and _handler_accepts_ctx(canonical_tool.handler):
                handler_kwargs["ctx"] = ctx
            result = canonical_tool.handler(**handler_kwargs)
        except Exception as exc:
            exception_type = type(exc).__name__
            summary = f"Handler raised {exception_type}"
            if str(exc):
                summary += f": {exc}"
            return _runtime_error_result(
                error_type="handler_exception",
                stage="invoke_handler",
                content=summary,
                extra_metadata={"exception_type": exception_type},
            )

        if isinstance(result, ToolResult):
            return result
        if isinstance(result, str):
            return ToolResult(ok=True, content=result)
        return ToolResult(ok=True, content=str(result))
