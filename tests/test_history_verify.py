from __future__ import annotations

from pathlib import Path

from pycodeagent.agent.history_verify import (
    verify_request_context_log,
    verify_request_context_log_from_paths,
)
from pycodeagent.agent.history_replay import (
    load_request_context_entries,
    load_retained_history_entries,
)
from pycodeagent.agent.history_lineage import build_history_lineage_report
from pycodeagent.agent.history_manager import RuntimeHistoryManager
from pycodeagent.agent.request_context import (
    RequestContextWriter,
    load_request_context_manifest,
    request_context_log_id,
)
from pycodeagent.agent.retained_history import (
    RetainedHistoryWriter,
    load_retained_history_manifest,
    retained_history_log_id,
)
from pycodeagent.agent.turn_state import ContextPolicyMode, RuntimeSessionState
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.trajectory.schema import Message, Role


def _msg(role: Role, content: str) -> Message:
    return Message(role=role, content=content)


def test_history_verify_accepts_deterministic_compaction_artifacts() -> None:
    tmp = make_unique_test_dir("history_verify")
    try:
        retained_writer = RetainedHistoryWriter.create(
            tmp,
            run_id="run_verify",
            task_id="task_verify",
            workspace_root="C:/workspace",
        )
        request_context_writer = RequestContextWriter.create(
            tmp,
            run_id="run_verify",
            task_id="task_verify",
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
        snapshot = manager.snapshot_for_request(
            policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION,
            max_messages=6,
            session_state=session_state,
            turn_index=4,
        )
        request_context_writer.append_snapshot(
            task_id="task_verify",
            turn_index=4,
            snapshot=snapshot,
            context_max_messages=6,
        )
        retained_writer.finalize()
        request_context_writer.finalize()

        reports = verify_request_context_log(
            load_request_context_entries(tmp / "request_context.jsonl"),
            load_retained_history_entries(tmp / "retained_history.jsonl"),
        )

        assert len(reports) == 1
        assert reports[0].ok is True
        assert reports[0].reconstructed_message_count == 5
        assert reports[0].reconstructed_pre_compaction_message_count == 8
        assert reports[0].errors == []
    finally:
        cleanup_test_path(tmp)


def test_history_verify_accepts_model_backed_compaction_fixture() -> None:
    fixture_dir = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "model_backed_compaction_history_mini"
    )
    reports = verify_request_context_log_from_paths(
        request_context_path=str(fixture_dir / "request_context.jsonl"),
        retained_history_path=str(fixture_dir / "retained_history.jsonl"),
    )

    assert len(reports) == 1
    assert all(report.ok for report in reports)
    assert reports[0].reconstructed_message_count == 5
    assert reports[0].reconstructed_pre_compaction_message_count == 8

    request_entries = load_request_context_entries(
        fixture_dir / "request_context.jsonl"
    )
    retained_entries = load_retained_history_entries(
        fixture_dir / "retained_history.jsonl"
    )
    entry = request_entries[0]
    assert entry.compaction_applied is True
    assert entry.compaction_considered_reason == "message_limit_exceeded"
    assert entry.trigger_message_overflow is True
    assert entry.trigger_token_overflow is False
    assert entry.context_max_tokens is None
    assert entry.model_backed_requested is True
    assert entry.model_backed_used is True
    assert entry.compaction_backend_mode == "inline_model"
    assert entry.fallback_applied is False
    assert entry.retained_history_last_entry_id == "retained_entry_000011"

    request_manifest = load_request_context_manifest(fixture_dir)
    retained_manifest = load_retained_history_manifest(fixture_dir)
    lineage = build_history_lineage_report(
        request_entries,
        retained_entries,
        request_context_log_id=request_context_log_id(request_manifest),
        retained_history_log_id=retained_history_log_id(retained_manifest),
    )
    assert lineage.ok is True
    assert lineage.replacement_record_count == 1
    assert lineage.records[0].compaction_artifact_entry_id == "retained_entry_000011"
    assert lineage.records[0].source_retained_entry_ids == [
        "retained_entry_000003",
        "retained_entry_000004",
        "retained_entry_000005",
        "retained_entry_000006",
    ]
