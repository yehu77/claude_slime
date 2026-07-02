"""Tests for Step B family-specific shell runtimes."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import GenerateResponse, ToolCallCandidate
from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.agent.runner import run_agent_task
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.tools.families import build_claude_canonical_registry
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.process_exec import ProcessExecResult, SharedProcessExecutor
from pycodeagent.tools.profile_factory import build_native_claude_profile
from pycodeagent.tools.registry import ToolRegistry
from pycodeagent.tools.runtime import ToolRuntime
from pycodeagent.tools.shell_runtimes import (
    ClaudeShellRuntime,
    CodexShellRuntime,
    CodexWriteStdinRuntime,
)
from pycodeagent.tools.spec import CanonicalTool, ToolProfile, ToolView
from pycodeagent.trajectory.schema import RunStatus, ToolCall, Trajectory


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


def _make_ctx(workspace_root: Path, *, artifact_root: Path | None = None) -> ToolContext:
    return ToolContext(workspace_root=workspace_root, artifact_root=artifact_root)


def _make_fake_shell(log_path: Path) -> Path:
    shell_path = log_path.parent / f"{log_path.stem}_shell.sh"
    shell_path.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > '{log_path}'\n",
        encoding="utf-8",
    )
    shell_path.chmod(0o755)
    return shell_path


def _native_response(
    *,
    assistant_text: str = "",
    call_id: str | None = None,
    name: str | None = None,
    arguments: dict | None = None,
    finish_reason: str = "tool_calls",
) -> GenerateResponse:
    tool_calls: list[ToolCallCandidate] = []
    if name is not None:
        tool_calls.append(
            ToolCallCandidate(
                call_id=call_id,
                name=name,
                arguments_raw=None if arguments is None else __import__("json").dumps(arguments),
                arguments_obj=arguments or {},
                source="native",
            )
        )
    return GenerateResponse.from_native_tool_calling(
        assistant_text=assistant_text,
        tool_calls=tool_calls,
        finish_reason=finish_reason if tool_calls else "stop",
    )


class _SpawnErrorExecutor:
    def run_foreground(self, request):  # pragma: no cover - signature-only stub
        return ProcessExecResult(
            stdout="",
            stderr="",
            exit_code=None,
            duration_ms=0,
            spawn_error="boom",
        )


class _UnexpectedErrorExecutor:
    def run_foreground(self, request):  # pragma: no cover - signature-only stub
        raise RuntimeError("kaboom")


class TestClaudeShellRuntime:
    def test_foreground_success_returns_deterministic_content_and_metadata(
        self,
        tmp_path: Path,
    ):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        runtime = ClaudeShellRuntime()

        result = runtime.execute_bash(
            "printf 'hello'; printf 'warn' >&2",
            ctx=_make_ctx(workspace),
        )

        assert result.ok is True
        assert result.is_error is False
        assert result.content == "[stdout]\nhello\n[stderr]\nwarn\n[exit code] 0"
        assert result.metadata["operation"] == "claude_bash"
        assert result.metadata["execution_kind"] == "command_exec"
        assert result.metadata["command_family"] == "claude_bash"
        assert result.metadata["run_in_background"] is False
        assert result.metadata["timeout_ms"] == 60_000
        assert result.metadata["shell"] == "bash"
        assert result.metadata["login"] is False
        assert result.metadata["resolved_cwd"] == str(workspace.resolve())

    def test_foreground_timeout_returns_timeout_error(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        runtime = ClaudeShellRuntime()

        result = runtime.execute_bash(
            "printf 'before'; sleep 2",
            timeout=50,
            ctx=_make_ctx(workspace),
        )

        assert result.ok is False
        assert result.is_error is True
        assert result.metadata["error_type"] == "timeout"
        assert result.metadata["stage"] == "execute"
        assert "before" in result.content
        assert "Command timed out after 50ms" in result.content

    def test_invalid_timeout_returns_structured_error(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        runtime = ClaudeShellRuntime()

        result = runtime.execute_bash(
            "echo ignored",
            timeout=0,
            ctx=_make_ctx(workspace),
        )

        assert result.ok is False
        assert result.is_error is True
        assert result.metadata["error_type"] == "invalid_timeout"
        assert result.metadata["stage"] == "validate_input"
        assert result.metadata["requested_timeout"] == 0

    def test_missing_context_returns_structured_error_for_foreground_and_background(self):
        runtime = ClaudeShellRuntime()

        foreground = runtime.execute_bash("echo ignored")
        background = runtime.execute_bash("echo ignored", run_in_background=True)

        assert foreground.ok is False
        assert foreground.is_error is True
        assert foreground.metadata["error_type"] == "missing_context"
        assert foreground.metadata["stage"] == "context_check"
        assert foreground.metadata["execution_kind"] == "command_exec"

        assert background.ok is False
        assert background.is_error is True
        assert background.metadata["error_type"] == "missing_context"
        assert background.metadata["stage"] == "context_check"
        assert background.metadata["execution_kind"] == "command_background"

    def test_background_execution_writes_under_artifact_root(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        artifact_root = tmp_path / "artifacts"
        workspace.mkdir()
        executor = SharedProcessExecutor()
        runtime = ClaudeShellRuntime(executor)

        result = runtime.execute_bash(
            "printf 'hello'; printf ' world' >&2",
            run_in_background=True,
            ctx=_make_ctx(workspace, artifact_root=artifact_root),
        )

        assert result.ok is True
        task_id = result.metadata["background_task_id"]
        output_path = Path(result.metadata["background_output_path"])
        status = _wait_for_terminal_status(executor, task_id)

        assert output_path == artifact_root / "background_tasks" / f"{task_id}.log"
        assert output_path.exists()
        assert status.state == "completed"
        assert output_path.read_text(encoding="utf-8") == "hello world"
        assert result.metadata["operation"] == "claude_bash"
        assert result.metadata["execution_kind"] == "command_background"
        assert result.metadata["run_in_background"] is True
        assert str(output_path) in result.content

    def test_shell_uses_real_shell_syntax_not_argv_parsing(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        runtime = ClaudeShellRuntime()

        result = runtime.execute_bash(
            "printf 'abc' | tr '[:lower:]' '[:upper:]'",
            ctx=_make_ctx(workspace),
        )

        assert result.ok is True
        assert "[stdout]\nABC" in result.content
        assert result.metadata["shell"] == "bash"

    def test_spawn_failures_become_structured_tool_results(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        runtime = ClaudeShellRuntime(_SpawnErrorExecutor())

        result = runtime.execute_bash("echo ignored", ctx=_make_ctx(workspace))

        assert result.ok is False
        assert result.is_error is True
        assert result.metadata["error_type"] == "execution"
        assert result.metadata["stage"] == "execute"
        assert result.metadata["spawn_error"] == "boom"
        assert "boom" in result.content

    def test_unexpected_executor_errors_become_structured_tool_results(
        self,
        tmp_path: Path,
    ):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        runtime = ClaudeShellRuntime(_UnexpectedErrorExecutor())

        result = runtime.execute_bash("echo ignored", ctx=_make_ctx(workspace))

        assert result.ok is False
        assert result.is_error is True
        assert result.metadata["error_type"] == "execution"
        assert result.metadata["unexpected_error"] == "kaboom"
        assert "kaboom" in result.content


class TestCodexShellRuntime:
    def test_missing_context_returns_structured_error(self):
        runtime = CodexShellRuntime()

        result = runtime.execute_command("echo ignored")

        assert result.ok is False
        assert result.is_error is True
        assert result.metadata["error_type"] == "missing_context"
        assert result.metadata["stage"] == "context_check"
        assert result.metadata["execution_kind"] == "command_exec"
    def test_workdir_resolves_inside_workspace_and_invalid_workdir_is_rejected(
        self,
        tmp_path: Path,
    ):
        workspace = tmp_path / "workspace"
        subdir = workspace / "src"
        subdir.mkdir(parents=True)
        runtime = CodexShellRuntime()
        ctx = _make_ctx(workspace)

        ok_result = runtime.execute_command("pwd", workdir="src", ctx=ctx)

        assert ok_result.ok is True
        assert str(subdir.resolve()) in ok_result.content
        assert ok_result.metadata["resolved_cwd"] == str(subdir.resolve())
        assert ok_result.metadata["operation"] == "codex_exec_command"

        bad_result = runtime.execute_command("pwd", workdir="..", ctx=ctx)

        assert bad_result.ok is False
        assert bad_result.is_error is True
        assert bad_result.metadata["stage"] == "validate_cwd"
        assert bad_result.metadata["error_type"] == "workspace_escape"
        assert bad_result.metadata["requested_workdir"] == ".."

    def test_default_login_true_and_explicit_false_change_shell_argv(
        self,
        tmp_path: Path,
    ):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        runtime = CodexShellRuntime()
        ctx = _make_ctx(workspace)

        default_log = tmp_path / "default.log"
        default_shell = _make_fake_shell(default_log)
        default_result = runtime.execute_command(
            "echo ignored",
            shell=str(default_shell),
            ctx=ctx,
        )

        explicit_log = tmp_path / "explicit.log"
        explicit_shell = _make_fake_shell(explicit_log)
        explicit_result = runtime.execute_command(
            "echo ignored",
            shell=str(explicit_shell),
            login=False,
            ctx=ctx,
        )

        assert default_result.ok is True
        assert default_log.read_text(encoding="utf-8").splitlines() == [
            "-lc",
            "echo ignored",
        ]
        assert default_result.metadata["login"] is True
        assert default_result.metadata["shell"] == str(default_shell)

        assert explicit_result.ok is True
        assert explicit_log.read_text(encoding="utf-8").splitlines() == [
            "-c",
            "echo ignored",
        ]
        assert explicit_result.metadata["login"] is False
        assert explicit_result.metadata["shell"] == str(explicit_shell)

    def test_custom_shell_is_passed_through_to_executor(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        runtime = CodexShellRuntime()
        ctx = _make_ctx(workspace)
        log_path = tmp_path / "shell.log"
        custom_shell = _make_fake_shell(log_path)

        result = runtime.execute_command(
            "echo ignored",
            shell=str(custom_shell),
            ctx=ctx,
        )

        assert result.ok is True
        assert log_path.exists()
        assert result.metadata["shell"] == str(custom_shell)
        assert result.metadata["command_family"] == "codex_exec_command"

    def test_spawn_failures_become_structured_tool_results(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        runtime = CodexShellRuntime()

        result = runtime.execute_command(
            "echo ignored",
            shell=str(tmp_path / "does_not_exist"),
            ctx=_make_ctx(workspace),
        )

        assert result.ok is False
        assert result.is_error is True
        assert result.metadata["error_type"] == "execution"
        assert result.metadata["stage"] == "execute"


class TestCodexWriteStdinRuntime:
    def test_invalid_session_id_returns_structured_error(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        runtime = CodexWriteStdinRuntime()

        result = runtime.write_stdin(0, ctx=_make_ctx(workspace))

        assert result.ok is False
        assert result.is_error is True
        assert result.metadata["error_type"] == "invalid_session_id"
        assert result.metadata["stage"] == "validate_input"

    def test_write_stdin_can_continue_live_session(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        executor = SharedProcessExecutor()
        shell_runtime = CodexShellRuntime(executor)
        stdin_runtime = CodexWriteStdinRuntime(executor)
        ctx = _make_ctx(workspace)

        start = shell_runtime.execute_command(
            "IFS= read -r line; printf '%s' \"$line\"",
            tty=True,
            yield_time_ms=50,
            ctx=ctx,
        )

        assert start.ok is True
        assert start.metadata["session_id"] is not None
        assert start.metadata["exit_code"] is None

        follow = stdin_runtime.write_stdin(
            start.metadata["session_id"],
            chars="hello\n",
            yield_time_ms=500,
            ctx=ctx,
        )

        assert follow.ok is True
        assert follow.content == "[stdout]\nhello\n[exit code] 0"
        assert follow.metadata["operation"] == "codex_write_stdin"
        assert follow.metadata["command_family"] == "codex_write_stdin"
        assert follow.metadata["exit_code"] == 0
        assert follow.metadata["chars_written"] == 6
        assert follow.metadata["poll_only"] is False


class TestShellRuntimeCompatibility:
    def test_tool_context_accepts_artifact_root(self, tmp_path: Path):
        artifact_root = tmp_path / "artifacts"
        ctx = ToolContext(workspace_root=tmp_path, artifact_root=artifact_root)

        assert ctx.artifact_root == artifact_root

    def test_run_coding_task_populates_artifact_root_from_output_dir(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        repo = tmp_path / "repo"
        output_dir = tmp_path / "run_output"
        repo.mkdir()
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        task = CodingTask(
            task_id="task_artifact_root",
            repo_path=repo,
            prompt="noop",
            test_command="true",
            max_turns=1,
        )
        profile = build_native_claude_profile()
        runtime = ToolRuntime(build_claude_canonical_registry())
        captured: dict[str, Path | None] = {}

        def _fake_run_agent_task(task, client, runtime, profile, ctx, **kwargs):
            captured["artifact_root"] = ctx.artifact_root
            return Trajectory(
                task_id=task.task_id,
                repo=str(task.repo_path),
                tool_profile_id=profile.profile_id,
                status=RunStatus.COMPLETED,
            )

        monkeypatch.setattr("pycodeagent.agent.runner.run_agent_task", _fake_run_agent_task)

        run_coding_task(
            task,
            FakeLLMClient([]),
            output_dir,
            profile=profile,
            runtime=runtime,
            tool_stack_kind="native_claude",
        )

        assert captured["artifact_root"] == output_dir.resolve()

    def test_runtime_metadata_survives_tool_runtime_execution(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        shell_runtime = ClaudeShellRuntime()
        schema = {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "number"},
                "run_in_background": {"type": "boolean"},
            },
            "required": ["command"],
            "additionalProperties": False,
        }
        registry = ToolRegistry()
        registry.register(
            CanonicalTool(
                canonical_name="claude_shell_runtime_test",
                description="Temporary Claude shell runtime wrapper.",
                canonical_schema=schema,
                handler=shell_runtime.execute_bash,
            )
        )
        profile = ToolProfile(
            profile_id="runtime_shell_smoke",
            tools=[
                ToolView(
                    canonical_name="claude_shell_runtime_test",
                    exposed_name="Bash",
                    description="Temporary Bash wrapper.",
                    input_schema=schema,
                )
            ],
        )
        runtime = ToolRuntime(registry)
        call = ToolCall(
            id="call_1",
            name="Bash",
            arguments={"command": "printf 'hi'"},
        )

        result = runtime.execute(call, profile, ctx=_make_ctx(workspace))

        assert result.ok is True
        assert result.metadata["operation"] == "claude_bash"
        assert result.metadata["command_family"] == "claude_bash"
        assert result.metadata["execution_kind"] == "command_exec"

    def test_runtime_metadata_survives_agent_trajectory(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        shell_runtime = ClaudeShellRuntime()
        schema = {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "number"},
                "run_in_background": {"type": "boolean"},
            },
            "required": ["command"],
            "additionalProperties": False,
        }
        registry = ToolRegistry()
        registry.register(
            CanonicalTool(
                canonical_name="claude_shell_runtime_traj_test",
                description="Temporary Claude shell runtime trajectory wrapper.",
                canonical_schema=schema,
                handler=shell_runtime.execute_bash,
            )
        )
        profile = ToolProfile(
            profile_id="runtime_shell_traj_smoke",
            tools=[
                ToolView(
                    canonical_name="claude_shell_runtime_traj_test",
                    exposed_name="Bash",
                    description="Temporary Bash wrapper.",
                    input_schema=schema,
                )
            ],
        )
        runtime = ToolRuntime(registry)
        task = CodingTask(
            task_id="runtime_shell_traj_smoke",
            repo_path=workspace,
            prompt="Run Bash once.",
            max_turns=2,
        )
        client = FakeLLMClient(
            [
                _native_response(
                    assistant_text="Running Bash.",
                    call_id="c1",
                    name="Bash",
                    arguments={"command": "printf 'hi'"},
                ),
                _native_response(assistant_text="Done."),
            ]
        )

        trajectory = run_agent_task(task, client, runtime, profile, _make_ctx(workspace))

        assert trajectory.tool_calls[0].canonical_name == "claude_shell_runtime_traj_test"
        assert trajectory.observations[0].result.metadata["operation"] == "claude_bash"
        assert trajectory.observations[0].result.metadata["command_family"] == "claude_bash"

    def test_native_claude_registry_and_profile_expose_claude_tools(self):
        registry = build_claude_canonical_registry()
        profile = build_native_claude_profile()
        canonical_names = {tool.canonical_name for tool in registry.list()}
        exposed_names = {spec["name"] for spec in profile.get_exposed_specs()}

        assert canonical_names == {"Bash", "Read", "Edit", "Write", "Grep", "Glob"}
        assert exposed_names == {"Bash", "Read", "Edit", "Write", "Grep", "Glob"}
