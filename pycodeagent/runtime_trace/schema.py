"""Contracts for the local-runtime-specific append-only trace bundle."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

MANIFEST_SCHEMA_VERSION = 2
EVENT_SCHEMA_VERSION = 1

RuntimeTraceEventKind = Literal[
    "run_started",
    "tool_profile_exposed",
    "turn_started",
    "context_selection_planned",
    "context_compaction_requested",
    "context_compaction_completed",
    "context_compaction_failed",
    "context_compaction_applied",
    "context_compaction_skipped",
    "model_request_built",
    "model_response_received",
    "provider_response_interpreted",
    "assistant_parse_completed",
    "tool_call_validation_completed",
    "tool_call_mapping_completed",
    "tool_execution_started",
    "tool_execution_completed",
    "tool_execution_failed",
    "tool_result_appended",
    "turn_stop_decision",
    "run_completed",
]


class RuntimeRetentionMetadata(BaseModel):
    """Retention fields embedded in a runtime trace manifest."""

    policy_id: str
    purpose_class: str
    sensitivity: Literal["internal", "restricted"]
    risk_labels: list[str]
    owner: str
    retention: dict[str, str | None]
    disposition: str
    checksum_algorithm: Literal["sha256-tree-manifest-v1"]
    source_checksum: str
    manifest_path: str
    index_path: str
    lifecycle_log_path: str


class RuntimeTraceManifest(BaseModel):
    """Manifest for one local runtime trace bundle."""

    schema_version: int = MANIFEST_SCHEMA_VERSION
    trace_id: str
    run_id: str
    task_id: str
    tool_profile_id: str
    workspace_root: str
    started_at_unix_ms: int
    ended_at_unix_ms: int | None = None
    payload_dir: str
    event_log_path: str
    retention: RuntimeRetentionMetadata


class RuntimePayloadRef(BaseModel):
    """Reference to a JSON payload externalized from the hot-path event log."""

    payload_id: str
    kind: str
    path: str


class RuntimeTraceEvent(BaseModel):
    """One append-only runtime event."""

    schema_version: int = EVENT_SCHEMA_VERSION
    seq: int
    event_id: str
    event_kind: RuntimeTraceEventKind
    wall_time_unix_ms: int
    run_id: str
    task_id: str
    turn_index: int | None = None
    tool_call_id: str | None = None
    payload_refs: list[RuntimePayloadRef] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
