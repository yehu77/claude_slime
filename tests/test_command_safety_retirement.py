"""RC-038 regression gates for retiring the inactive command policy."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.families.codex import build_codex_canonical_tools
from pycodeagent.tools.shell_runtimes import CodexShellRuntime


pytestmark = pytest.mark.mainline

ROOT = Path(__file__).resolve().parents[1]


def _context(workspace: Path) -> ToolContext:
    return ToolContext(workspace_root=workspace)


def test_legacy_command_safety_module_and_imports_are_absent() -> None:
    assert not (ROOT / "pycodeagent/tools/command_safety.py").exists()

    remaining = []
    for path in (ROOT / "pycodeagent").rglob("*.py"):
        if "command_safety" in path.read_text(encoding="utf-8"):
            remaining.append(path.relative_to(ROOT).as_posix())
    assert remaining == []


def test_workspace_cwd_rejection_survives_retirement(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = CodexShellRuntime()

    result = runtime.execute_command(
        "pwd",
        workdir="..",
        ctx=_context(workspace),
    )

    assert result.ok is False
    assert result.is_error is True
    assert result.metadata["stage"] == "validate_cwd"
    assert result.metadata["error_type"] == "workspace_escape"
    assert result.metadata["policy_decision"] == "deny"


def test_current_commands_are_not_filtered_by_the_retired_allowlist(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = CodexShellRuntime()
    command = " ".join(
        [
            shlex.quote(sys.executable),
            "-c",
            shlex.quote("print('policy-retirement-ok')"),
        ]
    )

    result = runtime.execute_command(
        command,
        login=False,
        yield_time_ms=30_000,
        ctx=_context(workspace),
    )

    assert result.ok is True
    assert "policy-retirement-ok" in result.content
    assert result.metadata["policy_decision"] == "allow"
    assert result.metadata["execution_stage"] == "result_finalize"


def test_requested_permission_fields_remain_observations_not_enforcement(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    exec_command = {
        tool.canonical_name: tool
        for tool in build_codex_canonical_tools()
    }["exec_command"]

    result = exec_command.handler(
        cmd="printf requested-permission-is-metadata",
        login=False,
        yield_time_ms=30_000,
        sandbox_permissions="require_escalated",
        justification="synthetic metadata boundary check",
        prefix_rule=["printf"],
        ctx=_context(workspace),
    )

    assert result.ok is True
    assert "requested-permission-is-metadata" in result.content
    assert result.metadata["requested_sandbox_permissions"] == "require_escalated"
    assert result.metadata["requested_justification"] == (
        "synthetic metadata boundary check"
    )
    assert result.metadata["requested_prefix_rule"] == ["printf"]
    assert "effective_sandbox_permissions" not in result.metadata


def test_retirement_decision_is_marked_implemented() -> None:
    payload = json.loads(
        (
            ROOT
            / "docs/repository_cleanup/command_policy_decision.json"
        ).read_text(encoding="utf-8")
    )

    assert payload["decision"] == "delete_legacy_implementation"
    assert payload["implementation_goal"] == "RC-038"
    assert payload["implementation_status"] == "completed"
