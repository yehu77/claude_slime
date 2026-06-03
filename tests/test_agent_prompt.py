"""Tests for prompt construction."""

from __future__ import annotations

from typing import Any

from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.agent.prompt import build_initial_messages, build_system_message
from pycodeagent.agent.runner import run_agent_task
from pycodeagent.env.task import CodingTask
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.tools.bootstrap import build_base_tool_runtime
from pycodeagent.tools.context import ToolContext


class RecordingFakeLLMClient(FakeLLMClient):
    """Fake client that records each generation request."""

    def __init__(self, responses: list[str]) -> None:
        super().__init__(responses)
        self.requests: list[Any] = []

    def generate(self, request):  # type: ignore[override]
        self.requests.append(request)
        return super().generate(request)


def _get_exposed_name(profile, canonical_name: str) -> str:
    for tool in profile.tools:
        if tool.canonical_name == canonical_name:
            return tool.exposed_name
    raise AssertionError(f"Tool not found: {canonical_name}")


def _assert_prompt_renders_tool_specs(
    prompt_content: str,
    tool_specs: list[dict[str, Any]],
) -> None:
    assert "<tools>" in prompt_content
    assert "</tools>" in prompt_content

    for spec in tool_specs:
        assert f"  {spec['name']}: {spec['description']}" in prompt_content

        schema = spec.get("input_schema", {})
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        for prop_name, prop_spec in props.items():
            prop_type = prop_spec.get("type", "any")
            prop_desc = prop_spec.get("description", "")
            req_marker = " (required)" if prop_name in required else ""
            expected_line = f"    - {prop_name}: {prop_type}{req_marker} - {prop_desc}"
            assert expected_line in prompt_content


class TestPromptConstruction:
    """Tests for prompt generation with tool profiles."""

    def test_system_prompt_does_not_list_canonical_tool_names(self):
        """The system prompt should not leak canonical tool names."""
        system_content = build_system_message()["content"]
        for tool_name in [
            "list_files",
            "read_file",
            "search_code",
            "apply_patch",
            "run_command",
            "finish",
        ]:
            assert tool_name not in system_content

    def test_mutated_profile_prompt_uses_exposed_names_only(self):
        """The prompt should reference mutated tool names, not canonical ones."""
        profile = ToolProfileSampler(seed=0).sample("name_only")
        finish_name = _get_exposed_name(profile, "finish")
        assert finish_name != "finish"

        messages = build_initial_messages("Solve the task.", profile.get_exposed_specs())
        system_content = messages[0]["content"]
        user_content = messages[1]["content"]

        assert finish_name in user_content
        assert "finish" not in system_content
        assert "finish" not in user_content
        assert "Use only the exact tool names" in user_content

    def test_tool_block_matches_mutated_profile_specs(self):
        """The rendered <tools> block must mirror the sampled profile specs."""
        profile = ToolProfileSampler(seed=0).sample("name_description_schema")
        messages = build_initial_messages("Solve the task.", profile.get_exposed_specs())
        user_content = messages[1]["content"]

        finish_name = _get_exposed_name(profile, "finish")
        assert finish_name != "finish"
        assert f"  {finish_name}:" in user_content
        assert "  finish:" not in user_content

        _assert_prompt_renders_tool_specs(user_content, profile.get_exposed_specs())

    def test_runner_uses_same_profile_specs_for_prompt_and_request(self):
        """Runner must send the same sampled specs in both prompt text and request.tools."""
        workspace = make_unique_test_dir("agent_prompt", prefix="prompt")
        try:
            _, _, runtime = build_base_tool_runtime()
            profile = ToolProfileSampler(seed=0).sample("name_description_schema")
            finish_name = _get_exposed_name(profile, "finish")
            client = RecordingFakeLLMClient(
                responses=[
                    f"""<assistant>
Done.
</assistant>
<|tool|>
{{"id":"c1","name":"{finish_name}","arguments":{{"summary":"Finished"}}}}
<|end|>"""
                ]
            )
            task = CodingTask(
                task_id="prompt_profile_consistency",
                repo_path=workspace,
                prompt="Complete the task immediately.",
                max_turns=1,
            )
            ctx = ToolContext(workspace_root=workspace, task=task)

            trajectory = run_agent_task(task, client, runtime, profile, ctx)

            assert len(client.requests) == 1
            request = client.requests[0]
            assert request.tools == profile.get_exposed_specs()
            assert request.messages[1]["role"] == "user"
            _assert_prompt_renders_tool_specs(request.messages[1]["content"], request.tools)
            assert f"  {finish_name}:" in request.messages[1]["content"]
            assert "  finish:" not in request.messages[1]["content"]
            assert trajectory.tool_calls[0].canonical_name == "finish"
        finally:
            cleanup_test_path(workspace)
