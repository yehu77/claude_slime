"""Validate the read-only runs retention policy and retained-run index."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from pycodeagent.dev.runs_inventory import (
    DEFAULT_INVENTORY_PATH,
    DEFAULT_SUMMARY_PATH,
    RUNS_INVENTORY_SCHEMA,
    RunsInventory,
    load_and_validate_inventory,
)


RUNS_RETENTION_POLICY_SCHEMA = "pycodeagent-runs-retention-policy/v1"
RETAINED_RUN_INDEX_RECORD_SCHEMA = (
    "pycodeagent-retained-run-index-record/v1"
)
RUNS_RETENTION_COVERAGE_SCHEMA = "pycodeagent-runs-retention-coverage/v1"
DEFAULT_POLICY_PATH = Path("references/runs-retention-policy.json")
DEFAULT_INDEX_SCHEMA_PATH = Path("references/retained-run-index.schema.json")
DEFAULT_EXAMPLE_INDEX_PATH = Path(
    "examples/runs_retention/retained-run-index.example.jsonl"
)
DEFAULT_COVERAGE_PATH = Path("references/runs-retention-coverage.json")

_PURPOSE_CLASSES = {
    "contract_golden",
    "unique_research_evidence",
    "provider_raw",
    "debug",
    "failed",
    "superseded",
    "duplicate",
    "unclassified_hold",
}
_PERMANENT_CLASSES = {
    "contract_golden",
    "unique_research_evidence",
    "unclassified_hold",
}
_SENSITIVITY_CLASSES = {"internal", "restricted"}
_DISPOSITIONS = {
    "retain_active",
    "retain_local",
    "manual_review_hold",
    "quarantine",
    "delete_authorized",
}
_STORAGE_KINDS = {
    "current_local",
    "local_filesystem_outside_git_worktree",
}
_DIGEST_ALGORITHMS = {"sha256", "sha256-tree-manifest-v1"}
_REQUIRED_PRECONDITIONS = {
    "retention_elapsed",
    "quarantine_elapsed",
    "backup_checksum_verified",
    "temporary_restore_verified",
    "scrub_or_sensitivity_review_complete",
}


class RunsRetentionError(ValueError):
    """Raised when the retention policy, index, or coverage is invalid."""


@dataclass(frozen=True)
class RetentionClass:
    name: str
    minimum_retention_days: int | None
    quarantine_days: int | None
    expiry_disposition: str
    deletion_eligible: bool


@dataclass(frozen=True)
class ClassificationRule:
    rule_id: str
    priority: int
    match: Mapping[str, Any]
    purpose_class: str


@dataclass(frozen=True)
class RunsRetentionPolicy:
    policy_id: str
    owner: str
    retention_classes: Mapping[str, RetentionClass]
    classification_rules: tuple[ClassificationRule, ...]
    raw_asset_classes: frozenset[str]
    credential_review_trigger: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class RetainedRunIndex:
    header: Mapping[str, Any]
    entries: tuple[Mapping[str, Any], ...]
    deletion_authorizations: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class CoverageDecision:
    purpose_class: str
    sensitivity: str
    disposition: str
    rule_id: str


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_retention_policy(path: str | Path) -> RunsRetentionPolicy:
    """Load and validate the approved conservative/local/manual policy."""
    policy_path = Path(path)
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunsRetentionError(
            f"Runs retention policy is missing: {policy_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RunsRetentionError(
            f"Runs retention policy is invalid JSON: {policy_path}"
        ) from exc
    if not isinstance(payload, dict):
        raise RunsRetentionError("Runs retention policy root must be an object")
    if payload.get("schema") != RUNS_RETENTION_POLICY_SCHEMA:
        raise RunsRetentionError("Unsupported runs retention policy schema")
    if payload.get("inventory_schema") != RUNS_INVENTORY_SCHEMA:
        raise RunsRetentionError("Retention policy inventory schema drift")
    if payload.get("index_record_schema") != RETAINED_RUN_INDEX_RECORD_SCHEMA:
        raise RunsRetentionError("Retention policy index schema drift")

    classes_payload = payload.get("retention_classes")
    if not isinstance(classes_payload, list):
        raise RunsRetentionError("retention_classes must be a list")
    retention_classes: dict[str, RetentionClass] = {}
    for item in classes_payload:
        if not isinstance(item, dict):
            raise RunsRetentionError("Each retention class must be an object")
        _require_exact_keys(
            item,
            {
                "name",
                "minimum_retention_days",
                "quarantine_days",
                "expiry_disposition",
                "deletion_eligible",
            },
            context="retention class",
        )
        name = _required_string(item, "name")
        if name in retention_classes:
            raise RunsRetentionError(f"Duplicate retention class: {name}")
        minimum_days = _optional_nonnegative_int(
            item.get("minimum_retention_days"),
            field=f"{name}.minimum_retention_days",
        )
        quarantine_days = _optional_nonnegative_int(
            item.get("quarantine_days"),
            field=f"{name}.quarantine_days",
        )
        deletion_eligible = item.get("deletion_eligible")
        if not isinstance(deletion_eligible, bool):
            raise RunsRetentionError(
                f"{name}.deletion_eligible must be boolean"
            )
        retention_classes[name] = RetentionClass(
            name=name,
            minimum_retention_days=minimum_days,
            quarantine_days=quarantine_days,
            expiry_disposition=_required_string(
                item,
                "expiry_disposition",
            ),
            deletion_eligible=deletion_eligible,
        )
    if set(retention_classes) != _PURPOSE_CLASSES:
        raise RunsRetentionError(
            "Retention policy must define the complete v1 purpose-class set"
        )
    _validate_approved_retention_schedule(retention_classes)

    rules_payload = payload.get("classification_rules")
    if not isinstance(rules_payload, list) or not rules_payload:
        raise RunsRetentionError("classification_rules must be non-empty")
    classification_rules: list[ClassificationRule] = []
    seen_rule_ids: set[str] = set()
    seen_priorities: set[int] = set()
    for item in rules_payload:
        if not isinstance(item, dict):
            raise RunsRetentionError("Each classification rule must be an object")
        _require_exact_keys(
            item,
            {"rule_id", "priority", "match", "purpose_class"},
            context="classification rule",
        )
        rule_id = _required_string(item, "rule_id")
        priority = item.get("priority")
        match = item.get("match")
        purpose_class = _required_string(item, "purpose_class")
        if rule_id in seen_rule_ids:
            raise RunsRetentionError(f"Duplicate classification rule: {rule_id}")
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise RunsRetentionError(f"Rule {rule_id} priority must be integer")
        if priority in seen_priorities:
            raise RunsRetentionError(
                f"Ambiguous classification priority: {priority}"
            )
        if purpose_class not in retention_classes:
            raise RunsRetentionError(
                f"Rule {rule_id} has unknown purpose class: {purpose_class}"
            )
        _validate_rule_match(rule_id, match)
        seen_rule_ids.add(rule_id)
        seen_priorities.add(priority)
        classification_rules.append(
            ClassificationRule(
                rule_id=rule_id,
                priority=priority,
                match=match,
                purpose_class=purpose_class,
            )
        )
    classification_rules.sort(key=lambda rule: rule.priority)
    fallback_rules = [
        rule
        for rule in classification_rules
        if rule.match == {"always": True}
    ]
    if (
        len(fallback_rules) != 1
        or fallback_rules[0] != classification_rules[-1]
        or fallback_rules[0].purpose_class != "unclassified_hold"
    ):
        raise RunsRetentionError(
            "The final classification rule must be one conservative fallback"
        )

    sensitivity = _required_object(payload, "sensitivity_policy")
    if sensitivity.get("risk_free_class") != "internal":
        raise RunsRetentionError("Risk-free assets must remain internal")
    if sensitivity.get("any_risk_class") != "restricted":
        raise RunsRetentionError("Any risk label must produce restricted data")
    if sensitivity.get("unknown_risk_handling") != "restricted":
        raise RunsRetentionError("Unknown risks must fail closed as restricted")
    if sensitivity.get("tracked_output_content") != "redacted_metadata_only":
        raise RunsRetentionError("Tracked retention output must stay redacted")

    storage = _required_object(payload, "storage_policy")
    raw_asset_classes = frozenset(
        _required_string_list(storage, "raw_asset_classes")
    )
    if storage.get("allowed_raw_location") != (
        "local_filesystem_outside_git_worktree"
    ):
        raise RunsRetentionError("Raw assets must remain local outside Git")
    forbidden_locations = set(
        _required_string_list(storage, "forbidden_raw_locations")
    )
    if forbidden_locations != {
        "git_worktree",
        "network_share",
        "self_managed_object_storage",
        "managed_cloud_storage",
    }:
        raise RunsRetentionError("Raw external-storage boundary has drifted")
    if storage.get("tracked_repository_content") != "redacted_metadata_only":
        raise RunsRetentionError("Tracked repository content must be redacted")

    scrub = _required_object(payload, "scrub_policy")
    if (
        scrub.get("source_overwrite_allowed") is not False
        or scrub.get("derivative_required") is not True
        or scrub.get("matched_text_in_tracked_report_allowed") is not False
        or scrub.get("failure_disposition") != "retain_and_report"
    ):
        raise RunsRetentionError("Scrub policy must preserve source and fail safe")

    archive = _required_object(payload, "archive_policy")
    if set(_required_string_list(archive, "digest_algorithms")) != (
        _DIGEST_ALGORITHMS
    ):
        raise RunsRetentionError("Archive digest algorithms have drifted")
    if archive.get("temporary_restore_verification_required") is not True:
        raise RunsRetentionError("Temporary restore verification is required")
    if archive.get("failure_disposition") != "retain_and_report":
        raise RunsRetentionError("Archive failure must retain and report")

    deletion = _required_object(payload, "deletion_policy")
    if deletion.get("mode") != "explicit_per_batch_user_authorization":
        raise RunsRetentionError("Deletion must use explicit per-batch approval")
    if (
        deletion.get("wildcards_allowed") is not False
        or deletion.get("authorization_reuse_allowed") is not False
        or deletion.get("required_authorized_by") != "repository_owner"
        or deletion.get("failure_disposition") != "retain_and_report"
    ):
        raise RunsRetentionError("Deletion policy is not conservative/manual")
    if set(_required_string_list(deletion, "required_preconditions")) != (
        _REQUIRED_PRECONDITIONS
    ):
        raise RunsRetentionError("Deletion preconditions are incomplete")

    defaults = _required_object(payload, "defaults")
    if (
        defaults.get("unknown_purpose_class") != "unclassified_hold"
        or defaults.get("unknown_or_present_risk_sensitivity") != "restricted"
        or defaults.get("no_risk_sensitivity") != "internal"
        or defaults.get("failure_disposition") != "retain_and_report"
    ):
        raise RunsRetentionError("Retention defaults must fail closed")

    return RunsRetentionPolicy(
        policy_id=_required_string(payload, "policy_id"),
        owner=_required_string(payload, "owner"),
        retention_classes=retention_classes,
        classification_rules=tuple(classification_rules),
        raw_asset_classes=raw_asset_classes,
        credential_review_trigger=_required_string(
            sensitivity,
            "credential_review_trigger",
        ),
        payload=payload,
    )


def classify_inventory_group(
    policy: RunsRetentionPolicy,
    group: Mapping[str, Any],
) -> CoverageDecision:
    """Return one conservative, non-destructive decision for a group."""
    matching = [
        rule
        for rule in policy.classification_rules
        if _rule_matches(rule, group)
    ]
    if not matching:
        raise RunsRetentionError("No classification rule matched inventory group")
    highest_priority = min(rule.priority for rule in matching)
    selected = [
        rule for rule in matching if rule.priority == highest_priority
    ]
    if len(selected) != 1:
        raise RunsRetentionError("Ambiguous classification rule result")
    rule = selected[0]
    risks = group.get("sensitive_risk_labels")
    sensitivity = (
        "internal"
        if isinstance(risks, list) and not risks
        else "restricted"
    )
    disposition = _initial_disposition(rule.purpose_class)
    if disposition == "delete_authorized":
        raise RunsRetentionError("Coverage classification cannot authorize deletion")
    return CoverageDecision(
        purpose_class=rule.purpose_class,
        sensitivity=sensitivity,
        disposition=disposition,
        rule_id=rule.rule_id,
    )


def build_coverage_report(
    policy: RunsRetentionPolicy,
    inventory: RunsInventory,
) -> dict[str, Any]:
    """Build a deterministic aggregate report without serializing run content."""
    purpose_counts: Counter[str] = Counter()
    sensitivity_counts: Counter[str] = Counter()
    disposition_counts: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    combinations: set[tuple[Any, ...]] = set()
    for group in inventory.groups:
        decision = classify_inventory_group(policy, group)
        purpose_counts[decision.purpose_class] += 1
        sensitivity_counts[decision.sensitivity] += 1
        disposition_counts[decision.disposition] += 1
        rule_counts[decision.rule_id] += 1
        combinations.add(
            (
                group.get("group_class"),
                group.get("manifest_status"),
                tuple(group.get("sensitive_risk_labels", [])),
                _metadata_scalar(group, "status"),
            )
        )
    deletion_count = disposition_counts.get("delete_authorized", 0)
    if deletion_count:
        raise RunsRetentionError(
            "RC-053 coverage report must not authorize deletion"
        )
    return {
        "schema": RUNS_RETENTION_COVERAGE_SCHEMA,
        "policy_id": policy.policy_id,
        "inventory_schema": inventory.summary["inventory_schema"],
        "inventory_state_fingerprint": inventory.summary["state_fingerprint"],
        "artifact_group_count": len(inventory.groups),
        "classified_group_count": len(inventory.groups),
        "classification_status": "complete",
        "observed_combination_count": len(combinations),
        "purpose_class_counts": dict(sorted(purpose_counts.items())),
        "sensitivity_counts": dict(sorted(sensitivity_counts.items())),
        "disposition_counts": dict(sorted(disposition_counts.items())),
        "classification_rule_counts": dict(sorted(rule_counts.items())),
        "delete_authorized_count": deletion_count,
        "content_policy": (
            "Aggregate counts only; no raw content, secret matches, or "
            "per-run disposition decisions are serialized."
        ),
    }


def verify_tracked_coverage(
    *,
    policy: RunsRetentionPolicy,
    inventory: RunsInventory,
    coverage_path: str | Path,
) -> Mapping[str, Any]:
    """Require the tracked aggregate coverage to match a read-only evaluation."""
    path = Path(coverage_path)
    try:
        tracked = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunsRetentionError(
            f"Runs retention coverage is missing: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RunsRetentionError(
            f"Runs retention coverage is invalid JSON: {path}"
        ) from exc
    expected = build_coverage_report(policy, inventory)
    if tracked != expected:
        raise RunsRetentionError(
            "Runs retention coverage drift; regenerate reviewed aggregate"
        )
    return tracked


def load_and_validate_index(
    path: str | Path,
    *,
    policy: RunsRetentionPolicy,
    inventory: RunsInventory | None = None,
) -> RetainedRunIndex:
    """Validate JSONL structure, lifecycle invariants, and optional coverage."""
    index_path = Path(path)
    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise RunsRetentionError(
            f"Retained-run index is missing: {index_path}"
        ) from exc
    if not lines:
        raise RunsRetentionError("Retained-run index must not be empty")
    records: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RunsRetentionError(
                f"Invalid retained-run index JSONL at line {line_number}"
            ) from exc
        if not isinstance(record, dict):
            raise RunsRetentionError(
                f"Index record at line {line_number} must be an object"
            )
        if record.get("schema") != RETAINED_RUN_INDEX_RECORD_SCHEMA:
            raise RunsRetentionError(
                f"Index schema drift at line {line_number}"
            )
        records.append(record)

    headers = [item for item in records if item.get("record_type") == "index"]
    entries = [item for item in records if item.get("record_type") == "entry"]
    authorizations = [
        item
        for item in records
        if item.get("record_type") == "deletion_authorization"
    ]
    if len(headers) != 1 or records[0] is not headers[0]:
        raise RunsRetentionError("Index must begin with exactly one header")
    if len(headers) + len(entries) + len(authorizations) != len(records):
        raise RunsRetentionError("Index contains an unsupported record type")
    header = headers[0]
    _validate_index_header(header, policy=policy)

    targets: dict[tuple[str, str], Mapping[str, Any]] = {}
    for entry in entries:
        _validate_index_entry(entry, policy=policy)
        target_key = _target_key(entry.get("target"), context="index entry")
        if target_key in targets:
            raise RunsRetentionError(
                f"Duplicate retained-run target: {target_key[1]}"
            )
        targets[target_key] = entry

    authorization_by_id: dict[str, Mapping[str, Any]] = {}
    for authorization in authorizations:
        authorization_id = _validate_deletion_authorization(
            authorization,
            header=header,
        )
        if authorization_id in authorization_by_id:
            raise RunsRetentionError(
                f"Duplicate deletion authorization: {authorization_id}"
            )
        authorization_by_id[authorization_id] = authorization
    _validate_authorized_entries(
        header=header,
        entries=entries,
        authorization_by_id=authorization_by_id,
        policy=policy,
    )
    if header["example"] and authorizations:
        raise RunsRetentionError(
            "Synthetic example indexes cannot authorize deletion"
        )
    if inventory is not None:
        _validate_index_inventory_coverage(
            header=header,
            entries=targets,
            inventory=inventory,
        )
    return RetainedRunIndex(
        header=header,
        entries=tuple(entries),
        deletion_authorizations=tuple(authorizations),
    )


def validate_index_schema_asset(path: str | Path) -> Mapping[str, Any]:
    """Validate the tracked JSON Schema's identity and record definitions."""
    schema_path = Path(path)
    try:
        payload = json.loads(schema_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunsRetentionError(
            f"Retained-run index schema is missing: {schema_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RunsRetentionError(
            f"Retained-run index schema is invalid JSON: {schema_path}"
        ) from exc
    definitions = payload.get("$defs") if isinstance(payload, dict) else None
    if (
        not isinstance(definitions, dict)
        or not {"header", "entry", "deletion_authorization"} <= set(definitions)
    ):
        raise RunsRetentionError("Retained-run index schema definitions drift")
    header_schema = definitions["header"]
    expected = header_schema.get("properties", {}).get("schema")
    if expected != {"const": RETAINED_RUN_INDEX_RECORD_SCHEMA}:
        raise RunsRetentionError("Retained-run index record schema drift")
    return payload


def _validate_approved_retention_schedule(
    classes: Mapping[str, RetentionClass],
) -> None:
    expected = {
        "contract_golden": (None, None, "retain", False),
        "unique_research_evidence": (None, None, "retain", False),
        "provider_raw": (365, 30, "manual_review", True),
        "debug": (90, 30, "quarantine", True),
        "failed": (90, 30, "quarantine", True),
        "superseded": (0, 30, "quarantine", True),
        "duplicate": (0, 30, "quarantine", True),
        "unclassified_hold": (None, None, "manual_review_hold", False),
    }
    actual = {
        name: (
            item.minimum_retention_days,
            item.quarantine_days,
            item.expiry_disposition,
            item.deletion_eligible,
        )
        for name, item in classes.items()
    }
    if actual != expected:
        raise RunsRetentionError("Approved conservative retention schedule drift")


def _validate_rule_match(rule_id: str, match: Any) -> None:
    if not isinstance(match, dict) or not match:
        raise RunsRetentionError(f"Rule {rule_id} match must be an object")
    allowed = {"always", "status_any", "group_class_any"}
    if not set(match) <= allowed:
        raise RunsRetentionError(f"Rule {rule_id} has unknown match keys")
    if "always" in match:
        if match != {"always": True}:
            raise RunsRetentionError(
                f"Rule {rule_id} always match cannot have other conditions"
            )
        return
    for key, value in match.items():
        if (
            key.endswith("_any")
            and (
                not isinstance(value, list)
                or not value
                or not all(isinstance(item, str) and item for item in value)
            )
        ):
            raise RunsRetentionError(
                f"Rule {rule_id} {key} must be a non-empty string list"
            )


def _rule_matches(
    rule: ClassificationRule,
    group: Mapping[str, Any],
) -> bool:
    if rule.match == {"always": True}:
        return True
    if "group_class_any" in rule.match and group.get("group_class") not in (
        rule.match["group_class_any"]
    ):
        return False
    if "status_any" in rule.match and _metadata_scalar(
        group,
        "status",
    ) not in rule.match["status_any"]:
        return False
    return True


def _metadata_scalar(group: Mapping[str, Any], key: str) -> Any:
    metadata = group.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    return value if isinstance(value, (str, int, float, bool)) else None


def _initial_disposition(purpose_class: str) -> str:
    if purpose_class in {"contract_golden", "unique_research_evidence"}:
        return "retain_active"
    if purpose_class == "unclassified_hold":
        return "manual_review_hold"
    return "retain_local"


def _validate_index_header(
    header: Mapping[str, Any],
    *,
    policy: RunsRetentionPolicy,
) -> None:
    _require_exact_keys(
        header,
        {
            "schema",
            "record_type",
            "index_id",
            "policy_id",
            "inventory_schema",
            "inventory_state_fingerprint",
            "example",
        },
        context="index header",
    )
    if header.get("policy_id") != policy.policy_id:
        raise RunsRetentionError("Index policy_id does not match policy")
    if header.get("inventory_schema") != RUNS_INVENTORY_SCHEMA:
        raise RunsRetentionError("Index inventory schema drift")
    _sha256(header, "inventory_state_fingerprint")
    _required_string(header, "index_id")
    if not isinstance(header.get("example"), bool):
        raise RunsRetentionError("Index example flag must be boolean")


def _validate_index_entry(
    entry: Mapping[str, Any],
    *,
    policy: RunsRetentionPolicy,
) -> None:
    _require_exact_keys(
        entry,
        {
            "schema",
            "record_type",
            "target",
            "purpose_class",
            "sensitivity",
            "risk_labels",
            "owner",
            "retention",
            "disposition",
            "storage",
            "checksums",
            "scrub",
            "restore",
            "credential_review",
            "deletion_authorization_id",
        },
        context="index entry",
    )
    _target_key(entry.get("target"), context="index entry")
    purpose_class = _required_string(entry, "purpose_class")
    if purpose_class not in policy.retention_classes:
        raise RunsRetentionError(
            f"Unknown retained-run purpose class: {purpose_class}"
        )
    sensitivity = _required_string(entry, "sensitivity")
    if sensitivity not in _SENSITIVITY_CLASSES:
        raise RunsRetentionError(f"Unknown sensitivity: {sensitivity}")
    risks = entry.get("risk_labels")
    if (
        not isinstance(risks, list)
        or not all(isinstance(item, str) and item for item in risks)
        or len(risks) != len(set(risks))
    ):
        raise RunsRetentionError("risk_labels must be a unique string list")
    expected_sensitivity = "restricted" if risks else "internal"
    if sensitivity != expected_sensitivity:
        raise RunsRetentionError("Sensitivity must be derived from risk_labels")
    _required_string(entry, "owner")
    disposition = _required_string(entry, "disposition")
    if disposition not in _DISPOSITIONS:
        raise RunsRetentionError(f"Unknown disposition: {disposition}")

    retention = _required_object(entry, "retention")
    _require_exact_keys(
        retention,
        {"starts_at", "expires_at", "quarantine_until"},
        context="retention window",
    )
    _timestamp(retention, "starts_at", nullable=False)
    expires_at = _timestamp(retention, "expires_at", nullable=True)
    quarantine_until = _timestamp(
        retention,
        "quarantine_until",
        nullable=True,
    )
    if purpose_class in _PERMANENT_CLASSES:
        if expires_at is not None or quarantine_until is not None:
            raise RunsRetentionError(
                f"Permanent class {purpose_class} cannot expire or quarantine"
            )
        if disposition in {"quarantine", "delete_authorized"}:
            raise RunsRetentionError(
                f"Permanent class {purpose_class} cannot be deleted"
            )
    elif expires_at is None:
        raise RunsRetentionError(
            f"Non-permanent class {purpose_class} requires expires_at"
        )

    storage = _required_object(entry, "storage")
    _require_exact_keys(
        storage,
        {"kind", "location_ref"},
        context="storage",
    )
    if storage.get("kind") not in _STORAGE_KINDS:
        raise RunsRetentionError("External or Git-worktree storage is forbidden")
    location_ref = storage.get("location_ref")
    if location_ref is not None and (
        not isinstance(location_ref, str)
        or not location_ref
        or "://" in location_ref
        or PurePosixPath(location_ref).is_absolute()
        or location_ref.startswith(("/home/", "/Users/"))
        or "@" in location_ref
    ):
        raise RunsRetentionError(
            "Storage location_ref must be one redacted local label"
        )

    checksums = _required_object(entry, "checksums")
    _require_exact_keys(
        checksums,
        {"algorithm", "source", "archive"},
        context="checksums",
    )
    if checksums.get("algorithm") not in _DIGEST_ALGORITHMS:
        raise RunsRetentionError("Unsupported checksum algorithm")
    _nullable_sha256(checksums, "source")
    _nullable_sha256(checksums, "archive")

    scrub = _required_object(entry, "scrub")
    _require_exact_keys(
        scrub,
        {"status", "report_ref", "source_preserved"},
        context="scrub",
    )
    if scrub.get("status") not in {"pending", "not_required", "verified"}:
        raise RunsRetentionError("Unknown scrub status")
    if scrub.get("source_preserved") is not True:
        raise RunsRetentionError("Scrub must preserve the source")
    _nullable_local_reference(scrub, "report_ref")

    restore = _required_object(entry, "restore")
    _require_exact_keys(
        restore,
        {"status", "verified_at"},
        context="restore",
    )
    if restore.get("status") not in {
        "pending",
        "not_applicable",
        "verified",
    }:
        raise RunsRetentionError("Unknown restore status")
    restore_at = _timestamp(restore, "verified_at", nullable=True)
    if (restore.get("status") == "verified") != (restore_at is not None):
        raise RunsRetentionError(
            "Verified restore status and verified_at must agree"
        )

    credential_review = _required_object(entry, "credential_review")
    _require_exact_keys(
        credential_review,
        {"status", "reviewed_at"},
        context="credential review",
    )
    if credential_review.get("status") not in {
        "pending",
        "not_required",
        "complete",
    }:
        raise RunsRetentionError("Unknown credential-review status")
    reviewed_at = _timestamp(
        credential_review,
        "reviewed_at",
        nullable=True,
    )
    if (credential_review.get("status") == "complete") != (
        reviewed_at is not None
    ):
        raise RunsRetentionError(
            "Completed credential review and reviewed_at must agree"
        )
    trigger_present = policy.credential_review_trigger in risks
    if trigger_present and credential_review.get("status") == "not_required":
        raise RunsRetentionError(
            "Potential authorization material requires credential review"
        )
    if (
        not trigger_present
        and credential_review.get("status") not in {"not_required", "complete"}
    ):
        raise RunsRetentionError(
            "Credential review may be pending only for its risk trigger"
        )

    authorization_id = entry.get("deletion_authorization_id")
    if authorization_id is not None and (
        not isinstance(authorization_id, str) or not authorization_id
    ):
        raise RunsRetentionError("Invalid deletion_authorization_id")
    if disposition == "delete_authorized" and authorization_id is None:
        raise RunsRetentionError(
            "delete_authorized requires explicit authorization"
        )
    if disposition != "delete_authorized" and authorization_id is not None:
        raise RunsRetentionError(
            "Deletion authorization cannot attach to a retained entry"
        )


def _validate_deletion_authorization(
    authorization: Mapping[str, Any],
    *,
    header: Mapping[str, Any],
) -> str:
    _require_exact_keys(
        authorization,
        {
            "schema",
            "record_type",
            "authorization_id",
            "authorized_by",
            "authorized_at",
            "inventory_state_fingerprint",
            "targets",
            "preconditions",
        },
        context="deletion authorization",
    )
    authorization_id = _required_string(
        authorization,
        "authorization_id",
    )
    if authorization.get("authorized_by") != "repository_owner":
        raise RunsRetentionError(
            "Deletion authorization must come from repository_owner"
        )
    _timestamp(authorization, "authorized_at", nullable=False)
    if authorization.get("inventory_state_fingerprint") != header.get(
        "inventory_state_fingerprint"
    ):
        raise RunsRetentionError(
            "Deletion authorization inventory fingerprint mismatch"
        )
    targets = authorization.get("targets")
    if not isinstance(targets, list) or not targets:
        raise RunsRetentionError(
            "Deletion authorization requires an exact non-empty target list"
        )
    keys = [
        _target_key(target, context="deletion authorization")
        for target in targets
    ]
    if len(keys) != len(set(keys)):
        raise RunsRetentionError("Deletion authorization targets must be unique")
    preconditions = _required_object(authorization, "preconditions")
    _require_exact_keys(
        preconditions,
        _REQUIRED_PRECONDITIONS,
        context="deletion preconditions",
    )
    if any(value is not True for value in preconditions.values()):
        raise RunsRetentionError(
            "Every deletion precondition must be explicitly true"
        )
    return authorization_id


def _validate_authorized_entries(
    *,
    header: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    authorization_by_id: Mapping[str, Mapping[str, Any]],
    policy: RunsRetentionPolicy,
) -> None:
    referenced: Counter[str] = Counter()
    entries_by_authorization: dict[str, set[tuple[str, str]]] = {}
    for entry in entries:
        if entry["disposition"] != "delete_authorized":
            continue
        authorization_id = str(entry["deletion_authorization_id"])
        authorization = authorization_by_id.get(authorization_id)
        if authorization is None:
            raise RunsRetentionError(
                f"Missing deletion authorization: {authorization_id}"
            )
        referenced[authorization_id] += 1
        entries_by_authorization.setdefault(authorization_id, set()).add(
            _target_key(entry["target"], context="authorized entry")
        )
        purpose_class = str(entry["purpose_class"])
        if not policy.retention_classes[purpose_class].deletion_eligible:
            raise RunsRetentionError(
                f"Purpose class {purpose_class} is not deletion-eligible"
            )
        checksums = entry["checksums"]
        if checksums.get("source") is None or checksums.get("archive") is None:
            raise RunsRetentionError(
                "Deletion requires source and archive checksums"
            )
        if entry["restore"].get("status") != "verified":
            raise RunsRetentionError(
                "Deletion requires verified temporary restore"
            )
        if entry["scrub"].get("status") not in {"verified", "not_required"}:
            raise RunsRetentionError(
                "Deletion requires completed scrub review"
            )
        risks = entry["risk_labels"]
        if (
            policy.credential_review_trigger in risks
            and entry["credential_review"].get("status") != "complete"
        ):
            raise RunsRetentionError(
                "Deletion requires completed credential review"
            )
        authorized_at = _parse_timestamp(authorization["authorized_at"])
        retention = entry["retention"]
        expires_at = _parse_timestamp(retention["expires_at"])
        quarantine_until = _parse_timestamp(retention["quarantine_until"])
        if expires_at is None or quarantine_until is None:
            raise RunsRetentionError(
                "Deletion requires elapsed retention and quarantine dates"
            )
        if expires_at > authorized_at or quarantine_until > authorized_at:
            raise RunsRetentionError(
                "Deletion authorization predates retention/quarantine expiry"
            )

    if set(referenced) != set(authorization_by_id):
        raise RunsRetentionError(
            "Deletion authorizations must be used by exactly one index batch"
        )
    for authorization_id, authorization in authorization_by_id.items():
        authorized_targets = {
            _target_key(target, context="deletion authorization")
            for target in authorization["targets"]
        }
        if authorized_targets != entries_by_authorization[authorization_id]:
            raise RunsRetentionError(
                "Deletion authorization targets must exactly match entries"
            )
    if header.get("example") and referenced:
        raise RunsRetentionError("Example indexes cannot authorize deletion")


def _validate_index_inventory_coverage(
    *,
    header: Mapping[str, Any],
    entries: Mapping[tuple[str, str], Mapping[str, Any]],
    inventory: RunsInventory,
) -> None:
    if header.get("example"):
        raise RunsRetentionError(
            "Synthetic example cannot claim live inventory coverage"
        )
    if header.get("inventory_state_fingerprint") != inventory.summary.get(
        "state_fingerprint"
    ):
        raise RunsRetentionError("Index is stale for the current inventory")
    group_paths = {str(group["path"]) for group in inventory.groups}
    artifact_paths = {
        str(artifact["path"]) for artifact in inventory.artifacts
    }
    for kind, path in entries:
        known = group_paths if kind == "artifact_group" else artifact_paths
        if path not in known:
            raise RunsRetentionError(f"Index target is not in inventory: {path}")
    uncovered: list[str] = []
    for artifact in inventory.artifacts:
        artifact_key = ("artifact", str(artifact["path"]))
        group_key = ("artifact_group", str(artifact["parent_group"]))
        if artifact_key not in entries and group_key not in entries:
            uncovered.append(str(artifact["path"]))
    if uncovered:
        raise RunsRetentionError(
            f"Retained-run index does not cover {len(uncovered)} artifacts"
        )


def _target_key(target: Any, *, context: str) -> tuple[str, str]:
    if not isinstance(target, dict):
        raise RunsRetentionError(f"{context} target must be an object")
    _require_exact_keys(target, {"kind", "path"}, context=f"{context} target")
    kind = target.get("kind")
    if kind not in {"artifact_group", "artifact"}:
        raise RunsRetentionError(f"{context} has invalid target kind")
    path = _required_string(target, "path")
    pure = PurePosixPath(path)
    if (
        pure.is_absolute()
        or not pure.parts
        or pure.parts[0] != "runs"
        or ".." in pure.parts
        or any(char in path for char in "*?[]")
    ):
        raise RunsRetentionError(
            f"{context} target must be one exact runs-relative path"
        )
    return str(kind), path


def _required_object(
    payload: Mapping[str, Any],
    field: str,
) -> Mapping[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise RunsRetentionError(f"{field} must be an object")
    return value


def _required_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise RunsRetentionError(f"{field} must be a non-empty string")
    return value


def _required_string_list(
    payload: Mapping[str, Any],
    field: str,
) -> list[str]:
    value = payload.get(field)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
        or len(value) != len(set(value))
    ):
        raise RunsRetentionError(f"{field} must be a unique string list")
    return value


def _require_exact_keys(
    payload: Mapping[str, Any],
    required: set[str],
    *,
    context: str,
) -> None:
    keys = set(payload)
    if keys != required:
        missing = sorted(required - keys)
        unknown = sorted(keys - required)
        raise RunsRetentionError(
            f"{context} fields drift; missing={missing}, unknown={unknown}"
        )


def _optional_nonnegative_int(value: Any, *, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RunsRetentionError(f"{field} must be null or non-negative integer")
    return value


def _sha256(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RunsRetentionError(f"{field} must be lowercase SHA-256")
    return value


def _nullable_sha256(payload: Mapping[str, Any], field: str) -> str | None:
    if payload.get(field) is None:
        return None
    return _sha256(payload, field)


def _timestamp(
    payload: Mapping[str, Any],
    field: str,
    *,
    nullable: bool,
) -> datetime | None:
    value = payload.get(field)
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise RunsRetentionError(f"{field} must be an ISO-8601 timestamp")
    parsed = _parse_timestamp(value)
    if parsed is None:
        raise RunsRetentionError(f"{field} must not be null")
    return parsed


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RunsRetentionError("Timestamp must be a non-empty string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RunsRetentionError(f"Invalid ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise RunsRetentionError("Timestamps must include a timezone")
    return parsed


def _nullable_local_reference(
    payload: Mapping[str, Any],
    field: str,
) -> None:
    value = payload.get(field)
    if value is None:
        return
    if (
        not isinstance(value, str)
        or not value
        or "://" in value
        or any(char in value for char in "*?[]")
    ):
        raise RunsRetentionError(f"{field} must be one local reference")


def _load_inventory(root: Path) -> RunsInventory:
    return load_and_validate_inventory(
        summary_path=root / DEFAULT_SUMMARY_PATH,
        inventory_path=root / DEFAULT_INVENTORY_PATH,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("validate-policy", "validate-index", "verify-coverage"),
    )
    parser.add_argument("--repo-root", type=Path, default=project_root())
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument(
        "--index-schema",
        type=Path,
        default=DEFAULT_INDEX_SCHEMA_PATH,
    )
    parser.add_argument("--index", type=Path, default=DEFAULT_EXAMPLE_INDEX_PATH)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = args.repo_root.resolve()

    def rooted(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    try:
        policy = load_retention_policy(rooted(args.policy))
        validate_index_schema_asset(rooted(args.index_schema))
        if args.command == "validate-policy":
            print(
                f"runs-retention: valid policy {policy.policy_id} with "
                f"{len(policy.retention_classes)} classes"
            )
        elif args.command == "validate-index":
            index = load_and_validate_index(
                rooted(args.index),
                policy=policy,
            )
            print(
                f"runs-retention: valid index with {len(index.entries)} "
                f"entries and {len(index.deletion_authorizations)} "
                f"deletion authorizations"
            )
        else:
            coverage = verify_tracked_coverage(
                policy=policy,
                inventory=_load_inventory(root),
                coverage_path=rooted(args.coverage),
            )
            print(
                f"runs-retention: coverage matches "
                f"{coverage['classified_group_count']} groups; "
                f"delete_authorized=0"
            )
    except (OSError, RunsRetentionError) as exc:
        print(f"runs-retention: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
