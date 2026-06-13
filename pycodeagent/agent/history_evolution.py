"""Cross-turn evolution audit for retained-history and request-context artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from pycodeagent.agent.history_replay import (
    build_retained_entry_index,
    load_request_context_entries,
    load_retained_history_entries,
    reconstruct_pre_compaction_messages,
    reconstruct_selected_messages,
)
from pycodeagent.agent.request_context import RequestContextEntry
from pycodeagent.agent.retained_history import RetainedHistoryEntry


class HistoryEvolutionTransition(BaseModel):
    """One cross-turn request-history evolution step."""

    previous_turn_index: int | None = None
    turn_index: int
    previous_request_context_entry_id: str | None = None
    request_context_entry_id: str
    transition_kind: str
    ok: bool
    previous_selected_message_count: int = 0
    pre_compaction_message_count: int = 0
    selected_message_count: int = 0
    appended_source_message_count: int = 0
    appended_source_retained_entry_ids: list[str] = Field(default_factory=list)
    appended_source_indices: list[int] = Field(default_factory=list)
    snapshot_appended_retained_entry_ids: list[str] = Field(default_factory=list)
    snapshot_appended_kinds: list[str] = Field(default_factory=list)
    replacement_history_record_id: str | None = None
    summary_retained_entry_id: str | None = None
    carried_forward_state_entry_id: str | None = None
    prefix_carryover_ok: bool = False
    appended_suffix_ok: bool = False
    errors: list[str] = Field(default_factory=list)


class HistoryEvolutionReport(BaseModel):
    """Structured post-run evolution report for request-visible history."""

    schema_version: int = 1
    turn_count: int
    transition_count: int
    ok: bool
    total_appended_source_message_count: int = 0
    total_compaction_transition_count: int = 0
    total_snapshot_artifact_entry_count: int = 0
    transitions: list[HistoryEvolutionTransition] = Field(default_factory=list)


def build_history_evolution_report(
    request_context_entries: list[RequestContextEntry],
    retained_entries: list[RetainedHistoryEntry],
) -> HistoryEvolutionReport:
    retained_index = build_retained_entry_index(retained_entries)
    transitions: list[HistoryEvolutionTransition] = []

    ordered_entries = sorted(request_context_entries, key=lambda entry: entry.turn_index)
    for idx, entry in enumerate(ordered_entries):
        previous = ordered_entries[idx - 1] if idx > 0 else None
        errors: list[str] = []
        previous_selected_count = 0
        pre_compaction_count = 0
        selected_count = 0
        prefix_carryover_ok = False
        appended_suffix_ok = False

        try:
            selected_messages = reconstruct_selected_messages(entry, retained_index)
            selected_count = len(selected_messages)
        except (KeyError, ValueError) as exc:
            errors.append(str(exc))
            selected_messages = []

        try:
            pre_compaction_messages = reconstruct_pre_compaction_messages(
                entry,
                retained_index,
            )
            pre_compaction_count = len(pre_compaction_messages)
        except (KeyError, ValueError) as exc:
            errors.append(str(exc))
            pre_compaction_messages = []

        before_snapshot_entries = retained_entries[: entry.retained_entry_count_before_snapshot]
        after_snapshot_entries = retained_entries[
            entry.retained_entry_count_before_snapshot : entry.retained_entry_count_after_snapshot
        ]
        snapshot_appended_retained_entry_ids = [
            retained_entry.entry_id for retained_entry in after_snapshot_entries
        ]
        snapshot_appended_kinds = [
            retained_entry.source_kind for retained_entry in after_snapshot_entries
        ]

        if previous is None:
            initial_source_entries = [
                retained_entry
                for retained_entry in before_snapshot_entries
                if retained_entry.source_kind == "source_message"
            ]
            initial_messages = []
            for retained_entry in initial_source_entries:
                payload = retained_entry.metadata.get("message_payload")
                if isinstance(payload, dict):
                    initial_messages.append(payload)
            if len(initial_messages) != len(pre_compaction_messages):
                errors.append(
                    "initial history mismatch: "
                    f"retained_source_count={len(initial_messages)} "
                    f"pre_compaction_count={len(pre_compaction_messages)}"
                )
            else:
                prefix_carryover_ok = True
                appended_suffix_ok = [
                    message.model_dump(mode="json") for message in pre_compaction_messages
                ] == initial_messages

            transition_kind = (
                "initial_compaction_snapshot"
                if entry.replacement_history_active
                else "initial_snapshot"
            )
            appended_source_message_count = len(initial_source_entries)
            appended_source_retained_entry_ids = [
                retained_entry.entry_id for retained_entry in initial_source_entries
            ]
            appended_source_indices = [
                retained_entry.source_trajectory_index
                for retained_entry in initial_source_entries
                if retained_entry.source_trajectory_index is not None
            ]
        else:
            try:
                previous_selected_messages = reconstruct_selected_messages(
                    previous,
                    retained_index,
                )
                previous_selected_count = len(previous_selected_messages)
            except (KeyError, ValueError) as exc:
                errors.append(str(exc))
                previous_selected_messages = []

            if len(pre_compaction_messages) < len(previous_selected_messages):
                errors.append(
                    "pre-compaction history is shorter than previous selected context"
                )
                appended_messages = []
            else:
                previous_payloads = [
                    message.model_dump(mode="json")
                    for message in previous_selected_messages
                ]
                current_prefix_payloads = [
                    message.model_dump(mode="json")
                    for message in pre_compaction_messages[: len(previous_selected_messages)]
                ]
                prefix_carryover_ok = current_prefix_payloads == previous_payloads
                if not prefix_carryover_ok:
                    errors.append(
                        "previous selected context is not preserved as the prefix of current pre-compaction history"
                    )
                appended_messages = pre_compaction_messages[len(previous_selected_messages) :]

            between_snapshot_entries = retained_entries[
                previous.retained_entry_count_after_snapshot : entry.retained_entry_count_before_snapshot
            ]
            appended_source_entries = [
                retained_entry
                for retained_entry in between_snapshot_entries
                if retained_entry.source_kind == "source_message"
            ]
            appended_source_payloads = []
            for retained_entry in appended_source_entries:
                payload = retained_entry.metadata.get("message_payload")
                if isinstance(payload, dict):
                    appended_source_payloads.append(payload)
            appended_suffix_ok = [
                message.model_dump(mode="json") for message in appended_messages
            ] == appended_source_payloads
            if not appended_suffix_ok:
                errors.append(
                    "newly appended source history does not match the suffix added since the previous snapshot"
                )

            transition_kind = (
                "replacement_compaction"
                if entry.replacement_history_active
                else "append_only"
            )
            appended_source_message_count = len(appended_source_entries)
            appended_source_retained_entry_ids = [
                retained_entry.entry_id for retained_entry in appended_source_entries
            ]
            appended_source_indices = [
                retained_entry.source_trajectory_index
                for retained_entry in appended_source_entries
                if retained_entry.source_trajectory_index is not None
            ]

        transition = HistoryEvolutionTransition(
            previous_turn_index=(
                previous.turn_index if previous is not None else None
            ),
            turn_index=entry.turn_index,
            previous_request_context_entry_id=(
                previous.entry_id if previous is not None else None
            ),
            request_context_entry_id=entry.entry_id,
            transition_kind=transition_kind,
            ok=not errors,
            previous_selected_message_count=previous_selected_count,
            pre_compaction_message_count=pre_compaction_count,
            selected_message_count=selected_count,
            appended_source_message_count=appended_source_message_count,
            appended_source_retained_entry_ids=appended_source_retained_entry_ids,
            appended_source_indices=appended_source_indices,
            snapshot_appended_retained_entry_ids=snapshot_appended_retained_entry_ids,
            snapshot_appended_kinds=snapshot_appended_kinds,
            replacement_history_record_id=entry.replacement_history_record_id,
            summary_retained_entry_id=entry.summary_retained_entry_id,
            carried_forward_state_entry_id=entry.carried_forward_state_entry_id,
            prefix_carryover_ok=prefix_carryover_ok,
            appended_suffix_ok=appended_suffix_ok,
            errors=errors,
        )
        transitions.append(transition)

    return HistoryEvolutionReport(
        turn_count=len(ordered_entries),
        transition_count=len(transitions),
        ok=all(transition.ok for transition in transitions),
        total_appended_source_message_count=sum(
            transition.appended_source_message_count for transition in transitions
        ),
        total_compaction_transition_count=sum(
            1 for transition in transitions if transition.transition_kind == "replacement_compaction"
        ),
        total_snapshot_artifact_entry_count=sum(
            len(transition.snapshot_appended_retained_entry_ids)
            for transition in transitions
        ),
        transitions=transitions,
    )


def build_history_evolution_report_from_paths(
    *,
    request_context_path: str | Path,
    retained_history_path: str | Path,
) -> HistoryEvolutionReport:
    request_context_entries = load_request_context_entries(request_context_path)
    retained_entries = load_retained_history_entries(retained_history_path)
    return build_history_evolution_report(request_context_entries, retained_entries)


def write_history_evolution_report(run_dir: str | Path) -> HistoryEvolutionReport:
    run_dir = Path(run_dir)
    report = build_history_evolution_report_from_paths(
        request_context_path=run_dir / "request_context.jsonl",
        retained_history_path=run_dir / "retained_history.jsonl",
    )
    (run_dir / "history_evolution_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report
