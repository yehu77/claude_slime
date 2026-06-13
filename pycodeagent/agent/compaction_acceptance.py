"""Verification helpers for P3-B model-backed compaction acceptance runs."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from pycodeagent.agent.history_lineage import write_history_lineage_report


class P3BCompactionAcceptanceReport(BaseModel):
    """Structured verification result for one P3-B acceptance run directory."""

    run_dir: str
    ok: bool
    provider: dict = Field(default_factory=dict)
    require_real_provider: bool = True
    requested_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    applied_count: int = 0
    successful_model_backed_apply_count: int = 0
    replacement_history_active: bool = False
    history_lineage_ok: bool = False
    errors: list[str] = Field(default_factory=list)


def verify_p3b_compaction_acceptance(
    run_dir: str | Path,
    *,
    require_real_provider: bool = True,
) -> P3BCompactionAcceptanceReport:
    """Verify that one runtime run satisfies the P3-B acceptance evidence shape."""

    root = Path(run_dir)
    errors: list[str] = []

    trajectory = _load_json_if_exists(root / "trajectory.json", errors, "trajectory.json")
    trace_events = _load_jsonl_if_exists(
        root / "runtime_trace.jsonl",
        errors,
        "runtime_trace.jsonl",
    )
    request_context_entries = _load_jsonl_if_exists(
        root / "request_context.jsonl",
        errors,
        "request_context.jsonl",
    )
    history_lineage = _load_or_rebuild_history_lineage_report(root, errors)

    provider = {}
    if trajectory is not None:
        provider = dict(trajectory.get("metadata", {}).get("provider", {}) or {})
        if require_real_provider:
            provider_kind = str(provider.get("provider_kind") or "")
            client_mode = str(provider.get("client_mode") or "")
            if not provider_kind:
                errors.append("missing provider metadata in trajectory.json")
            elif provider_kind == "fake" or client_mode.startswith("fake"):
                errors.append("trajectory provider metadata indicates a fake client run")

    requested = [
        event
        for event in trace_events
        if event.get("event_kind") == "context_compaction_requested"
    ]
    completed = [
        event
        for event in trace_events
        if event.get("event_kind") == "context_compaction_completed"
    ]
    failed = [
        event
        for event in trace_events
        if event.get("event_kind") == "context_compaction_failed"
    ]
    applied = [
        event
        for event in trace_events
        if event.get("event_kind") == "context_compaction_applied"
    ]

    if not requested:
        errors.append("runtime trace is missing context_compaction_requested")
    if not completed:
        errors.append("runtime trace is missing context_compaction_completed")
    if not applied:
        errors.append("runtime trace is missing context_compaction_applied")

    latest_completed = completed[-1] if completed else None
    successful_applied = [
        event
        for event in applied
        if bool((event.get("data", {}) or {}).get("model_backed_used"))
        and not bool((event.get("data", {}) or {}).get("fallback_applied"))
    ]

    if latest_completed is not None:
        completed_data = dict(latest_completed.get("data", {}) or {})
        if not completed_data.get("model_backed_used"):
            errors.append("latest context_compaction_completed does not mark model_backed_used=true")
        payload_kinds = {
            ref.get("kind")
            for ref in (latest_completed.get("payload_refs") or [])
            if isinstance(ref, dict)
        }
        for required_kind in {
            "context_compaction_response",
            "context_compaction_output",
            "context_compaction_final_artifact",
        }:
            if required_kind not in payload_kinds:
                errors.append(
                    "latest context_compaction_completed is missing payload kind "
                    f"{required_kind}"
                )
    if not successful_applied:
        errors.append(
            "runtime trace does not contain any context_compaction_applied event "
            "with model_backed_used=true and fallback_applied=false"
        )

    replacement_history_active = False
    if request_context_entries:
        replacement_history_active = any(
            bool(entry.get("replacement_history_active")) for entry in request_context_entries
        )
        if not replacement_history_active:
            errors.append("request_context.jsonl never records replacement_history_active=true")
        else:
            replacement_entries = [
                entry
                for entry in request_context_entries
                if entry.get("replacement_history_active")
            ]
            latest_replacement = replacement_entries[-1]
            if not latest_replacement.get("summary_retained_entry_id"):
                errors.append("replacement-history request-context entry is missing summary_retained_entry_id")
            if not latest_replacement.get("carried_forward_state_entry_id"):
                errors.append(
                    "replacement-history request-context entry is missing carried_forward_state_entry_id"
                )
            if not latest_replacement.get("replacement_history_record_id"):
                errors.append(
                    "replacement-history request-context entry is missing replacement_history_record_id"
                )

    history_lineage_ok = False
    if history_lineage is not None:
        history_lineage_ok = bool(history_lineage.get("ok"))
        if not history_lineage_ok:
            errors.append("history_lineage_report.json reports ok=false")
        if int(history_lineage.get("replacement_record_count") or 0) < 1:
            errors.append("history_lineage_report.json does not contain a replacement record")

    return P3BCompactionAcceptanceReport(
        run_dir=str(root),
        ok=not errors,
        provider=provider,
        require_real_provider=require_real_provider,
        requested_count=len(requested),
        completed_count=len(completed),
        failed_count=len(failed),
        applied_count=len(applied),
        successful_model_backed_apply_count=len(successful_applied),
        replacement_history_active=replacement_history_active,
        history_lineage_ok=history_lineage_ok,
        errors=errors,
    )


def _load_json_if_exists(path: Path, errors: list[str], label: str):
    if not path.exists():
        errors.append(f"missing {label}")
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl_if_exists(path: Path, errors: list[str], label: str) -> list[dict]:
    if not path.exists():
        errors.append(f"missing {label}")
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_or_rebuild_history_lineage_report(root: Path, errors: list[str]):
    retained_history_path = root / "retained_history.jsonl"
    request_context_path = root / "request_context.jsonl"
    if not retained_history_path.exists() or not request_context_path.exists():
        return _load_json_if_exists(
            root / "history_lineage_report.json",
            errors,
            "history_lineage_report.json",
        )
    try:
        report = write_history_lineage_report(root)
    except Exception as exc:
        errors.append(f"failed to rebuild history_lineage_report.json: {exc}")
        return _load_json_if_exists(
            root / "history_lineage_report.json",
            errors,
            "history_lineage_report.json",
        )
    return report.model_dump(mode="json")
