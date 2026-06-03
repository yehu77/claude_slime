"""Minimal verifier for coding tasks.

Runs the task's test_command inside the workspace and returns a VerifyResult.
Uses subprocess directly rather than the agent's run_command tool, because:

1. The agent's run_command has a strict command allowlist designed to prevent
   model-initiated host access. The verifier is a system-level operation, not
   a model-controlled action, so it should not be constrained by that policy.
2. The verifier needs to run arbitrary test commands (for example ``pytest -q``
   or ``python -m pytest``) reliably, including commands outside the agent's
   allowlist.

This verifier does not implement hidden tests, lint/type-check combinations,
forbidden file modification checks, or diff sanity checks.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pycodeagent.env.command_exec import parse_command_argv
from pycodeagent.env.task import CodingTask
from pycodeagent.trajectory.schema import VerifyResult

_DEFAULT_TIMEOUT = 120  # seconds
_MAX_OUTPUT_CHARS = 100_000


def _trunc(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated at {limit} chars]"


def run_verifier(
    task: CodingTask,
    workspace_root: Path,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
) -> VerifyResult:
    """Run the task's test command inside the workspace.

    Args:
        task: The coding task whose test_command to run.
        workspace_root: The workspace directory to run tests in.
        timeout: Maximum seconds to wait for the test command.

    Returns:
        VerifyResult with pass/fail status and captured output.
    """
    workspace_root = workspace_root.resolve()

    if not workspace_root.exists():
        return VerifyResult(
            passed=False,
            score=0.0,
            stdout="",
            stderr=f"Workspace does not exist: {workspace_root}",
        )

    try:
        argv = parse_command_argv(task.test_command, field_name="test_command")
    except ValueError as exc:
        return VerifyResult(
            passed=False,
            score=0.0,
            stdout="",
            stderr=f"Invalid test_command: {exc}",
        )

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workspace_root,
        )
        passed = proc.returncode == 0
        return VerifyResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            stdout=_trunc(proc.stdout),
            stderr=_trunc(proc.stderr),
        )

    except subprocess.TimeoutExpired:
        return VerifyResult(
            passed=False,
            score=0.0,
            stdout="",
            stderr=f"Test command timed out after {timeout}s",
        )
    except FileNotFoundError as exc:
        return VerifyResult(
            passed=False,
            score=0.0,
            stdout="",
            stderr=f"Test command executable not found: {exc}",
        )
    except Exception as exc:
        return VerifyResult(
            passed=False,
            score=0.0,
            stdout="",
            stderr=f"Verifier execution error: {exc}",
        )
