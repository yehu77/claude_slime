"""Consistency checks for retained-history and request-context artifacts."""

from __future__ import annotations

from pydantic import BaseModel, Field

from pycodeagent.agent.history_replay import (
    build_retained_entry_index,
    load_request_context_entries,
    load_retained_history_entries,
    reconstruct_post_compaction_messages_from_pre_compaction,
    reconstruct_pre_compaction_messages,
    reconstruct_selected_messages,
)
from pycodeagent.agent.request_context import RequestContextEntry
from pycodeagent.agent.retained_history import RetainedHistoryEntry


class HistoryConsistencyReport(BaseModel):
    """Structured result for one request-context consistency check."""

    turn_index: int
    ok: bool
    reconstructed_message_count: int = 0
    reconstructed_pre_compaction_message_count: int = 0
    errors: list[str] = Field(default_factory=list)


def verify_request_context_entry(
    entry: RequestContextEntry,
    retained_entry_index: dict[str, RetainedHistoryEntry],
) -> HistoryConsistencyReport:
    errors: list[str] = []

    for retained_entry_id in entry.selected_retained_entry_ids:
        if retained_entry_id not in retained_entry_index:
            errors.append(f"missing selected retained entry: {retained_entry_id}")
    for retained_entry_id in entry.omitted_retained_entry_ids:
        if retained_entry_id not in retained_entry_index:
            errors.append(f"missing omitted retained entry: {retained_entry_id}")

    reconstructed_message_count = 0
    reconstructed_pre_compaction_message_count = 0
    if not errors:
        try:
            reconstructed = reconstruct_selected_messages(entry, retained_entry_index)
            reconstructed_message_count = len(reconstructed)
        except (KeyError, ValueError) as exc:
            errors.append(str(exc))

    if reconstructed_message_count and reconstructed_message_count != entry.request_message_count:
        errors.append(
            "request message count mismatch: "
            f"entry={entry.request_message_count} reconstructed={reconstructed_message_count}"
        )

    if entry.replacement_history_active:
        if entry.summary_retained_entry_id is None:
            errors.append("replacement history active but summary_retained_entry_id is missing")
        if entry.carried_forward_state_entry_id is None:
            errors.append(
                "replacement history active but carried_forward_state_entry_id is missing"
            )
        if entry.replacement_history_record_id is None:
            errors.append(
                "replacement history active but replacement_history_record_id is missing"
            )

        summary_entry = (
            retained_entry_index.get(entry.summary_retained_entry_id)
            if entry.summary_retained_entry_id is not None
            else None
        )
        if summary_entry is None and entry.summary_retained_entry_id is not None:
            errors.append(
                f"missing replacement summary entry: {entry.summary_retained_entry_id}"
            )
        elif summary_entry is not None:
            if summary_entry.source_kind != "replacement_summary":
                errors.append(
                    "summary retained entry has wrong source kind: "
                    f"{summary_entry.source_kind}"
                )
            source_retained_entry_ids = list(
                summary_entry.metadata.get("source_retained_entry_ids") or []
            )
            if source_retained_entry_ids != entry.omitted_retained_entry_ids:
                errors.append(
                    "omitted retained entries do not match replacement summary sources"
                )
            replacement_record_id = summary_entry.metadata.get("replacement_record_id")
            if replacement_record_id != entry.replacement_history_record_id:
                errors.append(
                    "replacement summary record id does not match request context"
                )

        carried_entry = (
            retained_entry_index.get(entry.carried_forward_state_entry_id)
            if entry.carried_forward_state_entry_id is not None
            else None
        )
        if carried_entry is None and entry.carried_forward_state_entry_id is not None:
            errors.append(
                f"missing carried forward entry: {entry.carried_forward_state_entry_id}"
            )
        elif carried_entry is not None:
            if carried_entry.source_kind != "carry_forward_state":
                errors.append(
                    "carried forward retained entry has wrong source kind: "
                    f"{carried_entry.source_kind}"
                )
            replacement_record_id = carried_entry.metadata.get("replacement_record_id")
            if replacement_record_id != entry.replacement_history_record_id:
                errors.append(
                    "carried forward replacement record id does not match request context"
                )

        if entry.summary_retained_entry_id is not None:
            if entry.summary_retained_entry_id not in entry.selected_retained_entry_ids:
                errors.append("selected retained entries do not include the summary entry")
        if entry.carried_forward_state_entry_id is not None:
            if entry.carried_forward_state_entry_id in entry.selected_retained_entry_ids:
                errors.append(
                    "selected retained entries should not directly include carried forward state"
                )
        if not errors:
            try:
                pre_compaction_messages = reconstruct_pre_compaction_messages(
                    entry,
                    retained_entry_index,
                )
                reconstructed_pre_compaction_message_count = len(pre_compaction_messages)
                if (
                    reconstructed_pre_compaction_message_count
                    != entry.request_history_item_count_before_snapshot
                ):
                    errors.append(
                        "pre-compaction request history count mismatch: "
                        f"entry={entry.request_history_item_count_before_snapshot} "
                        f"reconstructed={reconstructed_pre_compaction_message_count}"
                    )
                rebuilt_post_compaction_messages = (
                    reconstruct_post_compaction_messages_from_pre_compaction(
                        entry,
                        retained_entry_index,
                    )
                )
                reconstructed_selected = reconstruct_selected_messages(
                    entry,
                    retained_entry_index,
                )
                if [
                    message.model_dump(mode="json")
                    for message in rebuilt_post_compaction_messages
                ] != [
                    message.model_dump(mode="json")
                    for message in reconstructed_selected
                ]:
                    errors.append(
                        "replacement-history reconstruction does not rebuild the selected post-compaction context"
                    )
            except (KeyError, ValueError) as exc:
                errors.append(str(exc))
    else:
        if entry.summary_retained_entry_id is not None:
            errors.append(
                "summary_retained_entry_id should be absent when replacement history is inactive"
            )
        if entry.carried_forward_state_entry_id is not None:
            errors.append(
                "carried_forward_state_entry_id should be absent when replacement history is inactive"
            )
        if entry.replacement_history_record_id is not None:
            errors.append(
                "replacement_history_record_id should be absent when replacement history is inactive"
            )

    return HistoryConsistencyReport(
        turn_index=entry.turn_index,
        ok=not errors,
        reconstructed_message_count=reconstructed_message_count,
        reconstructed_pre_compaction_message_count=(
            reconstructed_pre_compaction_message_count
        ),
        errors=errors,
    )


def verify_request_context_log(
    request_context_entries: list[RequestContextEntry],
    retained_entries: list[RetainedHistoryEntry],
) -> list[HistoryConsistencyReport]:
    retained_index = build_retained_entry_index(retained_entries)
    return [
        verify_request_context_entry(entry, retained_index)
        for entry in request_context_entries
    ]


def verify_request_context_log_from_paths(
    *,
    request_context_path: str,
    retained_history_path: str,
) -> list[HistoryConsistencyReport]:
    request_context_entries = load_request_context_entries(request_context_path)
    retained_entries = load_retained_history_entries(retained_history_path)
    return verify_request_context_log(request_context_entries, retained_entries)
