from __future__ import annotations

import json

from pycodeagent.agent.history_replay import (
    build_retained_entry_index,
    load_request_context_entries,
    load_retained_history_entries,
    reconstruct_pre_compaction_messages,
    reconstruct_selected_messages,
)
from pycodeagent.agent.request_context import RequestContextWriter
from pycodeagent.agent.request_context import (
    lookup_request_context_entry,
    lookup_request_context_entry_by_id,
    request_context_metadata,
)
from pycodeagent.agent.history_manager import RuntimeHistoryManager
from pycodeagent.agent.retained_history import RetainedHistoryWriter
from pycodeagent.agent.turn_state import ContextPolicyMode, RuntimeSessionState
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.trajectory.schema import Message, Role, ToolCall
from unittest.mock import patch


def _msg(role: Role, content: str) -> Message:
    return Message(role=role, content=content)


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_request_context_writer_persists_selected_context_snapshots() -> None:
    tmp = make_unique_test_dir("request_context")
    try:
        writer = RequestContextWriter.create(
            tmp,
            run_id="run_ctx",
            task_id="task_ctx",
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

        entry = writer.append_snapshot(
            task_id="task_ctx",
            turn_index=4,
            snapshot=snapshot,
            context_max_messages=6,
        )
        writer.finalize()

        assert entry.entry_id == "request_context_entry_000001"
        assert entry.policy_mode == "deterministic_compaction"
        assert entry.request_history_item_kinds == [
            "source",
            "source",
            "replacement",
            "source",
            "source",
        ]
        assert entry.replacement_history_active is True
        assert entry.replacement_history_record_id == "replacement_history_000001"

        manifest = _load_json(tmp / "request_context_manifest.json")
        rows = _load_jsonl(tmp / "request_context.jsonl")
        assert manifest["total_entries"] == 1
        assert manifest["last_entry_id"] == "request_context_entry_000001"
        assert rows[0]["summary_slot_included"] is True
        assert rows[0]["carried_forward_state_present"] is True
        assert rows[0]["selected_retained_entry_ids"] == []
    finally:
        cleanup_test_path(tmp)


def test_request_context_can_reconstruct_selected_messages_from_retained_history() -> None:
    tmp = make_unique_test_dir("request_context_replay")
    try:
        retained_writer = RetainedHistoryWriter.create(
            tmp,
            run_id="run_ctx",
            task_id="task_ctx",
            workspace_root="C:/workspace",
        )
        request_context_writer = RequestContextWriter.create(
            tmp,
            run_id="run_ctx",
            task_id="task_ctx",
            workspace_root="C:/workspace",
        )
        messages = [
            _msg(Role.SYSTEM, "system"),
            _msg(Role.USER, "task"),
            Message(
                role=Role.ASSISTANT,
                content="assistant-1",
                tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})],
            ),
            _msg(Role.TOOL, "tool-1"),
            _msg(Role.ASSISTANT, "assistant-2"),
            _msg(Role.TOOL, "tool-2"),
            Message(
                role=Role.ASSISTANT,
                content="assistant-3",
                tool_calls=[ToolCall(id="c3", name="read_file", arguments={"path": "b.py"})],
            ),
            Message(
                role=Role.TOOL,
                content="tool-3",
                tool_call_id="c3",
                tool_name="read_file",
            ),
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
            task_id="task_ctx",
            turn_index=4,
            snapshot=snapshot,
            context_max_messages=6,
        )
        retained_writer.finalize()
        request_context_writer.finalize()

        retained_entries = load_retained_history_entries(tmp / "retained_history.jsonl")
        request_context_entries = load_request_context_entries(tmp / "request_context.jsonl")
        reconstructed = reconstruct_selected_messages(
            request_context_entries[0],
            build_retained_entry_index(retained_entries),
        )

        assert [message.role.value for message in reconstructed] == [
            "system",
            "user",
            "system",
            "assistant",
            "tool",
        ]
        assert "[compacted runtime context]" in reconstructed[2].content
        assert reconstructed[3].tool_calls[0].name == "read_file"
        assert reconstructed[3].tool_calls[0].arguments == {"path": "b.py"}
        assert reconstructed[4].tool_call_id == "c3"
        assert reconstructed[4].tool_name == "read_file"

        pre_compaction = reconstruct_pre_compaction_messages(
            request_context_entries[0],
            build_retained_entry_index(retained_entries),
        )
        assert len(pre_compaction) == 8
        assert [message.role.value for message in pre_compaction] == [
            "system",
            "user",
            "assistant",
            "tool",
            "assistant",
            "tool",
            "assistant",
            "tool",
        ]
    finally:
        cleanup_test_path(tmp)


def test_request_context_metadata_and_lookup_use_stable_log_id() -> None:
    tmp = make_unique_test_dir("request_context_lookup")
    try:
        time_values = iter(range(1700000010000, 1700000010010))
        with patch(
            "pycodeagent.agent.request_context._unix_time_ms",
            side_effect=lambda: next(time_values),
        ):
            writer = RequestContextWriter.create(
                tmp,
                run_id="run_ctx_lookup",
                task_id="task_ctx_lookup",
                workspace_root="C:/workspace",
            )
            messages = [
                _msg(Role.SYSTEM, "system"),
                _msg(Role.USER, "task"),
            ]
            manager = RuntimeHistoryManager.from_trajectory_messages(messages)
            session_state = RuntimeSessionState(
                recovery_state=object(),
                context_policy_mode=ContextPolicyMode.FULL_HISTORY.value,
                context_max_messages=None,
            )
            first_snapshot = manager.snapshot_for_request(
                policy_mode=ContextPolicyMode.FULL_HISTORY,
                max_messages=None,
                session_state=session_state,
                turn_index=1,
            )
            first_entry = writer.append_snapshot(
                task_id="task_ctx_lookup",
                turn_index=1,
                snapshot=first_snapshot,
                context_max_messages=None,
            )
            first_metadata = request_context_metadata(tmp)
            assert first_metadata.log_id == "run_ctx_lookup:1700000010000"
            assert first_metadata.entry_count == 1

            messages.append(_msg(Role.ASSISTANT, "assistant"))
            manager.sync_source_messages(messages, turn_index=2)
            second_snapshot = manager.snapshot_for_request(
                policy_mode=ContextPolicyMode.FULL_HISTORY,
                max_messages=None,
                session_state=session_state,
                turn_index=2,
            )
            second_entry = writer.append_snapshot(
                task_id="task_ctx_lookup",
                turn_index=2,
                snapshot=second_snapshot,
                context_max_messages=None,
            )
            second_metadata = request_context_metadata(tmp)
            writer.finalize()

        assert second_metadata.log_id == first_metadata.log_id
        assert second_metadata.entry_count == 2
        assert second_metadata.last_entry_id == second_entry.entry_id

        looked_up_by_offset = lookup_request_context_entry(
            tmp,
            log_id=second_metadata.log_id,
            offset=1,
        )
        assert looked_up_by_offset is not None
        assert looked_up_by_offset.entry_id == second_entry.entry_id
        assert looked_up_by_offset.turn_index == 2

        looked_up_by_id = lookup_request_context_entry_by_id(
            tmp,
            entry_id=first_entry.entry_id,
        )
        assert looked_up_by_id is not None
        assert looked_up_by_id.turn_index == 1

        assert (
            lookup_request_context_entry(
                tmp,
                log_id="wrong-log-id",
                offset=1,
            )
            is None
        )
    finally:
        cleanup_test_path(tmp)


def test_request_context_metadata_ignores_stale_entries_from_previous_run() -> None:
    tmp = make_unique_test_dir("request_context_stale")
    try:
        time_values = iter(range(1700000020000, 1700000020020))
        with patch(
            "pycodeagent.agent.request_context._unix_time_ms",
            side_effect=lambda: next(time_values),
        ):
            first_writer = RequestContextWriter.create(
                tmp,
                run_id="run_ctx_stale",
                task_id="task_ctx_stale",
                workspace_root="C:/workspace",
            )
            manager = RuntimeHistoryManager.from_trajectory_messages(
                [_msg(Role.SYSTEM, "system"), _msg(Role.USER, "task")]
            )
            session_state = RuntimeSessionState(
                recovery_state=object(),
                context_policy_mode=ContextPolicyMode.FULL_HISTORY.value,
                context_max_messages=None,
            )
            first_snapshot = manager.snapshot_for_request(
                policy_mode=ContextPolicyMode.FULL_HISTORY,
                max_messages=None,
                session_state=session_state,
                turn_index=1,
            )
            first_writer.append_snapshot(
                task_id="task_ctx_stale",
                turn_index=1,
                snapshot=first_snapshot,
                context_max_messages=None,
            )
            first_writer.finalize()
            stale_line = (tmp / "request_context.jsonl").read_text(encoding="utf-8")

            second_writer = RequestContextWriter.create(
                tmp,
                run_id="run_ctx_stale",
                task_id="task_ctx_stale",
                workspace_root="C:/workspace",
            )
            second_snapshot = manager.snapshot_for_request(
                policy_mode=ContextPolicyMode.FULL_HISTORY,
                max_messages=None,
                session_state=session_state,
                turn_index=2,
            )
            current_entry = second_writer.append_snapshot(
                task_id="task_ctx_stale",
                turn_index=2,
                snapshot=second_snapshot,
                context_max_messages=None,
            )
            second_writer.finalize()

        with open(tmp / "request_context.jsonl", "a", encoding="utf-8") as handle:
            handle.write(stale_line)

        metadata = request_context_metadata(tmp)
        assert metadata.log_id == "run_ctx_stale:1700000020003"
        assert metadata.entry_count == 1
        assert metadata.last_entry_id == current_entry.entry_id

        looked_up = lookup_request_context_entry(
            tmp,
            log_id=metadata.log_id,
            offset=0,
        )
        assert looked_up is not None
        assert looked_up.turn_index == 2

        looked_up_by_id = lookup_request_context_entry_by_id(
            tmp,
            entry_id="request_context_entry_000001",
        )
        assert looked_up_by_id is not None
        assert looked_up_by_id.turn_index == 2
    finally:
        cleanup_test_path(tmp)
