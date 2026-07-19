"""Retention lifecycle enforcement for newly written run bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


RUN_RETENTION_MANIFEST_SCHEMA = "pycodeagent-run-retention-manifest/v1"
RUN_RETENTION_EVENT_SCHEMA = "pycodeagent-run-retention-event/v1"
RUN_CLEANUP_PLAN_SCHEMA = "pycodeagent-run-cleanup-plan/v1"
RUNS_INVENTORY_SCHEMA = "pycodeagent-runs-inventory/v1"
RETAINED_RUN_INDEX_RECORD_SCHEMA = "pycodeagent-retained-run-index-record/v1"

RETENTION_MANIFEST_NAME = "run_retention_manifest.json"
RETENTION_INDEX_NAME = "retained-run.index.jsonl"
RETENTION_EVENT_LOG_NAME = "run_retention_events.jsonl"
DEFAULT_RETENTION_CLASS = "unclassified_hold"
DEFAULT_RETENTION_OWNER = "repository-governance"
DEFAULT_RUNTIME_RISK_LABELS = (
    "raw_provider_content",
    "raw_trace_content",
)

_GOVERNANCE_FILES = {
    RETENTION_MANIFEST_NAME,
    RETENTION_INDEX_NAME,
    RETENTION_EVENT_LOG_NAME,
    "runtime_trace_manifest.json",
}


class RunRetentionError(ValueError):
    """Raised when a new run violates the retention contract."""


def default_policy_path() -> Path:
    return Path(__file__).resolve().parents[2] / "references/runs-retention-policy.json"


def _load_policy(path: str | Path) -> Any:
    from pycodeagent.dev.runs_retention import (
        RunsRetentionError,
        load_retention_policy,
    )

    try:
        return load_retention_policy(path)
    except RunsRetentionError as exc:
        raise RunRetentionError(str(exc)) from exc


def _validate_index(path: Path, *, policy: Any) -> Any:
    from pycodeagent.dev.runs_retention import (
        RunsRetentionError,
        load_and_validate_index,
    )

    try:
        return load_and_validate_index(path, policy=policy)
    except RunsRetentionError as exc:
        raise RunRetentionError(str(exc)) from exc


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    ) + "\n"


def compute_run_artifact_checksum(run_dir: str | Path) -> str:
    """Hash paths and bytes for run artifacts, excluding self-referential metadata."""
    root = Path(run_dir)
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in _GOVERNANCE_FILES:
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with open(path, "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _retention_window(
    policy: Any,
    purpose_class: str,
    starts_at: datetime,
) -> dict[str, str | None]:
    retention_class = policy.retention_classes[purpose_class]
    expires_at = (
        None
        if retention_class.minimum_retention_days is None
        else starts_at + timedelta(days=retention_class.minimum_retention_days)
    )
    quarantine_until = (
        None
        if expires_at is None or retention_class.quarantine_days is None
        else expires_at + timedelta(days=retention_class.quarantine_days)
    )
    return {
        "starts_at": _timestamp(starts_at),
        "expires_at": None if expires_at is None else _timestamp(expires_at),
        "quarantine_until": (
            None if quarantine_until is None else _timestamp(quarantine_until)
        ),
    }


def _initial_disposition(purpose_class: str) -> str:
    if purpose_class in {"contract_golden", "unique_research_evidence"}:
        return "retain_active"
    if purpose_class == "unclassified_hold":
        return "manual_review_hold"
    return "retain_local"


class RunRetentionTracker:
    """Maintain a fail-closed run manifest, index entry, and lifecycle journal."""

    def __init__(
        self,
        *,
        run_dir: Path,
        policy: Any,
        manifest: dict[str, Any],
        clock: Callable[[], datetime],
    ) -> None:
        self.run_dir = run_dir
        self.policy = policy
        self.manifest = manifest
        self._clock = clock
        self.manifest_path = run_dir / RETENTION_MANIFEST_NAME
        self.index_path = run_dir / RETENTION_INDEX_NAME
        self.event_log_path = run_dir / RETENTION_EVENT_LOG_NAME

    @classmethod
    def create_or_resume(
        cls,
        run_dir: str | Path,
        *,
        run_id: str,
        task_id: str,
        purpose_class: str = DEFAULT_RETENTION_CLASS,
        owner: str = DEFAULT_RETENTION_OWNER,
        risk_labels: Sequence[str] = DEFAULT_RUNTIME_RISK_LABELS,
        policy_path: str | Path | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> "RunRetentionTracker":
        policy = _load_policy(policy_path or default_policy_path())
        if purpose_class not in policy.retention_classes:
            raise RunRetentionError(
                f"Unknown run retention class: {purpose_class}"
            )
        if not run_id or not task_id or not owner:
            raise RunRetentionError("run_id, task_id, and retention owner are required")
        if (
            Path(run_id).name != run_id
            or ".." in Path(run_id).parts
            or any(char in run_id for char in "*?[]")
        ):
            raise RunRetentionError("run_id must be one safe path component")
        normalized_risks = sorted(set(risk_labels))
        if any(not isinstance(label, str) or not label for label in normalized_risks):
            raise RunRetentionError("Retention risk labels must be non-empty strings")

        root = Path(run_dir)
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root / RETENTION_MANIFEST_NAME
        if manifest_path.exists():
            manifest = cls._load_manifest(manifest_path)
            tracker = cls(
                run_dir=root,
                policy=policy,
                manifest=manifest,
                clock=clock,
            )
            tracker._validate_resume_identity(
                run_id=run_id,
                task_id=task_id,
                purpose_class=purpose_class,
                owner=owner,
                risk_labels=normalized_risks,
            )
            if manifest["lifecycle"]["state"] == "finalized":
                raise RunRetentionError("A finalized run cannot be resumed")
            manifest["lifecycle"]["resume_count"] += 1
            tracker._update("resumed")
            return tracker

        now = clock()
        retention = _retention_window(policy, purpose_class, now)
        checksum = compute_run_artifact_checksum(root)
        manifest = {
            "schema": RUN_RETENTION_MANIFEST_SCHEMA,
            "policy_id": policy.policy_id,
            "run_id": run_id,
            "task_id": task_id,
            "purpose_class": purpose_class,
            "sensitivity": "restricted" if normalized_risks else "internal",
            "risk_labels": normalized_risks,
            "owner": owner,
            "retention": retention,
            "disposition": _initial_disposition(purpose_class),
            "storage": {
                "kind": "current_local",
                "location_ref": None,
            },
            "checksums": {
                "algorithm": "sha256-tree-manifest-v1",
                "source": checksum,
                "archive": None,
            },
            "scrub": {
                "status": "pending" if normalized_risks else "not_required",
                "report_ref": None,
                "source_preserved": True,
            },
            "restore": {
                "status": "not_applicable",
                "verified_at": None,
            },
            "credential_review": {
                "status": (
                    "pending"
                    if policy.credential_review_trigger in normalized_risks
                    else "not_required"
                ),
                "reviewed_at": None,
            },
            "deletion_authorization_id": None,
            "lifecycle": {
                "state": "active",
                "created_at": _timestamp(now),
                "updated_at": _timestamp(now),
                "resume_count": 0,
            },
            "index_path": RETENTION_INDEX_NAME,
            "lifecycle_log_path": RETENTION_EVENT_LOG_NAME,
        }
        tracker = cls(
            run_dir=root,
            policy=policy,
            manifest=manifest,
            clock=clock,
        )
        tracker._persist()
        tracker._append_event("created")
        return tracker

    @staticmethod
    def _load_manifest(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunRetentionError(f"Invalid run retention manifest: {path}") from exc
        if not isinstance(payload, dict) or payload.get("schema") != (
            RUN_RETENTION_MANIFEST_SCHEMA
        ):
            raise RunRetentionError("Unsupported run retention manifest schema")
        return payload

    def _validate_resume_identity(
        self,
        *,
        run_id: str,
        task_id: str,
        purpose_class: str,
        owner: str,
        risk_labels: list[str],
    ) -> None:
        expected = {
            "policy_id": self.policy.policy_id,
            "run_id": run_id,
            "task_id": task_id,
            "purpose_class": purpose_class,
            "owner": owner,
            "risk_labels": risk_labels,
        }
        for field, value in expected.items():
            if self.manifest.get(field) != value:
                raise RunRetentionError(
                    f"Run retention resume mismatch for {field}"
                )
        retention = self.manifest.get("retention")
        if not isinstance(retention, dict) or not retention.get("starts_at"):
            raise RunRetentionError("Run retention window is missing")

    def refresh(self) -> None:
        self._update("artifacts_refreshed")

    def finalize(self) -> None:
        if self.manifest["lifecycle"]["state"] == "finalized":
            return
        self.manifest["lifecycle"]["state"] = "finalized"
        self._update("finalized")

    def summary(self) -> dict[str, Any]:
        return {
            "policy_id": self.manifest["policy_id"],
            "purpose_class": self.manifest["purpose_class"],
            "sensitivity": self.manifest["sensitivity"],
            "risk_labels": list(self.manifest["risk_labels"]),
            "owner": self.manifest["owner"],
            "retention": dict(self.manifest["retention"]),
            "disposition": self.manifest["disposition"],
            "checksum_algorithm": self.manifest["checksums"]["algorithm"],
            "source_checksum": self.manifest["checksums"]["source"],
            "manifest_path": RETENTION_MANIFEST_NAME,
            "index_path": RETENTION_INDEX_NAME,
            "lifecycle_log_path": RETENTION_EVENT_LOG_NAME,
        }

    def _update(self, event_kind: str) -> None:
        self.manifest["checksums"]["source"] = compute_run_artifact_checksum(
            self.run_dir
        )
        self.manifest["lifecycle"]["updated_at"] = _timestamp(self._clock())
        self._persist()
        self._append_event(event_kind)

    def _persist(self) -> None:
        index_records = self._index_records()
        index_text = "".join(
            json.dumps(
                record,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
            for record in index_records
        )
        _atomic_write_text(self.index_path, index_text)
        _atomic_write_text(self.manifest_path, _json_text(self.manifest))
        try:
            _validate_index(self.index_path, policy=self.policy)
        except RunRetentionError as exc:
            raise RunRetentionError(
                f"Run retained index failed policy validation: {exc}"
            ) from exc

    def _index_records(self) -> list[dict[str, Any]]:
        checksum = self.manifest["checksums"]["source"]
        header = {
            "schema": RETAINED_RUN_INDEX_RECORD_SCHEMA,
            "record_type": "index",
            "index_id": f"run-{self.manifest['run_id']}",
            "policy_id": self.policy.policy_id,
            "inventory_schema": RUNS_INVENTORY_SCHEMA,
            "inventory_state_fingerprint": checksum,
            "example": False,
        }
        entry = {
            "schema": RETAINED_RUN_INDEX_RECORD_SCHEMA,
            "record_type": "entry",
            "target": {
                "kind": "artifact_group",
                "path": f"runs/live/{self.manifest['run_id']}",
            },
            "purpose_class": self.manifest["purpose_class"],
            "sensitivity": self.manifest["sensitivity"],
            "risk_labels": self.manifest["risk_labels"],
            "owner": self.manifest["owner"],
            "retention": self.manifest["retention"],
            "disposition": self.manifest["disposition"],
            "storage": self.manifest["storage"],
            "checksums": self.manifest["checksums"],
            "scrub": self.manifest["scrub"],
            "restore": self.manifest["restore"],
            "credential_review": self.manifest["credential_review"],
            "deletion_authorization_id": self.manifest[
                "deletion_authorization_id"
            ],
        }
        return [header, entry]

    def _append_event(self, event_kind: str) -> None:
        event = {
            "schema": RUN_RETENTION_EVENT_SCHEMA,
            "event_kind": event_kind,
            "run_id": self.manifest["run_id"],
            "at": self.manifest["lifecycle"]["updated_at"],
            "state": self.manifest["lifecycle"]["state"],
            "source_checksum": self.manifest["checksums"]["source"],
        }
        with open(self.event_log_path, "a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())


def verify_run_retention(
    run_dir: str | Path,
    *,
    policy_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(run_dir)
    policy = _load_policy(policy_path or default_policy_path())
    manifest = RunRetentionTracker._load_manifest(
        root / RETENTION_MANIFEST_NAME
    )
    index = _validate_index(root / RETENTION_INDEX_NAME, policy=policy)
    if manifest.get("policy_id") != policy.policy_id:
        raise RunRetentionError("Run manifest policy_id mismatch")
    if len(index.entries) != 1 or index.deletion_authorizations:
        raise RunRetentionError("A live run index must contain one retained entry")
    entry = index.entries[0]
    comparisons = {
        "purpose_class": manifest.get("purpose_class"),
        "sensitivity": manifest.get("sensitivity"),
        "risk_labels": manifest.get("risk_labels"),
        "owner": manifest.get("owner"),
        "retention": manifest.get("retention"),
        "disposition": manifest.get("disposition"),
        "checksums": manifest.get("checksums"),
        "deletion_authorization_id": manifest.get("deletion_authorization_id"),
    }
    for field, expected in comparisons.items():
        if entry.get(field) != expected:
            raise RunRetentionError(f"Run manifest/index mismatch for {field}")
    current_checksum = compute_run_artifact_checksum(root)
    recorded_checksum = manifest["checksums"]["source"]
    state = manifest["lifecycle"]["state"]
    if state == "finalized" and current_checksum != recorded_checksum:
        raise RunRetentionError("Finalized run artifact checksum drift")
    return {
        "run_id": manifest["run_id"],
        "purpose_class": manifest["purpose_class"],
        "sensitivity": manifest["sensitivity"],
        "lifecycle_state": state,
        "indexed": True,
        "checksum_status": (
            "verified" if current_checksum == recorded_checksum else "pending_refresh"
        ),
        "deletion_authorized": False,
    }


def build_cleanup_plan(
    run_dirs: Sequence[str | Path],
    *,
    as_of: datetime | None = None,
    policy_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a non-mutating cleanup plan; this function never deletes artifacts."""
    now = as_of or utc_now()
    items: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        root = Path(run_dir)
        verification = verify_run_retention(root, policy_path=policy_path)
        manifest = RunRetentionTracker._load_manifest(
            root / RETENTION_MANIFEST_NAME
        )
        retention = manifest["retention"]
        expires_at = retention["expires_at"]
        quarantine_until = retention["quarantine_until"]
        reasons: list[str] = []
        if verification["lifecycle_state"] != "finalized":
            reasons.append("run_not_finalized")
        if expires_at is None or _parse_timestamp(expires_at) > now:
            reasons.append("retention_not_elapsed")
        if quarantine_until is None or _parse_timestamp(quarantine_until) > now:
            reasons.append("quarantine_not_elapsed")
        if manifest["checksums"]["archive"] is None:
            reasons.append("archive_checksum_missing")
        if manifest["restore"]["status"] != "verified":
            reasons.append("restore_not_verified")
        if manifest["scrub"]["status"] not in {"verified", "not_required"}:
            reasons.append("scrub_or_sensitivity_review_incomplete")
        if manifest["credential_review"]["status"] == "pending":
            reasons.append("credential_review_incomplete")
        if manifest["deletion_authorization_id"] is None:
            reasons.append("exact_batch_authorization_missing")
        items.append(
            {
                "run_id": verification["run_id"],
                "path": str(root),
                "action": "retain_and_report",
                "reasons": reasons or ["deletion_execution_not_available"],
            }
        )
    return {
        "schema": RUN_CLEANUP_PLAN_SCHEMA,
        "mode": "dry_run",
        "as_of": _timestamp(now),
        "run_count": len(items),
        "delete_count": 0,
        "items": items,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify new-run retention metadata or produce a dry-run cleanup plan."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("run_dir")
    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.add_argument("run_dirs", nargs="+")
    cleanup_parser.add_argument(
        "--execute",
        action="store_true",
        help="Rejected: deletion requires a separate owner-reviewed batch tool.",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            print(json.dumps(verify_run_retention(args.run_dir), sort_keys=True))
            return 0
        if args.execute:
            raise RunRetentionError(
                "Destructive cleanup is unavailable: validate an exact RC-053 "
                "deletion authorization in a separate owner-reviewed batch."
            )
        print(
            json.dumps(
                build_cleanup_plan(args.run_dirs),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except RunRetentionError as exc:
        print(f"run retention error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
