"""Tests for the Step B Codex patch runtime."""

from __future__ import annotations

from pathlib import Path

from pycodeagent.agent.llm_client import FakeLLMClient, GenerateResponse, ToolCallCandidate
from pycodeagent.agent.runner import run_agent_task
from pycodeagent.env.task import CodingTask
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.patch_runtime import CodexApplyPatchRuntime
from pycodeagent.tools.registry import ToolRegistry
from pycodeagent.tools.runtime import ToolRuntime
from pycodeagent.tools.spec import CanonicalTool, ToolProfile, ToolView
from pycodeagent.trajectory.schema import ToolCall


def _make_ctx(workspace_root: Path) -> ToolContext:
    return ToolContext(workspace_root=workspace_root)


def _native_response(
    *,
    assistant_text: str = "",
    call_id: str | None = None,
    name: str | None = None,
    arguments: dict | None = None,
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
        finish_reason="tool_calls" if tool_calls else "stop",
    )


class TestCodexApplyPatchRuntime:
    def test_patch_modifies_files_through_dedicated_path(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        target = workspace / "file.txt"
        target.write_text("old content\n", encoding="utf-8")
        runtime = CodexApplyPatchRuntime()
        patch = "--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-old content\n+new content\n"

        result = runtime.apply_patch(patch, ctx=_make_ctx(workspace))

        assert result.ok is True
        assert target.read_text(encoding="utf-8") == "new content\n"
        assert result.metadata["operation"] == "codex_apply_patch"
        assert result.metadata["command_family"] == "codex_apply_patch"
        assert result.metadata["execution_kind"] == "patch_apply"
        assert result.metadata["target_files"] == ["file.txt"]
        assert result.metadata["file_operations"] == [
            {"path": "file.txt", "operation": "modify", "hunks_applied": 1}
        ]
        assert result.metadata["patch_applied"] is True
        assert result.metadata["content_delta_kind"] == "patch"
        assert result.metadata["hunks_applied"] == 1

    def test_empty_patch_returns_validation_error(self):
        runtime = CodexApplyPatchRuntime()

        result = runtime.apply_patch("   \n")

        assert result.ok is False
        assert result.is_error is True
        assert result.metadata["error_type"] == "empty_diff"
        assert result.metadata["stage"] == "validate_input"
        assert result.metadata["operation"] == "codex_apply_patch"

    def test_missing_context_returns_structured_error(self):
        runtime = CodexApplyPatchRuntime()
        patch = "--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-old\n+new\n"

        result = runtime.apply_patch(patch)

        assert result.ok is False
        assert result.is_error is True
        assert result.metadata["error_type"] == "missing_context"
        assert result.metadata["stage"] == "context_check"

    def test_path_policy_violations_are_preserved(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        runtime = CodexApplyPatchRuntime()
        patch = "--- a/../outside.txt\n+++ b/../outside.txt\n@@ -1 +1 @@\n-old\n+new\n"

        result = runtime.apply_patch(patch, ctx=_make_ctx(workspace))

        assert result.ok is False
        assert result.is_error is True
        assert result.metadata["error_type"] == "workspace_escape"
        assert result.metadata["stage"] == "validate_target"
        assert result.metadata["operation"] == "codex_apply_patch"

    def test_patch_failures_become_structured_errors(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "file.txt").write_text("old content\n", encoding="utf-8")
        runtime = CodexApplyPatchRuntime()
        patch = (
            "--- a/file.txt\n"
            "+++ b/file.txt\n"
            "@@ -1 +1 @@\n"
            "-missing content\n"
            "+different content\n"
        )

        result = runtime.apply_patch(patch, ctx=_make_ctx(workspace))

        assert result.ok is False
        assert result.is_error is True
        assert result.metadata["error_type"] == "patch_apply"
        assert result.metadata["stage"] == "handler_execution"
        assert result.metadata["target_files"] == ["file.txt"]


class TestPatchRuntimeCompatibility:
    def test_runtime_metadata_survives_tool_runtime_execution(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        target = workspace / "file.txt"
        target.write_text("old content\n", encoding="utf-8")
        patch_runtime = CodexApplyPatchRuntime()
        schema = {
            "type": "object",
            "properties": {"patch": {"type": "string"}},
            "required": ["patch"],
            "additionalProperties": False,
        }
        registry = ToolRegistry()
        registry.register(
            CanonicalTool(
                canonical_name="codex_patch_runtime_test",
                description="Temporary Codex patch runtime wrapper.",
                canonical_schema=schema,
                handler=patch_runtime.apply_patch,
            )
        )
        profile = ToolProfile(
            profile_id="runtime_patch_smoke",
            tools=[
                ToolView(
                    canonical_name="codex_patch_runtime_test",
                    exposed_name="apply_patch",
                    description="Temporary apply_patch wrapper.",
                    input_schema=schema,
                )
            ],
        )
        runtime = ToolRuntime(registry)
        call = ToolCall(
            id="call_1",
            name="apply_patch",
            arguments={
                "patch": (
                    "--- a/file.txt\n"
                    "+++ b/file.txt\n"
                    "@@ -1 +1 @@\n"
                    "-old content\n"
                    "+new content\n"
                )
            },
        )

        result = runtime.execute(call, profile, ctx=_make_ctx(workspace))

        assert result.ok is True
        assert result.metadata["operation"] == "codex_apply_patch"
        assert result.metadata["execution_kind"] == "patch_apply"
        assert target.read_text(encoding="utf-8") == "new content\n"

    def test_runtime_metadata_survives_agent_trajectory(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        target = workspace / "file.txt"
        target.write_text("old content\n", encoding="utf-8")
        patch_runtime = CodexApplyPatchRuntime()
        schema = {
            "type": "object",
            "properties": {"patch": {"type": "string"}},
            "required": ["patch"],
            "additionalProperties": False,
        }
        registry = ToolRegistry()
        registry.register(
            CanonicalTool(
                canonical_name="codex_patch_runtime_traj_test",
                description="Temporary Codex patch trajectory wrapper.",
                canonical_schema=schema,
                handler=patch_runtime.apply_patch,
            )
        )
        profile = ToolProfile(
            profile_id="runtime_patch_traj_smoke",
            tools=[
                ToolView(
                    canonical_name="codex_patch_runtime_traj_test",
                    exposed_name="apply_patch",
                    description="Temporary apply_patch wrapper.",
                    input_schema=schema,
                )
            ],
        )
        runtime = ToolRuntime(registry)
        task = CodingTask(
            task_id="runtime_patch_traj_smoke",
            repo_path=workspace,
            prompt="Apply a patch once.",
            max_turns=2,
        )
        client = FakeLLMClient(
            [
                _native_response(
                    assistant_text="Applying patch.",
                    call_id="c1",
                    name="apply_patch",
                    arguments={
                        "patch": (
                            "--- a/file.txt\n"
                            "+++ b/file.txt\n"
                            "@@ -1 +1 @@\n"
                            "-old content\n"
                            "+new content\n"
                        )
                    },
                ),
                _native_response(assistant_text="Done."),
            ]
        )

        trajectory = run_agent_task(task, client, runtime, profile, _make_ctx(workspace))

        assert trajectory.tool_calls[0].canonical_name == "codex_patch_runtime_traj_test"
        assert trajectory.observations[0].result.metadata["operation"] == "codex_apply_patch"
        assert trajectory.observations[0].result.metadata["execution_kind"] == "patch_apply"
        assert target.read_text(encoding="utf-8") == "new content\n"
