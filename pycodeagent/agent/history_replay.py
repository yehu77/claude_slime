"""Helpers for replaying request-time selected context from runtime artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.agent.request_context import (
    RequestContextEntry,
    iter_request_context_entries,
)
from pycodeagent.agent.retained_history import (
    RetainedHistoryEntry,
    iter_retained_history_entries,
)
from pycodeagent.trajectory.schema import Message, Role


def load_retained_history_entries(path: str | Path) -> list[RetainedHistoryEntry]:
    return iter_retained_history_entries(path)


def load_request_context_entries(path: str | Path) -> list[RequestContextEntry]:
    return iter_request_context_entries(path)


def build_retained_entry_index(
    entries: list[RetainedHistoryEntry],
) -> dict[str, RetainedHistoryEntry]:
    return {entry.entry_id: entry for entry in entries}


def retained_entry_to_message(entry: RetainedHistoryEntry) -> Message | None:
    payload = entry.metadata.get("message_payload")
    if isinstance(payload, dict):
        return Message.model_validate(payload)
    if entry.role is None:
        return None
    return Message(
        role=Role(entry.role),
        content=entry.text,
        tool_call_id=entry.metadata.get("tool_call_id"),
        tool_name=entry.metadata.get("tool_name"),
        canonical_name=entry.metadata.get("canonical_name"),
        tool_version=entry.metadata.get("tool_version"),
        metadata=dict(entry.metadata.get("message_metadata") or {}),
    )


def reconstruct_selected_messages(
    request_context_entry: RequestContextEntry,
    retained_entry_index: dict[str, RetainedHistoryEntry],
) -> list[Message]:
    messages: list[Message] = []
    for retained_entry_id in request_context_entry.selected_retained_entry_ids:
        entry = retained_entry_index.get(retained_entry_id)
        if entry is None:
            raise KeyError(f"missing retained entry for selected context: {retained_entry_id}")
        message = retained_entry_to_message(entry)
        if message is None:
            raise ValueError(
                f"retained entry {retained_entry_id} does not contain replayable message payload"
            )
        messages.append(message)
    return messages


def reconstruct_pre_compaction_messages(
    request_context_entry: RequestContextEntry,
    retained_entry_index: dict[str, RetainedHistoryEntry],
) -> list[Message]:
    if not request_context_entry.replacement_history_active:
        return reconstruct_selected_messages(request_context_entry, retained_entry_index)

    if request_context_entry.summary_retained_entry_id is None:
        raise ValueError("replacement history is active but summary_retained_entry_id is missing")

    summary_entry = retained_entry_index.get(request_context_entry.summary_retained_entry_id)
    if summary_entry is None:
        raise KeyError(
            "missing replacement summary entry: "
            f"{request_context_entry.summary_retained_entry_id}"
        )

    source_retained_entry_ids = list(
        summary_entry.metadata.get("source_retained_entry_ids") or []
    )
    source_trajectory_indices = list(
        summary_entry.metadata.get("source_trajectory_indices") or []
    )
    if len(source_retained_entry_ids) != len(source_trajectory_indices):
        raise ValueError(
            "replacement summary source_retained_entry_ids and source_trajectory_indices "
            "length mismatch"
        )

    ordered_pairs: list[tuple[int, Message]] = []
    for retained_entry_id in request_context_entry.selected_retained_entry_ids:
        if retained_entry_id == request_context_entry.summary_retained_entry_id:
            continue
        entry = retained_entry_index.get(retained_entry_id)
        if entry is None:
            raise KeyError(f"missing selected retained entry for replay: {retained_entry_id}")
        if entry.source_trajectory_index is None:
            raise ValueError(
                f"selected retained entry {retained_entry_id} lacks source_trajectory_index"
            )
        message = retained_entry_to_message(entry)
        if message is None:
            raise ValueError(
                f"selected retained entry {retained_entry_id} does not contain message payload"
            )
        ordered_pairs.append((entry.source_trajectory_index, message))

    for source_retained_entry_id, source_trajectory_index in zip(
        source_retained_entry_ids,
        source_trajectory_indices,
        strict=False,
    ):
        entry = retained_entry_index.get(source_retained_entry_id)
        if entry is None:
            raise KeyError(
                f"missing compacted source retained entry for replay: {source_retained_entry_id}"
            )
        message = retained_entry_to_message(entry)
        if message is None:
            raise ValueError(
                f"compacted retained entry {source_retained_entry_id} does not contain message payload"
            )
        ordered_pairs.append((int(source_trajectory_index), message))

    ordered_pairs.sort(key=lambda pair: pair[0])
    return [message for _, message in ordered_pairs]


def reconstruct_post_compaction_messages_from_pre_compaction(
    request_context_entry: RequestContextEntry,
    retained_entry_index: dict[str, RetainedHistoryEntry],
) -> list[Message]:
    if not request_context_entry.replacement_history_active:
        return reconstruct_selected_messages(request_context_entry, retained_entry_index)

    if request_context_entry.summary_retained_entry_id is None:
        raise ValueError("replacement history is active but summary_retained_entry_id is missing")

    summary_entry = retained_entry_index.get(request_context_entry.summary_retained_entry_id)
    if summary_entry is None:
        raise KeyError(
            "missing replacement summary entry: "
            f"{request_context_entry.summary_retained_entry_id}"
        )
    summary_message = retained_entry_to_message(summary_entry)
    if summary_message is None:
        raise ValueError("replacement summary entry does not contain message payload")

    source_trajectory_indices = sorted(
        int(index)
        for index in (summary_entry.metadata.get("source_trajectory_indices") or [])
    )
    if not source_trajectory_indices:
        raise ValueError("replacement summary does not contain source_trajectory_indices")

    compacted_index_set = set(source_trajectory_indices)
    pre_messages = reconstruct_pre_compaction_messages(
        request_context_entry,
        retained_entry_index,
    )

    post_messages: list[Message] = []
    summary_inserted = False
    pre_indices = sorted(
        [
            entry.source_trajectory_index
            for entry in retained_entry_index.values()
            if entry.entry_id in (
                set(summary_entry.metadata.get("source_retained_entry_ids") or [])
                | {
                    retained_entry_id
                    for retained_entry_id in request_context_entry.selected_retained_entry_ids
                    if retained_entry_id != request_context_entry.summary_retained_entry_id
                }
            )
            and entry.source_trajectory_index is not None
        ]
    )
    if len(pre_indices) != len(pre_messages):
        raise ValueError("unable to align reconstructed pre-compaction messages to source indices")

    for source_index, message in zip(pre_indices, pre_messages, strict=False):
        if source_index in compacted_index_set:
            if not summary_inserted:
                post_messages.append(summary_message)
                summary_inserted = True
            continue
        post_messages.append(message)
    return post_messages


def reconstruct_selected_messages_from_paths(
    *,
    retained_history_path: str | Path,
    request_context_path: str | Path,
    turn_index: int,
) -> list[Message]:
    retained_entries = load_retained_history_entries(retained_history_path)
    request_context_entries = load_request_context_entries(request_context_path)
    request_context_entry = next(
        entry for entry in request_context_entries if entry.turn_index == turn_index
    )
    retained_index = build_retained_entry_index(retained_entries)
    return reconstruct_selected_messages(request_context_entry, retained_index)
