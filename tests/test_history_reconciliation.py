from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.agent.history_reconciliation import (
    build_compaction_chain_report,
    load_history_reconciliation_bundle,
    write_compaction_chain_report,
    write_history_reconciliation_report,
)
from pycodeagent.agent.history_manager import RuntimeHistoryManager
from pycodeagent.agent.request_context import RequestContextWriter
from pycodeagent.agent.retained_history import RetainedHistoryWriter
from pycodeagent.agent.turn_state import ContextPolicyMode, RuntimeSessionState
from pycodeagent.agent.llm_client import (
    FakeLLMClient,
    GenerateResponse,
    ToolCallCandidate,
)
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.trajectory.schema import Message, Role


def _make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (repo / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return repo


def _msg(role: Role, content: str) -> Message:
    return Message(role=role, content=content)


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


def test_history_reconciliation_bundle_reads_model_backed_compaction_fixture() -> None:
    fixture_dir = Path(
        "tests/fixtures/local_runtime_trace_bundle_model_backed_compaction"
    )
    bundle = load_history_reconciliation_bundle(fixture_dir)

    assert bundle.record_ids() == ["replacement_history_000001"]
    record = bundle.get_record("replacement_history_000001")
    assert record is not None
    assert record.ok is True
    assert record.compaction_artifact_entry_id == "retained_entry_000014"
    assert record.selected_message_count == 5
    assert record.pre_compaction_message_count == 8
    assert record.pre_compaction_message_roles == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]


def test_run_coding_task_persists_history_reconciliation_report() -> None:
    tmp_path = make_unique_test_dir("history_reconciliation")
    try:
        repo = _make_repo(tmp_path)
        output_dir = tmp_path / "output"
        task = CodingTask(
            task_id="history_reconciliation_task",
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
                _native_response(call_id="c1", name="read_file", arguments={"path": "main.py"}, response_id="resp_1"),
                _native_response(call_id="c2", name="list_files", arguments={"path": "."}, response_id="resp_2"),
                _native_response(call_id="c3", name="read_file", arguments={"path": "main.py"}, response_id="resp_3"),
                GenerateResponse.from_native_tool_calling(
                    assistant_text=json.dumps(compaction_output, ensure_ascii=False),
                    tool_calls=[],
                    finish_reason="stop",
                    response_id="resp_compact",
                    request_kind="context_compaction",
                    structured_output=compaction_output,
                ),
                _native_response(call_id="c4", name="finish", arguments={"answer": "Done"}, response_id="resp_4"),
            ]
        )

        trajectory = run_coding_task(
            task,
            client,
            output_dir,
            context_policy_mode="model_backed_compaction",
            context_max_messages=6,
        )
        assert trajectory.metadata["history_reconciliation_report_ok"] is True
        assert trajectory.metadata["compaction_chain_report_ok"] is True
        report_path = Path(trajectory.metadata["history_reconciliation_report_path"])
        assert report_path.exists()
        chain_path = Path(trajectory.metadata["compaction_chain_report_path"])
        assert chain_path.exists()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["replacement_record_ids"] == ["replacement_history_000001"]
        assert report["records"][0]["compaction_artifact_entry_id"] == "retained_entry_000014"
        assert report["records"][0]["selected_message_count"] == 5
        assert report["records"][0]["pre_compaction_message_count"] == 8
        chain = json.loads(chain_path.read_text(encoding="utf-8"))
        assert chain["ordered_record_ids"] == ["replacement_history_000001"]
        assert chain["nodes"][0]["predecessor_record_id"] is None
        assert chain["nodes"][0]["successor_record_id"] is None

        rewritten_report = write_history_reconciliation_report(output_dir)
        assert rewritten_report.ok is True
        assert rewritten_report.replacement_record_ids == ["replacement_history_000001"]
        rewritten_chain = write_compaction_chain_report(output_dir)
        assert rewritten_chain.ok is True
        assert rewritten_chain.ordered_record_ids == ["replacement_history_000001"]
    finally:
        cleanup_test_path(tmp_path)


def test_compaction_chain_report_orders_multiple_replacement_history_records() -> None:
    tmp_path = make_unique_test_dir("history_reconciliation_multi")
    try:
        retained_writer = RetainedHistoryWriter.create(
            tmp_path,
            run_id="run_multi",
            task_id="task_multi",
            workspace_root="C:/workspace",
        )
        request_context_writer = RequestContextWriter.create(
            tmp_path,
            run_id="run_multi",
            task_id="task_multi",
            workspace_root="C:/workspace",
        )
        messages = [
            _msg(Role.SYSTEM, "system"),
            _msg(Role.USER, "task"),
            _msg(Role.ASSISTANT, "assistant-1"),
            _msg(Role.TOOL, "tool-1"),
            _msg(Role.ASSISTANT, "assistant-2"),
            _msg(Role.TOOL, "tool-2"),
            _msg(Role.ASSISTANT, "assistant-3"),
            _msg(Role.TOOL, "tool-3"),
        ]
        manager = RuntimeHistoryManager.from_trajectory_messages(
            messages,
            retained_history_writer=retained_writer,
        )
        session_state = RuntimeSessionState(
            recovery_state=object(),
            context_policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION.value,
            context_max_messages=6,
        )
        first_snapshot = manager.snapshot_for_request(
            policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION,
            max_messages=6,
            session_state=session_state,
            turn_index=4,
        )
        request_context_writer.append_snapshot(
            task_id="task_multi",
            turn_index=4,
            snapshot=first_snapshot,
            context_max_messages=6,
        )

        messages.extend(
            [
                _msg(Role.ASSISTANT, "assistant-4"),
                _msg(Role.TOOL, "tool-4"),
                _msg(Role.ASSISTANT, "assistant-5"),
                _msg(Role.TOOL, "tool-5"),
            ]
        )
        manager.sync_source_messages(messages, turn_index=6)
        second_snapshot = manager.snapshot_for_request(
            policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION,
            max_messages=6,
            session_state=session_state,
            turn_index=6,
        )
        request_context_writer.append_snapshot(
            task_id="task_multi",
            turn_index=6,
            snapshot=second_snapshot,
            context_max_messages=6,
        )
        retained_writer.finalize()
        request_context_writer.finalize()

        bundle = load_history_reconciliation_bundle(tmp_path)
        assert bundle.record_ids() == [
            "replacement_history_000001",
            "replacement_history_000002",
        ]
        assert bundle.get_predecessor("replacement_history_000001") is None
        assert (
            bundle.get_successor("replacement_history_000001").record_id
            == "replacement_history_000002"
        )
        assert (
            bundle.get_predecessor("replacement_history_000002").record_id
            == "replacement_history_000001"
        )
        assert bundle.get_successor("replacement_history_000002") is None

        chain = build_compaction_chain_report(bundle)
        assert chain.chain_length == 2
        assert chain.ordered_record_ids == [
            "replacement_history_000001",
            "replacement_history_000002",
        ]
        assert chain.nodes[0].predecessor_record_id is None
        assert chain.nodes[0].successor_record_id == "replacement_history_000002"
        assert chain.nodes[1].predecessor_record_id == "replacement_history_000001"
        assert chain.nodes[1].successor_record_id is None
    finally:
        cleanup_test_path(tmp_path)
