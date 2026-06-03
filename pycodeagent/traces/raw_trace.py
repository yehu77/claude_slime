"""Raw trace contracts and JSONL persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from pycodeagent.trajectory.schema import RunStatus, VerifyResult

SCHEMA_VERSION = 1
RawEventVisibility = Literal["model", "harness", "internal"]
RawEventEvidenceLevel = Literal["observed", "synthetic", "derived"]
RawCommandRole = Literal[
    "agent_command",
    "harness_verifier",
    "setup",
    "cleanup",
    "unknown",
]


class ArtifactRef(BaseModel):
    """Reference from one raw event to a concrete artifact path."""

    artifact_kind: str
    path: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawEvent(BaseModel):
    """One raw event row in ``raw_trace.jsonl``."""

    event_id: str
    seq: int
    event_kind: str
    source: str
    visibility: RawEventVisibility
    evidence_level: RawEventEvidenceLevel
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    parsed_payload: dict[str, Any] = Field(default_factory=dict)
    parent_event_id: str | None = None
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_command_role(self) -> RawEvent:
        if self.event_kind != "command_exec":
            return self
        command_role = self.parsed_payload.get("command_role")
        if command_role is None:
            raise ValueError("command_exec event requires parsed_payload.command_role")
        if command_role not in {
            "agent_command",
            "harness_verifier",
            "setup",
            "cleanup",
            "unknown",
        }:
            raise ValueError(f"Invalid command_role: {command_role}")
        return self


class RawTraceSummary(BaseModel):
    """Header artifact stored in ``raw_trace_summary.json``."""

    schema_version: int = SCHEMA_VERSION
    trace_id: str
    agent_name: str
    agent_version: str
    task_id: str
    workspace_dir: str
    tool_catalog_id: str | None = None
    status: RunStatus = RunStatus.COMPLETED
    final_diff: str = ""
    verifier_result: VerifyResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawAgentRunResult(BaseModel):
    """Run-level artifact index returned by an agent adapter."""

    schema_version: int = SCHEMA_VERSION
    run_id: str
    task_id: str
    agent_id: str
    agent_version: str
    status: RunStatus = RunStatus.COMPLETED
    tool_catalog_path: str | None = None
    raw_trace_path: str | None = None
    raw_trace_summary_path: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    final_diff_path: str | None = None
    verifier_result_path: str | None = None
    workspace_before_hash: str
    workspace_after_hash: str
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawAgentTrace(BaseModel):
    """In-memory view of one raw trace composed from summary and events."""

    summary: RawTraceSummary
    events: list[RawEvent] = Field(default_factory=list)

    @property
    def trace_id(self) -> str:
        return self.summary.trace_id

    @property
    def agent_name(self) -> str:
        return self.summary.agent_name

    @property
    def agent_version(self) -> str:
        return self.summary.agent_version

    @property
    def task_id(self) -> str:
        return self.summary.task_id

    @property
    def workspace_dir(self) -> str:
        return self.summary.workspace_dir

    @property
    def tool_catalog_id(self) -> str | None:
        return self.summary.tool_catalog_id

    @property
    def final_diff(self) -> str:
        return self.summary.final_diff

    @property
    def verifier_result(self) -> VerifyResult | None:
        return self.summary.verifier_result

    @property
    def status(self) -> RunStatus:
        return self.summary.status

    @property
    def metadata(self) -> dict[str, Any]:
        return self.summary.metadata


def write_raw_trace_summary(summary: RawTraceSummary, path: str | Path) -> Path:
    """Write raw trace header JSON."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return target


def write_raw_events(events: list[RawEvent], path: str | Path) -> Path:
    """Write raw events as one JSON object per line."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        for event in sorted(events, key=lambda item: item.seq):
            handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False))
            handle.write("\n")
    return target


def write_raw_trace(trace: RawAgentTrace, events_path: str | Path, summary_path: str | Path) -> None:
    """Write a full raw trace as JSONL + summary JSON."""
    write_raw_events(trace.events, events_path)
    write_raw_trace_summary(trace.summary, summary_path)


def read_raw_trace_summary(path: str | Path) -> RawTraceSummary:
    """Load raw trace summary JSON."""
    source = Path(path)
    with open(source, encoding="utf-8") as handle:
        data = json.load(handle)
    return RawTraceSummary.model_validate(data)


def read_raw_events(path: str | Path) -> list[RawEvent]:
    """Load raw events from JSONL."""
    source = Path(path)
    events: list[RawEvent] = []
    with open(source, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            payload = line.strip()
            if not payload:
                continue
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid raw event JSON on line {line_number}: {exc}") from exc
            try:
                events.append(RawEvent.model_validate(data))
            except Exception as exc:
                raise ValueError(
                    f"Invalid raw event payload on line {line_number}: {exc}"
                ) from exc
    return events


def read_raw_trace(events_path: str | Path, summary_path: str | Path) -> RawAgentTrace:
    """Load a raw trace from JSONL + summary JSON."""
    return RawAgentTrace(
        summary=read_raw_trace_summary(summary_path),
        events=read_raw_events(events_path),
    )
