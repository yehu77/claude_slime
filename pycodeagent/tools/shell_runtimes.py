"""Family-specific shell runtimes built on the shared process executor."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from pycodeagent.env.path_policy import PathPolicyError
from pycodeagent.tools.command_safety import normalize_workdir
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.execution_contract import build_execution_metadata
from pycodeagent.tools.process_exec import (
    ProcessExecError,
    ProcessExecRequest,
    ProcessExecResult,
    SharedProcessExecutor,
)
from pycodeagent.trajectory.schema import ToolResult

_CLAUDE_DEFAULT_TIMEOUT_MS = 60_000
_CLAUDE_MIN_TIMEOUT_MS = 1
_CLAUDE_MAX_TIMEOUT_MS = 600_000

_CODEX_DEFAULT_YIELD_MS = 10_000
_CODEX_MIN_YIELD_MS = 250
_CODEX_MAX_YIELD_MS = 30_000
_CODEX_DEFAULT_EMPTY_POLL_YIELD_MS = 5_000
_CODEX_MAX_EMPTY_POLL_YIELD_MS = 300_000


def _render_command_output(result: ProcessExecResult) -> str:
    """Render one command result in the stable text layout."""
    parts: list[str] = []
    if result.stdout:
        parts.append(f"[stdout]\n{result.stdout}")
    if result.stderr:
        parts.append(f"[stderr]\n{result.stderr}")
    if result.exit_code is not None:
        parts.append(f"[exit code] {result.exit_code}")
    elif result.session_id is not None:
        parts.append(f"[session_id] {result.session_id}")
    return "\n".join(parts)


def _missing_context_error(
    *,
    operation: str,
    execution_kind: str,
    command_family: str | None = None,
    extra: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        ok=False,
        content="ToolContext is required for workspace enforcement",
        is_error=True,
        metadata=build_execution_metadata(
            operation=operation,
            execution_kind=execution_kind,
            execution_stage="context_check",
            policy_domain="runtime",
            policy_decision="deny",
            policy_reason="ToolContext is required for workspace enforcement",
            policy_reason_code="missing_context",
            dangerous=False,
            command_family=command_family,
            extra={"error_type": "missing_context", **(extra or {})},
        ),
    )


def _invalid_timeout_error(
    *,
    operation: str,
    execution_kind: str,
    command_family: str,
    timeout: object,
) -> ToolResult:
    return ToolResult(
        ok=False,
        content=(
            "Invalid timeout. Timeout must be a number between "
            f"{_CLAUDE_MIN_TIMEOUT_MS} and {_CLAUDE_MAX_TIMEOUT_MS} milliseconds."
        ),
        is_error=True,
        metadata=build_execution_metadata(
            operation=operation,
            execution_kind=execution_kind,
            execution_stage="validate_input",
            policy_domain="runtime",
            policy_decision="deny",
            policy_reason="Timeout must be between 1 and 600000 milliseconds",
            policy_reason_code="invalid_timeout",
            dangerous=False,
            command_family=command_family,
            extra={
                "error_type": "invalid_timeout",
                "requested_timeout": timeout,
            },
        ),
    )


def _invalid_session_id_error(
    *,
    operation: str,
    command_family: str,
    session_id: object,
) -> ToolResult:
    return ToolResult(
        ok=False,
        content="Invalid session_id. session_id must be a positive integer.",
        is_error=True,
        metadata=build_execution_metadata(
            operation=operation,
            execution_kind="command_exec",
            execution_stage="validate_input",
            policy_domain="runtime",
            policy_decision="deny",
            policy_reason="session_id must be a positive integer",
            policy_reason_code="invalid_session_id",
            dangerous=False,
            command_family=command_family,
            extra={
                "error_type": "invalid_session_id",
                "requested_session_id": session_id,
            },
        ),
    )


def _path_policy_error_result(
    error: PathPolicyError,
    *,
    operation: str,
    execution_kind: str,
    execution_stage: str,
    command_family: str | None = None,
    workspace_root: Path | None = None,
    resolved_cwd: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> ToolResult:
    metadata = build_execution_metadata(
        operation=operation,
        execution_kind=execution_kind,
        execution_stage=execution_stage,
        policy_domain=error.metadata.get("policy_domain", "filesystem"),
        policy_decision=error.metadata.get("policy_decision", "deny"),
        policy_reason=error.metadata.get("policy_reason", str(error)),
        policy_reason_code=error.metadata.get("policy_reason_code", error.error_type),
        dangerous=error.metadata.get(
            "dangerous",
            error.error_type in {"absolute_path", "workspace_escape", "protected_path"},
        ),
        command_family=command_family,
        workspace_root=workspace_root,
        resolved_cwd=resolved_cwd,
        extra={
            "error_type": error.error_type,
            **(extra or {}),
        },
    )
    for key, value in error.metadata.items():
        metadata.setdefault(key, value)
    return ToolResult(
        ok=False,
        content=str(error),
        is_error=True,
        metadata=metadata,
    )


def _process_exec_error_result(
    *,
    operation: str,
    execution_kind: str,
    command_family: str,
    workspace_root: Path,
    resolved_cwd: Path,
    content: str,
    error_type: str,
    execution_stage: str,
    extra: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        ok=False,
        content=content,
        is_error=True,
        metadata=build_execution_metadata(
            operation=operation,
            execution_kind=execution_kind,
            execution_stage=execution_stage,
            policy_domain="command",
            policy_decision="allow",
            dangerous=False,
            command_family=command_family,
            workspace_root=workspace_root,
            resolved_cwd=resolved_cwd,
            extra={
                "error_type": error_type,
                **(extra or {}),
            },
        ),
    )


def _unexpected_runtime_error_result(
    *,
    operation: str,
    execution_kind: str,
    command_family: str,
    workspace_root: Path,
    resolved_cwd: Path,
    exc: Exception,
    extra: dict[str, Any] | None = None,
) -> ToolResult:
    return _process_exec_error_result(
        operation=operation,
        execution_kind=execution_kind,
        command_family=command_family,
        workspace_root=workspace_root,
        resolved_cwd=resolved_cwd,
        content=f"Unexpected command execution error: {exc}",
        error_type="execution",
        execution_stage="execute",
        extra={
            "unexpected_error": str(exc),
            **(extra or {}),
        },
    )


def _command_result_to_tool_result(
    result: ProcessExecResult,
    *,
    operation: str,
    command_family: str,
    workspace_root: Path,
    resolved_cwd: Path,
    shell: str,
    login: bool,
    timeout_ms: int | None,
    execution_kind: str = "command_exec",
    extra: dict[str, Any] | None = None,
) -> ToolResult:
    base_extra = {
        "shell": shell,
        "login": login,
        "timeout_ms": timeout_ms,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
        "stdout_truncated": result.stdout_truncated,
        "stderr_truncated": result.stderr_truncated,
        **(extra or {}),
    }
    if result.session_id is not None:
        base_extra["session_id"] = result.session_id

    if result.spawn_error is not None:
        return _process_exec_error_result(
            operation=operation,
            execution_kind=execution_kind,
            command_family=command_family,
            workspace_root=workspace_root,
            resolved_cwd=resolved_cwd,
            content=f"Command execution error: {result.spawn_error}",
            error_type="execution",
            execution_stage="execute",
            extra={
                **base_extra,
                "spawn_error": result.spawn_error,
            },
        )

    rendered = _render_command_output(result)
    if result.timed_out:
        timeout_message = f"Command timed out after {timeout_ms}ms"
        content = rendered + ("\n" if rendered else "") + timeout_message
        return _process_exec_error_result(
            operation=operation,
            execution_kind=execution_kind,
            command_family=command_family,
            workspace_root=workspace_root,
            resolved_cwd=resolved_cwd,
            content=content,
            error_type="timeout",
            execution_stage="execute",
            extra=base_extra,
        )

    return ToolResult(
        ok=result.exit_code == 0 or result.session_id is not None,
        content=rendered,
        metadata=build_execution_metadata(
            operation=operation,
            execution_kind=execution_kind,
            execution_stage="result_finalize",
            policy_domain="command",
            policy_decision="allow",
            dangerous=False,
            command_family=command_family,
            workspace_root=workspace_root,
            resolved_cwd=resolved_cwd,
            extra=base_extra,
        ),
    )


def _coerce_claude_timeout_ms(timeout: int | float | None) -> int | None:
    if timeout is None:
        return _CLAUDE_DEFAULT_TIMEOUT_MS
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        return None
    if not math.isfinite(timeout):
        return None
    if timeout < _CLAUDE_MIN_TIMEOUT_MS or timeout > _CLAUDE_MAX_TIMEOUT_MS:
        return None
    return int(timeout)


def _coerce_codex_yield_time_ms(value: int | float | None) -> int:
    if value is None:
        return _CODEX_DEFAULT_YIELD_MS
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return _CODEX_DEFAULT_YIELD_MS
    return max(_CODEX_MIN_YIELD_MS, min(int(value), _CODEX_MAX_YIELD_MS))


def _coerce_codex_write_yield_time_ms(
    value: int | float | None,
    *,
    is_empty_poll: bool,
) -> int:
    if value is None:
        return (
            _CODEX_DEFAULT_EMPTY_POLL_YIELD_MS
            if is_empty_poll
            else _CODEX_MIN_YIELD_MS
        )
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return (
            _CODEX_DEFAULT_EMPTY_POLL_YIELD_MS
            if is_empty_poll
            else _CODEX_MIN_YIELD_MS
        )
    clamped = max(_CODEX_MIN_YIELD_MS, int(value))
    if is_empty_poll:
        return min(clamped, _CODEX_MAX_EMPTY_POLL_YIELD_MS)
    return min(clamped, _CODEX_MAX_YIELD_MS)


def _coerce_positive_session_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer() and value > 0:
        return int(value)
    return None


class ClaudeShellRuntime:
    """Claude-style shell runtime built on the shared process executor."""

    def __init__(self, executor: SharedProcessExecutor | None = None) -> None:
        self._executor = executor or SharedProcessExecutor()

    @property
    def executor(self) -> SharedProcessExecutor:
        return self._executor

    def execute_bash(
        self,
        command: str,
        timeout: int | float | None = None,
        run_in_background: bool = False,
        *,
        ctx: ToolContext | None = None,
    ) -> ToolResult:
        execution_kind = "command_background" if run_in_background else "command_exec"
        if ctx is None:
            return _missing_context_error(
                operation="claude_bash",
                execution_kind=execution_kind,
                command_family="claude_bash",
                extra={
                    "run_in_background": run_in_background,
                    "command": command,
                    "requested_timeout": timeout,
                },
            )

        timeout_ms = _coerce_claude_timeout_ms(timeout)
        if timeout_ms is None:
            return _invalid_timeout_error(
                operation="claude_bash",
                execution_kind=execution_kind,
                command_family="claude_bash",
                timeout=timeout,
            )

        request = ProcessExecRequest(
            command=command,
            cwd=ctx.workspace_root,
            shell="bash",
            login=False,
            timeout_ms=timeout_ms,
        )

        if run_in_background:
            try:
                handle = self._executor.run_background(
                    request,
                    artifact_root=ctx.artifact_root,
                )
            except ProcessExecError as exc:
                return _process_exec_error_result(
                    operation="claude_bash",
                    execution_kind="command_background",
                    command_family="claude_bash",
                    workspace_root=ctx.workspace_root,
                    resolved_cwd=ctx.workspace_root,
                    content=str(exc),
                    error_type="execution",
                    execution_stage="execute",
                    extra={
                        "run_in_background": True,
                        "timeout_ms": timeout_ms,
                        "shell": "bash",
                        "login": False,
                    },
                )
            except Exception as exc:
                return _unexpected_runtime_error_result(
                    operation="claude_bash",
                    execution_kind="command_background",
                    command_family="claude_bash",
                    workspace_root=ctx.workspace_root,
                    resolved_cwd=ctx.workspace_root,
                    exc=exc,
                    extra={
                        "run_in_background": True,
                        "timeout_ms": timeout_ms,
                        "shell": "bash",
                        "login": False,
                    },
                )

            return ToolResult(
                ok=True,
                content=(
                    f"Started background task {handle.task_id}. "
                    f"Output will be written to {handle.output_path}. "
                    "Use the future Claude Read tool on that file to inspect results."
                ),
                metadata=build_execution_metadata(
                    operation="claude_bash",
                    execution_kind="command_background",
                    execution_stage="result_finalize",
                    policy_domain="command",
                    policy_decision="allow",
                    dangerous=False,
                    command_family="claude_bash",
                    workspace_root=ctx.workspace_root,
                    resolved_cwd=ctx.workspace_root,
                    extra={
                        "run_in_background": True,
                        "timeout_ms": timeout_ms,
                        "shell": "bash",
                        "login": False,
                        "background_task_id": handle.task_id,
                        "background_output_path": str(handle.output_path),
                        "background_pid": handle.pid,
                        "background_started_at_ms": handle.started_at_ms,
                    },
                ),
            )

        try:
            result = self._executor.run_foreground(request)
        except ProcessExecError as exc:
            return _process_exec_error_result(
                operation="claude_bash",
                execution_kind="command_exec",
                command_family="claude_bash",
                workspace_root=ctx.workspace_root,
                resolved_cwd=ctx.workspace_root,
                content=str(exc),
                error_type="execution",
                execution_stage="execute",
                extra={
                    "run_in_background": False,
                    "timeout_ms": timeout_ms,
                    "shell": "bash",
                    "login": False,
                },
            )
        except Exception as exc:
            return _unexpected_runtime_error_result(
                operation="claude_bash",
                execution_kind="command_exec",
                command_family="claude_bash",
                workspace_root=ctx.workspace_root,
                resolved_cwd=ctx.workspace_root,
                exc=exc,
                extra={
                    "run_in_background": False,
                    "timeout_ms": timeout_ms,
                    "shell": "bash",
                    "login": False,
                },
            )
        return _command_result_to_tool_result(
            result,
            operation="claude_bash",
            command_family="claude_bash",
            workspace_root=ctx.workspace_root,
            resolved_cwd=ctx.workspace_root,
            shell="bash",
            login=False,
            timeout_ms=timeout_ms,
            extra={"run_in_background": False},
        )


class CodexShellRuntime:
    """Codex-style shell runtime built on the shared process executor."""

    def __init__(self, executor: SharedProcessExecutor | None = None) -> None:
        self._executor = executor or SharedProcessExecutor()

    @property
    def executor(self) -> SharedProcessExecutor:
        return self._executor

    def execute_command(
        self,
        cmd: str,
        workdir: str | None = None,
        shell: str | None = None,
        login: bool | None = None,
        tty: bool | None = None,
        yield_time_ms: int | float | None = None,
        max_output_tokens: int | float | None = None,
        *,
        ctx: ToolContext | None = None,
    ) -> ToolResult:
        if ctx is None:
            return _missing_context_error(
                operation="codex_exec_command",
                execution_kind="command_exec",
                command_family="codex_exec_command",
                extra={
                    "cmd": cmd,
                    "requested_workdir": workdir,
                    "shell": shell,
                    "login": login,
                    "tty": tty,
                    "yield_time_ms": yield_time_ms,
                    "max_output_tokens": max_output_tokens,
                },
            )

        try:
            resolved_cwd = normalize_workdir(workdir, ctx.workspace_root)
        except PathPolicyError as exc:
            return _path_policy_error_result(
                exc,
                operation="codex_exec_command",
                execution_kind="command_exec",
                execution_stage="validate_cwd",
                command_family="codex_exec_command",
                workspace_root=ctx.workspace_root,
                extra={
                    "requested_workdir": workdir,
                    "shell": shell or "bash",
                    "login": True if login is None else login,
                    "tty": False if tty is None else tty,
                    "yield_time_ms": _coerce_codex_yield_time_ms(yield_time_ms),
                    "max_output_tokens": max_output_tokens,
                },
            )

        selected_shell = shell or "bash"
        selected_login = True if login is None else login
        selected_tty = False if tty is None else tty
        selected_yield_ms = _coerce_codex_yield_time_ms(yield_time_ms)
        request = ProcessExecRequest(
            command=cmd,
            cwd=resolved_cwd,
            shell=selected_shell,
            login=selected_login,
            tty=selected_tty,
        )
        try:
            result = self._executor.start_session(
                request,
                yield_time_ms=selected_yield_ms,
            )
        except ProcessExecError as exc:
            return _process_exec_error_result(
                operation="codex_exec_command",
                execution_kind="command_exec",
                command_family="codex_exec_command",
                workspace_root=ctx.workspace_root,
                resolved_cwd=resolved_cwd,
                content=str(exc),
                error_type="execution",
                execution_stage="execute",
                extra={
                    "shell": selected_shell,
                    "login": selected_login,
                    "tty": selected_tty,
                    "yield_time_ms": selected_yield_ms,
                    "max_output_tokens": max_output_tokens,
                },
            )
        except Exception as exc:
            return _unexpected_runtime_error_result(
                operation="codex_exec_command",
                execution_kind="command_exec",
                command_family="codex_exec_command",
                workspace_root=ctx.workspace_root,
                resolved_cwd=resolved_cwd,
                exc=exc,
                extra={
                    "shell": selected_shell,
                    "login": selected_login,
                    "tty": selected_tty,
                    "yield_time_ms": selected_yield_ms,
                    "max_output_tokens": max_output_tokens,
                },
            )
        return _command_result_to_tool_result(
            result,
            operation="codex_exec_command",
            command_family="codex_exec_command",
            workspace_root=ctx.workspace_root,
            resolved_cwd=resolved_cwd,
            shell=selected_shell,
            login=selected_login,
            timeout_ms=request.timeout_ms,
            extra={
                "tty": selected_tty,
                "yield_time_ms": selected_yield_ms,
                "max_output_tokens": max_output_tokens,
            },
        )


class CodexWriteStdinRuntime:
    """Codex-style continuation runtime for live exec sessions."""

    def __init__(self, executor: SharedProcessExecutor | None = None) -> None:
        self._executor = executor or SharedProcessExecutor()

    @property
    def executor(self) -> SharedProcessExecutor:
        return self._executor

    def write_stdin(
        self,
        session_id: int | float,
        chars: str | None = None,
        yield_time_ms: int | float | None = None,
        max_output_tokens: int | float | None = None,
        *,
        ctx: ToolContext | None = None,
    ) -> ToolResult:
        if ctx is None:
            return _missing_context_error(
                operation="codex_write_stdin",
                execution_kind="command_exec",
                command_family="codex_write_stdin",
                extra={
                    "session_id": session_id,
                    "chars": chars,
                    "yield_time_ms": yield_time_ms,
                    "max_output_tokens": max_output_tokens,
                },
            )

        normalized_session_id = _coerce_positive_session_id(session_id)
        if normalized_session_id is None:
            return _invalid_session_id_error(
                operation="codex_write_stdin",
                command_family="codex_write_stdin",
                session_id=session_id,
            )

        input_chars = chars or ""
        selected_yield_ms = _coerce_codex_write_yield_time_ms(
            yield_time_ms,
            is_empty_poll=not bool(input_chars),
        )
        try:
            result = self._executor.write_session_stdin(
                normalized_session_id,
                input_chars,
                yield_time_ms=selected_yield_ms,
            )
        except ProcessExecError as exc:
            return _process_exec_error_result(
                operation="codex_write_stdin",
                execution_kind="command_exec",
                command_family="codex_write_stdin",
                workspace_root=ctx.workspace_root,
                resolved_cwd=ctx.workspace_root,
                content=str(exc),
                error_type="execution",
                execution_stage="execute",
                extra={
                    "session_id": normalized_session_id,
                    "chars": input_chars,
                    "yield_time_ms": selected_yield_ms,
                    "max_output_tokens": max_output_tokens,
                },
            )
        except Exception as exc:
            return _unexpected_runtime_error_result(
                operation="codex_write_stdin",
                execution_kind="command_exec",
                command_family="codex_write_stdin",
                workspace_root=ctx.workspace_root,
                resolved_cwd=ctx.workspace_root,
                exc=exc,
                extra={
                    "session_id": normalized_session_id,
                    "chars": input_chars,
                    "yield_time_ms": selected_yield_ms,
                    "max_output_tokens": max_output_tokens,
                },
            )
        return _command_result_to_tool_result(
            result,
            operation="codex_write_stdin",
            command_family="codex_write_stdin",
            workspace_root=ctx.workspace_root,
            resolved_cwd=ctx.workspace_root,
            shell="session",
            login=False,
            timeout_ms=None,
            extra={
                "session_id": normalized_session_id,
                "yield_time_ms": selected_yield_ms,
                "max_output_tokens": max_output_tokens,
                "chars_written": len(input_chars),
                "poll_only": not bool(input_chars),
            },
        )
