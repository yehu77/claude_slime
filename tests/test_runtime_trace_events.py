from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.agent.llm_client import (
    FakeLLMClient,
    GenerateResponse,
    RuntimeClientCapabilities,
    ToolCallCandidate,
)
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.tools.bootstrap import build_builtin_registry


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (repo / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return repo


def _native_response(
    *,
    assistant_text: str = "",
    call_id: str | None = None,
    name: str | None = None,
    arguments: dict | None = None,
    finish_reason: str | None = None,
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
        finish_reason=finish_reason or ("tool_calls" if tool_calls else "stop"),
        response_id=response_id,
    )


def test_local_runtime_emits_native_trace_bundle_and_tool_mapping() -> None:
    tmp_path = make_unique_test_dir("runtime_trace_events")
    try:
        repo = _make_repo(tmp_path)
        output_dir = tmp_path / "output"
        task = CodingTask(
            task_id="trace_task",
            repo_path=repo,
            prompt="Inspect main.py and finish.",
            max_turns=5,
        )
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="I will inspect the file.",
                    call_id="c1",
                    name="read_file",
                    arguments={"path": "main.py"},
                    response_id="resp_native_1",
                ),
                _native_response(
                    assistant_text="Done.",
                    call_id="c2",
                    name="finish",
                    arguments={"answer": "Done"},
                    response_id="resp_native_2",
                ),
            ],
            capabilities=RuntimeClientCapabilities(
                protocol_mode="native_tool_calling",
                supports_native_tools=True,
                text_fallback_allowed=False,
                structured_finish_mode="finish_tool_call",
                provider_family="fake",
                provider_name="fake_native",
            ),
            provenance={"provider_kind": "fake", "client_mode": "fake_native_tools"},
        )

        trajectory = run_coding_task(task, client, output_dir)
        assert trajectory.status.value == "completed"
        assert (output_dir / "retained_history.jsonl").exists()
        assert (output_dir / "retained_history_manifest.json").exists()
        assert (output_dir / "request_context.jsonl").exists()
        assert (output_dir / "request_context_manifest.json").exists()
        assert (output_dir / "history_evolution_report.json").exists()
        assert (output_dir / "history_lineage_report.json").exists()
        assert (output_dir / "history_reconciliation_report.json").exists()
        assert (output_dir / "compaction_chain_report.json").exists()
        assert trajectory.metadata["history_evolution_report_ok"] is True
        assert trajectory.metadata["history_lineage_report_ok"] is True
        assert trajectory.metadata["history_reconciliation_report_ok"] is True
        assert trajectory.metadata["compaction_chain_report_ok"] is True

        request_context_rows = _load_jsonl(output_dir / "request_context.jsonl")
        assert [row["turn_index"] for row in request_context_rows] == [1, 2]
        assert request_context_rows[0]["policy_mode"] == "full_history"
        assert request_context_rows[0]["request_message_count"] == 2
        assert request_context_rows[0]["compaction_considered"] is False
        assert request_context_rows[0]["compaction_considered_reason"] == "full_history_policy"
        assert request_context_rows[1]["request_message_count"] == 4

        events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        event_kinds = [event["event_kind"] for event in events]
        assert event_kinds[0] == "tool_profile_exposed"
        assert "context_selection_planned" in event_kinds
        assert "provider_response_interpreted" in event_kinds
        assert "assistant_parse_completed" in event_kinds
        assert "tool_call_mapping_completed" in event_kinds
        assert event_kinds[-1] == "run_completed"

        run_started = next(event for event in events if event["event_kind"] == "run_started")
        assert run_started["data"]["provider"]["client_mode"] == "fake_native_tools"
        assert run_started["data"]["provider"]["protocol_mode"] == "native_tool_calling"
        assert run_started["data"]["provider"]["text_fallback_allowed"] is False

        interpreted = next(
            event for event in events if event["event_kind"] == "provider_response_interpreted"
        )
        assert interpreted["data"]["transport_mode"] == "native_tool_calling"
        assert interpreted["data"]["protocol_decision"] == "accept_native"
        assert interpreted["data"]["fallback_parser_used"] is False
        assert interpreted["data"]["text_fallback_used"] is False
        assert interpreted["data"]["accepted_tool_call_count"] == 1
        assert interpreted["data"]["rejected_tool_call_candidate_count"] == 0

        parsed = next(event for event in events if event["event_kind"] == "assistant_parse_completed")
        assert parsed["data"]["format_family"] == "native_tool_calling"
        assert parsed["data"]["protocol_decision"] == "accept_native"
        assert parsed["data"]["tool_call_count"] == 1
        completed = next(
            event
            for event in events
            if event["event_kind"] == "tool_execution_completed" and event["tool_call_id"] == "c1"
        )
        assert completed["data"]["execution_kind"] == "file_read"
        assert completed["data"]["execution_stage"] == "result_finalize"
        assert completed["data"]["policy_decision"] == "allow"
        assert completed["data"]["policy_domain"] == "filesystem"
        assert completed["data"]["target_file_count"] == 1

        request_built = next(
            event for event in events if event["event_kind"] == "model_request_built"
        )
        context_planned = next(
            event for event in events if event["event_kind"] == "context_selection_planned"
        )
        assert context_planned["data"]["policy_mode"] == "full_history"
        assert context_planned["data"]["compaction_decision"] == "skipped"
        assert context_planned["data"]["compaction_considered"] is False
        assert context_planned["data"]["compaction_considered_reason"] == "full_history_policy"
        context_skipped = next(
            event for event in events if event["event_kind"] == "context_compaction_skipped"
        )
        assert context_skipped["data"]["policy_mode"] == "full_history"
        assert context_skipped["data"]["compaction_applied"] is False
        assert context_skipped["data"]["compaction_considered"] is False
        assert request_built["data"]["selected_retained_entry_ids"] == [
            "retained_entry_000001",
            "retained_entry_000002",
        ]
        assert request_built["data"]["retained_entry_count_before_snapshot"] == 2
        assert request_built["data"]["context_selection_retained_entry_id"] == "retained_entry_000003"
        assert request_built["data"]["retained_history_last_entry_id"] == "retained_entry_000003"

        turn_stop = next(event for event in events if event["event_kind"] == "turn_stop_decision")
        assert turn_stop["data"]["continuation_decision_kind"] == "continue_with_tool_calls"
        assert turn_stop["data"]["policy_mode"] == "native_tools_light_stop_hook"
        assert turn_stop["data"]["completion_block_family"] == "none"
        assert turn_stop["data"]["model_needs_follow_up"] is True
        assert turn_stop["data"]["runtime_needs_follow_up"] is False
        assert turn_stop["data"]["stop_hook_evaluated"] is False
        assert turn_stop["data"]["stop_hook_blocked"] is False
        assert turn_stop["data"]["stop_hook_reason"] is None
        assert turn_stop["data"]["stop_hook_reason_code"] == "none"
        assert turn_stop["data"]["session_continuation_turn_count"] == 1
        assert turn_stop["data"]["validation_budget_remaining"] == 2
        assert turn_stop["data"]["retained_history_last_entry_id"] == "retained_entry_000003"
        assert turn_stop["data"]["retained_entry_count"] == 3

        run_completed = next(event for event in events if event["event_kind"] == "run_completed")
        assert run_completed["data"]["session_outcome"]["session_termination_kind"] == "completed"
        assert run_completed["data"]["last_turn_continuation"]["continuation_decision_kind"] == "stop_finish"
        assert run_completed["data"]["last_turn_continuation"]["policy_mode"] == (
            "native_tools_light_stop_hook"
        )
        assert run_completed["data"]["last_turn_continuation"]["completion_block_family"] == "none"
        assert run_completed["data"]["last_turn_continuation"]["model_needs_follow_up"] is False
        assert run_completed["data"]["last_turn_continuation"]["runtime_needs_follow_up"] is False
        assert run_completed["data"]["last_turn_continuation"]["stop_hook_evaluated"] is True
        assert run_completed["data"]["last_turn_continuation"]["stop_hook_blocked"] is False
        assert run_completed["data"]["last_turn_continuation"]["stop_hook_reason_code"] == "none"
        assert run_completed["data"]["budget_snapshot"]["validation_budget_total"] == 2
        assert run_completed["data"]["retained_history"]["retained_entry_count"] == 8
        assert run_completed["data"]["retained_history"]["entry_counts_by_kind"] == {
            "source_message": 6,
            "history_control": 2,
        }

        mapped = next(
            event
            for event in events
            if event["event_kind"] == "tool_call_mapping_completed" and event["tool_call_id"] == "c1"
        )
        assert mapped["data"]["exposed_tool_name"] == "read_file"
        assert mapped["data"]["canonical_tool_name"] == "read_file"
        assert mapped["data"]["mapping_valid"] is True
    finally:
        cleanup_test_path(tmp_path)


def test_native_protocol_error_is_recorded_without_text_fallback() -> None:
    tmp_path = make_unique_test_dir("runtime_trace_events")
    try:
        repo = _make_repo(tmp_path)
        output_dir = tmp_path / "output_protocol_error"
        task = CodingTask(
            task_id="trace_protocol_error_task",
            repo_path=repo,
            prompt="Recover from malformed native tool calls and then finish.",
            max_turns=5,
        )
        client = FakeLLMClient(
            responses=[
                GenerateResponse.from_native_tool_calling(
                    assistant_text="I will inspect the file.",
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
                    assistant_text="Retrying.",
                    call_id="c2",
                    name="read_file",
                    arguments={"path": "main.py"},
                    response_id="resp_ok",
                ),
                _native_response(
                    assistant_text="Done.",
                    call_id="c3",
                    name="finish",
                    arguments={"answer": "Done"},
                    response_id="resp_finish",
                ),
            ],
            capabilities=RuntimeClientCapabilities(
                protocol_mode="native_tool_calling",
                supports_native_tools=True,
                text_fallback_allowed=False,
                structured_finish_mode="finish_tool_call",
                provider_family="fake",
                provider_name="fake_native",
            ),
        )

        trajectory = run_coding_task(task, client, output_dir)
        assert trajectory.status.value == "completed"

        events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        first_interpreted = next(
            event
            for event in events
            if event["event_kind"] == "provider_response_interpreted" and event["turn_index"] == 1
        )
        assert first_interpreted["data"]["protocol_decision"] == "protocol_error"
        assert first_interpreted["data"]["protocol_error_kind"] == "candidate_validation_error"
        assert first_interpreted["data"]["text_fallback_used"] is False
        assert first_interpreted["data"]["fallback_allowed"] is False
        assert first_interpreted["data"]["accepted_tool_call_count"] == 0
        assert first_interpreted["data"]["rejected_tool_call_candidate_count"] == 1

        first_parse = next(
            event
            for event in events
            if event["event_kind"] == "assistant_parse_completed" and event["turn_index"] == 1
        )
        assert first_parse["data"]["protocol_decision"] == "protocol_error"
        assert first_parse["data"]["protocol_error_kind"] == "candidate_validation_error"
        assert first_parse["data"]["tool_call_count"] == 0

        assert not any(
            event["event_kind"] == "tool_execution_started" and event["turn_index"] == 1
            for event in events
        )

        stop_event = next(
            event
            for event in events
            if event["event_kind"] == "turn_stop_decision" and event["turn_index"] == 1
        )
        payload_ref = stop_event["payload_refs"][0]["path"]
        turn_state = _load_json(output_dir / payload_ref)
        assert turn_state["phases_reached"] == [
            "turn_started",
            "request_built",
            "provider_response_received",
            "response_interpreted",
            "assistant_parsed",
            "tool_dispatch",
            "post_tool_observation",
            "stop_decided",
            "turn_completed",
        ]
        assert turn_state["provider_response_received"] is True
        assert turn_state["response_interpreted"] is True
        assert turn_state["assistant_parse_completed"] is True
        assert turn_state["tool_dispatch_entered"] is True
        assert turn_state["stop_decision_frozen"] is True
    finally:
        cleanup_test_path(tmp_path)


def test_runtime_trace_preserves_exposed_and_canonical_names_for_mutated_profile() -> None:
    tmp_path = make_unique_test_dir("runtime_trace_events")
    try:
        repo = _make_repo(tmp_path)
        output_dir = tmp_path / "output_mutated"
        task = CodingTask(
            task_id="trace_mutated_task",
            repo_path=repo,
            prompt="Inspect main.py and finish under a mutated tool profile.",
            max_turns=5,
        )
        registry = build_builtin_registry()
        profile = ToolProfileSampler(seed=0).sample("name_description_schema")
        read_call = profile.project_canonical_call(
            "read_file",
            {"path": "main.py"},
            call_id="c1",
            canonical_tool=registry.get("read_file"),
        )
        finish_call = profile.project_canonical_call(
            "finish",
            {"answer": "Done"},
            call_id="c2",
            canonical_tool=registry.get("finish"),
        )
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="I will inspect the file.",
                    call_id=read_call.call_id,
                    name=read_call.name,
                    arguments=read_call.arguments,
                    response_id="resp_1",
                ),
                _native_response(
                    assistant_text="Done.",
                    call_id=finish_call.call_id,
                    name=finish_call.name,
                    arguments=finish_call.arguments,
                    response_id="resp_2",
                ),
            ]
        )

        trajectory = run_coding_task(
            task,
            client,
            output_dir,
            profile_mode="name_description_schema",
            profile_seed=0,
        )
        assert trajectory.status.value == "completed"

        events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        profile_event = next(event for event in events if event["event_kind"] == "tool_profile_exposed")
        assert profile_event["data"]["profile_mode"] == "name_description_schema"
        assert profile_event["data"]["tool_order"] != profile_event["data"]["canonical_tool_order"]

        mapped = next(
            event
            for event in events
            if event["event_kind"] == "tool_call_mapping_completed" and event["tool_call_id"] == "c1"
        )
        assert mapped["data"]["exposed_tool_name"] == read_call.name
        assert mapped["data"]["canonical_tool_name"] == "read_file"
    finally:
        cleanup_test_path(tmp_path)


def test_runtime_trace_captures_tail_window_context_selection() -> None:
    tmp_path = make_unique_test_dir("runtime_trace_events")
    try:
        repo = _make_repo(tmp_path)
        output_dir = tmp_path / "output_tail_window"
        task = CodingTask(
            task_id="trace_tail_window_task",
            repo_path=repo,
            prompt="Inspect main.py, list files, inspect again, and finish.",
            max_turns=6,
        )
        client = FakeLLMClient(
            responses=[
                _native_response(call_id="c1", name="read_file", arguments={"path": "main.py"}, response_id="resp_1"),
                _native_response(call_id="c2", name="list_files", arguments={"path": "."}, response_id="resp_2"),
                _native_response(call_id="c3", name="read_file", arguments={"path": "main.py"}, response_id="resp_3"),
                _native_response(call_id="c4", name="finish", arguments={"answer": "Done"}, response_id="resp_4"),
            ]
        )

        trajectory = run_coding_task(
            task,
            client,
            output_dir,
            context_policy_mode="tail_window",
            context_max_messages=4,
        )
        assert trajectory.status.value == "completed"

        events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        tail_request = next(
            event
            for event in events
            if event["event_kind"] == "model_request_built" and event["turn_index"] == 3
        )
        tail_applied = next(
            event
            for event in events
            if event["event_kind"] == "context_compaction_applied"
            and event["turn_index"] == 3
        )
        assert tail_applied["data"]["policy_mode"] == "tail_window"
        assert tail_applied["data"]["compaction_reason"] == "tail_window_truncation"
        assert tail_request["data"]["included_message_indices"] == [0, 1, 4, 5]
        assert tail_request["data"]["omitted_message_count"] == 2
        assert tail_request["data"]["compaction_applied"] is True
        assert tail_request["data"]["compaction_reason"] == "tail_window_truncation"
    finally:
        cleanup_test_path(tmp_path)


def test_runtime_trace_captures_deterministic_compaction_retained_history() -> None:
    tmp_path = make_unique_test_dir("runtime_trace_events")
    try:
        repo = _make_repo(tmp_path)
        output_dir = tmp_path / "output_compaction"
        task = CodingTask(
            task_id="trace_compaction_task",
            repo_path=repo,
            prompt="Inspect, inspect again, inspect once more, and finish.",
            max_turns=6,
        )
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="Inspecting once.",
                    call_id="c1",
                    name="read_file",
                    arguments={"path": "main.py"},
                    response_id="resp_1",
                ),
                _native_response(
                    assistant_text="Inspecting again.",
                    call_id="c2",
                    name="list_files",
                    arguments={"path": "."},
                    response_id="resp_2",
                ),
                _native_response(
                    assistant_text="Inspecting once more.",
                    call_id="c3",
                    name="read_file",
                    arguments={"path": "main.py"},
                    response_id="resp_3",
                ),
                _native_response(
                    assistant_text="Done.",
                    call_id="c4",
                    name="finish",
                    arguments={"answer": "Done"},
                    response_id="resp_4",
                ),
            ]
        )

        trajectory = run_coding_task(
            task,
            client,
            output_dir,
            context_policy_mode="deterministic_compaction",
            context_max_messages=6,
        )
        assert trajectory.status.value == "completed"

        request_context_rows = _load_jsonl(output_dir / "request_context.jsonl")
        final_request_context = request_context_rows[-1]
        assert final_request_context["policy_mode"] == "deterministic_compaction"
        assert final_request_context["replacement_history_active"] is True
        assert final_request_context["replacement_history_record_id"] == (
            "replacement_history_000001"
        )
        assert final_request_context["summary_slot_included"] is True
        assert final_request_context["carried_forward_state_present"] is True
        assert final_request_context["compaction_considered"] is True
        assert final_request_context["compaction_considered_reason"] == "message_limit_exceeded"
        assert final_request_context["candidate_turn_indices"] == [1, 2, 3]
        assert final_request_context["compacted_turn_indices"] == [1, 2]

        events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        compaction_request = next(
            event
            for event in events
            if event["event_kind"] == "model_request_built" and event["turn_index"] == 4
        )
        planned = next(
            event
            for event in events
            if event["event_kind"] == "context_selection_planned" and event["turn_index"] == 4
        )
        assert planned["data"]["policy_mode"] == "deterministic_compaction"
        assert planned["data"]["compaction_decision"] == "applied"
        assert planned["data"]["compaction_considered"] is True
        assert planned["data"]["compaction_considered_reason"] == "message_limit_exceeded"
        assert planned["data"]["candidate_turn_indices"] == [1, 2, 3]
        assert planned["data"]["compacted_turn_indices"] == [1, 2]
        assert planned["data"]["compacted_message_count"] == 4
        applied = next(
            event
            for event in events
            if event["event_kind"] == "context_compaction_applied"
            and event["turn_index"] == 4
        )
        assert applied["data"]["summary_slot_planned"] is True
        assert applied["data"]["carried_forward_state_planned"] is True
        assert applied["data"]["artifact_reason"] == "message_limit_exceeded"
        assert applied["data"]["compacted_message_indices"] == [2, 3, 4, 5]
        assert compaction_request["data"]["compaction_applied"] is True
        assert (
            compaction_request["data"]["compaction_reason"]
            == "deterministic_turn_compaction"
        )
        assert compaction_request["data"]["summary_slot_included"] is True
        assert compaction_request["data"]["carried_forward_state_present"] is True
        assert compaction_request["data"]["selected_retained_entry_ids"] == [
            "retained_entry_000001",
            "retained_entry_000002",
            "retained_entry_000012",
            "retained_entry_000010",
            "retained_entry_000011",
        ]
        assert compaction_request["data"]["omitted_retained_entry_ids"] == [
            "retained_entry_000004",
            "retained_entry_000005",
            "retained_entry_000007",
            "retained_entry_000008",
        ]
        assert compaction_request["data"]["summary_retained_entry_id"] == "retained_entry_000012"
        assert (
            compaction_request["data"]["carried_forward_state_entry_id"]
            == "retained_entry_000013"
        )
        assert compaction_request["data"]["retained_entry_count_before_snapshot"] == 11
        assert compaction_request["data"]["retained_entry_count_after_snapshot"] == 15
        assert compaction_request["data"]["context_selection_retained_entry_id"] == "retained_entry_000015"
        assert compaction_request["data"]["replacement_history_record_id"] == (
            "replacement_history_000001"
        )

        snapshot_payload_path = next(
            payload_ref["path"]
            for payload_ref in compaction_request["payload_refs"]
            if payload_ref["kind"] == "request_history_snapshot"
        )
        snapshot_payload = _load_json(output_dir / snapshot_payload_path)
        assert snapshot_payload["request_history_item_kinds"] == [
            "source",
            "source",
            "replacement",
            "source",
            "source",
        ]
        assert snapshot_payload["omitted_retained_entry_ids"] == [
            "retained_entry_000004",
            "retained_entry_000005",
            "retained_entry_000007",
            "retained_entry_000008",
        ]

        stop_event = next(
            event
            for event in events
            if event["event_kind"] == "turn_stop_decision" and event["turn_index"] == 4
        )
        assert stop_event["data"]["replacement_history_active_after_turn"] is True
        assert stop_event["data"]["replacement_history_record_id"] == (
            "replacement_history_000001"
        )
        assert stop_event["data"]["retained_history_last_entry_id"] == "retained_entry_000015"
        assert stop_event["data"]["retained_entry_count"] == 15

        run_completed = next(event for event in events if event["event_kind"] == "run_completed")
        assert run_completed["data"]["retained_history"] == {
            "retained_entry_count": 17,
            "last_entry_id": "retained_entry_000017",
            "entry_counts_by_kind": {
                "source_message": 10,
                "replacement_summary": 1,
                "carry_forward_state": 1,
                "history_control": 5,
            },
            "replacement_history_count": 1,
        }
    finally:
        cleanup_test_path(tmp_path)


def test_runtime_trace_captures_model_backed_compaction_events() -> None:
    tmp_path = make_unique_test_dir("runtime_trace_events")
    try:
        repo = _make_repo(tmp_path)
        output_dir = tmp_path / "output_model_compaction"
        task = CodingTask(
            task_id="trace_model_compaction_task",
            repo_path=repo,
            prompt="Inspect, inspect again, inspect once more, and finish.",
            max_turns=6,
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
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="Inspecting once.",
                    call_id="c1",
                    name="read_file",
                    arguments={"path": "main.py"},
                    response_id="resp_1",
                ),
                _native_response(
                    assistant_text="Inspecting again.",
                    call_id="c2",
                    name="list_files",
                    arguments={"path": "."},
                    response_id="resp_2",
                ),
                _native_response(
                    assistant_text="Inspecting once more.",
                    call_id="c3",
                    name="read_file",
                    arguments={"path": "main.py"},
                    response_id="resp_3",
                ),
                GenerateResponse.from_native_tool_calling(
                    assistant_text=json.dumps(compaction_output, ensure_ascii=False),
                    tool_calls=[],
                    finish_reason="stop",
                    response_id="resp_compact",
                    request_kind="context_compaction",
                    structured_output=compaction_output,
                ),
                _native_response(
                    assistant_text="Done.",
                    call_id="c4",
                    name="finish",
                    arguments={"answer": "Done"},
                    response_id="resp_4",
                ),
            ]
        )

        trajectory = run_coding_task(
            task,
            client,
            output_dir,
            context_policy_mode="model_backed_compaction",
            context_max_messages=6,
        )
        assert trajectory.status.value == "completed"

        request_context_rows = _load_jsonl(output_dir / "request_context.jsonl")
        final_request_context = request_context_rows[-1]
        assert final_request_context["policy_mode"] == "model_backed_compaction"
        assert final_request_context["summary_slot_included"] is True
        assert final_request_context["carried_forward_state_present"] is True
        assert final_request_context["model_backed_requested"] is True
        assert final_request_context["model_backed_used"] is True
        assert final_request_context["fallback_applied"] is False

        events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        requested = next(
            event
            for event in events
            if event["event_kind"] == "context_compaction_requested"
            and event["turn_index"] == 4
        )
        assert requested["data"]["backend_mode"] == "inline_model"
        assert requested["data"]["request_kind"] == "context_compaction"
        assert requested["data"]["fallback_policy"] == "deterministic_compaction"

        completed = next(
            event
            for event in events
            if event["event_kind"] == "context_compaction_completed"
            and event["turn_index"] == 4
        )
        assert completed["data"]["summary_kind"] == "model_backed_compaction"
        assert completed["data"]["carried_forward_state_present"] is True
        assert completed["data"]["model_backed_used"] is True
        assert completed["data"]["fallback_applied"] is False
        assert completed["data"]["source_turn_indices"] == [1, 2]

        request_built = next(
            event
            for event in events
            if event["event_kind"] == "model_request_built" and event["turn_index"] == 4
        )
        assert request_built["data"]["compaction_applied"] is True
        assert request_built["data"]["summary_slot_included"] is True
        assert request_built["data"]["model_backed_used"] is True
        assert request_built["data"]["fallback_applied"] is False

        request_payload_path = next(
            payload_ref["path"]
            for payload_ref in request_built["payload_refs"]
            if payload_ref["kind"] == "model_request"
        )
        request_payload = _load_json(output_dir / request_payload_path)
        rendered_messages = json.dumps(request_payload["messages"], ensure_ascii=False)
        assert "[model compacted context]" in rendered_messages
    finally:
        cleanup_test_path(tmp_path)


def test_runtime_trace_records_model_backed_compaction_fallback() -> None:
    tmp_path = make_unique_test_dir("runtime_trace_events")
    try:
        repo = _make_repo(tmp_path)
        output_dir = tmp_path / "output_model_compaction_fallback"
        task = CodingTask(
            task_id="trace_model_compaction_fallback_task",
            repo_path=repo,
            prompt="Inspect, inspect again, inspect once more, and finish.",
            max_turns=6,
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
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="Inspecting once.",
                    call_id="c1",
                    name="read_file",
                    arguments={"path": "main.py"},
                    response_id="resp_1",
                ),
                _native_response(
                    assistant_text="Inspecting again.",
                    call_id="c2",
                    name="list_files",
                    arguments={"path": "."},
                    response_id="resp_2",
                ),
                _native_response(
                    assistant_text="Inspecting once more.",
                    call_id="c3",
                    name="read_file",
                    arguments={"path": "main.py"},
                    response_id="resp_3",
                ),
                GenerateResponse.from_native_tool_calling(
                    assistant_text=json.dumps(bad_compaction_output, ensure_ascii=False),
                    tool_calls=[],
                    finish_reason="stop",
                    response_id="resp_compact_bad",
                    request_kind="context_compaction",
                    structured_output=bad_compaction_output,
                ),
                _native_response(
                    assistant_text="Done.",
                    call_id="c4",
                    name="finish",
                    arguments={"answer": "Done"},
                    response_id="resp_4",
                ),
            ]
        )

        trajectory = run_coding_task(
            task,
            client,
            output_dir,
            context_policy_mode="model_backed_compaction",
            context_max_messages=6,
        )
        assert trajectory.status.value == "completed"

        request_context_rows = _load_jsonl(output_dir / "request_context.jsonl")
        final_request_context = request_context_rows[-1]
        assert final_request_context["model_backed_requested"] is True
        assert final_request_context["model_backed_used"] is False
        assert final_request_context["fallback_applied"] is True
        assert final_request_context["fallback_reason"] == "compacted_span_mismatch"

        events = _load_jsonl(output_dir / "runtime_trace.jsonl")
        failed = next(
            event
            for event in events
            if event["event_kind"] == "context_compaction_failed"
            and event["turn_index"] == 4
        )
        assert failed["data"]["failure_kind"] == "compacted_span_mismatch"
        assert failed["data"]["fallback_policy"] == "deterministic_compaction"
        assert failed["data"]["fallback_applied"] is True
        assert failed["data"]["fallback_reason"] == "compacted_span_mismatch"

        request_built = next(
            event
            for event in events
            if event["event_kind"] == "model_request_built" and event["turn_index"] == 4
        )
        assert request_built["data"]["model_backed_requested"] is True
        assert request_built["data"]["model_backed_used"] is False
        assert request_built["data"]["fallback_applied"] is True
        request_payload_path = next(
            payload_ref["path"]
            for payload_ref in request_built["payload_refs"]
            if payload_ref["kind"] == "model_request"
        )
        request_payload = _load_json(output_dir / request_payload_path)
        rendered_messages = json.dumps(request_payload["messages"], ensure_ascii=False)
        assert "[compacted runtime context]" in rendered_messages
        assert "[bad model compacted context]" not in rendered_messages
    finally:
        cleanup_test_path(tmp_path)
