"""Tests for strict Step C family-aware canonical tools."""

from __future__ import annotations

from pathlib import Path

from pycodeagent.agent.llm_client import FakeLLMClient, GenerateResponse, ToolCallCandidate
from pycodeagent.agent.runner import run_agent_task
from pycodeagent.env.task import CodingTask
from pycodeagent.rl.serializer import serialize_trajectory
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.contracts import ToolContractKind
from pycodeagent.tools.families import (
    build_claude_canonical_registry,
    build_claude_canonical_tools,
    build_codex_canonical_registry,
    build_codex_canonical_tools,
)
from pycodeagent.tools.profile_factory import (
    build_native_claude_profile,
    build_native_codex_profile,
)
from pycodeagent.tools.runtime import ToolRuntime
from pycodeagent.trajectory.schema import ToolCall, ToolResult


def _make_ctx(workspace_root: Path) -> ToolContext:
    return ToolContext(workspace_root=workspace_root)


def _native_response(
    *,
    assistant_text: str = "",
    call_id: str | None = None,
    name: str | None = None,
    arguments: dict | None = None,
    input_text: str | None = None,
) -> GenerateResponse:
    tool_calls: list[ToolCallCandidate] = []
    if name is not None:
        tool_calls.append(
            ToolCallCandidate(
                call_id=call_id,
                name=name,
                arguments_raw=None if arguments is None else __import__("json").dumps(arguments),
                arguments_obj=arguments,
                input_text=input_text,
                source="native",
            )
        )
    return GenerateResponse.from_native_tool_calling(
        assistant_text=assistant_text,
        tool_calls=tool_calls,
        finish_reason="tool_calls" if tool_calls else "stop",
    )


class _RecordingClaudeShellRuntime:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute_bash(
        self,
        command: str,
        timeout=None,
        run_in_background: bool = False,
        *,
        ctx=None,
    ) -> ToolResult:
        self.calls.append(
            {
                "command": command,
                "timeout": timeout,
                "run_in_background": run_in_background,
                "ctx": ctx,
            }
        )
        return ToolResult(
            ok=True,
            content="claude-shell-ok",
            metadata={
                "operation": "claude_bash",
                "command_family": "claude_bash",
            },
        )


class _RecordingCodexShellRuntime:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute_command(
        self,
        cmd: str,
        workdir=None,
        shell=None,
        login=None,
        tty=None,
        yield_time_ms=None,
        max_output_tokens=None,
        *,
        ctx=None,
    ) -> ToolResult:
        self.calls.append(
            {
                "cmd": cmd,
                "workdir": workdir,
                "shell": shell,
                "login": login,
                "tty": tty,
                "yield_time_ms": yield_time_ms,
                "max_output_tokens": max_output_tokens,
                "ctx": ctx,
            }
        )
        return ToolResult(
            ok=True,
            content="codex-shell-ok",
            metadata={
                "operation": "codex_exec_command",
                "command_family": "codex_exec_command",
                "session_id": 7,
            },
        )


class _RecordingCodexWriteStdinRuntime:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def write_stdin(
        self,
        session_id,
        chars=None,
        yield_time_ms=None,
        max_output_tokens=None,
        *,
        ctx=None,
    ) -> ToolResult:
        self.calls.append(
            {
                "session_id": session_id,
                "chars": chars,
                "yield_time_ms": yield_time_ms,
                "max_output_tokens": max_output_tokens,
                "ctx": ctx,
            }
        )
        return ToolResult(
            ok=True,
            content="codex-stdin-ok",
            metadata={
                "operation": "codex_write_stdin",
                "command_family": "codex_write_stdin",
            },
        )


class _RecordingCodexApplyPatchRuntime:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def apply_patch(self, patch: str, *, ctx=None) -> ToolResult:
        self.calls.append({"patch": patch, "ctx": ctx})
        return ToolResult(
            ok=True,
            content="codex-patch-ok",
            metadata={
                "operation": "codex_apply_patch",
                "command_family": "codex_apply_patch",
            },
        )


def test_claude_builder_matches_strict_names_versions_and_family_metadata():
    tools = build_claude_canonical_tools()

    assert [tool.canonical_name for tool in tools] == [
        "Bash",
        "Read",
        "Edit",
        "Write",
        "Grep",
        "Glob",
    ]
    assert [tool.version for tool in tools] == [
        "Bash_v1",
        "Read_v1",
        "Edit_v1",
        "Write_v1",
        "Grep_v1",
        "Glob_v1",
    ]
    assert all(tool.metadata["family"] == "claude" for tool in tools)
    assert all(tool.contract_kind == ToolContractKind.FUNCTION for tool in tools)

    profile = build_native_claude_profile()
    specs = {spec["name"]: spec for spec in profile.get_exposed_specs()}

    assert [tool.exposed_name for tool in profile.tools] == [
        "Bash",
        "Read",
        "Edit",
        "Write",
        "Grep",
        "Glob",
    ]
    assert profile.metadata["family"] == "claude"
    assert profile.metadata["native_profile_kind"] == "native_claude"
    assert profile.metadata["profile_origin"] == "strict_family_canonical_tools"
    assert "source_catalog_id" not in profile.metadata
    assert all(tool.exposed_name == tool.canonical_name for tool in profile.tools)
    assert all(
        tool.metadata["native_profile_kind"] == "native_claude"
        for tool in profile.tools
    )
    assert all("source_catalog_id" not in tool.metadata for tool in profile.tools)
    assert "kind" not in specs["Bash"]
    assert "run_in_background" in specs["Bash"]["input_schema"]["properties"]
    assert "dangerouslyDisableSandbox" in specs["Bash"]["input_schema"]["properties"]


def test_codex_builder_matches_strict_names_versions_and_freeform_apply_patch():
    tools = build_codex_canonical_tools()
    by_name = {tool.canonical_name: tool for tool in tools}

    assert [tool.canonical_name for tool in tools] == [
        "exec_command",
        "write_stdin",
        "apply_patch",
    ]
    assert [tool.version for tool in tools] == [
        "exec_command_v1",
        "write_stdin_v1",
        "apply_patch_v1",
    ]
    assert all(tool.metadata["family"] == "codex" for tool in tools)
    assert by_name["write_stdin"].contract_kind == ToolContractKind.FUNCTION
    assert by_name["apply_patch"].contract_kind == ToolContractKind.FREEFORM
    assert by_name["apply_patch"].input_format["syntax"] == "lark"

    profile = build_native_codex_profile()
    specs = {spec["name"]: spec for spec in profile.get_exposed_specs()}

    assert [tool.exposed_name for tool in profile.tools] == [
        "exec_command",
        "write_stdin",
        "apply_patch",
    ]
    assert profile.metadata["family"] == "codex"
    assert profile.metadata["native_profile_kind"] == "native_codex"
    assert (
        profile.metadata["canonical_mapping_status"]
        == "native_identity_not_canonicalized"
    )
    assert "source_catalog_id" not in profile.metadata
    assert all(tool.exposed_name == tool.canonical_name for tool in profile.tools)
    assert all("source_catalog_id" not in tool.metadata for tool in profile.tools)
    assert profile.tools[-1].contract_kind == ToolContractKind.FREEFORM
    assert profile.tools[-1].input_format is not None
    assert specs["apply_patch"]["kind"] == "freeform"
    assert specs["apply_patch"]["input_format"]["syntax"] == "lark"
    assert "input_schema" not in specs["apply_patch"]


def test_strict_family_registries_are_separate():
    claude_registry = build_claude_canonical_registry()
    codex_registry = build_codex_canonical_registry()

    assert {tool.canonical_name for tool in claude_registry.list()} == {
        "Bash",
        "Read",
        "Edit",
        "Write",
        "Grep",
        "Glob",
    }
    assert {tool.canonical_name for tool in codex_registry.list()} == {
        "exec_command",
        "write_stdin",
        "apply_patch",
    }


def test_strict_runtime_backed_tools_delegate_to_family_runtimes(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    claude_runtime = _RecordingClaudeShellRuntime()
    codex_shell = _RecordingCodexShellRuntime()
    codex_stdin = _RecordingCodexWriteStdinRuntime()
    codex_patch = _RecordingCodexApplyPatchRuntime()

    claude_bash = build_claude_canonical_tools(shell_runtime=claude_runtime)[0]
    codex_tools = {
        tool.canonical_name: tool
        for tool in build_codex_canonical_tools(
            shell_runtime=codex_shell,
            write_stdin_runtime=codex_stdin,
            apply_patch_runtime=codex_patch,
        )
    }

    bash_result = claude_bash.handler(
        command="pwd",
        timeout=10,
        run_in_background=True,
        ctx=ctx,
    )
    exec_result = codex_tools["exec_command"].handler(
        cmd="pwd",
        workdir="src",
        tty=True,
        yield_time_ms=50,
        ctx=ctx,
    )
    stdin_result = codex_tools["write_stdin"].handler(
        session_id=7,
        chars="hello\n",
        yield_time_ms=500,
        ctx=ctx,
    )
    patch_result = codex_tools["apply_patch"].handler(
        input_text="*** Begin Patch\n*** End Patch\n",
        ctx=ctx,
    )

    assert claude_runtime.calls[0]["command"] == "pwd"
    assert claude_runtime.calls[0]["run_in_background"] is True
    assert bash_result.metadata["operation"] == "Bash"
    assert bash_result.metadata["command_family"] == "Bash"
    assert bash_result.metadata["family"] == "claude"

    assert codex_shell.calls[0]["cmd"] == "pwd"
    assert codex_shell.calls[0]["tty"] is True
    assert exec_result.metadata["operation"] == "exec_command"
    assert exec_result.metadata["command_family"] == "exec_command"
    assert exec_result.metadata["family"] == "codex"

    assert codex_stdin.calls[0]["session_id"] == 7
    assert codex_stdin.calls[0]["chars"] == "hello\n"
    assert stdin_result.metadata["operation"] == "write_stdin"
    assert stdin_result.metadata["command_family"] == "write_stdin"
    assert stdin_result.metadata["family"] == "codex"

    assert codex_patch.calls[0]["patch"].startswith("*** Begin Patch")
    assert patch_result.metadata["operation"] == "apply_patch"
    assert patch_result.metadata["command_family"] == "apply_patch"
    assert patch_result.metadata["family"] == "codex"


def test_claude_family_smoke_flow_covers_bash_read_edit_write_grep_and_glob(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    source_dir = workspace / "src"
    source_dir.mkdir(parents=True)
    target = source_dir / "app.py"
    target.write_text(
        "def add(a, b):\n    return a - b\n",
        encoding="utf-8",
    )

    registry = build_claude_canonical_registry()
    profile = build_native_claude_profile()
    runtime = ToolRuntime(registry)
    ctx = _make_ctx(workspace)

    read_result = runtime.execute(
        ToolCall(
            id="read_1",
            name="Read",
            arguments={"file_path": str(target)},
        ),
        profile,
        ctx=ctx,
    )
    grep_result = runtime.execute(
        ToolCall(
            id="grep_1",
            name="Grep",
            arguments={
                "pattern": r"return a - b",
                "path": str(workspace),
                "output_mode": "content",
            },
        ),
        profile,
        ctx=ctx,
    )
    glob_result = runtime.execute(
        ToolCall(
            id="glob_1",
            name="Glob",
            arguments={"pattern": "**/*.py", "path": str(workspace)},
        ),
        profile,
        ctx=ctx,
    )
    edit_result = runtime.execute(
        ToolCall(
            id="edit_1",
            name="Edit",
            arguments={
                "file_path": str(target),
                "old_string": "return a - b",
                "new_string": "return a + b",
            },
        ),
        profile,
        ctx=ctx,
    )
    bash_result = runtime.execute(
        ToolCall(
            id="bash_1",
            name="Bash",
            arguments={"command": "python -m py_compile src/app.py"},
        ),
        profile,
        ctx=ctx,
    )
    write_result = runtime.execute(
        ToolCall(
            id="write_1",
            name="Write",
            arguments={
                "file_path": str(workspace / "notes.txt"),
                "content": "verified\n",
            },
        ),
        profile,
        ctx=ctx,
    )

    assert read_result.ok is True
    assert read_result.metadata["operation"] == "Read"
    assert "1 | def add(a, b):" in read_result.content
    assert grep_result.ok is True
    assert "src/app.py:2:" in grep_result.content
    assert glob_result.ok is True
    assert "src/app.py" in glob_result.content
    assert edit_result.ok is True
    assert bash_result.ok is True
    assert bash_result.metadata["operation"] == "Bash"
    assert write_result.ok is True
    assert target.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "verified\n"
    assert str(target.resolve()) in ctx.tool_state["claude_read_paths"]


def test_claude_edit_and_write_enforce_read_discipline_on_existing_files(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "config.txt"
    target.write_text("old\n", encoding="utf-8")
    registry = build_claude_canonical_registry()
    profile = build_native_claude_profile()
    runtime = ToolRuntime(registry)
    ctx = _make_ctx(workspace)

    edit_without_read = runtime.execute(
        ToolCall(
            id="edit_1",
            name="Edit",
            arguments={
                "file_path": str(target),
                "old_string": "old",
                "new_string": "new",
            },
        ),
        profile,
        ctx=ctx,
    )
    write_without_read = runtime.execute(
        ToolCall(
            id="write_1",
            name="Write",
            arguments={"file_path": str(target), "content": "new\n"},
        ),
        profile,
        ctx=ctx,
    )

    assert edit_without_read.ok is False
    assert edit_without_read.metadata["error_type"] == "stale_read_state"
    assert write_without_read.ok is False
    assert write_without_read.metadata["error_type"] == "stale_read_state"

    read_result = runtime.execute(
        ToolCall(
            id="read_1",
            name="Read",
            arguments={"file_path": str(target)},
        ),
        profile,
        ctx=ctx,
    )
    write_after_read = runtime.execute(
        ToolCall(
            id="write_2",
            name="Write",
            arguments={"file_path": str(target), "content": "new\n"},
        ),
        profile,
        ctx=ctx,
    )

    assert read_result.ok is True
    assert write_after_read.ok is True
    assert target.read_text(encoding="utf-8") == "new\n"


def test_claude_edit_supports_native_empty_old_string_creation(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "new_file.txt"
    registry = build_claude_canonical_registry()
    profile = build_native_claude_profile()
    runtime = ToolRuntime(registry)

    result = runtime.execute(
        ToolCall(
            id="edit_create",
            name="Edit",
            arguments={
                "file_path": str(target),
                "old_string": "",
                "new_string": "hello\n",
            },
        ),
        profile,
        ctx=_make_ctx(workspace),
    )

    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "hello\n"
    assert result.metadata["created"] is True


def test_codex_family_smoke_flow_covers_exec_command_write_stdin_and_apply_patch(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "calc.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    registry = build_codex_canonical_registry()
    profile = build_native_codex_profile()
    runtime = ToolRuntime(registry)
    ctx = _make_ctx(workspace)

    exec_result = runtime.execute(
        ToolCall(
            id="exec_1",
            name="exec_command",
            arguments={
                "cmd": "IFS= read -r line; printf '%s' \"$line\"",
                "tty": True,
                "yield_time_ms": 50,
            },
        ),
        profile,
        ctx=ctx,
    )

    assert exec_result.ok is True
    assert exec_result.metadata["operation"] == "exec_command"
    assert exec_result.metadata["session_id"] is not None

    stdin_result = runtime.execute(
        ToolCall(
            id="stdin_1",
            name="write_stdin",
            arguments={
                "session_id": exec_result.metadata["session_id"],
                "chars": "hello\n",
                "yield_time_ms": 500,
            },
        ),
        profile,
        ctx=ctx,
    )
    patch_result = runtime.execute(
        ToolCall(
            id="patch_1",
            name="apply_patch",
            input_text=(
                "*** Begin Patch\n"
                "*** Update File: calc.py\n"
                "@@\n"
                "-def add(a, b):\n"
                "-    return a - b\n"
                "+def add(a, b):\n"
                "+    return a + b\n"
                "*** End Patch\n"
            ),
        ),
        profile,
        ctx=ctx,
    )

    assert stdin_result.ok is True
    assert stdin_result.content == "[stdout]\nhello\n[exit code] 0"
    assert stdin_result.metadata["operation"] == "write_stdin"
    assert patch_result.ok is True
    assert patch_result.metadata["operation"] == "apply_patch"
    assert target.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"


def test_codex_freeform_apply_patch_survives_tool_runtime_trajectory_and_serializer(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "demo.txt"
    target.write_text("hello\n", encoding="utf-8")
    registry = build_codex_canonical_registry()
    profile = build_native_codex_profile()
    runtime = ToolRuntime(registry)
    task = CodingTask(
        task_id="strict_codex_traj",
        repo_path=workspace,
        prompt="Use apply_patch once.",
        max_turns=2,
    )
    client = FakeLLMClient(
        [
            _native_response(
                assistant_text="Applying patch.",
                call_id="c1",
                name="apply_patch",
                input_text=(
                    "*** Begin Patch\n"
                    "*** Update File: demo.txt\n"
                    "@@\n"
                    "-hello\n"
                    "+hola\n"
                    "*** End Patch\n"
                ),
            ),
            _native_response(assistant_text="Done."),
        ]
    )

    trajectory = run_agent_task(task, client, runtime, profile, _make_ctx(workspace))
    serialized = serialize_trajectory(trajectory)
    tool_segments = [segment for segment in serialized.segments if segment.kind == "assistant_tool_call"]

    assert trajectory.tool_calls[0].canonical_name == "apply_patch"
    assert trajectory.tool_versions["apply_patch"]["version"] == "apply_patch_v1"
    assert trajectory.observations[0].result.metadata["family"] == "codex"
    assert tool_segments
    assert '"payload_kind": "input_text"' in tool_segments[0].text
    assert '"name": "apply_patch"' in tool_segments[0].text
    assert '"input_text": "*** Begin Patch\\n*** Update File: demo.txt' in tool_segments[0].text
    assert target.read_text(encoding="utf-8") == "hola\n"
