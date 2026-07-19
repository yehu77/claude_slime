"""Create and verify a non-destructive, locally scrubbed runs archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, MutableMapping, Sequence

from pycodeagent.dev.runs_inventory import (
    DEFAULT_INVENTORY_PATH,
    DEFAULT_SUMMARY_PATH,
    RunsInventory,
    scan_runs,
    verify_inventory_against_runs,
)
from pycodeagent.dev.runs_retention import (
    DEFAULT_INDEX_SCHEMA_PATH,
    DEFAULT_POLICY_PATH,
    RETAINED_RUN_INDEX_RECORD_SCHEMA,
    RunsRetentionError,
    RunsRetentionPolicy,
    load_and_validate_index,
    load_retention_policy,
    validate_index_schema_asset,
)


RUNS_ARCHIVE_CLASSIFICATION_SCHEMA = (
    "pycodeagent-runs-archive-classification/v1"
)
RUNS_ARCHIVE_MANIFEST_SCHEMA = "pycodeagent-runs-archive-manifest/v1"
RUNS_SCRUB_REPORT_SCHEMA = "pycodeagent-runs-scrub-report/v1"
EXTERNAL_ARCHIVE_MANIFEST_SCHEMA = "pycodeagent-local-runs-archive/v1"

DEFAULT_CLASSIFICATION_PATH = Path(
    "references/runs-archive-classification.json"
)
DEFAULT_RETAINED_INDEX_PATH = Path("references/retained-runs.index.jsonl")
DEFAULT_ARCHIVE_REPORT_PATH = Path("references/runs-archive-manifest.json")
DEFAULT_SCRUB_REPORT_PATH = Path("references/runs-archive-scrub-report.json")

_SENSITIVE_KEY_RE = re.compile(
    r"(?i)^(authorization|api[_-]?key|access[_-]?token|"
    r"secret[_-]?key|private[_-]?key)$"
)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.DOTALL,
)
_EMAIL_RE = re.compile(
    r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
)
_HOME_PATH_RE = re.compile(r"(?:/home/|/Users/)[A-Za-z0-9._-]+")
_BEARER_RE = re.compile(
    r"(?i)\bBearer[ \t]+(?!<redacted>)[A-Za-z0-9._~+/\-=]+"
)
_TEXT_SECRET_RE = re.compile(
    r"(?i)\b(authorization|api[_-]?key|access[_-]?token|"
    r"secret[_-]?key)[ \t]*[:=][ \t]*(?!<redacted>)[^\s,;]+"
)
_COMPILED_CACHE_PLACEHOLDER = (
    b'{"reason":"compiled_cache_omitted","redacted":true}\n'
)


class RunsArchiveError(ValueError):
    """Raised when classification, scrubbing, archive, or restore fails."""


@dataclass(frozen=True)
class CampaignClassification:
    campaign: str
    purpose_class: str
    owner: str
    provider_payload_override: bool


@dataclass(frozen=True)
class RunsArchiveClassification:
    classification_id: str
    policy_id: str
    inventory_state_fingerprint: str
    archive_id: str
    storage_location_ref: str
    delete_authorized_count: int
    campaigns: Mapping[str, CampaignClassification]


@dataclass(frozen=True)
class ArchiveResult:
    archive_id: str
    destination: Path
    artifact_count: int
    artifact_group_count: int
    changed_file_count: int
    archive_payload_sha256: str
    retained_index_path: Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_archive_classification(
    path: str | Path,
    *,
    policy: RunsRetentionPolicy,
    inventory: RunsInventory,
) -> RunsArchiveClassification:
    classification_path = Path(path)
    try:
        payload = json.loads(classification_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunsArchiveError(
            f"Runs archive classification is missing: {classification_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RunsArchiveError(
            f"Runs archive classification is invalid JSON: {classification_path}"
        ) from exc
    if not isinstance(payload, dict):
        raise RunsArchiveError("Runs archive classification must be an object")
    if payload.get("schema") != RUNS_ARCHIVE_CLASSIFICATION_SCHEMA:
        raise RunsArchiveError("Unsupported archive classification schema")
    if payload.get("policy_id") != policy.policy_id:
        raise RunsArchiveError("Archive classification policy_id drift")
    if payload.get("inventory_state_fingerprint") != inventory.summary.get(
        "state_fingerprint"
    ):
        raise RunsArchiveError("Archive classification inventory drift")
    if payload.get("delete_authorized_count") != 0:
        raise RunsArchiveError("RC-054 has no authorized deletion batch")
    archive_id = _required_label(payload, "archive_id")
    location_ref = _required_label(payload, "storage_location_ref")
    if (
        not location_ref.startswith("local-archive:")
        or "://" in location_ref
        or "/" in location_ref
    ):
        raise RunsArchiveError(
            "storage_location_ref must be one redacted local archive label"
        )

    campaigns_payload = payload.get("campaigns")
    if not isinstance(campaigns_payload, list) or not campaigns_payload:
        raise RunsArchiveError("Archive campaigns must be a non-empty list")
    campaigns: dict[str, CampaignClassification] = {}
    for item in campaigns_payload:
        if not isinstance(item, dict) or set(item) != {
            "campaign",
            "purpose_class",
            "owner",
            "provider_payload_override",
        }:
            raise RunsArchiveError("Archive campaign fields drift")
        campaign = _required_label(item, "campaign")
        purpose_class = _required_label(item, "purpose_class")
        owner = _required_label(item, "owner")
        provider_override = item.get("provider_payload_override")
        if campaign in campaigns:
            raise RunsArchiveError(f"Duplicate campaign classification: {campaign}")
        if purpose_class not in policy.retention_classes:
            raise RunsArchiveError(
                f"Unknown campaign purpose class: {purpose_class}"
            )
        if not isinstance(provider_override, bool):
            raise RunsArchiveError(
                "provider_payload_override must be boolean"
            )
        campaigns[campaign] = CampaignClassification(
            campaign=campaign,
            purpose_class=purpose_class,
            owner=owner,
            provider_payload_override=provider_override,
        )
    observed_campaigns = {
        str(group["campaign"]) for group in inventory.groups
    }
    if set(campaigns) != observed_campaigns:
        raise RunsArchiveError(
            "Campaign classification must exactly cover current inventory"
        )
    return RunsArchiveClassification(
        classification_id=_required_label(payload, "classification_id"),
        policy_id=policy.policy_id,
        inventory_state_fingerprint=str(
            payload["inventory_state_fingerprint"]
        ),
        archive_id=archive_id,
        storage_location_ref=location_ref,
        delete_authorized_count=0,
        campaigns=campaigns,
    )


def archive_runs(
    repo_root: str | Path,
    *,
    destination: str | Path,
    execution_time: str | None = None,
    classification_path: str | Path = DEFAULT_CLASSIFICATION_PATH,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
    index_schema_path: str | Path = DEFAULT_INDEX_SCHEMA_PATH,
    retained_index_path: str | Path = DEFAULT_RETAINED_INDEX_PATH,
    archive_report_path: str | Path = DEFAULT_ARCHIVE_REPORT_PATH,
    scrub_report_path: str | Path = DEFAULT_SCRUB_REPORT_PATH,
) -> ArchiveResult:
    """Create a new local archive; never overwrite source or destination."""
    root = Path(repo_root).resolve()
    archive_destination = Path(destination).expanduser().resolve()
    _require_outside_worktree(root, archive_destination)
    if archive_destination.exists():
        raise RunsArchiveError(
            f"Archive destination already exists: {archive_destination}"
        )
    policy = load_retention_policy(_rooted(root, policy_path))
    validate_index_schema_asset(_rooted(root, index_schema_path))
    inventory = verify_inventory_against_runs(
        root,
        summary_path=DEFAULT_SUMMARY_PATH,
        inventory_path=DEFAULT_INVENTORY_PATH,
    )
    classification = load_archive_classification(
        _rooted(root, classification_path),
        policy=policy,
        inventory=inventory,
    )
    executed_at = _normalize_timestamp(execution_time)
    archive_destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{classification.archive_id}.staging-",
            dir=archive_destination.parent,
        )
    )
    staging.chmod(0o700)
    installed = False
    try:
        payload_root = staging / "payload"
        payload_root.mkdir(mode=0o700)
        (
            file_records,
            group_source_files,
            group_archive_files,
            scrub_counts,
            changed_file_count,
        ) = _materialize_scrubbed_payload(
            root=root,
            payload_root=payload_root,
            inventory=inventory,
        )
        archive_payload_sha256 = _manifest_digest(file_records)
        group_source_digests = {
            path: _manifest_digest(records)
            for path, records in group_source_files.items()
        }
        group_archive_digests = {
            path: _manifest_digest(records)
            for path, records in group_archive_files.items()
        }
        restore_report = _verify_temporary_restore(
            payload_root=payload_root,
            inventory=inventory,
        )
        index_records = _build_retained_index_records(
            inventory=inventory,
            policy=policy,
            classification=classification,
            group_source_digests=group_source_digests,
            group_archive_digests=group_archive_digests,
            execution_time=executed_at,
        )
        index_text = _jsonl_text(index_records)
        index_sha256 = hashlib.sha256(index_text.encode("utf-8")).hexdigest()
        scrub_report = {
            "schema": RUNS_SCRUB_REPORT_SCHEMA,
            "archive_id": classification.archive_id,
            "inventory_state_fingerprint": (
                classification.inventory_state_fingerprint
            ),
            "source_preserved": True,
            "artifact_count": len(inventory.artifacts),
            "scanned_file_count": len(inventory.artifacts),
            "changed_file_count": changed_file_count,
            "unchanged_file_count": len(inventory.artifacts)
            - changed_file_count,
            "replacement_counts": dict(sorted(scrub_counts.items())),
            "post_scrub_idempotency_failure_count": 0,
            "tracked_content_policy": (
                "Counts and statuses only; no source text or matched value."
            ),
        }
        archive_report = {
            "schema": RUNS_ARCHIVE_MANIFEST_SCHEMA,
            "archive_id": classification.archive_id,
            "classification_id": classification.classification_id,
            "policy_id": policy.policy_id,
            "storage_location_ref": classification.storage_location_ref,
            "inventory_state_fingerprint": (
                classification.inventory_state_fingerprint
            ),
            "execution_time": executed_at,
            "artifact_count": len(inventory.artifacts),
            "artifact_group_count": len(inventory.groups),
            "source_total_bytes": inventory.summary["total_bytes"],
            "archive_total_bytes": sum(
                int(record["size_bytes"]) for record in file_records
            ),
            "archive_payload_sha256": archive_payload_sha256,
            "retained_index_sha256": index_sha256,
            "scrub_status": "verified",
            "restore_status": "verified",
            "restore_verified_artifact_count": restore_report[
                "verified_artifact_count"
            ],
            "restore_verified_group_count": restore_report[
                "verified_group_count"
            ],
            "contract_metadata_match_count": restore_report[
                "metadata_match_count"
            ],
            "delete_authorized_count": 0,
            "source_preserved": True,
        }
        external_manifest = {
            **archive_report,
            "schema": EXTERNAL_ARCHIVE_MANIFEST_SCHEMA,
            "files": file_records,
        }
        _write_json(staging / ".rc054-archive-manifest.json", external_manifest)
        os.replace(staging, archive_destination)
        installed = True

        retained_target = _rooted(root, retained_index_path)
        archive_report_target = _rooted(root, archive_report_path)
        scrub_report_target = _rooted(root, scrub_report_path)
        _write_text_atomic(retained_target, index_text)
        _write_json_atomic(archive_report_target, archive_report)
        _write_json_atomic(scrub_report_target, scrub_report)

        load_and_validate_index(
            retained_target,
            policy=policy,
            inventory=inventory,
        )
        verify_archive(
            root,
            destination=archive_destination,
            classification_path=classification_path,
            policy_path=policy_path,
            index_schema_path=index_schema_path,
            retained_index_path=retained_index_path,
            archive_report_path=archive_report_path,
            scrub_report_path=scrub_report_path,
        )
        return ArchiveResult(
            archive_id=classification.archive_id,
            destination=archive_destination,
            artifact_count=len(inventory.artifacts),
            artifact_group_count=len(inventory.groups),
            changed_file_count=changed_file_count,
            archive_payload_sha256=archive_payload_sha256,
            retained_index_path=retained_target,
        )
    finally:
        if not installed and staging.exists():
            shutil.rmtree(staging)


def verify_archive(
    repo_root: str | Path,
    *,
    destination: str | Path,
    classification_path: str | Path = DEFAULT_CLASSIFICATION_PATH,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
    index_schema_path: str | Path = DEFAULT_INDEX_SCHEMA_PATH,
    retained_index_path: str | Path = DEFAULT_RETAINED_INDEX_PATH,
    archive_report_path: str | Path = DEFAULT_ARCHIVE_REPORT_PATH,
    scrub_report_path: str | Path = DEFAULT_SCRUB_REPORT_PATH,
) -> Mapping[str, Any]:
    """Read-only verification of source state, tracked evidence, and archive."""
    root = Path(repo_root).resolve()
    archive_destination = Path(destination).expanduser().resolve()
    _require_outside_worktree(root, archive_destination)
    policy = load_retention_policy(_rooted(root, policy_path))
    validate_index_schema_asset(_rooted(root, index_schema_path))
    inventory = verify_inventory_against_runs(
        root,
        summary_path=DEFAULT_SUMMARY_PATH,
        inventory_path=DEFAULT_INVENTORY_PATH,
    )
    classification = load_archive_classification(
        _rooted(root, classification_path),
        policy=policy,
        inventory=inventory,
    )
    index_path = _rooted(root, retained_index_path)
    index = load_and_validate_index(
        index_path,
        policy=policy,
        inventory=inventory,
    )
    if len(index.entries) != len(inventory.groups):
        raise RunsArchiveError("Real retained index must contain every group")
    if index.deletion_authorizations:
        raise RunsArchiveError("RC-054 retained index cannot delete anything")
    archive_report = _load_json_object(
        _rooted(root, archive_report_path),
        context="tracked archive report",
    )
    scrub_report = _load_json_object(
        _rooted(root, scrub_report_path),
        context="tracked scrub report",
    )
    if archive_report.get("schema") != RUNS_ARCHIVE_MANIFEST_SCHEMA:
        raise RunsArchiveError("Tracked archive report schema drift")
    if scrub_report.get("schema") != RUNS_SCRUB_REPORT_SCHEMA:
        raise RunsArchiveError("Tracked scrub report schema drift")
    if (
        archive_report.get("archive_id") != classification.archive_id
        or scrub_report.get("archive_id") != classification.archive_id
    ):
        raise RunsArchiveError("Archive evidence ID mismatch")
    if archive_report.get("delete_authorized_count") != 0:
        raise RunsArchiveError("Tracked archive report cannot authorize deletion")
    index_sha256 = hashlib.sha256(index_path.read_bytes()).hexdigest()
    if index_sha256 != archive_report.get("retained_index_sha256"):
        raise RunsArchiveError("Retained index checksum drift")

    external_manifest = _load_json_object(
        archive_destination / ".rc054-archive-manifest.json",
        context="external archive manifest",
    )
    if external_manifest.get("schema") != EXTERNAL_ARCHIVE_MANIFEST_SCHEMA:
        raise RunsArchiveError("External archive manifest schema drift")
    file_records = external_manifest.get("files")
    if not isinstance(file_records, list):
        raise RunsArchiveError("External archive file records are missing")
    if len(file_records) != len(inventory.artifacts):
        raise RunsArchiveError("External archive artifact count drift")
    seen_paths: set[str] = set()
    verified_records: list[dict[str, Any]] = []
    for record in file_records:
        if not isinstance(record, dict) or set(record) != {
            "path",
            "size_bytes",
            "sha256",
            "scrubbed",
        }:
            raise RunsArchiveError("External archive file record drift")
        relative_path = _exact_runs_path(record.get("path"))
        if relative_path in seen_paths:
            raise RunsArchiveError(f"Duplicate archived path: {relative_path}")
        seen_paths.add(relative_path)
        archived_path = archive_destination / "payload" / relative_path
        if not archived_path.is_file() or archived_path.is_symlink():
            raise RunsArchiveError(f"Archived file is missing: {relative_path}")
        payload = archived_path.read_bytes()
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        if (
            len(payload) != record.get("size_bytes")
            or actual_sha256 != record.get("sha256")
        ):
            raise RunsArchiveError(f"Archived file checksum drift: {relative_path}")
        scrubbed_again, _counts = _scrub_bytes(
            payload,
            suffix=archived_path.suffix.lower(),
        )
        if scrubbed_again != payload:
            raise RunsArchiveError(
                f"Archived file failed scrub idempotency: {relative_path}"
            )
        verified_records.append(dict(record))
    actual_payload_sha256 = _manifest_digest(verified_records)
    if actual_payload_sha256 != archive_report.get("archive_payload_sha256"):
        raise RunsArchiveError("Archive payload checksum drift")
    expected_external = {**archive_report, "schema": EXTERNAL_ARCHIVE_MANIFEST_SCHEMA}
    for key, value in expected_external.items():
        if external_manifest.get(key) != value:
            raise RunsArchiveError(f"External archive evidence drift: {key}")
    if scrub_report.get("source_preserved") is not True:
        raise RunsArchiveError("Scrub report must preserve source")
    return archive_report


def _materialize_scrubbed_payload(
    *,
    root: Path,
    payload_root: Path,
    inventory: RunsInventory,
) -> tuple[
    list[dict[str, Any]],
    Mapping[str, list[dict[str, Any]]],
    Mapping[str, list[dict[str, Any]]],
    Counter[str],
    int,
]:
    file_records: list[dict[str, Any]] = []
    group_source_files: MutableMapping[str, list[dict[str, Any]]] = defaultdict(
        list
    )
    group_archive_files: MutableMapping[str, list[dict[str, Any]]] = defaultdict(
        list
    )
    scrub_counts: Counter[str] = Counter()
    changed_file_count = 0
    for artifact in inventory.artifacts:
        relative_path = _exact_runs_path(artifact["path"])
        source = root / relative_path
        if source.is_symlink() or not source.is_file():
            raise RunsArchiveError(
                f"Only regular source files may be archived: {relative_path}"
            )
        source_bytes = source.read_bytes()
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        scrubbed_bytes, counts = _scrub_bytes(
            source_bytes,
            suffix=source.suffix.lower(),
        )
        scrubbed_again, _second_counts = _scrub_bytes(
            scrubbed_bytes,
            suffix=source.suffix.lower(),
        )
        if scrubbed_again != scrubbed_bytes:
            raise RunsArchiveError(
                f"Scrub is not idempotent for {relative_path}"
            )
        changed = scrubbed_bytes != source_bytes
        changed_file_count += int(changed)
        scrub_counts.update(counts)
        archived = payload_root / relative_path
        archived.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        archived.write_bytes(scrubbed_bytes)
        archived.chmod(0o600)
        archive_sha256 = hashlib.sha256(scrubbed_bytes).hexdigest()
        file_record = {
            "path": relative_path,
            "size_bytes": len(scrubbed_bytes),
            "sha256": archive_sha256,
            "scrubbed": changed,
        }
        file_records.append(file_record)
        group_path = str(artifact["parent_group"])
        group_relative = PurePosixPath(relative_path).name
        group_source_files[group_path].append(
            {
                "path": group_relative,
                "size_bytes": len(source_bytes),
                "sha256": source_sha256,
                "scrubbed": False,
            }
        )
        group_archive_files[group_path].append(
            {
                "path": group_relative,
                "size_bytes": len(scrubbed_bytes),
                "sha256": archive_sha256,
                "scrubbed": changed,
            }
        )
    file_records.sort(key=lambda item: str(item["path"]))
    for records in (*group_source_files.values(), *group_archive_files.values()):
        records.sort(key=lambda item: str(item["path"]))
    return (
        file_records,
        group_source_files,
        group_archive_files,
        scrub_counts,
        changed_file_count,
    )


def _scrub_bytes(
    payload: bytes,
    *,
    suffix: str,
) -> tuple[bytes, Counter[str]]:
    counts: Counter[str] = Counter()
    if suffix in {".pyc", ".pyo"}:
        if payload != _COMPILED_CACHE_PLACEHOLDER:
            counts["compiled_cache_omitted"] += 1
        return _COMPILED_CACHE_PLACEHOLDER, counts
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RunsArchiveError(
            "Non-UTF-8 artifact cannot be safely scrubbed"
        ) from exc
    if suffix == ".json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            scrubbed_text = _scrub_text(text, counts)
        else:
            scrubbed_value = _scrub_json(value, counts)
            scrubbed_text = (
                json.dumps(
                    scrubbed_value,
                    ensure_ascii=True,
                    indent=2,
                )
                + "\n"
            )
    elif suffix == ".jsonl":
        output_lines: list[str] = []
        parsed_all = True
        for line in text.splitlines():
            if not line.strip():
                output_lines.append("")
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                parsed_all = False
                break
            output_lines.append(
                json.dumps(
                    _scrub_json(value, counts),
                    ensure_ascii=True,
                    separators=(",", ":"),
                )
            )
        if parsed_all:
            scrubbed_text = "\n".join(output_lines)
            if text.endswith("\n"):
                scrubbed_text += "\n"
        else:
            counts.clear()
            scrubbed_text = _scrub_text(text, counts)
    else:
        scrubbed_text = _scrub_text(text, counts)
    return scrubbed_text.encode("utf-8"), counts


def _scrub_json(
    value: Any,
    counts: Counter[str],
    *,
    key: str | None = None,
) -> Any:
    if key is not None and _SENSITIVE_KEY_RE.fullmatch(key):
        if isinstance(value, str) and not _is_redacted(value):
            counts["credential_value"] += 1
            return "<redacted>"
        if isinstance(value, (int, float, bool)):
            counts["credential_value"] += 1
            return "<redacted>"
    if isinstance(value, dict):
        return {
            str(child_key): _scrub_json(
                child,
                counts,
                key=str(child_key),
            )
            for child_key, child in value.items()
        }
    if isinstance(value, list):
        return [_scrub_json(child, counts) for child in value]
    if isinstance(value, str):
        return _scrub_text(value, counts)
    return value


def _scrub_text(text: str, counts: Counter[str]) -> str:
    text = _replace_counted(
        _PRIVATE_KEY_RE,
        text,
        "<redacted-private-key>",
        counts,
        "private_key",
    )
    text = _replace_counted(
        _EMAIL_RE,
        text,
        "<redacted-email>",
        counts,
        "email",
    )
    text = _replace_counted(
        _HOME_PATH_RE,
        text,
        "$HOME",
        counts,
        "absolute_user_path",
    )
    text = _replace_counted(
        _BEARER_RE,
        text,
        "Bearer <redacted>",
        counts,
        "bearer_token",
    )

    def secret_replacement(match: re.Match[str]) -> str:
        counts["credential_assignment"] += 1
        return f"{match.group(1)}=<redacted>"

    return _TEXT_SECRET_RE.sub(secret_replacement, text)


def _replace_counted(
    pattern: re.Pattern[str],
    text: str,
    replacement: str,
    counts: Counter[str],
    label: str,
) -> str:
    result, count = pattern.subn(replacement, text)
    if count:
        counts[label] += count
    return result


def _is_redacted(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {
        "<redacted>",
        "[redacted]",
        "redacted",
        "***",
    }


def _verify_temporary_restore(
    *,
    payload_root: Path,
    inventory: RunsInventory,
) -> dict[str, int]:
    with tempfile.TemporaryDirectory(prefix="rc054-restore-") as temp_dir:
        restore_root = Path(temp_dir)
        shutil.copytree(payload_root / "runs", restore_root / "runs")
        restored = scan_runs(restore_root, runs_root="runs")
        if len(restored.artifacts) != len(inventory.artifacts):
            raise RunsArchiveError("Temporary restore artifact count mismatch")
        source_by_path = {
            str(record["path"]): record for record in inventory.artifacts
        }
        restored_by_path = {
            str(record["path"]): record for record in restored.artifacts
        }
        if set(source_by_path) != set(restored_by_path):
            raise RunsArchiveError("Temporary restore path coverage mismatch")
        metadata_match_count = 0
        for path, source in source_by_path.items():
            candidate = restored_by_path[path]
            if source["artifact_class"] != candidate["artifact_class"]:
                raise RunsArchiveError(
                    f"Temporary restore class mismatch: {path}"
                )
            if not _metadata_contract_matches(
                source["metadata"],
                candidate["metadata"],
            ):
                raise RunsArchiveError(
                    f"Temporary restore metadata mismatch: {path}"
                )
            metadata_match_count += 1
        return {
            "verified_artifact_count": len(restored.artifacts),
            "verified_group_count": len(restored.groups),
            "metadata_match_count": metadata_match_count,
        }


def _metadata_contract_matches(
    source: Mapping[str, Any],
    restored: Mapping[str, Any],
) -> bool:
    if set(source) != set(restored):
        return False
    for key, source_value in source.items():
        restored_value = restored[key]
        if isinstance(source_value, dict) and source_value.get("redacted") is True:
            if not (
                isinstance(restored_value, dict)
                and restored_value.get("redacted") is True
            ):
                return False
        elif source_value != restored_value:
            return False
    return True


def _build_retained_index_records(
    *,
    inventory: RunsInventory,
    policy: RunsRetentionPolicy,
    classification: RunsArchiveClassification,
    group_source_digests: Mapping[str, str],
    group_archive_digests: Mapping[str, str],
    execution_time: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = [
        {
            "schema": RETAINED_RUN_INDEX_RECORD_SCHEMA,
            "record_type": "index",
            "index_id": f"retained-runs-{classification.archive_id}",
            "policy_id": policy.policy_id,
            "inventory_schema": inventory.summary["inventory_schema"],
            "inventory_state_fingerprint": (
                inventory.summary["state_fingerprint"]
            ),
            "example": False,
        }
    ]
    artifacts_by_group: MutableMapping[str, list[Mapping[str, Any]]] = (
        defaultdict(list)
    )
    for artifact in inventory.artifacts:
        artifacts_by_group[str(artifact["parent_group"])].append(artifact)
    execution_dt = _parse_timestamp(execution_time)
    for group in sorted(inventory.groups, key=lambda item: str(item["path"])):
        path = str(group["path"])
        campaign = classification.campaigns[str(group["campaign"])]
        purpose_class = campaign.purpose_class
        if (
            campaign.provider_payload_override
            and group["group_class"] == "provider_payload_group"
        ):
            purpose_class = "provider_raw"
        starts_at = min(
            _parse_timestamp(str(artifact["mtime_utc"]))
            for artifact in artifacts_by_group[path]
        )
        expires_at, quarantine_until, disposition = _retention_window(
            purpose_class,
            starts_at=starts_at,
            execution_time=execution_dt,
        )
        risks = sorted(str(item) for item in group["sensitive_risk_labels"])
        credential_trigger = policy.credential_review_trigger in risks
        records.append(
            {
                "schema": RETAINED_RUN_INDEX_RECORD_SCHEMA,
                "record_type": "entry",
                "target": {"kind": "artifact_group", "path": path},
                "purpose_class": purpose_class,
                "sensitivity": "restricted" if risks else "internal",
                "risk_labels": risks,
                "owner": campaign.owner,
                "retention": {
                    "starts_at": _format_timestamp(starts_at),
                    "expires_at": _format_timestamp(expires_at),
                    "quarantine_until": _format_timestamp(quarantine_until),
                },
                "disposition": disposition,
                "storage": {
                    "kind": "local_filesystem_outside_git_worktree",
                    "location_ref": classification.storage_location_ref,
                },
                "checksums": {
                    "algorithm": "sha256",
                    "source": group_source_digests[path],
                    "archive": group_archive_digests[path],
                },
                "scrub": {
                    "status": "verified" if risks else "not_required",
                    "report_ref": DEFAULT_SCRUB_REPORT_PATH.as_posix(),
                    "source_preserved": True,
                },
                "restore": {
                    "status": "verified",
                    "verified_at": execution_time,
                },
                "credential_review": {
                    "status": "complete" if credential_trigger else "not_required",
                    "reviewed_at": execution_time if credential_trigger else None,
                },
                "deletion_authorization_id": None,
            }
        )
    return records


def _retention_window(
    purpose_class: str,
    *,
    starts_at: datetime,
    execution_time: datetime,
) -> tuple[datetime | None, datetime | None, str]:
    if purpose_class in {
        "contract_golden",
        "unique_research_evidence",
        "unclassified_hold",
    }:
        disposition = (
            "manual_review_hold"
            if purpose_class == "unclassified_hold"
            else "retain_active"
        )
        return None, None, disposition
    if purpose_class == "provider_raw":
        expires_at = starts_at + timedelta(days=365)
        disposition = (
            "manual_review_hold"
            if execution_time >= expires_at
            else "retain_local"
        )
        return expires_at, None, disposition
    if purpose_class in {"debug", "failed"}:
        expires_at = starts_at + timedelta(days=90)
        quarantine_until = expires_at + timedelta(days=30)
        disposition = (
            "quarantine" if execution_time >= expires_at else "retain_local"
        )
        return expires_at, quarantine_until, disposition
    if purpose_class in {"superseded", "duplicate"}:
        return starts_at, execution_time + timedelta(days=30), "quarantine"
    raise RunsArchiveError(f"Unsupported purpose class: {purpose_class}")


def _manifest_digest(records: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: str(item["path"])):
        digest.update(str(record["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record["size_bytes"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(record["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _exact_runs_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise RunsArchiveError("Archive path must be a non-empty string")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or path.parts[0] != "runs"
        or ".." in path.parts
        or any(character in value for character in "*?[]")
    ):
        raise RunsArchiveError("Archive path must be one exact runs path")
    return value


def _require_outside_worktree(root: Path, destination: Path) -> None:
    try:
        destination.relative_to(root)
    except ValueError:
        return
    raise RunsArchiveError("Archive destination must be outside Git worktree")


def _rooted(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (root / candidate).resolve()
    )
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RunsArchiveError(f"Tracked path escapes repository: {path}") from exc
    return resolved


def _required_label(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if (
        not isinstance(value, str)
        or not value
        or any(character in value for character in "\r\n")
    ):
        raise RunsArchiveError(f"{field} must be a non-empty label")
    return value


def _normalize_timestamp(value: str | None) -> str:
    if value is None:
        timestamp = datetime.now(timezone.utc)
    else:
        timestamp = _parse_timestamp(value)
    return _format_timestamp(timestamp) or ""


def _parse_timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RunsArchiveError(f"Invalid timestamp: {value}") from exc
    if timestamp.tzinfo is None:
        raise RunsArchiveError("Timestamp must include timezone")
    return timestamp.astimezone(timezone.utc)


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonl_text(records: Sequence[Mapping[str, Any]]) -> str:
    return "".join(
        json.dumps(
            record,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
        for record in records
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    _write_text_atomic(
        path,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_json_object(path: Path, *, context: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunsArchiveError(f"{context} is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RunsArchiveError(f"{context} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RunsArchiveError(f"{context} must be an object")
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("archive", "verify"))
    parser.add_argument("--repo-root", type=Path, default=project_root())
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--execution-time")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "archive":
            result = archive_runs(
                args.repo_root,
                destination=args.destination,
                execution_time=args.execution_time,
            )
            print(
                f"runs-archive: created {result.archive_id} with "
                f"{result.artifact_count} artifacts, "
                f"{result.artifact_group_count} groups, "
                f"{result.changed_file_count} scrubbed files; "
                f"payload={result.archive_payload_sha256}"
            )
        else:
            report = verify_archive(
                args.repo_root,
                destination=args.destination,
            )
            print(
                f"runs-archive: verified {report['archive_id']} with "
                f"{report['artifact_count']} artifacts; deleted=0"
            )
    except (
        OSError,
        RunsArchiveError,
        RunsRetentionError,
    ) as exc:
        print(f"runs-archive: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
