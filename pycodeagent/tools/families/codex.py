"""Strict Codex-family canonical tools."""

from __future__ import annotations

from typing import Any

from pycodeagent.tools.contracts import ToolContractKind
from pycodeagent.tools.patch_runtime import CodexApplyPatchRuntime
from pycodeagent.tools.process_exec import SharedProcessExecutor
from pycodeagent.tools.registry import ToolRegistry
from pycodeagent.tools.shell_runtimes import (
    CodexShellRuntime,
    CodexWriteStdinRuntime,
)
from pycodeagent.tools.spec import CanonicalTool
from pycodeagent.trajectory.schema import ToolResult

_FAMILY = "codex"
_APPLY_PATCH_GRAMMAR = """start: begin_patch hunk+ end_patch
begin_patch: "*** Begin Patch" LF
end_patch: "*** End Patch" LF?

hunk: add_hunk | delete_hunk | update_hunk
add_hunk: "*** Add File: " filename LF add_line+
delete_hunk: "*** Delete File: " filename LF
update_hunk: "*** Update File: " filename LF change_move? change?

filename: /(.+)/
add_line: "+" /(.*)/ LF -> line

change_move: "*** Move to: " filename LF
change: (change_context | change_line)+ eof_line?
change_context: ("@@" | "@@ " /(.+)/) LF
change_line: ("+" | "-" | " ") /(.*)/ LF
eof_line: "*** End of File" LF

%import common.LF
"""


def build_codex_canonical_tools(
    *,
    shell_runtime: CodexShellRuntime | None = None,
    write_stdin_runtime: CodexWriteStdinRuntime | None = None,
    apply_patch_runtime: CodexApplyPatchRuntime | None = None,
) -> list[CanonicalTool]:
    shared_executor = _pick_shared_executor(shell_runtime, write_stdin_runtime)
    if shell_runtime is not None:
        exec_runtime = shell_runtime
    else:
        exec_runtime = CodexShellRuntime(shared_executor or SharedProcessExecutor())
    if write_stdin_runtime is not None:
        stdin_runtime = write_stdin_runtime
    else:
        stdin_runtime = CodexWriteStdinRuntime(
            shared_executor or exec_runtime.executor
        )
    patch_runtime = apply_patch_runtime or CodexApplyPatchRuntime()

    def exec_command_handler(
        cmd: str,
        workdir: str | None = None,
        tty: bool | None = None,
        yield_time_ms: int | float | None = None,
        max_output_tokens: int | float | None = None,
        shell: str | None = None,
        login: bool | None = None,
        sandbox_permissions: str | None = None,
        justification: str | None = None,
        prefix_rule: list[str] | None = None,
        additional_permissions: dict[str, Any] | None = None,
        environment_id: str | None = None,
        *,
        ctx=None,
    ) -> ToolResult:
        result = exec_runtime.execute_command(
            cmd,
            workdir=workdir,
            shell=shell,
            login=login,
            tty=tty,
            yield_time_ms=yield_time_ms,
            max_output_tokens=max_output_tokens,
            ctx=ctx,
        )
        return _relabel_result(
            result,
            operation="exec_command",
            command_family="exec_command",
            extra={
                "requested_sandbox_permissions": sandbox_permissions,
                "requested_justification": justification,
                "requested_prefix_rule": prefix_rule,
                "requested_additional_permissions": additional_permissions,
                "requested_environment_id": environment_id,
            },
        )

    def write_stdin_handler(
        session_id: int | float,
        chars: str | None = None,
        yield_time_ms: int | float | None = None,
        max_output_tokens: int | float | None = None,
        *,
        ctx=None,
    ) -> ToolResult:
        result = stdin_runtime.write_stdin(
            session_id,
            chars=chars,
            yield_time_ms=yield_time_ms,
            max_output_tokens=max_output_tokens,
            ctx=ctx,
        )
        return _relabel_result(
            result,
            operation="write_stdin",
            command_family="write_stdin",
            extra={"requested_max_output_tokens": max_output_tokens},
        )

    def apply_patch_handler(*, input_text: str, ctx=None) -> ToolResult:
        result = patch_runtime.apply_patch(input_text, ctx=ctx)
        return _relabel_result(
            result,
            operation="apply_patch",
            command_family="apply_patch",
        )

    return [
        CanonicalTool(
            canonical_name="exec_command",
            description=(
                "Runs a command in a PTY, returning output or a session ID for "
                "ongoing interaction."
            ),
            canonical_schema=_exec_command_schema(),
            handler=exec_command_handler,
            version="exec_command_v1",
            metadata={
                "family": _FAMILY,
                "source_runtime": "codex_shell",
                "native_tool_name": "exec_command",
            },
        ),
        CanonicalTool(
            canonical_name="write_stdin",
            description=(
                "Writes characters to an existing unified exec session and returns "
                "recent output."
            ),
            canonical_schema=_write_stdin_schema(),
            handler=write_stdin_handler,
            version="write_stdin_v1",
            metadata={
                "family": _FAMILY,
                "source_runtime": "codex_shell",
                "native_tool_name": "write_stdin",
            },
        ),
        CanonicalTool(
            canonical_name="apply_patch",
            description=(
                "Use the `apply_patch` tool to edit files. This is a FREEFORM "
                "tool, so do not wrap the patch in JSON."
            ),
            contract_kind=ToolContractKind.FREEFORM,
            input_format={
                "type": "grammar",
                "syntax": "lark",
                "definition": _APPLY_PATCH_GRAMMAR,
            },
            handler=apply_patch_handler,
            version="apply_patch_v1",
            metadata={
                "family": _FAMILY,
                "source_runtime": "codex_apply_patch",
                "native_tool_name": "apply_patch",
            },
        ),
    ]


def build_codex_canonical_registry(
    *,
    shell_runtime: CodexShellRuntime | None = None,
    write_stdin_runtime: CodexWriteStdinRuntime | None = None,
    apply_patch_runtime: CodexApplyPatchRuntime | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in build_codex_canonical_tools(
        shell_runtime=shell_runtime,
        write_stdin_runtime=write_stdin_runtime,
        apply_patch_runtime=apply_patch_runtime,
    ):
        registry.register(tool)
    return registry


def _pick_shared_executor(
    shell_runtime: CodexShellRuntime | None,
    write_stdin_runtime: CodexWriteStdinRuntime | None,
) -> SharedProcessExecutor | None:
    if shell_runtime is not None and write_stdin_runtime is not None:
        return None
    if shell_runtime is not None:
        return getattr(shell_runtime, "executor", None)
    if write_stdin_runtime is not None:
        return getattr(write_stdin_runtime, "executor", None)
    return None


def _relabel_result(
    result: ToolResult,
    *,
    operation: str,
    command_family: str,
    extra: dict[str, Any] | None = None,
) -> ToolResult:
    metadata = dict(result.metadata)
    metadata["operation"] = operation
    metadata["command_family"] = command_family
    metadata["family"] = _FAMILY
    if extra:
        metadata.update(extra)
    return ToolResult(
        ok=result.ok,
        content=result.content,
        metadata=metadata,
        is_error=result.is_error,
    )


def _exec_command_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "cmd": {"type": "string"},
            "workdir": {"type": "string"},
            "tty": {"type": "boolean"},
            "yield_time_ms": {"type": "number"},
            "max_output_tokens": {"type": "number"},
            "shell": {"type": "string"},
            "login": {"type": "boolean"},
            "sandbox_permissions": {
                "type": "string",
                "enum": [
                    "use_default",
                    "with_additional_permissions",
                    "require_escalated",
                ],
            },
            "justification": {"type": "string"},
            "prefix_rule": {
                "type": "array",
                "items": {"type": "string"},
            },
            "additional_permissions": {"type": "object"},
            "environment_id": {"type": "string"},
        },
        "required": ["cmd"],
        "additionalProperties": False,
    }


def _write_stdin_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "session_id": {"type": "number"},
            "chars": {"type": "string"},
            "yield_time_ms": {"type": "number"},
            "max_output_tokens": {"type": "number"},
        },
        "required": ["session_id"],
        "additionalProperties": False,
    }
