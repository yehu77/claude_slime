"""Shared command safety and subprocess execution helpers."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pycodeagent.env.path_policy import validate_cwd
from pycodeagent.tools.execution_contract import build_execution_metadata

RUN_COMMAND_ALLOW_EXECUTABLES: set[str] = {
    "pytest",
    "ruff",
    "mypy",
    "git",
}

RUN_COMMAND_ALLOWED_GIT_SUBCOMMANDS: set[str] = {
    "--version",
    "version",
    "branch",
    "diff",
    "grep",
    "log",
    "ls-files",
    "rev-parse",
    "show",
    "status",
}

RUN_COMMAND_DENIED_EXECUTABLES: set[str] = {
    "chmod",
    "chown",
    "curl",
    "dd",
    "docker",
    "kill",
    "mkfs",
    "node",
    "npm",
    "pip",
    "pip3",
    "pnpm",
    "python",
    "python3",
    "reboot",
    "rm",
    "scp",
    "shutdown",
    "ssh",
    "sudo",
    "wget",
}


@dataclass(frozen=True)
class CommandPolicyDecision:
    """Normalized command-policy decision."""

    allowed: bool
    command_family: str
    policy_reason: str | None
    dangerous: bool

    @property
    def policy_decision(self) -> str:
        return "allow" if self.allowed else "deny"


@dataclass(frozen=True)
class CommandExecutionResult:
    """Normalized subprocess execution result."""

    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: int
    error_type: str | None = None
    error_message: str | None = None

    @property
    def completed(self) -> bool:
        return self.error_type is None


def truncate_output(text: str, limit: int = 50_000) -> tuple[str, bool]:
    """Truncate output text to a stable maximum size."""
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n... [truncated at {limit} chars]", True


def normalize_executable_name(token: str) -> str:
    """Normalize an executable token for policy checks."""
    path = Path(token)
    normalized = path.stem or path.name
    return normalized.lower()


def allow_command(command_family: str) -> CommandPolicyDecision:
    return CommandPolicyDecision(
        allowed=True,
        command_family=command_family,
        policy_reason=None,
        dangerous=False,
    )


def deny_command(
    command_family: str,
    reason: str,
    *,
    dangerous: bool,
) -> CommandPolicyDecision:
    return CommandPolicyDecision(
        allowed=False,
        command_family=command_family,
        policy_reason=reason,
        dangerous=dangerous,
    )


def classify_command_argv(argv: list[str]) -> CommandPolicyDecision:
    """Classify one run_command argv against the current allow/deny policy."""
    if not argv:
        return deny_command("unknown", "Empty command", dangerous=False)

    executable = normalize_executable_name(argv[0])

    if executable in RUN_COMMAND_DENIED_EXECUTABLES:
        return deny_command(
            executable,
            f"Command not in allowlist: {argv[0]!r} (blocked executable)",
            dangerous=True,
        )

    if executable not in RUN_COMMAND_ALLOW_EXECUTABLES:
        return deny_command(
            executable,
            f"Command not in allowlist: {argv[0]!r}",
            dangerous=False,
        )

    if executable == "git":
        if len(argv) < 2:
            return deny_command(
                "git",
                "git command requires an allowed subcommand",
                dangerous=False,
            )
        subcommand = argv[1]
        if subcommand not in RUN_COMMAND_ALLOWED_GIT_SUBCOMMANDS:
            return deny_command(
                "git",
                f"git subcommand not allowed: {subcommand!r}",
                dangerous=True,
            )

    return allow_command(executable)


def normalize_workdir(raw_cwd: str | None, workspace_root: Path) -> Path:
    """Resolve a working directory inside workspace."""
    return validate_cwd(raw_cwd, workspace_root)


def build_command_metadata(
    *,
    stage: str,
    decision: CommandPolicyDecision,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build stable command-safety metadata for tool results."""
    payload = dict(extra or {})
    operation = str(payload.pop("operation", "command"))
    execution_kind = str(payload.pop("execution_kind", "command_exec"))
    workspace_root = payload.pop("workspace_root", None)
    resolved_target_paths = payload.pop("resolved_target_paths", None)
    resolved_cwd = payload.pop("resolved_cwd", None)
    policy_reason = payload.pop("policy_reason", decision.policy_reason)
    policy_reason_code = payload.pop("policy_reason_code", None)
    if policy_reason_code is None and decision.policy_reason is not None:
        policy_reason_code = "command_policy"
    return build_execution_metadata(
        operation=operation,
        execution_kind=execution_kind,
        execution_stage=stage,
        policy_domain="command",
        policy_decision=decision.policy_decision,
        policy_reason=policy_reason,
        policy_reason_code=policy_reason_code,
        dangerous=decision.dangerous,
        command_family=decision.command_family,
        workspace_root=workspace_root,
        resolved_target_paths=resolved_target_paths,
        resolved_cwd=resolved_cwd,
        extra=payload,
    )


def run_subprocess(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int,
    output_limit: int = 50_000,
) -> CommandExecutionResult:
    """Run a subprocess with stable timeout/timing/output handling."""
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        stdout, stdout_truncated = truncate_output(proc.stdout, limit=output_limit)
        stderr, stderr_truncated = truncate_output(proc.stderr, limit=output_limit)
        return CommandExecutionResult(
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            duration_ms=duration_ms,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        stdout, stdout_truncated = truncate_output(
            _coerce_optional_output(exc.stdout),
            limit=output_limit,
        )
        stderr, stderr_truncated = truncate_output(
            _coerce_optional_output(exc.stderr),
            limit=output_limit,
        )
        return CommandExecutionResult(
            exit_code=None,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            duration_ms=duration_ms,
            error_type="timeout",
            error_message=f"Command timed out after {timeout}s",
        )
    except FileNotFoundError as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return CommandExecutionResult(
            exit_code=None,
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            duration_ms=duration_ms,
            error_type="execution",
            error_message=str(exc),
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return CommandExecutionResult(
            exit_code=None,
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            duration_ms=duration_ms,
            error_type="execution",
            error_message=str(exc),
        )


def render_subprocess_output(result: CommandExecutionResult) -> str:
    """Render a completed subprocess result in the shared text layout."""
    parts: list[str] = []
    if result.stdout:
        parts.append(f"[stdout]\n{result.stdout}")
    if result.stderr:
        parts.append(f"[stderr]\n{result.stderr}")
    if result.exit_code is not None:
        parts.append(f"[exit code] {result.exit_code}")
    return "\n".join(parts)


def _coerce_optional_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
