"""Append-only request-context snapshots for runtime-owned selected history."""

from __future__ import annotations

import json
from pathlib import Path
from time import time

from pydantic import BaseModel, Field

from pycodeagent.agent.history_manager import RuntimeHistorySnapshot


def _unix_time_ms() -> int:
    return int(time() * 1000)


class RequestContextEntry(BaseModel):
    """One append-only selected-context snapshot."""

    schema_version: int = 1
    entry_id: str
    run_id: str
    task_id: str
    turn_index: int
    policy_mode: str
    context_max_messages: int | None = None
    context_max_tokens: int | None = None
    request_message_count: int = 0
    request_history_item_ids: list[str] = Field(default_factory=list)
    request_history_item_kinds: list[str] = Field(default_factory=list)
    request_history_source_indices: list[int] = Field(default_factory=list)
    context_selection_retained_entry_id: str | None = None
    included_message_indices: list[int] = Field(default_factory=list)
    omitted_message_count: int = 0
    compacted_message_count: int = 0
    compaction_applied: bool = False
    compaction_reason: str | None = None
    compaction_considered: bool = False
    compaction_considered_reason: str | None = None
    compaction_skip_reason: str | None = None
    trigger_message_overflow: bool = False
    trigger_token_overflow: bool = False
    pinned_message_indices: list[int] = Field(default_factory=list)
    preserved_from_turn: int | None = None
    candidate_turn_indices: list[int] = Field(default_factory=list)
    compacted_turn_indices: list[int] = Field(default_factory=list)
    model_backed_requested: bool = False
    model_backed_used: bool = False
    compaction_backend_mode: str | None = None
    fallback_policy: str | None = None
    fallback_applied: bool = False
    fallback_reason: str | None = None
    compaction_backend_failure_kind: str | None = None
    selected_retained_entry_ids: list[str] = Field(default_factory=list)
    omitted_retained_entry_ids: list[str] = Field(default_factory=list)
    summary_retained_entry_id: str | None = None
    carried_forward_state_entry_id: str | None = None
    retained_history_last_entry_id: str | None = None
    retained_entry_count_before_snapshot: int = 0
    retained_entry_count_after_snapshot: int = 0
    request_history_item_count_before_snapshot: int = 0
    request_history_item_count_after_snapshot: int = 0
    replacement_history_active: bool = False
    replacement_history_record_id: str | None = None
    summary_slot_included: bool = False
    carried_forward_state_present: bool = False
    estimated_selected_tokens: int = 0
    estimated_omitted_tokens: int = 0
    tool_token_reserve: int = 0
    response_token_reserve: int = 0
    token_budget_satisfied: bool = True
    token_overflow: int = 0
    ts_unix_ms: int


class RequestContextManifest(BaseModel):
    """Manifest for one request-context bundle."""

    schema_version: int = 1
    run_id: str
    task_id: str
    workspace_root: str
    started_at_unix_ms: int
    ended_at_unix_ms: int | None = None
    entry_log_path: str
    total_entries: int = 0
    last_entry_id: str | None = None


class RequestContextLookupMetadata(BaseModel):
    """Stable lookup metadata for one request-context log."""

    log_id: str
    entry_count: int
    last_entry_id: str | None = None


def request_context_log_id(manifest: RequestContextManifest) -> str:
    """Return a stable log identity for one request-context artifact."""

    return f"{manifest.run_id}:{manifest.started_at_unix_ms}"


def _entry_belongs_to_manifest(
    entry: RequestContextEntry,
    manifest: RequestContextManifest,
) -> bool:
    if entry.run_id != manifest.run_id:
        return False
    if entry.ts_unix_ms < manifest.started_at_unix_ms:
        return False
    if (
        manifest.ended_at_unix_ms is not None
        and entry.ts_unix_ms > manifest.ended_at_unix_ms
    ):
        return False
    return True


def iter_request_context_entries(
    path: str | Path,
) -> list[RequestContextEntry]:
    """Load only the entries that belong to the current manifest-backed log."""

    manifest_path, entry_log_path = _resolve_request_context_paths(path)
    manifest = RequestContextManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    entries: list[RequestContextEntry] = []
    for line in entry_log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = RequestContextEntry.model_validate_json(line)
        if _entry_belongs_to_manifest(entry, manifest):
            entries.append(entry)
    return entries


def _resolve_request_context_paths(
    path: str | Path,
) -> tuple[Path, Path]:
    resolved = Path(path)
    if resolved.is_dir():
        return (
            resolved / "request_context_manifest.json",
            resolved / "request_context.jsonl",
        )
    if resolved.name == "request_context_manifest.json":
        return resolved, resolved.with_name("request_context.jsonl")
    if resolved.name == "request_context.jsonl":
        return resolved.with_name("request_context_manifest.json"), resolved
    raise ValueError(f"unsupported request context path: {resolved}")


def load_request_context_manifest(path: str | Path) -> RequestContextManifest:
    """Load the request-context manifest from a run dir or artifact path."""

    manifest_path, _ = _resolve_request_context_paths(path)
    return RequestContextManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )


def request_context_metadata(path: str | Path) -> RequestContextLookupMetadata:
    """Return stable lookup metadata for a request-context artifact."""

    manifest_path, entry_log_path = _resolve_request_context_paths(path)
    manifest = RequestContextManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    entry_count = 0
    last_entry_id: str | None = None
    for entry in iter_request_context_entries(path):
        entry_count += 1
        last_entry_id = entry.entry_id
    return RequestContextLookupMetadata(
        log_id=request_context_log_id(manifest),
        entry_count=entry_count,
        last_entry_id=last_entry_id,
    )


def lookup_request_context_entry(
    path: str | Path,
    *,
    log_id: str,
    offset: int,
) -> RequestContextEntry | None:
    """Look up one request-context entry by stable log id and offset."""

    if offset < 0:
        return None

    current_metadata = request_context_metadata(path)
    if current_metadata.log_id != log_id:
        return None

    _, entry_log_path = _resolve_request_context_paths(path)
    current_offset = 0
    for entry in iter_request_context_entries(path):
        if current_offset == offset:
            return entry
        current_offset += 1
    return None


def lookup_request_context_entry_by_id(
    path: str | Path,
    *,
    entry_id: str,
) -> RequestContextEntry | None:
    """Look up one request-context entry by entry id."""

    for entry in iter_request_context_entries(path):
        if entry.entry_id == entry_id:
            return entry
    return None


class RequestContextWriter:
    """Append-only writer for request-time selected context snapshots."""

    def __init__(
        self,
        *,
        run_dir: Path,
        manifest_path: Path,
        entry_log_path: Path,
        manifest: RequestContextManifest,
    ) -> None:
        self._run_dir = run_dir
        self._manifest_path = manifest_path
        self._entry_log_path = entry_log_path
        self._manifest = manifest
        self._next_entry_ordinal = 1

    @classmethod
    def create(
        cls,
        run_dir: str | Path,
        *,
        run_id: str,
        task_id: str,
        workspace_root: str,
    ) -> "RequestContextWriter":
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = run_dir / "request_context_manifest.json"
        entry_log_path = run_dir / "request_context.jsonl"
        manifest = RequestContextManifest(
            run_id=run_id,
            task_id=task_id,
            workspace_root=workspace_root,
            started_at_unix_ms=_unix_time_ms(),
            entry_log_path=entry_log_path.name,
        )
        writer = cls(
            run_dir=run_dir,
            manifest_path=manifest_path,
            entry_log_path=entry_log_path,
            manifest=manifest,
        )
        writer._write_manifest()
        entry_log_path.write_text("", encoding="utf-8")
        return writer

    @property
    def manifest(self) -> RequestContextManifest:
        return self._manifest

    def append_snapshot(
        self,
        *,
        task_id: str,
        turn_index: int,
        snapshot: RuntimeHistorySnapshot,
        context_max_messages: int | None,
    ) -> RequestContextEntry:
        selection = snapshot.context_selection
        ordinal = self._next_entry_ordinal
        self._next_entry_ordinal += 1
        entry = RequestContextEntry(
            entry_id=f"request_context_entry_{ordinal:06d}",
            run_id=self._manifest.run_id,
            task_id=task_id,
            turn_index=turn_index,
            policy_mode=selection.policy_mode,
            context_max_messages=context_max_messages,
            context_max_tokens=selection.context_max_tokens,
            request_message_count=len(snapshot.selected_messages),
            request_history_item_ids=list(snapshot.request_history_item_ids),
            request_history_item_kinds=list(snapshot.request_history_item_kinds),
            request_history_source_indices=list(snapshot.request_history_source_indices),
            context_selection_retained_entry_id=(
                snapshot.context_selection_retained_entry_id
            ),
            included_message_indices=list(selection.included_message_indices),
            omitted_message_count=selection.omitted_message_count,
            compacted_message_count=selection.compacted_message_count,
            compaction_applied=selection.compaction_applied,
            compaction_reason=selection.compaction_reason,
            compaction_considered=snapshot.context_selection_plan.compaction_considered,
            compaction_considered_reason=(
                snapshot.context_selection_plan.compaction_considered_reason
            ),
            compaction_skip_reason=(
                snapshot.context_selection_plan.compaction_skip_reason
            ),
            trigger_message_overflow=(
                snapshot.context_selection_plan.trigger_message_overflow
            ),
            trigger_token_overflow=(
                snapshot.context_selection_plan.trigger_token_overflow
            ),
            pinned_message_indices=list(
                snapshot.context_selection_plan.pinned_message_indices
            ),
            preserved_from_turn=snapshot.context_selection_plan.preserved_from_turn,
            candidate_turn_indices=list(
                snapshot.context_selection_plan.candidate_turn_indices
            ),
            compacted_turn_indices=list(
                snapshot.context_selection_plan.compacted_turn_indices
            ),
            model_backed_requested=snapshot.context_selection_plan.model_backed_requested,
            model_backed_used=snapshot.context_selection_plan.model_backed_used,
            compaction_backend_mode=(
                snapshot.context_selection_plan.compaction_backend_mode
            ),
            fallback_policy=snapshot.context_selection_plan.fallback_policy,
            fallback_applied=snapshot.context_selection_plan.fallback_applied,
            fallback_reason=snapshot.context_selection_plan.fallback_reason,
            compaction_backend_failure_kind=(
                snapshot.context_selection_plan.compaction_backend_failure_kind
            ),
            selected_retained_entry_ids=list(snapshot.selected_retained_entry_ids),
            omitted_retained_entry_ids=list(snapshot.omitted_retained_entry_ids),
            summary_retained_entry_id=snapshot.summary_retained_entry_id,
            carried_forward_state_entry_id=snapshot.carried_forward_state_entry_id,
            retained_history_last_entry_id=snapshot.retained_history_last_entry_id,
            retained_entry_count_before_snapshot=(
                snapshot.retained_entry_count_before_snapshot
            ),
            retained_entry_count_after_snapshot=(
                snapshot.retained_entry_count_after_snapshot
            ),
            request_history_item_count_before_snapshot=(
                snapshot.request_history_item_count_before_snapshot
            ),
            request_history_item_count_after_snapshot=(
                snapshot.request_history_item_count_after_snapshot
            ),
            replacement_history_active=snapshot.replacement_history_active,
            replacement_history_record_id=snapshot.replacement_history_record_id,
            summary_slot_included=snapshot.synthetic_summary_message is not None,
            carried_forward_state_present=(
                snapshot.compaction_artifact is not None
                and snapshot.compaction_artifact.carried_forward_state is not None
            ),
            estimated_selected_tokens=selection.estimated_selected_tokens,
            estimated_omitted_tokens=selection.estimated_omitted_tokens,
            tool_token_reserve=selection.tool_token_reserve,
            response_token_reserve=selection.response_token_reserve,
            token_budget_satisfied=selection.token_budget_satisfied,
            token_overflow=selection.token_overflow,
            ts_unix_ms=_unix_time_ms(),
        )
        with open(self._entry_log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False))
            handle.write("\n")
        self._manifest.total_entries += 1
        self._manifest.last_entry_id = entry.entry_id
        return entry

    def finalize(self) -> None:
        self._manifest.ended_at_unix_ms = _unix_time_ms()
        self._write_manifest()

    def _write_manifest(self) -> None:
        self._manifest_path.write_text(
            json.dumps(
                self._manifest.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
