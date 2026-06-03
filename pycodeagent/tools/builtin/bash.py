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

import subprocess
from pathlib import Path

from pycodeagent.env.command_exec import parse_command_argv
from pycodeagent.env.path_policy import (
    PathPolicyError,
    make_error_result,
    validate_cwd,
)
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.spec import CanonicalTool
from pycodeagent.trajectory.schema import ToolResult

_DEFAULT_TIMEOUT = 60  # seconds
_MAX_OUTPUT_CHARS = 50_000

# --- Command policy ---

# Allowed executables (first argv token after parsing).
# NOTE: Only commands that are reliably available across platforms (Windows +
# Linux/macOS) and cannot execute arbitrary host code are included.
# POSIX-only utilities (ls, cat, grep, find, etc.) are excluded because they
# depend on Git Bash / MSYS2 on Windows and are not guaranteed to exist.
# python, python3, node, npm, pnpm are excluded because without a sandbox
# they can execute arbitrary code that accesses the host filesystem.
# A future sandbox (env/sandbox.py) can relax these restrictions.
_ALLOW_EXECUTABLES: set[str] = {
    "pytest",
    "ruff",
    "mypy",
    "git",
}

_ALLOWED_GIT_SUBCOMMANDS: set[str] = {
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

_DENIED_EXECUTABLES: set[str] = {
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


def _trunc(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated at {limit} chars]"


def _normalize_executable_name(token: str) -> str:
    """Normalize an executable token for policy checks."""
    path = Path(token)
    normalized = path.stem or path.name
    return normalized.lower()


def _check_policy(argv: list[str]) -> str | None:
    """Return a rejection reason, or ``None`` if the argv is allowed."""
    if not argv:
        return "Empty command"

    executable = _normalize_executable_name(argv[0])

    if executable in _DENIED_EXECUTABLES:
        return f"Command not in allowlist: {argv[0]!r} (blocked executable)"

    if executable not in _ALLOW_EXECUTABLES:
        return f"Command not in allowlist: {argv[0]!r}"

    if executable == "git":
        if len(argv) < 2:
            return "git command requires an allowed subcommand"
        subcommand = argv[1]
        if subcommand not in _ALLOWED_GIT_SUBCOMMANDS:
            return f"git subcommand not allowed: {subcommand!r}"

    return None


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
            metadata={"error_type": "missing_context"},
        )

    # Validate cwd is within workspace
    try:
        resolved_cwd = validate_cwd(cwd, ctx.workspace_root)
    except PathPolicyError as e:
        return make_error_result(e)

    try:
        argv = parse_command_argv(command, field_name="command")
    except ValueError as exc:
        return ToolResult(
            ok=False,
            content=f"Command rejected by policy: {exc}",
            is_error=True,
            metadata={"error_type": "command_policy", "reason": str(exc)},
        )

    reason = _check_policy(argv)
    if reason is not None:
        return ToolResult(
            ok=False,
            content=f"Command rejected by policy: {reason}",
            is_error=True,
            metadata={"error_type": "command_policy", "reason": reason},
        )

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=resolved_cwd,
        )
        stdout = _trunc(proc.stdout)
        stderr = _trunc(proc.stderr)
        parts: list[str] = []
        if stdout:
            parts.append(f"[stdout]\n{stdout}")
        if stderr:
            parts.append(f"[stderr]\n{stderr}")
        parts.append(f"[exit code] {proc.returncode}")
        content = "\n".join(parts)
        return ToolResult(
            ok=proc.returncode == 0,
            content=content,
            metadata={"exit_code": proc.returncode},
        )

    except subprocess.TimeoutExpired:
        return ToolResult(
            ok=False,
            content=f"Command timed out after {timeout}s",
            is_error=True,
            metadata={"error_type": "timeout", "timeout": timeout},
        )
    except FileNotFoundError as exc:
        return ToolResult(
            ok=False,
            content=f"Command execution error: {exc}",
            is_error=True,
            metadata={"error_type": "execution"},
        )
    except Exception as exc:
        return ToolResult(
            ok=False,
            content=f"Command execution error: {exc}",
            is_error=True,
            metadata={"error_type": "execution"},
        )


# --- CanonicalTool definition ---

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
