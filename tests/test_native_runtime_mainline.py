from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import (
    FakeLLMClient,
    GenerateRequest,
    GenerateResponse,
    ToolCallCandidate,
)
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.trajectory.schema import RunStatus


pytestmark = pytest.mark.mainline


NATIVE_CLAUDE_TOOLS = ["Bash", "Read", "Edit", "Write", "Grep", "Glob"]
LEGACY_TOOLS = {
    "apply_patch",
    "create_file",
    "finish",
    "list_files",
    "python_run",
    "read_file",
    "run_command",
    "search_code",
    "write_file",
}


class RecordingFakeLLMClient(FakeLLMClient):
    def __init__(self, responses: list[GenerateResponse]) -> None:
        super().__init__(responses)
        self.requests: list[GenerateRequest] = []

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.requests.append(request)
        return super().generate(request)


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_native_claude_local_runtime_mainline_contract(tmp_path: Path) -> None:
    source_repo = tmp_path / "source"
    source_repo.mkdir()
    (source_repo / "main.py").write_text("VALUE = 42\n", encoding="utf-8")

    task = CodingTask(
        task_id="native_claude_mainline",
        repo_path=source_repo,
        prompt="Read main.py and report the value without changing the workspace.",
        test_command=[
            sys.executable,
            "-c",
            "from pathlib import Path; assert Path('main.py').read_text() == 'VALUE = 42\\n'",
        ],
        max_turns=3,
    )
    client = RecordingFakeLLMClient(
        [
            GenerateResponse.from_native_tool_calling(
                assistant_text="I will inspect main.py.",
                tool_calls=[
                    ToolCallCandidate(
                        call_id="read_1",
                        name="Read",
                        arguments_raw='{"file_path":"main.py"}',
                        arguments_obj={"file_path": "main.py"},
                        source="native",
                    )
                ],
                finish_reason="tool_calls",
                response_id="response_1",
            ),
            GenerateResponse.from_native_tool_calling(
                assistant_text="main.py defines VALUE as 42.",
                finish_reason="stop",
                response_id="response_2",
            ),
        ]
    )
    run_dir = tmp_path / "run"

    trajectory = run_coding_task(
        task,
        client,
        run_dir,
        tool_stack_kind="native_claude",
    )

    assert client.call_count == 2
    assert len(client.requests) == 2
    for request in client.requests:
        assert [tool.name for tool in request.tools] == NATIVE_CLAUDE_TOOLS
        assert {tool.name for tool in request.tools}.isdisjoint(LEGACY_TOOLS)

    assert trajectory.status is RunStatus.COMPLETED
    assert trajectory.verifier is not None
    assert trajectory.verifier.passed is True
    assert trajectory.reward == 1.0
    assert trajectory.metadata["reward_reason"] == "verifier_passed"
    assert trajectory.tool_profile_id == "native_claude"
    assert len(trajectory.tool_calls) == 1
    assert trajectory.tool_calls[0].name == "Read"
    assert trajectory.tool_calls[0].canonical_name == "Read"
    assert len(trajectory.observations) == 1
    assert trajectory.observations[0].tool_name == "Read"
    assert trajectory.observations[0].canonical_name == "Read"
    assert trajectory.observations[0].result.ok is True
    assert trajectory.observations[0].result.metadata["family"] == "claude"

    artifact_paths = {
        name: run_dir / name
        for name in (
            "trajectory.json",
            "tool_profile.json",
            "verifier.json",
            "runtime_trace.jsonl",
            "runtime_trace_manifest.json",
        )
    }
    assert all(path.is_file() for path in artifact_paths.values())

    saved_trajectory = json.loads(
        artifact_paths["trajectory.json"].read_text(encoding="utf-8")
    )
    assert saved_trajectory["status"] == "completed"
    assert saved_trajectory["reward"] == 1.0
    assert saved_trajectory["verifier"]["passed"] is True
    assert saved_trajectory["tool_calls"][0]["name"] == "Read"
    assert saved_trajectory["tool_calls"][0]["canonical_name"] == "Read"

    saved_profile = json.loads(
        artifact_paths["tool_profile.json"].read_text(encoding="utf-8")
    )
    assert saved_profile["profile_id"] == "native_claude"
    assert saved_profile["metadata"]["family"] == "claude"
    exposed_names = [tool["exposed_name"] for tool in saved_profile["tools"]]
    canonical_names = [tool["canonical_name"] for tool in saved_profile["tools"]]
    assert exposed_names == NATIVE_CLAUDE_TOOLS
    assert canonical_names == NATIVE_CLAUDE_TOOLS
    assert set(exposed_names + canonical_names).isdisjoint(LEGACY_TOOLS)

    trace_manifest = json.loads(
        artifact_paths["runtime_trace_manifest.json"].read_text(encoding="utf-8")
    )
    assert trace_manifest["task_id"] == task.task_id
    assert trace_manifest["tool_profile_id"] == "native_claude"
    assert trace_manifest["ended_at_unix_ms"] is not None
    assert trace_manifest["retention"]["purpose_class"] == "unclassified_hold"
    assert trace_manifest["retention"]["sensitivity"] == "restricted"
    assert (
        trace_manifest["retention"]["source_checksum"]
        == json.loads(
            (run_dir / "run_retention_manifest.json").read_text(encoding="utf-8")
        )["checksums"]["source"]
    )

    trace_events = _load_jsonl(artifact_paths["runtime_trace.jsonl"])
    event_kinds = [event["event_kind"] for event in trace_events]
    for required_kind in (
        "run_started",
        "tool_profile_exposed",
        "model_request_built",
        "tool_call_validation_completed",
        "tool_call_mapping_completed",
        "tool_execution_completed",
        "run_completed",
    ):
        assert required_kind in event_kinds

    profile_event = next(
        event for event in trace_events if event["event_kind"] == "tool_profile_exposed"
    )
    assert profile_event["data"]["tool_names"] == NATIVE_CLAUDE_TOOLS
    assert profile_event["data"]["canonical_tool_order"] == NATIVE_CLAUDE_TOOLS

    validation_event = next(
        event
        for event in trace_events
        if event["event_kind"] == "tool_call_validation_completed"
    )
    assert validation_event["data"]["exposed_tool_name"] == "Read"
    assert validation_event["data"]["schema_valid"] is True

    mapping_event = next(
        event
        for event in trace_events
        if event["event_kind"] == "tool_call_mapping_completed"
    )
    assert mapping_event["data"]["exposed_tool_name"] == "Read"
    assert mapping_event["data"]["canonical_tool_name"] == "Read"
    assert mapping_event["data"]["mapping_valid"] is True

    execution_event = next(
        event
        for event in trace_events
        if event["event_kind"] == "tool_execution_completed"
    )
    assert execution_event["data"]["canonical_tool_name"] == "Read"
    assert execution_event["data"]["ok"] is True

    trace_tool_identities = set(profile_event["data"]["tool_names"])
    trace_tool_identities.update(profile_event["data"]["canonical_tool_order"])
    trace_tool_identities.add(validation_event["data"]["exposed_tool_name"])
    trace_tool_identities.add(mapping_event["data"]["exposed_tool_name"])
    trace_tool_identities.add(mapping_event["data"]["canonical_tool_name"])
    trace_tool_identities.add(execution_event["data"]["canonical_tool_name"])
    assert trace_tool_identities.isdisjoint(LEGACY_TOOLS)
