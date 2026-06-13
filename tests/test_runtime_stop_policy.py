from __future__ import annotations

import json

from pycodeagent.agent.llm_client import (
    FakeLLMClient,
    GenerateResponse,
    ToolCallCandidate,
)
from pycodeagent.agent.runner import run_agent_task
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.tools.bootstrap import build_base_tool_runtime
from pycodeagent.tools.context import ToolContext
from pycodeagent.trajectory.schema import RunStatus


def _load_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


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
                arguments_raw=json.dumps(arguments or {}, ensure_ascii=False),
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


def test_finish_after_mutation_requires_validation_evidence() -> None:
    tmp_path = make_unique_test_dir("runtime_stop_policy")
    try:
        repo = tmp_path / "repo_missing_validation"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "test_generated.py").write_text(
            "from generated import add_one\n\n"
            "def test_add_one():\n"
            "    assert add_one(1) == 2\n",
            encoding="utf-8",
        )
        task = CodingTask(
            task_id="missing_validation_evidence",
            repo_path=repo,
            prompt="Create generated.py, validate it, and then finish.",
            test_command="pytest -q -p no:cacheprovider",
            max_turns=6,
            metadata={"require_runtime_validation_evidence": True},
        )
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="Creating the file.",
                    call_id="c1",
                    name="create_file",
                    arguments={"path": "generated.py", "content": "def add_one(x):\n    return x + 1\n"},
                    response_id="resp_1",
                ),
                _native_response(
                    assistant_text="Done.",
                    call_id="c2",
                    name="finish",
                    arguments={"answer": "Done"},
                    response_id="resp_2",
                ),
                _native_response(
                    assistant_text="Validating.",
                    call_id="c3",
                    name="python_run",
                    arguments={"target": "pytest", "run_as_module": True, "args": ["-q", "-p", "no:cacheprovider", "test_generated.py"]},
                    response_id="resp_3",
                ),
                _native_response(
                    assistant_text="Validated and done.",
                    call_id="c4",
                    name="finish",
                    arguments={"answer": "Validated and done"},
                    response_id="resp_4",
                ),
            ]
        )
        output_dir = tmp_path / "output_missing_validation"

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.status == RunStatus.COMPLETED, trajectory.metadata
        assert [call.name for call in trajectory.tool_calls] == [
            "create_file",
            "finish",
            "python_run",
            "finish",
        ]
        assert trajectory.metadata["completion_evidence_status"] == "validated"
        assert trajectory.metadata["validation_phase"] == "validated"
        assert trajectory.metadata["last_successful_validation_turn"] == 3
        assert trajectory.metadata["last_validation_attempt_turn"] == 3
        assert trajectory.metadata["last_validation_failure_turn"] is None
        assert trajectory.metadata["last_mutation_turn"] == 1
        blocked_finish_observation = trajectory.observations[1]
        assert blocked_finish_observation.tool_name == "finish"
        assert blocked_finish_observation.result.is_error is True
        assert blocked_finish_observation.result.metadata["error_type"] == "completion_blocked"
        assert blocked_finish_observation.result.metadata["finish_block_reason"] == (
            "post_mutation_validation_pending"
        )
        assert blocked_finish_observation.result.metadata["finish_gate_reason"] == (
            "post_mutation_validation_pending"
        )
        assert blocked_finish_observation.result.metadata["completion_block_family"] == (
            "validation_evidence"
        )
        assert blocked_finish_observation.result.metadata["completion_allowed"] is False
        assert blocked_finish_observation.result.metadata["meaningful_progress_observed"] is True
        assert (
            blocked_finish_observation.result.metadata["expected_next_step"]
            == "validate"
        )
        assert (
            blocked_finish_observation.result.metadata["completion_gate_status"]
            == "blocked_missing_validation"
        )
        assert "Next step: validate." in blocked_finish_observation.result.content
        assert not any(
            message.metadata.get("message_kind") == "runtime_repair"
            and message.metadata.get("repair_kind", "").startswith("completion_blocked")
            for message in trajectory.messages
        )

        runtime_events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        deferred_finish = next(
            event
            for event in runtime_events
            if event["event_kind"] == "turn_stop_decision"
            and event["turn_index"] == 2
        )
        assert deferred_finish["data"]["should_stop"] is False
        assert (
            deferred_finish["data"]["decision_code"]
            == "defer_finish_missing_completion_evidence"
        )
        assert deferred_finish["data"]["policy_mode"] == "native_tools_light_stop_hook"
        assert deferred_finish["data"]["model_needs_follow_up"] is False
        assert deferred_finish["data"]["runtime_needs_follow_up"] is True
        assert deferred_finish["data"]["stop_hook_evaluated"] is True
        assert deferred_finish["data"]["stop_hook_blocked"] is True
        assert (
            deferred_finish["data"]["stop_hook_reason"]
            == "post_mutation_validation_pending"
        )
        assert deferred_finish["data"]["stop_hook_reason_code"] == "validation_required"
        assert (
            deferred_finish["data"]["continue_reason"]
            == "defer_completion_missing_completion_evidence"
        )
        assert deferred_finish["data"]["completion_evidence_status"] == "missing"
        assert deferred_finish["data"]["completion_block_family"] == (
            "validation_evidence"
        )
        assert deferred_finish["data"]["expected_next_step"] == "validate"
        assert (
            deferred_finish["data"]["completion_gate_status"]
            == "blocked_missing_validation"
        )
        assert deferred_finish["data"]["finish_blocked_by_policy"] is True
        assert deferred_finish["data"]["finish_block_reason"] == "post_mutation_validation_pending"
        assert deferred_finish["data"]["finish_gate_reason"] == "post_mutation_validation_pending"
        assert deferred_finish["data"]["finish_attempted"] is True
        assert deferred_finish["data"]["completion_allowed"] is False
        assert deferred_finish["data"]["validation_evidence_fresh"] is False
        assert deferred_finish["data"]["post_mutation_validation_pending"] is True
        assert deferred_finish["data"]["meaningful_progress_observed"] is True
        assert deferred_finish["data"]["recent_failure_kind"] is None
        assert deferred_finish["data"]["validation_phase_after_turn"] == "mutated_unvalidated"
        assert deferred_finish["data"]["turn_action"] == "finish_attempt"
        assert deferred_finish["data"]["turn_outcome"] == "finish_blocked_by_validation"
        assert deferred_finish["data"]["active_validation_issue_kind"] == (
            "finish_without_required_validation"
        )
        assert deferred_finish["data"]["active_validation_issue_id"] == "validation_issue_002"
        assert deferred_finish["data"]["finish_deferral_count"] == 1
        assert deferred_finish["data"]["last_mutation_turn"] == 1
        assert "workspace changes still need fresh validation" in deferred_finish["data"]["detail"]
        assert trajectory.metadata["blocked_finish_validation_evidence_count"] == 1
    finally:
        cleanup_test_path(tmp_path)


def test_validation_failure_then_finish_stays_deferred_until_rerun() -> None:
    tmp_path = make_unique_test_dir("runtime_stop_policy")
    try:
        repo = tmp_path / "repo_failed_validation"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "test_generated.py").write_text(
            "from generated import add_one\n\n"
            "def test_add_one():\n"
            "    assert add_one(1) == 2\n",
            encoding="utf-8",
        )
        task = CodingTask(
            task_id="failed_validation_evidence",
            repo_path=repo,
            prompt="Create generated.py, recover from failed validation, and only then finish.",
            test_command="pytest -q -p no:cacheprovider",
            max_turns=8,
            metadata={"require_runtime_validation_evidence": True},
        )
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="Creating the file.",
                    call_id="c1",
                    name="create_file",
                    arguments={"path": "generated.py", "content": "def add_one(x):\n    return x + 2\n"},
                    response_id="resp_1",
                ),
                _native_response(
                    assistant_text="Running validation.",
                    call_id="c2",
                    name="python_run",
                    arguments={"target": "pytest", "run_as_module": True, "args": ["-q", "-p", "no:cacheprovider", "test_generated.py"]},
                    response_id="resp_2",
                ),
                _native_response(
                    assistant_text="Done.",
                    call_id="c3",
                    name="finish",
                    arguments={"answer": "Done"},
                    response_id="resp_3",
                ),
                _native_response(
                    assistant_text="Revising the file.",
                    call_id="c4",
                    name="write_file",
                    arguments={"path": "generated.py", "content": "def add_one(x):\n    return x + 1\n"},
                    response_id="resp_4",
                ),
                _native_response(
                    assistant_text="Revalidating.",
                    call_id="c5",
                    name="python_run",
                    arguments={"target": "pytest", "run_as_module": True, "args": ["-q", "-p", "no:cacheprovider", "test_generated.py"]},
                    response_id="resp_5",
                ),
                _native_response(
                    assistant_text="Recovered and validated.",
                    call_id="c6",
                    name="finish",
                    arguments={"answer": "Recovered and validated"},
                    response_id="resp_6",
                ),
            ]
        )
        output_dir = tmp_path / "output_failed_validation"

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.status == RunStatus.COMPLETED, trajectory.metadata
        assert trajectory.metadata["completion_evidence_status"] == "validated"
        assert trajectory.metadata["validation_phase"] == "validated"
        assert trajectory.metadata["last_successful_validation_turn"] == 5
        assert trajectory.metadata["last_validation_attempt_turn"] == 5
        assert trajectory.metadata["last_validation_failure_turn"] == 2
        assert trajectory.metadata["validation_failure_count"] == 1
        assert trajectory.metadata["last_mutation_turn"] == 4
        blocked_finish_observation = trajectory.observations[2]
        assert blocked_finish_observation.tool_name == "finish"
        assert blocked_finish_observation.result.is_error is True
        assert blocked_finish_observation.result.metadata["error_type"] == "completion_blocked"
        assert blocked_finish_observation.result.metadata["finish_block_reason"] == (
            "unresolved_validation_failure"
        )
        assert blocked_finish_observation.result.metadata["active_failure_kind"] == (
            "validation_failure"
        )
        assert blocked_finish_observation.result.metadata["recent_failure_kind"] == (
            "validation_failure"
        )
        assert blocked_finish_observation.result.metadata["completion_block_family"] == (
            "pending_issue"
        )
        assert (
            blocked_finish_observation.result.metadata["expected_next_step"]
            == "revise"
        )
        assert (
            blocked_finish_observation.result.metadata["completion_gate_status"]
            == "blocked_pending_issue"
        )
        assert "Next step: revise." in blocked_finish_observation.result.content
        assert not any(
            message.metadata.get("message_kind") == "runtime_repair"
            and message.metadata.get("repair_kind", "").startswith("completion_blocked")
            for message in trajectory.messages
        )

        runtime_events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        deferred_finish = next(
            event
            for event in runtime_events
            if event["event_kind"] == "turn_stop_decision"
            and event["turn_index"] == 3
        )
        assert deferred_finish["data"]["should_stop"] is False
        assert deferred_finish["data"]["decision_code"] == "defer_finish_pending_issue"
        assert deferred_finish["data"]["policy_mode"] == "native_tools_light_stop_hook"
        assert deferred_finish["data"]["model_needs_follow_up"] is False
        assert deferred_finish["data"]["runtime_needs_follow_up"] is True
        assert deferred_finish["data"]["stop_hook_evaluated"] is True
        assert deferred_finish["data"]["stop_hook_blocked"] is True
        assert (
            deferred_finish["data"]["stop_hook_reason"]
            == "unresolved_validation_failure"
        )
        assert deferred_finish["data"]["stop_hook_reason_code"] == "pending_issue"
        assert deferred_finish["data"]["continue_reason"] == "defer_completion_pending_issue"
        assert deferred_finish["data"]["pending_issue_kind"] == "validation_failure"
        assert deferred_finish["data"]["completion_evidence_status"] == "missing"
        assert deferred_finish["data"]["completion_block_family"] == "pending_issue"
        assert deferred_finish["data"]["expected_next_step"] == "revise"
        assert (
            deferred_finish["data"]["completion_gate_status"]
            == "blocked_pending_issue"
        )
        assert deferred_finish["data"]["finish_blocked_by_policy"] is True
        assert deferred_finish["data"]["finish_block_reason"] == "unresolved_validation_failure"
        assert deferred_finish["data"]["finish_gate_reason"] == "unresolved_validation_failure"
        assert deferred_finish["data"]["finish_attempted"] is True
        assert deferred_finish["data"]["completion_allowed"] is False
        assert deferred_finish["data"]["validation_evidence_fresh"] is False
        assert deferred_finish["data"]["active_failure_kind"] == "validation_failure"
        assert deferred_finish["data"]["meaningful_progress_observed"] is True
        assert deferred_finish["data"]["recent_failure_kind"] == "validation_failure"
        assert deferred_finish["data"]["validation_phase_after_turn"] == "validation_failed"
        assert deferred_finish["data"]["turn_action"] == "finish_attempt"
        assert deferred_finish["data"]["turn_outcome"] == "finish_blocked_by_validation"
        assert deferred_finish["data"]["active_validation_issue_kind"] == (
            "validation_command_nonzero_exit"
        )
        assert deferred_finish["data"]["active_validation_issue_id"] == "validation_issue_002"
        assert deferred_finish["data"]["validation_attempt_count"] == 1
        assert deferred_finish["data"]["finish_deferral_count"] == 1
        assert deferred_finish["data"]["last_validation_attempt_turn"] == 2
        assert deferred_finish["data"]["last_validation_failure_turn"] == 2
        assert deferred_finish["data"]["last_mutation_turn"] == 1
        assert trajectory.metadata["blocked_finish_pending_issue_count"] == 1

        final_stop = next(
            event
            for event in runtime_events
            if event["event_kind"] == "turn_stop_decision"
            and event["turn_index"] == 6
        )
        assert final_stop["data"]["should_stop"] is True
        assert final_stop["data"]["reason"] == "finish"
        assert final_stop["data"]["policy_mode"] == "native_tools_light_stop_hook"
        assert final_stop["data"]["model_needs_follow_up"] is False
        assert final_stop["data"]["runtime_needs_follow_up"] is False
        assert final_stop["data"]["stop_hook_evaluated"] is True
        assert final_stop["data"]["stop_hook_blocked"] is False
        assert final_stop["data"]["stop_hook_reason"] is None
        assert final_stop["data"]["stop_hook_reason_code"] == "none"
        assert final_stop["data"]["completion_block_family"] == "none"
        assert final_stop["data"]["completion_evidence_status"] == "validated"
        assert final_stop["data"]["expected_next_step"] == "finish_allowed"
        assert final_stop["data"]["completion_gate_status"] == "open"
        assert final_stop["data"]["finish_blocked_by_policy"] is False
        assert final_stop["data"]["finish_block_reason"] is None
        assert final_stop["data"]["completion_allowed"] is True
        assert final_stop["data"]["validation_evidence_fresh"] is True
        assert final_stop["data"]["finish_attempted"] is True
        assert final_stop["data"]["meaningful_progress_observed"] is True
        assert final_stop["data"]["validation_phase_after_turn"] == "validated"
        assert final_stop["data"]["turn_action"] == "finish_attempt"
        assert final_stop["data"]["turn_outcome"] == "finish_accepted"
        assert final_stop["data"]["active_validation_issue_kind"] == (
            "validation_command_nonzero_exit"
        )
        assert final_stop["data"]["active_validation_issue_id"] is None
        assert final_stop["data"]["validation_attempt_count"] == 2
        assert final_stop["data"]["revision_attempt_count"] == 1
        assert final_stop["data"]["last_successful_validation_turn"] == 5
        assert final_stop["data"]["last_validation_attempt_turn"] == 5
        assert final_stop["data"]["last_validation_failure_turn"] == 2
        assert final_stop["data"]["last_mutation_turn"] == 4
    finally:
        cleanup_test_path(tmp_path)


def test_finish_without_runtime_validation_requirement_is_not_gated() -> None:
    tmp_path = make_unique_test_dir("runtime_stop_policy")
    try:
        workspace = tmp_path / "workspace_no_gate"
        workspace.mkdir(parents=True, exist_ok=True)
        task = CodingTask(
            task_id="no_runtime_validation_gate",
            repo_path=workspace,
            prompt="Update a file and finish.",
            max_turns=4,
        )
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="Creating the note.",
                    call_id="c1",
                    name="create_file",
                    arguments={"path": "note.txt", "content": "hello\n"},
                    response_id="resp_1",
                ),
                _native_response(
                    assistant_text="Done.",
                    call_id="c2",
                    name="finish",
                    arguments={"answer": "Done"},
                    response_id="resp_2",
                ),
            ]
        )

        _, profile, runtime = build_base_tool_runtime()
        ctx = ToolContext(workspace_root=workspace, task=task)
        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        assert trajectory.status == RunStatus.COMPLETED
        assert trajectory.metadata["stop_reason"] == "finish"
        assert trajectory.metadata["completion_evidence_status"] == "not_required"
        assert trajectory.metadata["validation_phase"] == "mutated_unvalidated"
        assert trajectory.metadata["expected_next_step"] == "finish_allowed"
        assert trajectory.metadata["completion_gate_status"] == "open"
        assert trajectory.metadata["finish_blocked_by_policy"] is False
        assert [call.name for call in trajectory.tool_calls] == ["create_file", "finish"]
    finally:
        cleanup_test_path(tmp_path)


def test_validation_failure_then_revision_only_still_requires_revalidation() -> None:
    tmp_path = make_unique_test_dir("runtime_stop_policy")
    try:
        repo = tmp_path / "repo_revision_without_revalidation"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "test_generated.py").write_text(
            "from generated import add_one\n\n"
            "def test_add_one():\n"
            "    assert add_one(1) == 2\n",
            encoding="utf-8",
        )
        task = CodingTask(
            task_id="revision_without_revalidation",
            repo_path=repo,
            prompt="Fix validation failures, but do not finish until revalidation passes.",
            test_command="pytest -q -p no:cacheprovider",
            max_turns=8,
            metadata={"require_runtime_validation_evidence": True},
        )
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="Create the file.",
                    call_id="c1",
                    name="create_file",
                    arguments={"path": "generated.py", "content": "def add_one(x):\n    return x + 2\n"},
                    response_id="resp_1",
                ),
                _native_response(
                    assistant_text="Validate it.",
                    call_id="c2",
                    name="python_run",
                    arguments={"target": "pytest", "run_as_module": True, "args": ["-q", "-p", "no:cacheprovider", "test_generated.py"]},
                    response_id="resp_2",
                ),
                _native_response(
                    assistant_text="Apply the fix.",
                    call_id="c3",
                    name="write_file",
                    arguments={"path": "generated.py", "content": "def add_one(x):\n    return x + 1\n"},
                    response_id="resp_3",
                ),
                _native_response(
                    assistant_text="Done now.",
                    call_id="c4",
                    name="finish",
                    arguments={"answer": "Done now"},
                    response_id="resp_4",
                ),
                _native_response(
                    assistant_text="Revalidate.",
                    call_id="c5",
                    name="python_run",
                    arguments={"target": "pytest", "run_as_module": True, "args": ["-q", "-p", "no:cacheprovider", "test_generated.py"]},
                    response_id="resp_5",
                ),
                _native_response(
                    assistant_text="Done after revalidation.",
                    call_id="c6",
                    name="finish",
                    arguments={"answer": "Done after revalidation"},
                    response_id="resp_6",
                ),
            ]
        )
        output_dir = tmp_path / "output_revision_without_revalidation"

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.status == RunStatus.COMPLETED, trajectory.metadata
        runtime_events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        blocked_finish = next(
            event
            for event in runtime_events
            if event["event_kind"] == "turn_stop_decision"
            and event["turn_index"] == 4
        )
        assert blocked_finish["data"]["should_stop"] is False
        assert blocked_finish["data"]["completion_block_family"] == "pending_issue"
        assert blocked_finish["data"]["finish_block_reason"] == "unresolved_validation_failure"
        assert blocked_finish["data"]["expected_next_step"] == "revalidate"
        assert blocked_finish["data"]["validation_phase_after_turn"] == "validation_failed"
        assert blocked_finish["data"]["revision_attempt_count"] == 1
        assert blocked_finish["data"]["last_mutation_turn"] == 3

        blocked_finish_observation = trajectory.observations[3]
        assert blocked_finish_observation.tool_name == "finish"
        assert blocked_finish_observation.result.metadata["completion_block_family"] == (
            "pending_issue"
        )
        assert blocked_finish_observation.result.metadata["expected_next_step"] == (
            "revalidate"
        )
    finally:
        cleanup_test_path(tmp_path)


def test_recoverable_tool_failure_then_successful_retry_allows_finish() -> None:
    tmp_path = make_unique_test_dir("runtime_stop_policy")
    try:
        workspace = tmp_path / "workspace_recoverable_tool_failure"
        workspace.mkdir(parents=True, exist_ok=True)
        task = CodingTask(
            task_id="recoverable_tool_failure_then_finish",
            repo_path=workspace,
            prompt="Recover from a tool failure, create a file, and only then finish.",
            max_turns=5,
        )
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="Read the wrong file first.",
                    call_id="c1",
                    name="read_file",
                    arguments={"path": "missing.txt"},
                    response_id="resp_1",
                ),
                _native_response(
                    assistant_text="Create the recovery file.",
                    call_id="c2",
                    name="create_file",
                    arguments={"path": "recovered.txt", "content": "ok\n"},
                    response_id="resp_2",
                ),
                _native_response(
                    assistant_text="Done.",
                    call_id="c3",
                    name="finish",
                    arguments={"answer": "Done"},
                    response_id="resp_3",
                ),
            ]
        )
        output_dir = tmp_path / "output_recoverable_tool_failure"

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.metadata["stop_reason"] == "finish"
        assert trajectory.metadata["stop_decision_code"] == "finish"
        runtime_events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        final_stop = next(
            event
            for event in runtime_events
            if event["event_kind"] == "turn_stop_decision"
            and event["turn_index"] == 3
        )
        assert final_stop["data"]["should_stop"] is True
        assert final_stop["data"]["completion_block_family"] == "none"
        assert final_stop["data"]["reason"] == "finish"
        assert final_stop["data"]["active_failure_kind"] is None
        first_stop = next(
            event
            for event in runtime_events
            if event["event_kind"] == "turn_stop_decision"
            and event["turn_index"] == 1
        )
        assert first_stop["data"]["completion_block_family"] == "pending_issue"
        assert first_stop["data"]["active_failure_kind"] == "tool_failure"
        assert trajectory.metadata["meaningful_progress_observed"] is True
    finally:
        cleanup_test_path(tmp_path)


def test_no_tool_call_completion_with_stale_validation_evidence_is_blocked() -> None:
    tmp_path = make_unique_test_dir("runtime_stop_policy")
    try:
        repo = tmp_path / "repo_stale_no_tool_completion"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "test_generated.py").write_text(
            "from generated import add_one\n\n"
            "def test_add_one():\n"
            "    assert add_one(1) == 2\n",
            encoding="utf-8",
        )
        task = CodingTask(
            task_id="stale_no_tool_completion",
            repo_path=repo,
            prompt="Validate, mutate again, then avoid finishing until you revalidate.",
            test_command="pytest -q -p no:cacheprovider",
            max_turns=7,
            metadata={"require_runtime_validation_evidence": True},
        )
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="Create the file.",
                    call_id="c1",
                    name="create_file",
                    arguments={"path": "generated.py", "content": "def add_one(x):\n    return x + 1\n"},
                    response_id="resp_1",
                ),
                _native_response(
                    assistant_text="Validate it.",
                    call_id="c2",
                    name="python_run",
                    arguments={"target": "pytest", "run_as_module": True, "args": ["-q", "-p", "no:cacheprovider", "test_generated.py"]},
                    response_id="resp_2",
                ),
                _native_response(
                    assistant_text="Change the file again.",
                    call_id="c3",
                    name="write_file",
                    arguments={"path": "generated.py", "content": "def add_one(x):\n    return x + 1\n# formatting change\n"},
                    response_id="resp_3",
                ),
                _native_response(
                    assistant_text="Done without another tool call.",
                    response_id="resp_4",
                ),
                _native_response(
                    assistant_text="Revalidate now.",
                    call_id="c5",
                    name="python_run",
                    arguments={"target": "pytest", "run_as_module": True, "args": ["-q", "-p", "no:cacheprovider", "test_generated.py"]},
                    response_id="resp_5",
                ),
                _native_response(
                    assistant_text="Done after fresh validation.",
                    call_id="c6",
                    name="finish",
                    arguments={"answer": "Done after fresh validation"},
                    response_id="resp_6",
                ),
            ]
        )
        output_dir = tmp_path / "output_stale_no_tool_completion"

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.status == RunStatus.COMPLETED, trajectory.metadata
        runtime_events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        blocked_completion = next(
            event
            for event in runtime_events
            if event["event_kind"] == "turn_stop_decision"
            and event["turn_index"] == 4
        )
        assert blocked_completion["data"]["should_stop"] is False
        assert blocked_completion["data"]["decision_code"] == (
            "defer_no_tool_calls_missing_completion_evidence"
        )
        assert blocked_completion["data"]["completion_block_family"] == (
            "validation_evidence"
        )
        assert blocked_completion["data"]["finish_block_reason"] == (
            "post_mutation_validation_pending"
        )
        assert blocked_completion["data"]["expected_next_step"] == "validate"
        assert blocked_completion["data"]["finish_attempted"] is True
    finally:
        cleanup_test_path(tmp_path)


def test_repeated_inspect_then_finish_is_blocked_for_no_meaningful_progress() -> None:
    tmp_path = make_unique_test_dir("runtime_stop_policy")
    try:
        workspace = tmp_path / "workspace_no_progress"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "note.txt").write_text("hello\n", encoding="utf-8")
        task = CodingTask(
            task_id="no_meaningful_progress",
            repo_path=workspace,
            prompt="Inspect the file before finishing.",
            max_turns=4,
        )
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="Inspecting once.",
                    call_id="c1",
                    name="read_file",
                    arguments={"path": "note.txt"},
                    response_id="resp_1",
                ),
                _native_response(
                    assistant_text="Inspecting twice.",
                    call_id="c2",
                    name="read_file",
                    arguments={"path": "note.txt"},
                    response_id="resp_2",
                ),
                _native_response(
                    assistant_text="Done.",
                    call_id="c3",
                    name="finish",
                    arguments={"answer": "Done"},
                    response_id="resp_3",
                ),
                _native_response(
                    assistant_text="Still done.",
                    call_id="c4",
                    name="finish",
                    arguments={"answer": "Still done"},
                    response_id="resp_4",
                ),
            ]
        )
        output_dir = tmp_path / "output_no_progress"

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.status == RunStatus.FAILED
        assert trajectory.metadata["finish_attempt_count"] == 2
        assert trajectory.metadata["finish_blocked_count"] == 1
        assert trajectory.metadata["finish_block_reason"] == "no_meaningful_progress"
        assert trajectory.metadata["finish_without_progress_count"] == 2
        assert trajectory.metadata["meaningful_progress_observed"] is False
        assert "finish_without_progress" in trajectory.metadata["observed_failure_buckets"]
        assert "no_meaningful_progress" in trajectory.metadata["observed_failure_buckets"]

        blocked_finish_observation = trajectory.observations[2]
        assert blocked_finish_observation.tool_name == "finish"
        assert blocked_finish_observation.result.metadata["finish_block_reason"] == (
            "no_meaningful_progress"
        )
        assert blocked_finish_observation.result.metadata["completion_block_family"] == (
            "progress_gate"
        )
        assert blocked_finish_observation.result.metadata["expected_next_step"] == (
            "retry_parse_or_tool"
        )
        assert blocked_finish_observation.result.metadata["meaningful_progress_observed"] is False

        runtime_events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        blocked_stop = next(
            event
            for event in runtime_events
            if event["event_kind"] == "turn_stop_decision"
            and event["turn_index"] == 3
        )
        assert blocked_stop["data"]["should_stop"] is False
        assert blocked_stop["data"]["finish_blocked_by_policy"] is True
        assert blocked_stop["data"]["finish_block_reason"] == "no_meaningful_progress"
        assert blocked_stop["data"]["completion_block_family"] == "progress_gate"
        assert blocked_stop["data"]["finish_attempted"] is True
        assert blocked_stop["data"]["meaningful_progress_observed"] is False
        assert blocked_stop["data"]["stop_hook_evaluated"] is True
        assert blocked_stop["data"]["stop_hook_blocked"] is True
        assert blocked_stop["data"]["stop_hook_reason"] == "no_meaningful_progress"
        assert blocked_stop["data"]["stop_hook_reason_code"] == "no_progress"

        final_stop = next(
            event
            for event in runtime_events
            if event["event_kind"] == "turn_stop_decision"
            and event["turn_index"] == 4
        )
        assert final_stop["data"]["reason"] == "max_turns"
        assert final_stop["data"]["stop_hook_evaluated"] is False
        assert final_stop["data"]["stop_hook_blocked"] is False
        assert final_stop["data"]["stop_hook_reason_code"] == "none"
        assert trajectory.metadata["blocked_finish_progress_gate_count"] == 1
    finally:
        cleanup_test_path(tmp_path)


def test_repeated_finish_deferrals_exhaust_budget() -> None:
    tmp_path = make_unique_test_dir("runtime_stop_policy")
    try:
        repo = tmp_path / "repo_finish_budget"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "test_generated.py").write_text(
            "from generated import add_one\n\n"
            "def test_add_one():\n"
            "    assert add_one(1) == 2\n",
            encoding="utf-8",
        )
        task = CodingTask(
            task_id="finish_budget_exhausted",
            repo_path=repo,
            prompt="Create generated.py and do not stop until validation evidence exists.",
            test_command="pytest -q -p no:cacheprovider",
            max_turns=6,
            metadata={"require_runtime_validation_evidence": True},
        )
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="Creating the file.",
                    call_id="c1",
                    name="create_file",
                    arguments={"path": "generated.py", "content": "def add_one(x):\n    return x + 1\n"},
                    response_id="resp_1",
                ),
                _native_response(
                    assistant_text="Done.",
                    call_id="c2",
                    name="finish",
                    arguments={"answer": "Done"},
                    response_id="resp_2",
                ),
                _native_response(
                    assistant_text="Still done.",
                    call_id="c3",
                    name="finish",
                    arguments={"answer": "Still done"},
                    response_id="resp_3",
                ),
                _native_response(
                    assistant_text="Really done.",
                    call_id="c4",
                    name="finish",
                    arguments={"answer": "Really done"},
                    response_id="resp_4",
                ),
            ]
        )
        output_dir = tmp_path / "output_finish_budget"

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.status == RunStatus.FAILED
        assert trajectory.metadata["stop_reason"] == "finish_deferral_budget_exhausted"
        assert trajectory.metadata["finish_deferral_count"] == 3
        runtime_events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        final_stop = next(
            event
            for event in runtime_events
            if event["event_kind"] == "turn_stop_decision"
            and event["turn_index"] == 4
        )
        assert final_stop["data"]["should_stop"] is True
        assert final_stop["data"]["reason"] == "finish_deferral_budget_exhausted"
        assert final_stop["data"]["decision_code"] == "finish_deferral_budget_exhausted"
        assert final_stop["data"]["turn_outcome"] == "finish_deferral_budget_exhausted"
        assert final_stop["data"]["finish_deferral_count"] == 3
    finally:
        cleanup_test_path(tmp_path)


def test_repeated_validation_failures_exhaust_validation_budget() -> None:
    tmp_path = make_unique_test_dir("runtime_stop_policy")
    try:
        repo = tmp_path / "repo_validation_budget"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "test_generated.py").write_text(
            "from generated import add_one\n\n"
            "def test_add_one():\n"
            "    assert add_one(1) == 2\n",
            encoding="utf-8",
        )
        task = CodingTask(
            task_id="validation_budget_exhausted",
            repo_path=repo,
            prompt="Create generated.py and keep rerunning validation until the runtime stops you.",
            test_command="pytest -q -p no:cacheprovider",
            max_turns=6,
            metadata={"require_runtime_validation_evidence": True},
        )
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="Creating the file.",
                    call_id="c1",
                    name="create_file",
                    arguments={"path": "generated.py", "content": "def add_one(x):\n    return x + 2\n"},
                    response_id="resp_1",
                ),
                _native_response(
                    assistant_text="Validation attempt one.",
                    call_id="c2",
                    name="python_run",
                    arguments={"target": "pytest", "run_as_module": True, "args": ["-q", "-p", "no:cacheprovider", "test_generated.py"]},
                    response_id="resp_2",
                ),
                _native_response(
                    assistant_text="Validation attempt two.",
                    call_id="c3",
                    name="python_run",
                    arguments={"target": "pytest", "run_as_module": True, "args": ["-q", "-p", "no:cacheprovider", "test_generated.py"]},
                    response_id="resp_3",
                ),
                _native_response(
                    assistant_text="Validation attempt three.",
                    call_id="c4",
                    name="python_run",
                    arguments={"target": "pytest", "run_as_module": True, "args": ["-q", "-p", "no:cacheprovider", "test_generated.py"]},
                    response_id="resp_4",
                ),
            ]
        )
        output_dir = tmp_path / "output_validation_budget"

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.status == RunStatus.FAILED
        assert trajectory.metadata["stop_reason"] == "validation_budget_exhausted"
        assert trajectory.metadata["validation_attempt_count"] == 3
        runtime_events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        final_stop = next(
            event
            for event in runtime_events
            if event["event_kind"] == "turn_stop_decision"
            and event["turn_index"] == 4
        )
        assert final_stop["data"]["should_stop"] is True
        assert final_stop["data"]["reason"] == "validation_budget_exhausted"
        assert final_stop["data"]["decision_code"] == "validation_budget_exhausted"
        assert final_stop["data"]["turn_outcome"] == "validation_budget_exhausted"
        assert final_stop["data"]["validation_attempt_count"] == 3
    finally:
        cleanup_test_path(tmp_path)
