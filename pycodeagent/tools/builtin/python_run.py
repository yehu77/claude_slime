"""Built-in python_run tool with narrow structured execution semantics."""

from __future__ import annotations

import sys

from pycodeagent.env.path_policy import PathPolicyError, resolve_and_validate_path
from pycodeagent.tools.command_safety import (
    allow_command,
    build_command_metadata,
    deny_command,
    normalize_workdir,
    render_subprocess_output,
    run_subprocess,
)
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.spec import CanonicalTool
from pycodeagent.trajectory.schema import ToolResult

_DEFAULT_TIMEOUT = 60
_MAX_OUTPUT_CHARS = 50_000
_ALLOWED_MODULES = {"pytest", "unittest"}


def _execution_kind_for_target(target: str, *, run_as_module: bool) -> str | None:
    if not run_as_module:
        return "script"
    if target == "pytest":
        return "pytest_module"
    if target == "unittest":
        return "unittest_module"
    return None


def _python_run_handler(
    target: str,
    args: list[str] | None = None,
    run_as_module: bool = False,
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
                    "python_run",
                    "ToolContext is required for workspace enforcement",
                    dangerous=False,
                ),
                extra={
                    "error_type": "missing_context",
                    "operation": "python_run",
                    "requested_cwd": cwd,
                    "target": target,
                    "timeout_sec": timeout,
                    "run_as_module": run_as_module,
                    "execution_kind": _execution_kind_for_target(
                        target, run_as_module=run_as_module
                    ),
                    "policy_reason_code": "missing_context",
                },
            ),
        )

    args = list(args or [])
    execution_kind = _execution_kind_for_target(target, run_as_module=run_as_module)
    target_kind = "module" if run_as_module else "script_path"

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
                    "python_run",
                    str(exc),
                    dangerous=exc.error_type in {"absolute_path", "workspace_escape"},
                ),
                extra={
                    "error_type": exc.error_type,
                    "operation": "python_run",
                    "workspace_root": str(ctx.workspace_root),
                    "requested_cwd": cwd,
                    "timeout_sec": timeout,
                    "target": target,
                    "target_kind": target_kind,
                    "execution_kind": execution_kind,
                    "policy_reason_code": exc.error_type,
                },
            ),
        )

    resolved_target: str | None = None
    command = [sys.executable, "-B"]
    command_family = "python_module" if run_as_module else "python_script"

    if run_as_module:
        if target not in _ALLOWED_MODULES:
            decision = deny_command(
                command_family,
                f"module target not allowed: {target!r}",
                dangerous=False,
            )
            return ToolResult(
                ok=False,
                content=f"Unsupported Python module target: {target!r}",
                is_error=True,
                metadata=build_command_metadata(
                    stage="validate_target",
                    decision=decision,
                    extra={
                        "error_type": "invalid_module",
                        "operation": "python_run",
                        "workspace_root": str(ctx.workspace_root),
                        "requested_cwd": cwd,
                        "target": target,
                        "target_kind": target_kind,
                        "execution_kind": execution_kind,
                        "policy_reason_code": "invalid_module",
                    },
                ),
            )
        command.extend(["-m", target, *args])
    else:
        try:
            script_path = resolve_and_validate_path(
                target,
                ctx.workspace_root,
                must_exist=True,
                must_be_file=True,
                check_allowed_fn=ctx.is_file_allowed,
            )
        except PathPolicyError as exc:
            return ToolResult(
                ok=False,
                content=str(exc),
                is_error=True,
                metadata=build_command_metadata(
                    stage="validate_target",
                    decision=deny_command(command_family, str(exc), dangerous=False),
                    extra={
                        "error_type": exc.error_type,
                        "operation": "python_run",
                        "workspace_root": str(ctx.workspace_root),
                        "requested_cwd": cwd,
                        "target": target,
                        "target_kind": target_kind,
                        "execution_kind": execution_kind,
                        "policy_reason_code": exc.error_type,
                    },
                ),
            )
        if script_path.suffix.lower() != ".py":
            decision = deny_command(
                command_family,
                f"script target must be a .py file: {target!r}",
                dangerous=False,
            )
            return ToolResult(
                ok=False,
                content=f"Python script target must be a .py file: {target!r}",
                is_error=True,
                metadata=build_command_metadata(
                    stage="validate_target",
                    decision=decision,
                    extra={
                        "error_type": "invalid_target",
                        "operation": "python_run",
                        "workspace_root": str(ctx.workspace_root),
                        "requested_cwd": cwd,
                        "target": target,
                        "target_kind": target_kind,
                        "execution_kind": execution_kind,
                        "policy_reason_code": "invalid_target",
                    },
                ),
            )
        resolved_target = str(script_path)
        command.extend([resolved_target, *args])

    decision = allow_command(command_family)
    metadata = {
        "operation": "python_run",
        "target": target,
        "run_as_module": run_as_module,
        "args": args,
        "workspace_root": str(ctx.workspace_root),
        "requested_cwd": cwd,
        "resolved_cwd": str(resolved_cwd),
        "timeout_sec": timeout,
        "execution_kind": execution_kind,
        "target_kind": target_kind,
    }
    if resolved_target is not None:
        metadata["resolved_target"] = resolved_target
        metadata["resolved_target_paths"] = [target]

    result = run_subprocess(
        command,
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
                    **metadata,
                    "exit_code": result.exit_code,
                    "duration_ms": result.duration_ms,
                    "stdout_truncated": result.stdout_truncated,
                    "stderr_truncated": result.stderr_truncated,
                },
            ),
        )

    error_prefix = "Python run timed out" if result.error_type == "timeout" else "Python run failed"
    return ToolResult(
        ok=False,
        content=f"{error_prefix}: {result.error_message}",
        is_error=True,
        metadata=build_command_metadata(
            stage="execute",
            decision=decision,
                extra={
                    **metadata,
                    "error_type": result.error_type,
                    "duration_ms": result.duration_ms,
                    "stdout_truncated": result.stdout_truncated,
                "stderr_truncated": result.stderr_truncated,
            },
        ),
    )


python_run_tool = CanonicalTool(
    canonical_name="python_run",
    description="Run a Python script or a narrow allowed Python test module inside the workspace.",
    canonical_schema={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Workspace .py file, or an allowed module name."},
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Command-line args passed to the script or module.",
            },
            "run_as_module": {
                "type": "boolean",
                "description": "When true, run `python -m <target>` for an allowed module.",
            },
            "timeout": {
                "type": "integer",
                "description": f"Timeout in seconds (default {_DEFAULT_TIMEOUT}).",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for execution (must remain in workspace).",
            },
        },
        "required": ["target"],
    },
    handler=_python_run_handler,
)
