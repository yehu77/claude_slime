"""Tests for Step A shared process execution primitives."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from pycodeagent.tools.families import build_claude_canonical_registry
from pycodeagent.tools.process_exec import (
    ProcessExecError,
    ProcessExecRequest,
    SharedProcessExecutor,
)
from pycodeagent.tools.profile_factory import build_native_claude_profile


def _wait_for_terminal_status(
    executor: SharedProcessExecutor,
    task_id: str,
    *,
    timeout_seconds: float = 3.0,
):
    deadline = time.monotonic() + timeout_seconds
    last_status = executor.get_background_status(task_id)
    while time.monotonic() < deadline:
        last_status = executor.get_background_status(task_id)
        if last_status.state != "running":
            return last_status
        time.sleep(0.02)
    pytest.fail(f"Background task {task_id} did not finish in time: {last_status}")


class TestSharedProcessExecutorForeground:
    def test_run_foreground_captures_stdout_stderr_exit_code_and_duration(self, tmp_path: Path):
        executor = SharedProcessExecutor()
        request = ProcessExecRequest(
            command="printf 'hello stdout'; printf 'hello stderr' >&2",
            cwd=tmp_path,
        )

        result = executor.run_foreground(request)

        assert result.stdout == "hello stdout"
        assert result.stderr == "hello stderr"
        assert result.exit_code == 0
        assert result.duration_ms >= 0
        assert result.timed_out is False
        assert result.spawn_error is None

    def test_run_foreground_honors_cwd(self, tmp_path: Path):
        workspace = tmp_path / "nested"
        workspace.mkdir()
        executor = SharedProcessExecutor()
        request = ProcessExecRequest(command="pwd", cwd=workspace)

        result = executor.run_foreground(request)

        assert result.exit_code == 0
        assert result.stdout.strip() == str(workspace.resolve())

    def test_run_foreground_honors_login_flag_in_shell_argv(self, tmp_path: Path):
        log_path = tmp_path / "argv.log"
        fake_shell = tmp_path / "fake_shell.sh"
        fake_shell.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$@\" > '{log_path}'\n",
            encoding="utf-8",
        )
        fake_shell.chmod(0o755)

        executor = SharedProcessExecutor()
        request = ProcessExecRequest(
            command="echo ignored",
            cwd=tmp_path,
            shell=str(fake_shell),
            login=True,
        )

        result = executor.run_foreground(request)

        assert result.exit_code == 0
        assert log_path.read_text(encoding="utf-8").splitlines() == [
            "-lc",
            "echo ignored",
        ]

    def test_run_foreground_truncates_streams_independently(self, tmp_path: Path):
        executor = SharedProcessExecutor()
        request = ProcessExecRequest(
            command="printf '123456789'; printf 'abcdefghi' >&2",
            cwd=tmp_path,
            output_limit_chars=5,
        )

        result = executor.run_foreground(request)

        assert result.exit_code == 0
        assert result.stdout.startswith("12345")
        assert result.stderr.startswith("abcde")
        assert result.stdout_truncated is True
        assert result.stderr_truncated is True
        assert "[truncated at 5 chars]" in result.stdout
        assert "[truncated at 5 chars]" in result.stderr

    def test_run_foreground_timeout_returns_partial_output(self, tmp_path: Path):
        executor = SharedProcessExecutor()
        request = ProcessExecRequest(
            command="printf 'before'; printf 'warn' >&2; sleep 2",
            cwd=tmp_path,
            timeout_ms=100,
        )

        result = executor.run_foreground(request)

        assert result.timed_out is True
        assert result.exit_code is None
        assert result.stdout == "before"
        assert result.stderr == "warn"
        assert result.duration_ms >= 0

    def test_run_foreground_spawn_failure_populates_spawn_error(self, tmp_path: Path):
        executor = SharedProcessExecutor()
        request = ProcessExecRequest(
            command="echo unreachable",
            cwd=tmp_path,
            shell=str(tmp_path / "does_not_exist"),
        )

        result = executor.run_foreground(request)

        assert result.spawn_error is not None
        assert result.exit_code is None
        assert result.stdout == ""
        assert result.stderr == ""


class TestSharedProcessExecutorBackground:
    def test_run_background_returns_handle_and_persists_merged_output(self, tmp_path: Path):
        artifact_root = tmp_path / "artifacts"
        executor = SharedProcessExecutor()
        request = ProcessExecRequest(
            command="printf 'hello'; printf ' world' >&2",
            cwd=tmp_path,
            timeout_ms=500,
        )

        handle = executor.run_background(request, artifact_root=artifact_root)
        status = _wait_for_terminal_status(executor, handle.task_id)

        assert handle.task_id == "bg_000001"
        assert handle.output_path == artifact_root / "background_tasks" / "bg_000001.log"
        assert handle.output_path.exists()
        assert status.state == "completed"
        assert status.exit_code == 0
        assert status.finished_at_ms is not None
        assert status.duration_ms is not None
        assert handle.output_path.read_text(encoding="utf-8") == "hello world"

    def test_run_background_uses_fallback_temp_root_without_artifact_root(self, tmp_path: Path):
        executor = SharedProcessExecutor()
        request = ProcessExecRequest(
            command="printf 'fallback output'",
            cwd=tmp_path,
            timeout_ms=500,
        )

        handle = executor.run_background(request)
        status = _wait_for_terminal_status(executor, handle.task_id)

        expected_root = Path(tempfile.gettempdir()) / "pycodeagent-process-tasks"
        assert handle.output_path.parent == expected_root
        assert status.state == "completed"
        assert handle.output_path.read_text(encoding="utf-8") == "fallback output"

    def test_run_background_timeout_transitions_to_timed_out(self, tmp_path: Path):
        artifact_root = tmp_path / "artifacts"
        executor = SharedProcessExecutor()
        request = ProcessExecRequest(
            command="printf 'start'; sleep 2",
            cwd=tmp_path,
            timeout_ms=100,
        )

        handle = executor.run_background(request, artifact_root=artifact_root)
        status = _wait_for_terminal_status(executor, handle.task_id)

        assert status.state == "timed_out"
        assert status.finished_at_ms is not None
        assert status.duration_ms is not None
        assert status.error_message == "Command timed out after 100ms"
        assert "start" in handle.output_path.read_text(encoding="utf-8")

    def test_run_background_spawn_failure_raises_process_exec_error(self, tmp_path: Path):
        executor = SharedProcessExecutor()
        request = ProcessExecRequest(
            command="echo unreachable",
            cwd=tmp_path / "missing_dir",
        )

        with pytest.raises(ProcessExecError, match="Failed to start background process"):
            executor.run_background(request, artifact_root=tmp_path)

    def test_get_background_status_unknown_task_raises_process_exec_error(self, tmp_path: Path):
        executor = SharedProcessExecutor()

        with pytest.raises(ProcessExecError, match="Unknown background task"):
            executor.get_background_status("bg_999999")


class TestSharedProcessExecutorLiveSessions:
    def test_start_session_returns_session_id_and_poll_completes(self, tmp_path: Path):
        executor = SharedProcessExecutor()
        request = ProcessExecRequest(
            command="printf 'hello'; sleep 0.2",
            cwd=tmp_path,
        )

        start = executor.start_session(request, yield_time_ms=10)

        assert start.session_id is not None
        assert start.exit_code is None
        assert start.stdout == "hello"

        follow = executor.write_session_stdin(
            start.session_id,
            yield_time_ms=1000,
        )

        assert follow.exit_code == 0
        assert follow.session_id is None
        assert follow.stdout == ""

    def test_write_session_stdin_with_tty_input_can_finish_interactive_command(
        self,
        tmp_path: Path,
    ):
        executor = SharedProcessExecutor()
        request = ProcessExecRequest(
            command="IFS= read -r line; printf '%s' \"$line\"",
            cwd=tmp_path,
            tty=True,
        )

        start = executor.start_session(request, yield_time_ms=10)

        assert start.session_id is not None
        assert start.exit_code is None

        follow = executor.write_session_stdin(
            start.session_id,
            chars="hello\n",
            yield_time_ms=1000,
        )

        assert follow.exit_code == 0
        assert follow.session_id is None
        assert follow.stdout == "hello"

    def test_write_session_stdin_rejects_non_tty_input(self, tmp_path: Path):
        executor = SharedProcessExecutor()
        request = ProcessExecRequest(
            command="sleep 0.2",
            cwd=tmp_path,
        )

        start = executor.start_session(request, yield_time_ms=10)

        assert start.session_id is not None
        with pytest.raises(
            ProcessExecError,
            match="stdin is closed for non-tty sessions",
        ):
            executor.write_session_stdin(start.session_id, chars="hello")


class TestSharedProcessExecutorArchitectureBoundary:
    def test_shared_process_executor_is_not_registered_as_canonical_tool(self):
        registry = build_claude_canonical_registry()

        assert registry.has("process_exec") is False
        assert {tool.canonical_name for tool in registry.list()}.isdisjoint(
            {"process_exec", "shared_process_executor"}
        )

    def test_shared_process_executor_is_not_model_visible_in_native_profile(self):
        profile = build_native_claude_profile()
        exposed_names = {spec["name"] for spec in profile.get_exposed_specs()}

        assert exposed_names.isdisjoint({"process_exec", "shared_process_executor"})
