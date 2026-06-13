"""Focused tests for shared command safety helpers and metadata."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.tools.builtin.bash import _run_command_handler
from pycodeagent.tools.builtin.python_run import _python_run_handler
from pycodeagent.tools.command_safety import classify_command_argv, run_subprocess
from pycodeagent.tools.context import ToolContext


_TEST_NAMESPACE = "command_safety"


def _make_workspace(files: dict[str, str] | None = None) -> Path:
    workspace = make_unique_test_dir(_TEST_NAMESPACE)
    if files:
        for rel_path, content in files.items():
            target = workspace / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    return workspace


class TestCommandClassification:
    def test_blocked_executable_marked_dangerous(self):
        decision = classify_command_argv(["python", "script.py"])
        assert decision.allowed is False
        assert decision.command_family == "python"
        assert decision.dangerous is True
        assert "blocked executable" in str(decision.policy_reason)

    def test_unknown_executable_denied_not_marked_dangerous(self):
        decision = classify_command_argv(["custom_tool", "--help"])
        assert decision.allowed is False
        assert decision.command_family == "custom_tool"
        assert decision.dangerous is False

    def test_git_write_subcommand_denied_and_dangerous(self):
        decision = classify_command_argv(["git", "push"])
        assert decision.allowed is False
        assert decision.command_family == "git"
        assert decision.dangerous is True
        assert decision.policy_reason == "git subcommand not allowed: 'push'"


class TestSharedExecutionHelper:
    def test_run_subprocess_reports_truncation_and_duration(self):
        workspace = _make_workspace()
        try:
            result = run_subprocess(
                [sys.executable, "-c", "print('x' * 100)"],
                cwd=workspace,
                timeout=5,
                output_limit=20,
            )
            assert result.completed is True
            assert result.exit_code == 0
            assert result.stdout_truncated is True
            assert result.stderr_truncated is False
            assert "... [truncated at 20 chars]" in result.stdout
            assert isinstance(result.duration_ms, int)
        finally:
            cleanup_test_path(workspace)


class TestCommandMetadata:
    def test_run_command_rejection_metadata_is_stable(self):
        workspace = _make_workspace()
        try:
            result = _run_command_handler(
                command="python script.py",
                ctx=ToolContext(workspace_root=workspace),
            )
            assert result.is_error
            assert result.metadata["error_type"] == "command_policy"
            assert result.metadata["operation"] == "run_command"
            assert result.metadata["requested_cwd"] is None
            assert result.metadata["stage"] == "policy_check"
            assert result.metadata["policy_domain"] == "command"
            assert result.metadata["policy_decision"] == "deny"
            assert result.metadata["dangerous"] is True
            assert result.metadata["command_family"] == "python"
            assert result.metadata["parsed_executable"] == "python"
            assert result.metadata["arg_count"] == 1
            assert "blocked executable" in str(result.metadata["policy_reason"])
        finally:
            cleanup_test_path(workspace)

    def test_python_run_invalid_module_metadata_is_stable(self):
        workspace = _make_workspace()
        try:
            result = _python_run_handler(
                target="pip",
                run_as_module=True,
                ctx=ToolContext(workspace_root=workspace),
            )
            assert result.is_error
            assert result.metadata["error_type"] == "invalid_module"
            assert result.metadata["operation"] == "python_run"
            assert result.metadata["requested_cwd"] is None
            assert result.metadata["stage"] == "validate_target"
            assert result.metadata["policy_domain"] == "command"
            assert result.metadata["policy_decision"] == "deny"
            assert result.metadata["dangerous"] is False
            assert result.metadata["command_family"] == "python_module"
            assert result.metadata["target_kind"] == "module"
            assert result.metadata["policy_reason"] == "module target not allowed: 'pip'"
        finally:
            cleanup_test_path(workspace)

    def test_python_run_timeout_metadata_uses_shared_execution_contract(self):
        workspace = _make_workspace({"sleepy.py": "import time\ntime.sleep(2)\n"})
        try:
            result = _python_run_handler(
                target="sleepy.py",
                timeout=1,
                ctx=ToolContext(workspace_root=workspace),
            )
            assert result.is_error
            assert result.metadata["error_type"] == "timeout"
            assert result.metadata["operation"] == "python_run"
            assert result.metadata["requested_cwd"] is None
            assert result.metadata["stage"] == "execute"
            assert result.metadata["policy_domain"] == "command"
            assert result.metadata["policy_decision"] == "allow"
            assert result.metadata["dangerous"] is False
            assert result.metadata["command_family"] == "python_script"
            assert result.metadata["execution_kind"] == "script"
            assert result.metadata["target_kind"] == "script_path"
            assert result.metadata["timeout_sec"] == 1
            assert isinstance(result.metadata["duration_ms"], int)
        finally:
            cleanup_test_path(workspace)
