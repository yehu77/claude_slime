"""Canonical trace contracts and persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.trajectory.schema import RunStatus, VerifyResult

SCHEMA_VERSION = 1


class CanonicalAction(BaseModel):
    """One normalized capability step."""

    action_id: str
    capability: str
    canonical_args: dict[str, Any]
    raw_event_refs: list[str] = Field(default_factory=list)
    raw_tool_name: str | None = None
    mapping_confidence: float = 1.0
    normalization_notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalTrace(BaseModel):
    """Normalized run trace anchored to raw evidence."""

    schema_version: int = SCHEMA_VERSION
    trace_id: str
    task_id: str
    agent_name: str
    agent_version: str
    actions: list[CanonicalAction] = Field(default_factory=list)
    final_diff: str = ""
    verifier_result: VerifyResult | None = None
    status: RunStatus = RunStatus.COMPLETED
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizationReport(BaseModel):
    """Inspectable normalization diagnostics."""

    schema_version: int = SCHEMA_VERSION
    trace_id: str
    catalog_id: str | None = None
    mapped_events: list[str] = Field(default_factory=list)
    unmapped_events: list[str] = Field(default_factory=list)
    ambiguous_events: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class NormalizationResult(BaseModel):
    """Trace normalization output bundle."""

    canonical_trace: CanonicalTrace
    report: NormalizationReport


def write_canonical_trace(trace: CanonicalTrace, path: str | Path) -> Path:
    """Write a canonical trace artifact."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(trace.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return target


def read_canonical_trace(path: str | Path) -> CanonicalTrace:
    """Load a canonical trace artifact."""
    source = Path(path)
    with open(source, encoding="utf-8") as handle:
        data = json.load(handle)
    return CanonicalTrace.model_validate(data)


def write_normalization_report(report: NormalizationReport, path: str | Path) -> Path:
    """Write a normalization report artifact."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return target


def read_normalization_report(path: str | Path) -> NormalizationReport:
    """Load a normalization report artifact."""
    source = Path(path)
    with open(source, encoding="utf-8") as handle:
        data = json.load(handle)
    return NormalizationReport.model_validate(data)
