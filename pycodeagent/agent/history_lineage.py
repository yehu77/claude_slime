"""Cross-artifact lineage report for replacement-history / compaction records."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from pycodeagent.agent.request_context import (
    RequestContextEntry,
    iter_request_context_entries,
    load_request_context_manifest,
)
from pycodeagent.agent.retained_history import (
    RetainedHistoryEntry,
    iter_retained_history_entries,
    load_retained_history_manifest,
)


class ReplacementHistoryLineageRecord(BaseModel):
    """One reconciled replacement-history lineage record."""

    record_id: str
    turn_index: int
    request_context_entry_id: str
    request_context_log_id: str
    retained_history_log_id: str
    summary_retained_entry_id: str | None = None
    carried_forward_state_entry_id: str | None = None
    compaction_artifact_entry_id: str | None = None
    source_retained_entry_ids: list[str] = Field(default_factory=list)
    source_trajectory_indices: list[int] = Field(default_factory=list)
    source_item_count: int = 0
    ok: bool
    errors: list[str] = Field(default_factory=list)


class HistoryLineageReport(BaseModel):
    """Cross-artifact lineage summary for replacement-history records."""

    schema_version: int = 1
    request_context_log_id: str
    retained_history_log_id: str
    replacement_record_count: int
    ok: bool
    records: list[ReplacementHistoryLineageRecord] = Field(default_factory=list)


def _manifest_log_id(run_id: str, started_at_unix_ms: int) -> str:
    return f"{run_id}:{started_at_unix_ms}"


def build_history_lineage_report(
    request_context_entries: list[RequestContextEntry],
    retained_entries: list[RetainedHistoryEntry],
    *,
    request_context_log_id: str,
    retained_history_log_id: str,
) -> HistoryLineageReport:
    retained_by_id = {entry.entry_id: entry for entry in retained_entries}
    records: list[ReplacementHistoryLineageRecord] = []

    for entry in sorted(request_context_entries, key=lambda item: item.turn_index):
        if not entry.replacement_history_active or not entry.replacement_history_record_id:
            continue

        record_id = entry.replacement_history_record_id
        errors: list[str] = []

        summary_entry = (
            retained_by_id.get(entry.summary_retained_entry_id)
            if entry.summary_retained_entry_id
            else None
        )
        carried_entry = (
            retained_by_id.get(entry.carried_forward_state_entry_id)
            if entry.carried_forward_state_entry_id
            else None
        )

        if summary_entry is None:
            errors.append("missing replacement summary entry")
            source_retained_entry_ids: list[str] = []
            source_trajectory_indices: list[int] = []
        else:
            if summary_entry.source_kind != "replacement_summary":
                errors.append(
                    f"summary entry has unexpected source_kind={summary_entry.source_kind}"
                )
            if summary_entry.metadata.get("replacement_record_id") != record_id:
                errors.append("summary entry replacement_record_id mismatch")
            source_retained_entry_ids = list(
                summary_entry.metadata.get("source_retained_entry_ids") or []
            )
            source_trajectory_indices = list(
                summary_entry.metadata.get("source_trajectory_indices") or []
            )

        if carried_entry is None:
            errors.append("missing carried forward state entry")
        else:
            if carried_entry.source_kind != "carry_forward_state":
                errors.append(
                    "carried forward entry has unexpected "
                    f"source_kind={carried_entry.source_kind}"
                )
            if carried_entry.metadata.get("replacement_record_id") != record_id:
                errors.append("carried forward entry replacement_record_id mismatch")

        compaction_artifact_entries = [
            retained_entry
            for retained_entry in retained_entries
            if retained_entry.turn_index == entry.turn_index
            and retained_entry.source_kind == "history_control"
            and retained_entry.metadata.get("control_kind") == "compaction_artifact"
        ]
        compaction_artifact_entry_id: str | None = None
        if len(compaction_artifact_entries) == 1:
            compaction_artifact_entry_id = compaction_artifact_entries[0].entry_id
        elif len(compaction_artifact_entries) == 0:
            errors.append("missing compaction artifact entry")
        else:
            errors.append("ambiguous compaction artifact entry for replacement turn")

        for source_retained_entry_id in source_retained_entry_ids:
            source_entry = retained_by_id.get(source_retained_entry_id)
            if source_entry is None:
                errors.append(
                    f"missing compacted source retained entry: {source_retained_entry_id}"
                )
                continue
            if source_entry.source_kind != "source_message":
                errors.append(
                    "compacted source retained entry has unexpected "
                    f"source_kind={source_entry.source_kind}"
                )

        if entry.summary_retained_entry_id not in entry.selected_retained_entry_ids:
            errors.append("selected_retained_entry_ids does not include summary entry")

        if entry.carried_forward_state_entry_id in entry.selected_retained_entry_ids:
            errors.append("selected_retained_entry_ids should not include carried forward entry")

        records.append(
            ReplacementHistoryLineageRecord(
                record_id=record_id,
                turn_index=entry.turn_index,
                request_context_entry_id=entry.entry_id,
                request_context_log_id=request_context_log_id,
                retained_history_log_id=retained_history_log_id,
                summary_retained_entry_id=entry.summary_retained_entry_id,
                carried_forward_state_entry_id=entry.carried_forward_state_entry_id,
                compaction_artifact_entry_id=compaction_artifact_entry_id,
                source_retained_entry_ids=source_retained_entry_ids,
                source_trajectory_indices=source_trajectory_indices,
                source_item_count=len(source_retained_entry_ids),
                ok=not errors,
                errors=errors,
            )
        )

    return HistoryLineageReport(
        request_context_log_id=request_context_log_id,
        retained_history_log_id=retained_history_log_id,
        replacement_record_count=len(records),
        ok=all(record.ok for record in records),
        records=records,
    )


def write_history_lineage_report(run_dir: str | Path) -> HistoryLineageReport:
    run_dir = Path(run_dir)
    request_manifest = load_request_context_manifest(run_dir)
    retained_manifest = load_retained_history_manifest(run_dir)
    request_context_log_id = _manifest_log_id(
        request_manifest.run_id,
        request_manifest.started_at_unix_ms,
    )
    retained_history_log_id = _manifest_log_id(
        retained_manifest.run_id,
        retained_manifest.started_at_unix_ms,
    )

    request_context_entries = iter_request_context_entries(run_dir)
    retained_entries = iter_retained_history_entries(run_dir)

    report = build_history_lineage_report(
        request_context_entries,
        retained_entries,
        request_context_log_id=request_context_log_id,
        retained_history_log_id=retained_history_log_id,
    )
    (run_dir / "history_lineage_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report
