"""Native-only tests for the agent runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import (
    BaseLLMClient,
    FakeLLMClient,
    GenerateRequest,
    GenerateResponse,
    RuntimeClientCapabilities,
    ToolCallCandidate,
)
from pycodeagent.agent.runner import AgentRunner, run_agent_task
from pycodeagent.agent.stopping import StopReason
from pycodeagent.env.task import CodingTask
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.testing import cleanup_test_path, get_managed_test_root, reset_test_root
from pycodeagent.tools.bootstrap import build_base_tool_runtime
from pycodeagent.tools.context import ToolContext
from pycodeagent.trajectory.schema import Role, RunStatus


_TEST_WORKSPACE_NAMESPACE = "agent_runner"


@pytest.fixture(autouse=True)
def _clean_test_workspace():
    reset_test_root(_TEST_WORKSPACE_NAMESPACE)
    yield
    cleanup_test_path(get_managed_test_root(_TEST_WORKSPACE_NAMESPACE))


def _make_workspace(suffix: str = "", files: dict[str, str] | None = None) -> Path:
    workspace = get_managed_test_root(_TEST_WORKSPACE_NAMESPACE) / f"ws_{suffix}"
    workspace.mkdir(parents=True, exist_ok=True)
    if files:
        for rel, content in files.items():
            p = workspace / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
    return workspace


def _make_task(workspace: Path, prompt: str = "Test task", *, max_turns: int = 5) -> CodingTask:
    return CodingTask(
        task_id="test_task",
        repo_path=workspace,
        prompt=prompt,
        max_turns=max_turns,
    )


def _native_response(
    *,
    assistant_text: str = "",
    call_id: str | None = None,
    name: str | None = None,
    arguments: dict | None = None,
    finish_reason: str = "tool_calls",
    response_id: str | None = None,
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
        response_id=response_id,
    )


class RaisingClient:
    def generate(self, request):
        raise RuntimeError("provider disconnected")


class CapturingClient(BaseLLMClient):
    def __init__(
        self,
        responses: list[GenerateResponse],
        *,
        capabilities: RuntimeClientCapabilities | None = None,
    ) -> None:
        self._responses = list(responses)
        self.requests: list[GenerateRequest] = []
        self._call_count = 0
        self._capabilities = capabilities or RuntimeClientCapabilities(
            protocol_mode="native_tool_calling",
            supports_native_tools=True,
            text_fallback_allowed=False,
            structured_finish_mode="finish_tool_call",
            supports_structured_output=True,
            supports_model_backed_compaction=True,
            provider_family="fake",
            provider_name="capturing_native",
        )

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.requests.append(request)
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        return self._responses[idx]

    def runtime_capabilities(self) -> RuntimeClientCapabilities:
        return self._capabilities


def test_finish_ends_run():
    workspace = _make_workspace("finish")
    task = _make_task(workspace, prompt="Do nothing, just finish.")
    client = FakeLLMClient(
        responses=[
            _native_response(
                assistant_text="Task is already complete.",
                call_id="c1",
                name="finish",
                arguments={"answer": "Nothing to do"},
                response_id="resp_1",
            )
        ]
    )

    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace, task=task)
    trajectory = run_agent_task(task, client, runtime, profile, ctx)

    assert trajectory.status == RunStatus.COMPLETED
    assert trajectory.messages[0].role == Role.SYSTEM
    assert trajectory.tool_calls[0].name == "finish"
    assert trajectory.metadata["session_outcome"]["session_termination_kind"] == "completed"
    assert trajectory.metadata["last_turn_continuation"]["continuation_decision_kind"] == "stop_finish"
    assert any(m.role == Role.ASSISTANT and "complete" in m.content for m in trajectory.messages)


def test_mutated_finish_still_stops_run():
    workspace = _make_workspace("mutated_finish")
    task = _make_task(workspace, prompt="Complete the task.")
    _, _, runtime = build_base_tool_runtime()
    profile = ToolProfileSampler(seed=0).sample("name_only")
    finish_exposed = next(tool.exposed_name for tool in profile.tools if tool.canonical_name == "finish")

    client = FakeLLMClient(
        responses=[
            _native_response(
                assistant_text="Task is already complete.",
                call_id="c1",
                name=finish_exposed,
                arguments={"answer": "Nothing to do"},
                response_id="resp_1",
            )
        ]
    )

    ctx = ToolContext(workspace_root=workspace, task=task)
    trajectory = run_agent_task(task, client, runtime, profile, ctx)

    assert trajectory.status == RunStatus.COMPLETED
    assert trajectory.metadata["stop_reason"] == StopReason.FINISH.value
    assert trajectory.tool_calls[0].canonical_name == "finish"


def test_tool_call_execution():
    workspace = _make_workspace("tool_exec", {"test.txt": "hello world"})
    task = _make_task(workspace, prompt="Read the file test.txt")
    client = FakeLLMClient(
        responses=[
            _native_response(
                assistant_text="I will read the file.",
                call_id="c1",
                name="read_file",
                arguments={"path": "test.txt"},
                response_id="resp_1",
            ),
            _native_response(
                assistant_text="Done.",
                call_id="c2",
                name="finish",
                arguments={"answer": "Read the file"},
                response_id="resp_2",
            ),
        ]
    )

    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace, task=task)
    trajectory = run_agent_task(task, client, runtime, profile, ctx)

    assert [call.name for call in trajectory.tool_calls] == ["read_file", "finish"]
    assert "hello world" in trajectory.observations[0].result.content


def test_no_tool_calls_ends_run():
    workspace = _make_workspace("no_tools")
    task = _make_task(workspace, prompt="Just say hello")
    client = FakeLLMClient(
        responses=[
            _native_response(
                assistant_text="Hello! The task is done.",
                name=None,
                response_id="resp_1",
            )
        ]
    )

    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace, task=task)
    trajectory = run_agent_task(task, client, runtime, profile, ctx)

    assert trajectory.status == RunStatus.COMPLETED
    assert len(trajectory.tool_calls) == 0
    assert any(m.role == Role.ASSISTANT and "Hello" in m.content for m in trajectory.messages)


def test_max_turns_stops_run():
    workspace = _make_workspace("max_turns")
    task = _make_task(workspace, prompt="Keep going", max_turns=2)
    client = FakeLLMClient(
        responses=[
            _native_response(call_id="c1", name="list_files", arguments={"path": "."}, response_id="resp_1"),
            _native_response(call_id="c2", name="list_files", arguments={"path": "."}, response_id="resp_2"),
            _native_response(call_id="c3", name="list_files", arguments={"path": "."}, response_id="resp_3"),
        ]
    )

    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace, task=task)
    trajectory = run_agent_task(task, client, runtime, profile, ctx)

    assert trajectory.metadata["total_turns"] == 2
    assert trajectory.metadata["stop_reason"] == StopReason.MAX_TURNS.value
    assert trajectory.metadata["session_outcome"]["session_termination_kind"] == "max_turns"
    assert trajectory.metadata["last_turn_continuation"]["continuation_decision_kind"] == "stop_max_turns"
    assert trajectory.status == RunStatus.FAILED


def test_native_protocol_error_handling():
    workspace = _make_workspace("protocol_error")
    task = _make_task(workspace, prompt="Test malformed native tool call")
    client = FakeLLMClient(
        responses=[
            GenerateResponse.from_native_tool_calling(
                assistant_text="I will read the file.",
                tool_calls=[
                    ToolCallCandidate(
                        call_id="bad_1",
                        name="read_file",
                        arguments_raw='{"path":',
                        arguments_parse_error="Expecting value",
                        source="native",
                    )
                ],
                finish_reason="tool_calls",
                response_id="resp_bad",
            )
        ]
    )

    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace, task=task)
    trajectory = run_agent_task(task, client, runtime, profile, ctx)

    assert trajectory.status == RunStatus.ERROR
    assert trajectory.metadata["parse_errors"] > 0
    assert len(trajectory.tool_calls) == 0
    repair_messages = [
        m for m in trajectory.messages if m.role == Role.USER and m.metadata.get("repair_kind") == "parse_error"
    ]
    assert len(repair_messages) == 1
    assert "invalid or malformed native tool call" in repair_messages[0].content


def test_native_protocol_error_then_valid_tool_recovers():
    workspace = _make_workspace("parse_recover", {"test.txt": "hello\n"})
    task = _make_task(workspace, prompt="Recover from a malformed tool call and then read the file.")
    client = FakeLLMClient(
        responses=[
            GenerateResponse.from_native_tool_calling(
                assistant_text="I will read the file.",
                tool_calls=[
                    ToolCallCandidate(
                        call_id="bad_1",
                        name="read_file",
                        arguments_raw='{"path":',
                        arguments_parse_error="Expecting value",
                        source="native",
                    )
                ],
                finish_reason="tool_calls",
                response_id="resp_bad",
            ),
            _native_response(
                call_id="c2",
                name="read_file",
                arguments={"path": "test.txt"},
                response_id="resp_2",
            ),
            _native_response(
                call_id="c3",
                name="finish",
                arguments={"answer": "Recovered and read the file"},
                response_id="resp_3",
            ),
        ]
    )

    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace, task=task)
    trajectory = run_agent_task(task, client, runtime, profile, ctx)

    assert trajectory.status == RunStatus.COMPLETED
    assert [call.name for call in trajectory.tool_calls] == ["read_file", "finish"]
    assert "hello" in trajectory.observations[0].result.content


def test_full_history_default_keeps_all_messages_in_request():
    workspace = _make_workspace("full_history", {"test.txt": "hello world"})
    task = _make_task(workspace, prompt="Read the file and finish.")
    client = CapturingClient(
        responses=[
            _native_response(call_id="c1", name="read_file", arguments={"path": "test.txt"}, response_id="resp_1"),
            _native_response(call_id="c2", name="finish", arguments={"answer": "Done"}, response_id="resp_2"),
        ]
    )

    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace, task=task)
    trajectory = run_agent_task(task, client, runtime, profile, ctx)

    assert trajectory.status == RunStatus.COMPLETED
    assert len(client.requests) == 2
    assert len(client.requests[0].messages) == 2
    assert len(client.requests[1].messages) == 4
    assert [message["role"] for message in client.requests[1].messages] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]


def test_tail_window_truncates_request_but_preserves_full_trajectory():
    workspace = _make_workspace("tail_window", {"test.txt": "hello world"})
    task = _make_task(workspace, prompt="Inspect the file, list files, and finish.")
    client = CapturingClient(
        responses=[
            _native_response(call_id="c1", name="read_file", arguments={"path": "test.txt"}, response_id="resp_1"),
            _native_response(call_id="c2", name="list_files", arguments={"path": "."}, response_id="resp_2"),
            _native_response(call_id="c3", name="finish", arguments={"answer": "Done"}, response_id="resp_3"),
        ]
    )

    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace, task=task)
    trajectory = run_agent_task(
        task,
        client,
        runtime,
        profile,
        ctx,
        context_policy_mode="tail_window",
        context_max_messages=4,
    )

    assert trajectory.status == RunStatus.COMPLETED
    assert len(client.requests) == 3
    assert len(client.requests[2].messages) == 4
    assert len(client.requests[2].messages) < len(trajectory.messages)


def test_deterministic_compaction_inserts_summary_into_request_only():
    workspace = _make_workspace("deterministic_compaction", {"test.txt": "hello world"})
    task = _make_task(
        workspace,
        prompt="Inspect, inspect again, inspect once more, and finish.",
        max_turns=5,
    )
    client = CapturingClient(
        responses=[
            _native_response(call_id="c1", name="read_file", arguments={"path": "test.txt"}, response_id="resp_1"),
            _native_response(call_id="c2", name="list_files", arguments={"path": "."}, response_id="resp_2"),
            _native_response(call_id="c3", name="read_file", arguments={"path": "test.txt"}, response_id="resp_3"),
            _native_response(call_id="c4", name="finish", arguments={"answer": "Done"}, response_id="resp_4"),
        ]
    )

    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace, task=task)
    trajectory = run_agent_task(
        task,
        client,
        runtime,
        profile,
        ctx,
        context_policy_mode="deterministic_compaction",
        context_max_messages=6,
    )

    assert trajectory.status == RunStatus.COMPLETED
    assert any(
        "[compacted runtime context]" in message["content"]
        for message in client.requests[3].messages
    )
    assert not any(
        "[compacted runtime context]" in message.content
        for message in trajectory.messages
    )


def test_model_backed_compaction_issues_dedicated_compaction_request():
    workspace = _make_workspace("model_backed_compaction", {"test.txt": "hello world"})
    task = _make_task(
        workspace,
        prompt="Inspect, inspect again, inspect once more, and finish.",
        max_turns=5,
    )
    compaction_output = {
        "summary_text": "[model compacted context]\ncovered_turns=1-2\nnext_focus=latest inspection context",
        "carried_forward_state": {
            "pending_issue_kind": None,
            "pending_issue_detail": "",
            "completion_evidence_status": "not_required",
            "validation_phase": "idle",
            "last_successful_validation_turn": None,
            "last_validation_attempt_turn": None,
            "last_validation_failure_turn": None,
            "last_mutation_turn": None,
            "recent_compacted_tool_outcomes": [],
            "carried_notes": ["Model-backed compaction preserved the earlier inspections."],
        },
        "compacted_span": {
            "source_message_indices": [2, 3, 4, 5],
            "source_turn_indices": [1, 2],
            "pinned_message_indices": [0, 1],
            "replacement_summary_kind": "model_backed_compaction",
        },
    }
    client = CapturingClient(
        responses=[
            _native_response(call_id="c1", name="read_file", arguments={"path": "test.txt"}, response_id="resp_1"),
            _native_response(call_id="c2", name="list_files", arguments={"path": "."}, response_id="resp_2"),
            _native_response(call_id="c3", name="read_file", arguments={"path": "test.txt"}, response_id="resp_3"),
            GenerateResponse.from_native_tool_calling(
                assistant_text=json.dumps(compaction_output, ensure_ascii=False),
                tool_calls=[],
                finish_reason="stop",
                response_id="resp_compact",
                request_kind="context_compaction",
                structured_output=compaction_output,
            ),
            _native_response(call_id="c4", name="finish", arguments={"answer": "Done"}, response_id="resp_4"),
        ],
    )

    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace, task=task)
    trajectory = run_agent_task(
        task,
        client,
        runtime,
        profile,
        ctx,
        context_policy_mode="model_backed_compaction",
        context_max_messages=6,
    )

    assert trajectory.status == RunStatus.COMPLETED
    assert len(client.requests) == 5
    assert client.requests[3].request_kind == "context_compaction"
    assert client.requests[3].structured_output_schema is not None
    assert client.requests[3].tools == []
    assert client.requests[4].request_kind == "agent_turn"
    assert any(
        "[model compacted context]" in message["content"]
        for message in client.requests[4].messages
    )
    assert not any(
        "[model compacted context]" in message.content
        for message in trajectory.messages
    )


def test_model_backed_compaction_falls_back_when_capability_is_disabled():
    workspace = _make_workspace("model_backed_compaction_capability_off", {"test.txt": "hello world"})
    task = _make_task(
        workspace,
        prompt="Inspect, inspect again, inspect once more, and finish.",
        max_turns=5,
    )
    client = CapturingClient(
        responses=[
            _native_response(call_id="c1", name="read_file", arguments={"path": "test.txt"}, response_id="resp_1"),
            _native_response(call_id="c2", name="list_files", arguments={"path": "."}, response_id="resp_2"),
            _native_response(call_id="c3", name="read_file", arguments={"path": "test.txt"}, response_id="resp_3"),
            _native_response(call_id="c4", name="finish", arguments={"answer": "Done"}, response_id="resp_4"),
        ],
        capabilities=RuntimeClientCapabilities(
            protocol_mode="native_tool_calling",
            supports_native_tools=True,
            text_fallback_allowed=False,
            structured_finish_mode="finish_tool_call",
            supports_structured_output=False,
            supports_model_backed_compaction=False,
            provider_family="fake",
            provider_name="capturing_native",
        ),
    )

    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace, task=task)
    trajectory = run_agent_task(
        task,
        client,
        runtime,
        profile,
        ctx,
        context_policy_mode="model_backed_compaction",
        context_max_messages=6,
    )

    assert trajectory.status == RunStatus.COMPLETED
    assert len(client.requests) == 4
    assert client.requests[3].request_kind == "agent_turn"
    assert any(
        "[compacted runtime context]" in message["content"]
        for message in client.requests[3].messages
    )


def test_model_backed_compaction_normalizes_provider_span_drift():
    workspace = _make_workspace(
        "model_backed_compaction_provider_drift",
        {"test.txt": "hello world"},
    )
    task = _make_task(
        workspace,
        prompt="Inspect, inspect again, inspect once more, and finish.",
        max_turns=5,
    )
    provider_drift_output = {
        "summary_text": "[provider compacted context]\ncovered_turns=1-2",
        "carried_forward_state": {
            "pending_issue_kind": None,
            "pending_issue_detail": "",
            "completion_evidence_status": "not_required",
            "validation_phase": "idle",
            "last_successful_validation_turn": None,
            "last_validation_attempt_turn": None,
            "last_validation_failure_turn": None,
            "last_mutation_turn": None,
            "recent_compacted_tool_outcomes": [],
            "carried_notes": ["Provider placed one span field at the top level."],
        },
        "compacted_span": {
            "source_message_indices": [2, 3, 4, 5],
            "source_turn_indices": [1, 2],
            "replacement_summary_kind": "text",
        },
        "pinned_message_indices": [0, 1],
    }
    client = CapturingClient(
        responses=[
            _native_response(call_id="c1", name="read_file", arguments={"path": "test.txt"}, response_id="resp_1"),
            _native_response(call_id="c2", name="list_files", arguments={"path": "."}, response_id="resp_2"),
            _native_response(call_id="c3", name="read_file", arguments={"path": "test.txt"}, response_id="resp_3"),
            GenerateResponse.from_native_tool_calling(
                assistant_text=json.dumps(provider_drift_output, ensure_ascii=False),
                tool_calls=[],
                finish_reason="stop",
                response_id="resp_compact_drift",
                request_kind="context_compaction",
                structured_output=provider_drift_output,
            ),
            _native_response(call_id="c4", name="finish", arguments={"answer": "Done"}, response_id="resp_4"),
        ]
    )

    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace, task=task)
    trajectory = run_agent_task(
        task,
        client,
        runtime,
        profile,
        ctx,
        context_policy_mode="model_backed_compaction",
        context_max_messages=6,
    )

    assert trajectory.status == RunStatus.COMPLETED
    assert len(client.requests) == 5
    assert client.requests[3].request_kind == "context_compaction"
    assert client.requests[4].request_kind == "agent_turn"


def test_model_backed_compaction_falls_back_on_compacted_span_mismatch():
    workspace = _make_workspace("model_backed_compaction_span_mismatch", {"test.txt": "hello world"})
    task = _make_task(
        workspace,
        prompt="Inspect, inspect again, inspect once more, and finish.",
        max_turns=5,
    )
    bad_compaction_output = {
        "summary_text": "[bad model compacted context]",
        "carried_forward_state": {
            "pending_issue_kind": None,
            "pending_issue_detail": "",
            "completion_evidence_status": "not_required",
            "validation_phase": "idle",
            "last_successful_validation_turn": None,
            "last_validation_attempt_turn": None,
            "last_validation_failure_turn": None,
            "last_mutation_turn": None,
            "recent_compacted_tool_outcomes": [],
            "carried_notes": ["Bad compacted span."],
        },
        "compacted_span": {
            "source_message_indices": [99],
            "source_turn_indices": [9],
            "pinned_message_indices": [0, 1],
            "replacement_summary_kind": "model_backed_compaction",
        },
    }
    client = CapturingClient(
        responses=[
            _native_response(call_id="c1", name="read_file", arguments={"path": "test.txt"}, response_id="resp_1"),
            _native_response(call_id="c2", name="list_files", arguments={"path": "."}, response_id="resp_2"),
            _native_response(call_id="c3", name="read_file", arguments={"path": "test.txt"}, response_id="resp_3"),
            GenerateResponse.from_native_tool_calling(
                assistant_text=json.dumps(bad_compaction_output, ensure_ascii=False),
                tool_calls=[],
                finish_reason="stop",
                response_id="resp_compact_bad",
                request_kind="context_compaction",
                structured_output=bad_compaction_output,
            ),
            _native_response(call_id="c4", name="finish", arguments={"answer": "Done"}, response_id="resp_4"),
        ],
    )

    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace, task=task)
    trajectory = run_agent_task(
        task,
        client,
        runtime,
        profile,
        ctx,
        context_policy_mode="model_backed_compaction",
        context_max_messages=6,
    )

    assert trajectory.status == RunStatus.COMPLETED
    assert len(client.requests) == 5
    assert client.requests[3].request_kind == "context_compaction"
    assert client.requests[4].request_kind == "agent_turn"
    assert any(
        "[compacted runtime context]" in message["content"]
        for message in client.requests[4].messages
    )
    assert not any(
        "[bad model compacted context]" in message["content"]
        for message in client.requests[4].messages
    )


def test_runner_class_accepts_context_policy_config():
    workspace = _make_workspace("runner_class_tail", {"test.txt": "hello"})
    task = _make_task(workspace, prompt="Read and finish.")
    client = CapturingClient(
        responses=[
            _native_response(call_id="c1", name="read_file", arguments={"path": "test.txt"}, response_id="resp_1"),
            _native_response(call_id="c2", name="finish", arguments={"answer": "Done"}, response_id="resp_2"),
        ]
    )

    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace, task=task)
    runner = AgentRunner(
        client=client,
        runtime=runtime,
        profile=profile,
        context_policy_mode="tail_window",
        context_max_messages=3,
    )
    trajectory = runner.run(task, ctx)

    assert trajectory.status == RunStatus.COMPLETED
    assert len(client.requests[1].messages) == 3


def test_llm_error_returns_error_trajectory():
    workspace = _make_workspace("llm_error")
    task = _make_task(workspace, prompt="Test provider failure")
    _, profile, runtime = build_base_tool_runtime()
    ctx = ToolContext(workspace_root=workspace)

    trajectory = run_agent_task(task, RaisingClient(), runtime, profile, ctx)

    assert trajectory.status == RunStatus.ERROR
    assert trajectory.metadata["final_status"] == "error"
    assert trajectory.metadata["session_termination_kind"] == "llm_error"
    assert trajectory.metadata["session_outcome"]["session_termination_kind"] == "llm_error"
    assert trajectory.metadata["budget_snapshot"]["validation_budget_total"] == 2
    assert trajectory.metadata["llm_error_type"] == "RuntimeError"
