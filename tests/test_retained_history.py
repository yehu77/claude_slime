from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from pycodeagent.agent.retained_history import (
    RetainedHistoryWriter,
    lookup_retained_history_entry,
    lookup_retained_history_entry_by_id,
    retained_history_metadata,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.trajectory.schema import Message, Role


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_retained_history_writer_creates_manifest_and_entry_log() -> None:
    tmp = make_unique_test_dir("retained_history")
    try:
        time_values = iter(range(1700000000000, 1700000000010))
        with patch(
            "pycodeagent.agent.retained_history._unix_time_ms",
            side_effect=lambda: next(time_values),
        ):
            writer = RetainedHistoryWriter.create(
                tmp,
                run_id="run_001",
                task_id="task_001",
                workspace_root="C:/workspace",
            )
            writer.append_source_message(
                turn_index=0,
                request_item_id="history_item_000000",
                source_trajectory_index=0,
                message=Message(role=Role.SYSTEM, content="system"),
            )
            writer.finalize()

        manifest = _load_json(tmp / "retained_history_manifest.json")
        rows = _load_jsonl(tmp / "retained_history.jsonl")

        assert manifest["run_id"] == "run_001"
        assert manifest["task_id"] == "task_001"
        assert manifest["total_entries"] == 1
        assert manifest["entry_counts_by_kind"] == {"source_message": 1}
        assert manifest["last_entry_id"] == "retained_entry_000001"
        assert manifest["started_at_unix_ms"] == 1700000000000
        assert manifest["ended_at_unix_ms"] == 1700000000002

        assert rows == [
            {
                "schema_version": 1,
                "entry_id": "retained_entry_000001",
                "run_id": "run_001",
                "turn_index": 0,
                "source_kind": "source_message",
                "source_trajectory_index": 0,
                "request_item_id": "history_item_000000",
                "role": "system",
                "text": "system",
                "metadata": {
                    "tool_call_id": None,
                    "tool_name": None,
                    "canonical_name": None,
                    "tool_version": None,
                    "tool_call_count": 0,
                    "message_metadata": {},
                    "message_payload": {
                        "role": "system",
                        "content": "system",
                        "tool_calls": [],
                        "tool_call_id": None,
                        "tool_name": None,
                        "canonical_name": None,
                        "tool_version": None,
                        "metadata": {},
                    },
                },
                "ts_unix_ms": 1700000000001,
            }
        ]
    finally:
        cleanup_test_path(tmp)


def test_retained_history_metadata_and_lookup_use_stable_log_id() -> None:
    tmp = make_unique_test_dir("retained_history_lookup")
    try:
        time_values = iter(range(1700000001000, 1700000001010))
        with patch(
            "pycodeagent.agent.retained_history._unix_time_ms",
            side_effect=lambda: next(time_values),
        ):
            writer = RetainedHistoryWriter.create(
                tmp,
                run_id="run_lookup",
                task_id="task_lookup",
                workspace_root="C:/workspace",
            )
            writer.append_source_message(
                turn_index=0,
                request_item_id="history_item_000000",
                source_trajectory_index=0,
                message=Message(role=Role.SYSTEM, content="system"),
            )

            metadata_before_append = retained_history_metadata(tmp)
            assert metadata_before_append.log_id == "run_lookup:1700000001000"
            assert metadata_before_append.entry_count == 1

            writer.append_source_message(
                turn_index=1,
                request_item_id="history_item_000001",
                source_trajectory_index=1,
                message=Message(role=Role.USER, content="task"),
            )
            metadata_after_append = retained_history_metadata(tmp)
            writer.finalize()

        assert metadata_after_append.log_id == metadata_before_append.log_id
        assert metadata_after_append.entry_count == 2

        second_entry = lookup_retained_history_entry(
            tmp,
            log_id=metadata_after_append.log_id,
            offset=1,
        )
        assert second_entry is not None
        assert second_entry.turn_index == 1
        assert second_entry.role == "user"
        assert second_entry.text == "task"
        assert (
            lookup_retained_history_entry_by_id(
                tmp,
                entry_id=second_entry.entry_id,
            ).entry_id
            == second_entry.entry_id
        )

        assert (
            lookup_retained_history_entry(
                tmp,
                log_id="wrong-log-id",
                offset=1,
            )
            is None
        )
    finally:
        cleanup_test_path(tmp)


def test_retained_history_metadata_ignores_stale_entries_from_previous_run() -> None:
    tmp = make_unique_test_dir("retained_history_stale")
    try:
        time_values = iter(range(1700000002000, 1700000002020))
        with patch(
            "pycodeagent.agent.retained_history._unix_time_ms",
            side_effect=lambda: next(time_values),
        ):
            first_writer = RetainedHistoryWriter.create(
                tmp,
                run_id="run_retained_stale",
                task_id="task_retained_stale",
                workspace_root="C:/workspace",
            )
            first_writer.append_source_message(
                turn_index=0,
                request_item_id="history_item_000000",
                source_trajectory_index=0,
                message=Message(role=Role.SYSTEM, content="system"),
            )
            first_writer.finalize()
            stale_line = (tmp / "retained_history.jsonl").read_text(encoding="utf-8")

            second_writer = RetainedHistoryWriter.create(
                tmp,
                run_id="run_retained_stale",
                task_id="task_retained_stale",
                workspace_root="C:/workspace",
            )
            second_writer.append_source_message(
                turn_index=1,
                request_item_id="history_item_000001",
                source_trajectory_index=1,
                message=Message(role=Role.USER, content="task"),
            )
            second_writer.finalize()

        with open(tmp / "retained_history.jsonl", "a", encoding="utf-8") as handle:
            handle.write(stale_line)

        metadata = retained_history_metadata(tmp)
        assert metadata.log_id == "run_retained_stale:1700000002003"
        assert metadata.entry_count == 1
        assert metadata.last_entry_id == "retained_entry_000001"

        looked_up = lookup_retained_history_entry(
            tmp,
            log_id=metadata.log_id,
            offset=0,
        )
        assert looked_up is not None
        assert looked_up.turn_index == 1
        assert looked_up.role == "user"

        looked_up_by_id = lookup_retained_history_entry_by_id(
            tmp,
            entry_id="retained_entry_000001",
        )
        assert looked_up_by_id is not None
        assert looked_up_by_id.turn_index == 1
        assert looked_up_by_id.role == "user"
    finally:
        cleanup_test_path(tmp)
