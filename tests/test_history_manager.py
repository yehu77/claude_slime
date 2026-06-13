from __future__ import annotations

from pycodeagent.agent.retained_history import RetainedHistoryWriter
from pycodeagent.agent.history_manager import RuntimeHistoryManager
from pycodeagent.agent.turn_state import ContextPolicyMode, RuntimeSessionState
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.trajectory.schema import Message, Role


def _msg(role: Role, content: str) -> Message:
    return Message(role=role, content=content)


def test_history_manager_syncs_append_only_source_history() -> None:
    messages = [
        _msg(Role.SYSTEM, "system"),
        _msg(Role.USER, "task"),
    ]
    manager = RuntimeHistoryManager.from_trajectory_messages(messages)

    assert [item.source_trajectory_index for item in manager.source_items] == [0, 1]
    assert [item.item_kind for item in manager.request_items] == ["source", "source"]

    messages.append(_msg(Role.ASSISTANT, "inspect"))
    messages.append(_msg(Role.TOOL, "result"))
    manager.sync_source_messages(messages)

    assert [item.source_trajectory_index for item in manager.source_items] == [0, 1, 2, 3]
    assert [item.source_trajectory_index for item in manager.request_items] == [0, 1, 2, 3]


def test_history_manager_persists_replacement_history_after_compaction() -> None:
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
    manager = RuntimeHistoryManager.from_trajectory_messages(messages)
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

    assert snapshot.compaction_artifact is not None
    assert snapshot.replacement_history_record is not None
    assert snapshot.context_selection_plan.policy_mode == "deterministic_compaction"
    assert snapshot.context_selection_plan.compaction_decision == "applied"
    assert snapshot.context_selection_plan.selected_request_item_indices == [0, 1, 6, 7]
    assert snapshot.request_history_source_indices == [0, 1, 6, 7]
    assert snapshot.request_history_item_kinds == [
        "source",
        "source",
        "replacement",
        "source",
        "source",
    ]
    assert snapshot.request_history_item_count_before_snapshot == 8
    assert snapshot.request_history_item_count_after_snapshot == 5
    assert snapshot.replacement_history_active is True
    assert snapshot.replacement_history_record_id == "replacement_history_000001"
    assert snapshot.context_selection_retained_entry_id is None
    assert len(manager.request_items) == 5
    assert manager.replacement_history[0].source_trajectory_indices == [2, 3, 4, 5]
    assert "[compacted runtime context]" in snapshot.selected_messages[2].content


def test_history_manager_carries_replacement_history_into_later_snapshots() -> None:
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
    manager = RuntimeHistoryManager.from_trajectory_messages(messages)
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
    assert first_snapshot.replacement_history_active is True

    messages.extend(
        [
            _msg(Role.ASSISTANT, "assistant-4"),
            _msg(Role.TOOL, "tool-4"),
        ]
    )
    manager.sync_source_messages(messages)

    second_snapshot = manager.snapshot_for_request(
        policy_mode=ContextPolicyMode.FULL_HISTORY,
        max_messages=None,
        session_state=session_state,
        turn_index=5,
    )

    assert second_snapshot.context_selection_plan.policy_mode == "full_history"
    assert second_snapshot.context_selection_plan.compaction_decision == "skipped"
    assert second_snapshot.request_history_item_count_before_snapshot == 7
    assert second_snapshot.replacement_history_active is True
    assert second_snapshot.request_history_item_kinds[:3] == [
        "source",
        "source",
        "replacement",
    ]
    assert second_snapshot.request_history_source_indices == [0, 1, 6, 7, 8, 9]


def test_history_manager_supports_multiple_replacement_history_records() -> None:
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
    manager = RuntimeHistoryManager.from_trajectory_messages(messages)
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
    assert first_snapshot.replacement_history_record_id == "replacement_history_000001"

    messages.extend(
        [
            _msg(Role.ASSISTANT, "assistant-4"),
            _msg(Role.TOOL, "tool-4"),
            _msg(Role.ASSISTANT, "assistant-5"),
            _msg(Role.TOOL, "tool-5"),
        ]
    )
    manager.sync_source_messages(messages)

    second_snapshot = manager.snapshot_for_request(
        policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION,
        max_messages=6,
        session_state=session_state,
        turn_index=6,
    )

    assert second_snapshot.replacement_history_active is True
    assert second_snapshot.replacement_history_record_id == "replacement_history_000002"
    assert len(manager.replacement_history) == 2
    assert [record.record_id for record in manager.replacement_history] == [
        "replacement_history_000001",
        "replacement_history_000002",
    ]
    assert manager.replacement_history[1].source_trajectory_indices == [6, 7, 8, 9]


def test_history_manager_records_retained_history_ids_and_replacement_linkage() -> None:
    tmp = make_unique_test_dir("history_manager_retained")
    try:
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
        writer = RetainedHistoryWriter.create(
            tmp,
            run_id="run_history",
            task_id="task_history",
            workspace_root="C:/workspace",
        )
        manager = RuntimeHistoryManager.from_trajectory_messages(
            messages,
            retained_history_writer=writer,
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

        assert snapshot.selected_retained_entry_ids[:2] == [
            "retained_entry_000001",
            "retained_entry_000002",
        ]
        assert snapshot.omitted_retained_entry_ids == [
            "retained_entry_000003",
            "retained_entry_000004",
            "retained_entry_000005",
            "retained_entry_000006",
        ]
        assert snapshot.summary_retained_entry_id == "retained_entry_000009"
        assert snapshot.carried_forward_state_entry_id == "retained_entry_000010"
        assert snapshot.context_selection_retained_entry_id == "retained_entry_000012"
        assert snapshot.retained_history_last_entry_id == "retained_entry_000012"
        assert snapshot.retained_entry_count_before_snapshot == 8
        assert snapshot.retained_entry_count_after_snapshot == 12
        assert manager.replacement_history[0].source_retained_entry_ids == [
            "retained_entry_000003",
            "retained_entry_000004",
            "retained_entry_000005",
            "retained_entry_000006",
        ]
        assert manager.replacement_history[0].replacement_retained_entry_id == "retained_entry_000009"
        assert manager.replacement_history[0].carried_forward_state_entry_id == "retained_entry_000010"
        assert manager.replacement_history[0].compaction_artifact_entry_id == "retained_entry_000011"
        assert manager.retained_history_summary()["entry_counts_by_kind"] == {
            "source_message": 8,
            "replacement_summary": 1,
            "carry_forward_state": 1,
            "history_control": 2,
        }
    finally:
        cleanup_test_path(tmp)
