"""Tests for native-only tool-stack selection and runtime resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient, GenerateResponse, ToolCallCandidate
from pycodeagent.env.coding_env import _resolve_profile_and_runtime, run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.profile_factory import (
    build_native_claude_profile,
    build_native_codex_profile,
)
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.trajectory.schema import ToolCall


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
                arguments_raw=None if arguments is None else json.dumps(arguments),
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


def test_resolve_profile_and_runtime_selects_native_claude_stack():
    profile, runtime = _resolve_profile_and_runtime(
        profile=None,
        runtime=None,
        profile_mode=None,
        profile_seed=0,
        tool_stack_kind="native_claude",
    )

    assert runtime is not None
    assert profile.profile_id == "native_claude"
    assert [tool.exposed_name for tool in profile.tools] == [
        "Bash",
        "Read",
        "Edit",
        "Write",
        "Grep",
        "Glob",
    ]


def test_resolve_profile_and_runtime_selects_native_codex_stack():
    profile, runtime = _resolve_profile_and_runtime(
        profile=None,
        runtime=None,
        profile_mode=None,
        profile_seed=0,
        tool_stack_kind="native_codex",
    )

    assert runtime is not None
    assert profile.profile_id == "native_codex"
    assert [tool.exposed_name for tool in profile.tools] == [
        "exec_command",
        "write_stdin",
        "apply_patch",
    ]


def test_profile_mode_samples_from_selected_native_family():
    profile, runtime = _resolve_profile_and_runtime(
        profile=None,
        runtime=None,
        profile_mode="name_only",
        profile_seed=0,
        tool_stack_kind="native_claude",
    )

    assert runtime is not None
    assert profile.metadata["family"] == "claude"
    assert profile.metadata["mode"] == "name_only"
    assert {tool.metadata["mutation_source_family"] for tool in profile.tools} == {"claude"}


def test_native_claude_profile_without_runtime_inferrs_claude_runtime(tmp_path: Path):
    profile = build_native_claude_profile()
    resolved_profile, runtime = _resolve_profile_and_runtime(
        profile=profile,
        runtime=None,
        profile_mode=None,
        profile_seed=0,
        tool_stack_kind="native_claude",
    )

    result = runtime.execute(
        ToolCall(
            id="bash_1",
            name="Bash",
            arguments={"command": "pwd"},
        ),
        resolved_profile,
        ctx=ToolContext(workspace_root=tmp_path),
    )

    assert resolved_profile is profile
    assert result.ok is True
    assert result.metadata["family"] == "claude"


def test_native_codex_profile_without_runtime_inferrs_codex_runtime(tmp_path: Path):
    target = tmp_path / "demo.txt"
    target.write_text("hello\n", encoding="utf-8")
    profile = build_native_codex_profile()
    resolved_profile, runtime = _resolve_profile_and_runtime(
        profile=profile,
        runtime=None,
        profile_mode=None,
        profile_seed=0,
        tool_stack_kind="native_codex",
    )

    result = runtime.execute(
        ToolCall(
            id="patch_1",
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
        resolved_profile,
        ctx=ToolContext(workspace_root=tmp_path),
    )

    assert resolved_profile is profile
    assert result.ok is True
    assert result.metadata["family"] == "codex"
    assert target.read_text(encoding="utf-8") == "hola\n"


def test_conflicting_native_profile_and_explicit_stack_kind_fails():
    with pytest.raises(ValueError, match="conflicts with tool_stack_kind"):
        _resolve_profile_and_runtime(
            profile=build_native_codex_profile(),
            runtime=None,
            profile_mode=None,
            profile_seed=0,
            tool_stack_kind="native_claude",
        )


def test_profile_without_native_family_metadata_is_rejected():
    profile = ToolProfile(profile_id="bad", tools=[], adapters={}, metadata={})

    with pytest.raises(ValueError, match="without native family metadata"):
        _resolve_profile_and_runtime(
            profile=profile,
            runtime=None,
            profile_mode=None,
            profile_seed=0,
            tool_stack_kind="native_claude",
        )


def test_run_coding_task_native_claude_stack_without_manual_runtime(tmp_path: Path):
    repo = tmp_path / "claude_repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")

    task = CodingTask(
        task_id="native_claude_stack",
        repo_path=repo,
        prompt="Read main.py and stop.",
        test_command="python -c \"print('ok')\"",
        max_turns=2,
    )
    client = FakeLLMClient(
        [
            _native_response(
                assistant_text="Reading the file.",
                call_id="c1",
                name="Read",
                arguments={"file_path": "main.py"},
            ),
            _native_response(assistant_text="Done."),
        ]
    )

    trajectory = run_coding_task(
        task,
        client,
        tmp_path / "run_claude",
        tool_stack_kind="native_claude",
    )

    assert trajectory.tool_profile_id == "native_claude"
    assert [call.name for call in trajectory.tool_calls] == ["Read"]


def test_run_coding_task_requires_explicit_native_family(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    task = CodingTask(
        task_id="missing_stack_kind",
        repo_path=repo,
        prompt="noop",
        test_command="python -c \"print('ok')\"",
        max_turns=1,
    )

    with pytest.raises(TypeError):
        run_coding_task(task, FakeLLMClient([]), tmp_path / "run_missing")
