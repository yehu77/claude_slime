"""Unified reconciliation/query surface for runtime history artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from pycodeagent.agent.history_lineage import (
    HistoryLineageReport,
    ReplacementHistoryLineageRecord,
    build_history_lineage_report,
)
from pycodeagent.agent.history_replay import (
    build_retained_entry_index,
    load_request_context_entries,
    load_retained_history_entries,
    reconstruct_pre_compaction_messages,
    reconstruct_selected_messages,
)
from pycodeagent.agent.request_context import (
    RequestContextEntry,
    request_context_metadata,
)
from pycodeagent.agent.retained_history import (
    RetainedHistoryEntry,
    retained_history_metadata,
)


class ReplacementHistoryReconciliationRecord(BaseModel):
    """One fully reconciled replacement-history record."""

    record_id: str
    turn_index: int
    request_context_entry_id: str
    summary_retained_entry_id: str | None = None
    carried_forward_state_entry_id: str | None = None
    compaction_artifact_entry_id: str | None = None
    source_retained_entry_ids: list[str] = Field(default_factory=list)
    source_trajectory_indices: list[int] = Field(default_factory=list)
    selected_message_count: int = 0
    pre_compaction_message_count: int = 0
    selected_message_roles: list[str] = Field(default_factory=list)
    pre_compaction_message_roles: list[str] = Field(default_factory=list)
    ok: bool
    errors: list[str] = Field(default_factory=list)


class HistoryReconciliationReport(BaseModel):
    """Compact query/report artifact over history lineage and replay surfaces."""

    schema_version: int = 1
    request_context_log_id: str
    retained_history_log_id: str
    replacement_record_count: int
    replacement_record_ids: list[str] = Field(default_factory=list)
    replacement_turn_indices: list[int] = Field(default_factory=list)
    ok: bool
    records: list[ReplacementHistoryReconciliationRecord] = Field(default_factory=list)


class HistoryReconciliationBundle(BaseModel):
    """In-memory query bundle for a run's history artifacts."""

    request_context_log_id: str
    retained_history_log_id: str
    lineage_report: HistoryLineageReport
    records: list[ReplacementHistoryReconciliationRecord]

    def ordered_records(self) -> list[ReplacementHistoryReconciliationRecord]:
        return sorted(self.records, key=lambda record: (record.turn_index, record.record_id))

    def record_ids(self) -> list[str]:
        return [record.record_id for record in self.ordered_records()]

    def get_record(self, record_id: str) -> ReplacementHistoryReconciliationRecord | None:
        for record in self.records:
            if record.record_id == record_id:
                return record
        return None

    def get_predecessor(
        self,
        record_id: str,
    ) -> ReplacementHistoryReconciliationRecord | None:
        ordered = self.ordered_records()
        for index, record in enumerate(ordered):
            if record.record_id == record_id:
                return ordered[index - 1] if index > 0 else None
        return None

    def get_successor(
        self,
        record_id: str,
    ) -> ReplacementHistoryReconciliationRecord | None:
        ordered = self.ordered_records()
        for index, record in enumerate(ordered):
            if record.record_id == record_id:
                return ordered[index + 1] if index + 1 < len(ordered) else None
        return None


class CompactionChainNode(BaseModel):
    """One ordered node in the session-level compaction chain."""

    record_id: str
    turn_index: int
    predecessor_record_id: str | None = None
    successor_record_id: str | None = None
    request_context_entry_id: str
    summary_retained_entry_id: str | None = None
    carried_forward_state_entry_id: str | None = None
    compaction_artifact_entry_id: str | None = None
    source_retained_entry_ids: list[str] = Field(default_factory=list)
    source_trajectory_indices: list[int] = Field(default_factory=list)
    selected_message_count: int = 0
    pre_compaction_message_count: int = 0
    ok: bool
    errors: list[str] = Field(default_factory=list)


class CompactionChainReport(BaseModel):
    """Ordered compaction-chain view over replacement-history records."""

    schema_version: int = 1
    request_context_log_id: str
    retained_history_log_id: str
    chain_length: int
    ordered_record_ids: list[str] = Field(default_factory=list)
    ordered_turn_indices: list[int] = Field(default_factory=list)
    ok: bool
    nodes: list[CompactionChainNode] = Field(default_factory=list)


def build_history_reconciliation_bundle(
    request_context_entries: list[RequestContextEntry],
    retained_entries: list[RetainedHistoryEntry],
    *,
    request_context_log_id: str,
    retained_history_log_id: str,
) -> HistoryReconciliationBundle:
    lineage_report = build_history_lineage_report(
        request_context_entries,
        retained_entries,
        request_context_log_id=request_context_log_id,
        retained_history_log_id=retained_history_log_id,
    )
    request_context_by_record_id = {
        entry.replacement_history_record_id: entry
        for entry in request_context_entries
        if entry.replacement_history_record_id
    }
    retained_index = build_retained_entry_index(retained_entries)

    records: list[ReplacementHistoryReconciliationRecord] = []
    for lineage_record in lineage_report.records:
        request_context_entry = request_context_by_record_id.get(lineage_record.record_id)
        errors = list(lineage_record.errors)
        selected_messages = []
        pre_compaction_messages = []

        if request_context_entry is None:
            errors.append(
                "request context entry not found for replacement_history_record_id"
            )
        else:
            try:
                selected_messages = reconstruct_selected_messages(
                    request_context_entry,
                    retained_index,
                )
            except (KeyError, ValueError) as exc:
                errors.append(str(exc))
            try:
                pre_compaction_messages = reconstruct_pre_compaction_messages(
                    request_context_entry,
                    retained_index,
                )
            except (KeyError, ValueError) as exc:
                errors.append(str(exc))

        records.append(
            ReplacementHistoryReconciliationRecord(
                record_id=lineage_record.record_id,
                turn_index=lineage_record.turn_index,
                request_context_entry_id=lineage_record.request_context_entry_id,
                summary_retained_entry_id=lineage_record.summary_retained_entry_id,
                carried_forward_state_entry_id=(
                    lineage_record.carried_forward_state_entry_id
                ),
                compaction_artifact_entry_id=lineage_record.compaction_artifact_entry_id,
                source_retained_entry_ids=list(lineage_record.source_retained_entry_ids),
                source_trajectory_indices=list(lineage_record.source_trajectory_indices),
                selected_message_count=len(selected_messages),
                pre_compaction_message_count=len(pre_compaction_messages),
                selected_message_roles=[
                    message.role.value for message in selected_messages
                ],
                pre_compaction_message_roles=[
                    message.role.value for message in pre_compaction_messages
                ],
                ok=not errors,
                errors=errors,
            )
        )

    return HistoryReconciliationBundle(
        request_context_log_id=request_context_log_id,
        retained_history_log_id=retained_history_log_id,
        lineage_report=lineage_report,
        records=records,
    )


def load_history_reconciliation_bundle(
    run_dir: str | Path,
) -> HistoryReconciliationBundle:
    run_dir = Path(run_dir)
    request_context_entries = load_request_context_entries(run_dir / "request_context.jsonl")
    retained_entries = load_retained_history_entries(run_dir / "retained_history.jsonl")
    request_context_log_id = request_context_metadata(run_dir).log_id
    retained_history_log_id = retained_history_metadata(run_dir).log_id
    return build_history_reconciliation_bundle(
        request_context_entries,
        retained_entries,
        request_context_log_id=request_context_log_id,
        retained_history_log_id=retained_history_log_id,
    )


def build_history_reconciliation_report(
    bundle: HistoryReconciliationBundle,
) -> HistoryReconciliationReport:
    ordered_records = bundle.ordered_records()
    return HistoryReconciliationReport(
        request_context_log_id=bundle.request_context_log_id,
        retained_history_log_id=bundle.retained_history_log_id,
        replacement_record_count=len(ordered_records),
        replacement_record_ids=[record.record_id for record in ordered_records],
        replacement_turn_indices=[record.turn_index for record in ordered_records],
        ok=all(record.ok for record in ordered_records),
        records=ordered_records,
    )


def build_compaction_chain_report(
    bundle: HistoryReconciliationBundle,
) -> CompactionChainReport:
    ordered_records = bundle.ordered_records()
    nodes: list[CompactionChainNode] = []
    for index, record in enumerate(ordered_records):
        predecessor = ordered_records[index - 1] if index > 0 else None
        successor = (
            ordered_records[index + 1] if index + 1 < len(ordered_records) else None
        )
        nodes.append(
            CompactionChainNode(
                record_id=record.record_id,
                turn_index=record.turn_index,
                predecessor_record_id=(
                    predecessor.record_id if predecessor is not None else None
                ),
                successor_record_id=(
                    successor.record_id if successor is not None else None
                ),
                request_context_entry_id=record.request_context_entry_id,
                summary_retained_entry_id=record.summary_retained_entry_id,
                carried_forward_state_entry_id=record.carried_forward_state_entry_id,
                compaction_artifact_entry_id=record.compaction_artifact_entry_id,
                source_retained_entry_ids=list(record.source_retained_entry_ids),
                source_trajectory_indices=list(record.source_trajectory_indices),
                selected_message_count=record.selected_message_count,
                pre_compaction_message_count=record.pre_compaction_message_count,
                ok=record.ok,
                errors=list(record.errors),
            )
        )
    return CompactionChainReport(
        request_context_log_id=bundle.request_context_log_id,
        retained_history_log_id=bundle.retained_history_log_id,
        chain_length=len(nodes),
        ordered_record_ids=[node.record_id for node in nodes],
        ordered_turn_indices=[node.turn_index for node in nodes],
        ok=all(node.ok for node in nodes),
        nodes=nodes,
    )


def write_history_reconciliation_report(
    run_dir: str | Path,
) -> HistoryReconciliationReport:
    run_dir = Path(run_dir)
    bundle = load_history_reconciliation_bundle(run_dir)
    report = build_history_reconciliation_report(bundle)
    (run_dir / "history_reconciliation_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def write_compaction_chain_report(
    run_dir: str | Path,
) -> CompactionChainReport:
    run_dir = Path(run_dir)
    bundle = load_history_reconciliation_bundle(run_dir)
    report = build_compaction_chain_report(bundle)
    (run_dir / "compaction_chain_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report
