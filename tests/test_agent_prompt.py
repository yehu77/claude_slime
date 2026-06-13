"""Tests for native runtime prompt construction."""

from __future__ import annotations

from typing import Any

from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.agent.model_config import ModelConfig
from pycodeagent.agent.mimo_native_client import MimoNativeToolClient
from pycodeagent.agent.prompt import build_initial_messages, build_system_message
from pycodeagent.agent.runner import run_agent_task
from pycodeagent.env.task import CodingTask
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.tools.bootstrap import build_base_tool_runtime
from pycodeagent.tools.context import ToolContext


class RecordingFakeLLMClient(FakeLLMClient):
    """Fake client that records each generation request."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        super().__init__(responses)
        self.requests: list[Any] = []

    def generate(self, request):  # type: ignore[override]
        self.requests.append(request)
        return super().generate(request)


class RecordingMimoNativeClient(MimoNativeToolClient):
    """Native-tools client double that records requests and returns a fake native response."""

    def __init__(self) -> None:
        super().__init__(
            ModelConfig(
                provider="mimo",
                model="mimo-v2.5-pro",
                api_key_env="PYCODEAGENT_API_KEY",
                base_url="https://token-plan-cn.xiaomimimo.com/v1",
            )
        )
        self.requests: list[Any] = []

    def generate(self, request):  # type: ignore[override]
        self.requests.append(request)
        finish_spec = next(
            spec for spec in request.tools if "answer" in spec["input_schema"]["properties"]
        )
        return FakeLLMClient(
            responses=[
                {
                    "transport_mode": "native_tool_calling",
                    "assistant_text": "",
                    "tool_calls": [
                        {
                            "call_id": "native_finish_1",
                            "name": finish_spec["name"],
                            "arguments_raw": '{"answer":"Done"}',
                            "arguments_obj": {"answer": "Done"},
                            "source": "native",
                        }
                    ],
                    "finish_reason": "tool_calls",
                }
            ]
        ).generate(request)


def _get_exposed_name(profile, canonical_name: str) -> str:
    for tool in profile.tools:
        if tool.canonical_name == canonical_name:
            return tool.exposed_name
    raise AssertionError(f"Tool not found: {canonical_name}")


class TestPromptConstruction:
    def test_default_system_prompt_uses_native_contract(self):
        system_content = build_system_message()["content"]
        assert "native tool-calling interface" in system_content
        assert "<tools>" not in system_content

    def test_native_initial_messages_do_not_embed_tool_block(self):
        profile = ToolProfileSampler(seed=0).sample("name_description_schema")
        messages = build_initial_messages("Solve the task.", profile.get_exposed_specs())
        assert "<tools>" not in messages[1]["content"]
        assert "<|tool|>" not in messages[1]["content"]
        assert messages[1]["content"] == "Solve the task."

    def test_runner_uses_same_profile_specs_for_request(self):
        workspace = make_unique_test_dir("agent_prompt", prefix="prompt")
        try:
            _, _, runtime = build_base_tool_runtime()
            profile = ToolProfileSampler(seed=0).sample("name_description_schema")
            finish_name = _get_exposed_name(profile, "finish")
            client = RecordingFakeLLMClient(
                responses=[
                    {
                        "transport_mode": "native_tool_calling",
                        "assistant_text": "Done.",
                        "tool_calls": [
                            {
                                "call_id": "c1",
                                "name": finish_name,
                                "arguments_raw": '{"summary":"Finished"}',
                                "arguments_obj": {"summary": "Finished"},
                                "source": "native",
                            }
                        ],
                        "finish_reason": "tool_calls",
                    }
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
            assert request.messages[1]["content"] == "Complete the task immediately."
            assert trajectory.tool_calls[0].canonical_name == "finish"
        finally:
            cleanup_test_path(workspace)

    def test_native_runner_does_not_send_legacy_tool_block_contract(self):
        workspace = make_unique_test_dir("agent_prompt", prefix="native_prompt")
        try:
            _, profile, runtime = build_base_tool_runtime()
            client = RecordingMimoNativeClient()
            task = CodingTask(
                task_id="native_prompt_contract",
                repo_path=workspace,
                prompt="Complete the task immediately.",
                max_turns=1,
            )
            ctx = ToolContext(workspace_root=workspace, task=task)

            trajectory = run_agent_task(task, client, runtime, profile, ctx)

            assert len(client.requests) == 1
            request = client.requests[0]
            assert request.tools == profile.get_exposed_specs()
            assert "<tools>" not in request.messages[1]["content"]
            assert "canonical <|tool|> ... <|end|> blocks only" not in request.messages[1]["content"]
            assert "native tool-calling interface" in request.messages[0]["content"]
            assert trajectory.tool_calls[0].canonical_name == "finish"
        finally:
            cleanup_test_path(workspace)
