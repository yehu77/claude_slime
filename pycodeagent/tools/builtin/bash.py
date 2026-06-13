"""Built-in run_command tool with workspace enforcement and command policy.

Commands are always executed as structured argv within the workspace. The
``cwd`` parameter is accepted but must resolve to a directory inside
``workspace_root``.

Security note (NS-01):
    Without a full process sandbox, arbitrary commands can always access the
    host filesystem. To make workspace enforcement real rather than nominal,
    we apply these conservative restrictions:

    1. ``cwd`` is always pinned to workspace.
    2. Commands are parsed into argv and shell control syntax is rejected.
    3. Only a minimal allowlist of controlled executables is permitted.
    4. Common host-access executables are explicitly denied.

    This is intentionally conservative. A future sandbox (env/sandbox.py)
    can relax these restrictions once process-level isolation is in place.
"""

from __future__ import annotations

from pycodeagent.env.command_exec import parse_command_argv
from pycodeagent.env.path_policy import PathPolicyError
from pycodeagent.tools.command_safety import (
    build_command_metadata,
    classify_command_argv,
    deny_command,
    normalize_executable_name,
    normalize_workdir,
    render_subprocess_output,
    run_subprocess,
)
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.spec import CanonicalTool
from pycodeagent.trajectory.schema import ToolResult

_DEFAULT_TIMEOUT = 60  # seconds
_MAX_OUTPUT_CHARS = 50_000


def _run_command_handler(
    command: str,
    timeout: int = _DEFAULT_TIMEOUT,
    cwd: str | None = None,
    *,
    ctx: ToolContext | None = None,
) -> ToolResult:
    if ctx is None:
        return ToolResult(
            ok=False,
            content="ToolContext is required for workspace enforcement",
            is_error=True,
            metadata=build_command_metadata(
                stage="context_check",
                decision=deny_command(
                    "workspace_command",
                    "ToolContext is required for workspace enforcement",
                    dangerous=False,
                ),
                extra={
                    "error_type": "missing_context",
                    "operation": "run_command",
                    "execution_kind": "command_exec",
                    "requested_cwd": cwd,
                    "timeout_sec": timeout,
                    "command": command,
                    "policy_reason_code": "missing_context",
                },
            ),
        )

    try:
        resolved_cwd = normalize_workdir(cwd, ctx.workspace_root)
    except PathPolicyError as exc:
        return ToolResult(
            ok=False,
            content=str(exc),
            is_error=True,
            metadata=build_command_metadata(
                stage="validate_cwd",
                decision=deny_command(
                    "workspace_command",
                    str(exc),
                    dangerous=exc.error_type in {"absolute_path", "workspace_escape"},
                ),
                extra={
                    "error_type": exc.error_type,
                    "operation": "run_command",
                    "command": command,
                    "requested_cwd": cwd,
                    "timeout_sec": timeout,
                },
            ),
        )

    base_metadata = {
        "operation": "run_command",
        "execution_kind": "command_exec",
        "workspace_root": str(ctx.workspace_root),
        "requested_cwd": cwd,
        "resolved_cwd": str(resolved_cwd),
        "timeout_sec": timeout,
    }

    try:
        argv = parse_command_argv(command, field_name="command")
    except ValueError as exc:
        decision = deny_command("unparsed_command", str(exc), dangerous=False)
        return ToolResult(
            ok=False,
            content=f"Command rejected by policy: {exc}",
            is_error=True,
            metadata=build_command_metadata(
                stage="parse_command",
                decision=decision,
                extra={
                    "error_type": "command_policy",
                    "command": command,
                    **base_metadata,
                    "parsed_executable": None,
                    "arg_count": 0,
                    "reason": str(exc),
                    "policy_reason_code": "command_policy",
                },
            ),
        )

    decision = classify_command_argv(argv)
    parsed_executable = normalize_executable_name(argv[0]) if argv else None
    arg_count = max(0, len(argv) - 1)
    if not decision.allowed:
        return ToolResult(
            ok=False,
            content=f"Command rejected by policy: {decision.policy_reason}",
            is_error=True,
            metadata=build_command_metadata(
                stage="policy_check",
                decision=decision,
                extra={
                    "error_type": "command_policy",
                    "command": command,
                    "argv": argv,
                    **base_metadata,
                    "parsed_executable": parsed_executable,
                    "arg_count": arg_count,
                    "reason": decision.policy_reason,
                    "policy_reason_code": "command_policy",
                },
            ),
        )

    result = run_subprocess(
        argv,
        cwd=resolved_cwd,
        timeout=timeout,
        output_limit=_MAX_OUTPUT_CHARS,
    )
    if result.completed:
        return ToolResult(
            ok=result.exit_code == 0,
            content=render_subprocess_output(result),
            metadata=build_command_metadata(
                stage="execute",
                decision=decision,
                extra={
                    "command": command,
                    "argv": argv,
                    **base_metadata,
                    "parsed_executable": parsed_executable,
                    "arg_count": arg_count,
                    "exit_code": result.exit_code,
                    "duration_ms": result.duration_ms,
                    "stdout_truncated": result.stdout_truncated,
                    "stderr_truncated": result.stderr_truncated,
                },
            ),
        )

    error_prefix = "Command timed out" if result.error_type == "timeout" else "Command execution error"
    return ToolResult(
        ok=False,
        content=f"{error_prefix}: {result.error_message}",
        is_error=True,
        metadata=build_command_metadata(
            stage="execute",
            decision=decision,
            extra={
                "error_type": result.error_type,
                "command": command,
                "argv": argv,
                **base_metadata,
                "parsed_executable": parsed_executable,
                "arg_count": arg_count,
                "duration_ms": result.duration_ms,
                "stdout_truncated": result.stdout_truncated,
                "stderr_truncated": result.stderr_truncated,
            },
        ),
    )


run_command_tool = CanonicalTool(
    canonical_name="run_command",
    description="Execute a controlled command within the workspace.",
    canonical_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Command string parsed as argv; shell control syntax is not allowed.",
            },
            "timeout": {
                "type": "integer",
                "description": f"Timeout in seconds (default {_DEFAULT_TIMEOUT}).",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for the command (must be within workspace).",
            },
        },
        "required": ["command"],
    },
    handler=_run_command_handler,
)
