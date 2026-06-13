"""Append-only retained history artifacts for local runtime runs."""

from __future__ import annotations

import json
from pathlib import Path
from time import time
from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.trajectory.schema import Message


def _unix_time_ms() -> int:
    return int(time() * 1000)


class RetainedHistoryEntry(BaseModel):
    """One append-only retained-history record."""

    schema_version: int = 1
    entry_id: str
    run_id: str
    turn_index: int
    source_kind: str
    source_trajectory_index: int | None = None
    request_item_id: str | None = None
    role: str | None = None
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    ts_unix_ms: int


class RetainedHistoryManifest(BaseModel):
    """Manifest for one retained-history bundle."""

    schema_version: int = 1
    run_id: str
    task_id: str
    workspace_root: str
    started_at_unix_ms: int
    ended_at_unix_ms: int | None = None
    entry_log_path: str
    total_entries: int = 0
    entry_counts_by_kind: dict[str, int] = Field(default_factory=dict)
    last_entry_id: str | None = None


class RetainedHistoryLookupMetadata(BaseModel):
    """Stable lookup metadata for one retained-history log."""

    log_id: str
    entry_count: int
    last_entry_id: str | None = None


def retained_history_log_id(manifest: RetainedHistoryManifest) -> str:
    """Return a stable log identity for one retained-history artifact."""

    return f"{manifest.run_id}:{manifest.started_at_unix_ms}"


def _entry_belongs_to_manifest(
    entry: RetainedHistoryEntry,
    manifest: RetainedHistoryManifest,
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


def iter_retained_history_entries(
    path: str | Path,
) -> list[RetainedHistoryEntry]:
    """Load only the entries that belong to the current manifest-backed log."""

    manifest_path, entry_log_path = _resolve_retained_history_paths(path)
    manifest = RetainedHistoryManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    entries: list[RetainedHistoryEntry] = []
    for line in entry_log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = RetainedHistoryEntry.model_validate_json(line)
        if _entry_belongs_to_manifest(entry, manifest):
            entries.append(entry)
    return entries


def _resolve_retained_history_paths(
    path: str | Path,
) -> tuple[Path, Path]:
    resolved = Path(path)
    if resolved.is_dir():
        return (
            resolved / "retained_history_manifest.json",
            resolved / "retained_history.jsonl",
        )
    if resolved.name == "retained_history_manifest.json":
        return resolved, resolved.with_name("retained_history.jsonl")
    if resolved.name == "retained_history.jsonl":
        return resolved.with_name("retained_history_manifest.json"), resolved
    raise ValueError(f"unsupported retained history path: {resolved}")


def load_retained_history_manifest(path: str | Path) -> RetainedHistoryManifest:
    """Load the retained-history manifest from a run dir or artifact path."""

    manifest_path, _ = _resolve_retained_history_paths(path)
    return RetainedHistoryManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )


def retained_history_metadata(path: str | Path) -> RetainedHistoryLookupMetadata:
    """Return stable lookup metadata for a retained-history artifact."""

    manifest_path, entry_log_path = _resolve_retained_history_paths(path)
    manifest = RetainedHistoryManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    entry_count = 0
    last_entry_id: str | None = None
    for entry in iter_retained_history_entries(path):
        entry_count += 1
        last_entry_id = entry.entry_id
    return RetainedHistoryLookupMetadata(
        log_id=retained_history_log_id(manifest),
        entry_count=entry_count,
        last_entry_id=last_entry_id,
    )


def lookup_retained_history_entry(
    path: str | Path,
    *,
    log_id: str,
    offset: int,
) -> RetainedHistoryEntry | None:
    """Look up one retained-history entry by stable log id and offset."""

    if offset < 0:
        return None

    current_metadata = retained_history_metadata(path)
    if current_metadata.log_id != log_id:
        return None

    current_offset = 0
    for entry in iter_retained_history_entries(path):
        if current_offset == offset:
            return entry
        current_offset += 1
    return None


def lookup_retained_history_entry_by_id(
    path: str | Path,
    *,
    entry_id: str,
) -> RetainedHistoryEntry | None:
    """Look up one retained-history entry by entry id."""

    for entry in iter_retained_history_entries(path):
        if entry.entry_id == entry_id:
            return entry
    return None


class RetainedHistoryWriter:
    """Append-only writer for runtime-owned retained history."""

    def __init__(
        self,
        *,
        run_dir: Path,
        manifest_path: Path,
        entry_log_path: Path,
        manifest: RetainedHistoryManifest,
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
    ) -> "RetainedHistoryWriter":
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = run_dir / "retained_history_manifest.json"
        entry_log_path = run_dir / "retained_history.jsonl"
        manifest = RetainedHistoryManifest(
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
    def manifest(self) -> RetainedHistoryManifest:
        return self._manifest

    def append(
        self,
        *,
        turn_index: int,
        source_kind: str,
        text: str,
        source_trajectory_index: int | None = None,
        request_item_id: str | None = None,
        role: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RetainedHistoryEntry:
        ordinal = self._next_entry_ordinal
        self._next_entry_ordinal += 1
        entry = RetainedHistoryEntry(
            entry_id=f"retained_entry_{ordinal:06d}",
            run_id=self._manifest.run_id,
            turn_index=turn_index,
            source_kind=source_kind,
            source_trajectory_index=source_trajectory_index,
            request_item_id=request_item_id,
            role=role,
            text=text,
            metadata=dict(metadata or {}),
            ts_unix_ms=_unix_time_ms(),
        )
        with open(self._entry_log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False))
            handle.write("\n")
        self._manifest.total_entries += 1
        self._manifest.last_entry_id = entry.entry_id
        self._manifest.entry_counts_by_kind[source_kind] = (
            self._manifest.entry_counts_by_kind.get(source_kind, 0) + 1
        )
        return entry

    def append_source_message(
        self,
        *,
        turn_index: int,
        request_item_id: str,
        source_trajectory_index: int,
        message: Message,
    ) -> RetainedHistoryEntry:
        return self.append(
            turn_index=turn_index,
            source_kind="source_message",
            source_trajectory_index=source_trajectory_index,
            request_item_id=request_item_id,
            role=message.role.value,
            text=message.content,
            metadata={
                "tool_call_id": message.tool_call_id,
                "tool_name": message.tool_name,
                "canonical_name": message.canonical_name,
                "tool_version": message.tool_version,
                "tool_call_count": len(message.tool_calls),
                "message_metadata": dict(message.metadata),
                "message_payload": message.model_dump(mode="json"),
            },
        )

    def append_replacement_summary(
        self,
        *,
        turn_index: int,
        request_item_id: str,
        message: Message,
        replacement_record_id: str,
        source_item_ids: list[str],
        source_retained_entry_ids: list[str],
        source_trajectory_indices: list[int],
        summary_slot_id: str | None,
    ) -> RetainedHistoryEntry:
        return self.append(
            turn_index=turn_index,
            source_kind="replacement_summary",
            request_item_id=request_item_id,
            role=message.role.value,
            text=message.content,
            metadata={
                "replacement_record_id": replacement_record_id,
                "source_item_ids": list(source_item_ids),
                "source_retained_entry_ids": list(source_retained_entry_ids),
                "source_trajectory_indices": list(source_trajectory_indices),
                "summary_slot_id": summary_slot_id,
                "message_payload": message.model_dump(mode="json"),
            },
        )

    def append_carried_forward_state(
        self,
        *,
        turn_index: int,
        replacement_record_id: str,
        value: dict[str, Any],
    ) -> RetainedHistoryEntry:
        return self.append(
            turn_index=turn_index,
            source_kind="carry_forward_state",
            text=json.dumps(value, ensure_ascii=False, sort_keys=True),
            metadata={
                "replacement_record_id": replacement_record_id,
                "state": value,
            },
        )

    def append_history_control(
        self,
        *,
        turn_index: int,
        control_kind: str,
        value: dict[str, Any],
    ) -> RetainedHistoryEntry:
        return self.append(
            turn_index=turn_index,
            source_kind="history_control",
            text=json.dumps(value, ensure_ascii=False, sort_keys=True),
            metadata={
                "control_kind": control_kind,
                "control_payload": value,
            },
        )

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
