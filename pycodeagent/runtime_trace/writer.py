"""Append-only writer for local runtime trace bundles."""

from __future__ import annotations

import json
from pathlib import Path
from time import time
from typing import Any

from .schema import RuntimePayloadRef, RuntimeTraceEvent, RuntimeTraceEventKind, RuntimeTraceManifest


def _unix_time_ms() -> int:
    return int(time() * 1000)


class RuntimeTraceWriter:
    """Write a manifest, payload files, and an append-only event log."""

    def __init__(
        self,
        *,
        run_dir: Path,
        manifest_path: Path,
        event_log_path: Path,
        payload_dir: Path,
        manifest: RuntimeTraceManifest,
    ) -> None:
        self._run_dir = run_dir
        self._manifest_path = manifest_path
        self._event_log_path = event_log_path
        self._payload_dir = payload_dir
        self._manifest = manifest
        self._next_seq = 1
        self._next_payload_ordinal = 1

    @classmethod
    def create(
        cls,
        run_dir: str | Path,
        *,
        run_id: str,
        task_id: str,
        tool_profile_id: str,
        workspace_root: str,
    ) -> "RuntimeTraceWriter":
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        payload_dir = run_dir / "payloads"
        payload_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = run_dir / "runtime_trace_manifest.json"
        event_log_path = run_dir / "runtime_trace.jsonl"
        trace_id = f"{run_id}__runtime_trace"
        manifest = RuntimeTraceManifest(
            trace_id=trace_id,
            run_id=run_id,
            task_id=task_id,
            tool_profile_id=tool_profile_id,
            workspace_root=workspace_root,
            started_at_unix_ms=_unix_time_ms(),
            payload_dir=payload_dir.name,
            event_log_path=event_log_path.name,
        )
        writer = cls(
            run_dir=run_dir,
            manifest_path=manifest_path,
            event_log_path=event_log_path,
            payload_dir=payload_dir,
            manifest=manifest,
        )
        writer._write_manifest()
        if not event_log_path.exists():
            event_log_path.write_text("", encoding="utf-8")
        return writer

    @property
    def manifest(self) -> RuntimeTraceManifest:
        return self._manifest

    def write_json_payload(self, kind: str, value: Any) -> RuntimePayloadRef:
        ordinal = self._next_payload_ordinal
        self._next_payload_ordinal += 1
        payload_id = f"runtime_payload_{ordinal:06d}"
        relative_path = f"{self._payload_dir.name}/{ordinal:06d}.json"
        absolute_path = self._run_dir / relative_path
        absolute_path.write_text(
            json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return RuntimePayloadRef(
            payload_id=payload_id,
            kind=kind,
            path=relative_path,
        )

    def append(
        self,
        event_kind: RuntimeTraceEventKind,
        *,
        turn_index: int | None = None,
        tool_call_id: str | None = None,
        data: dict[str, Any],
        payload_refs: list[RuntimePayloadRef] | None = None,
    ) -> RuntimeTraceEvent:
        seq = self._next_seq
        self._next_seq += 1
        event = RuntimeTraceEvent(
            seq=seq,
            event_id=f"runtime_event_{seq:06d}",
            event_kind=event_kind,
            wall_time_unix_ms=_unix_time_ms(),
            run_id=self._manifest.run_id,
            task_id=self._manifest.task_id,
            turn_index=turn_index,
            tool_call_id=tool_call_id,
            payload_refs=list(payload_refs or []),
            data=data,
        )
        with open(self._event_log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False))
            handle.write("\n")
        return event

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
