"""Mainline contract tests for conservative local runs retention."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from pycodeagent.dev.runs_inventory import (
    RUNS_INVENTORY_SCHEMA,
    RunsInventory,
    load_and_validate_inventory,
)
from pycodeagent.dev.runs_retention import (
    DEFAULT_COVERAGE_PATH,
    DEFAULT_EXAMPLE_INDEX_PATH,
    DEFAULT_INDEX_SCHEMA_PATH,
    DEFAULT_POLICY_PATH,
    RETAINED_RUN_INDEX_RECORD_SCHEMA,
    RUNS_RETENTION_COVERAGE_SCHEMA,
    RUNS_RETENTION_POLICY_SCHEMA,
    RunsRetentionError,
    build_coverage_report,
    classify_inventory_group,
    load_and_validate_index,
    load_retention_policy,
    validate_index_schema_asset,
    verify_tracked_coverage,
)


pytestmark = pytest.mark.mainline

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_SUMMARY = ROOT / "references/runs-inventory.summary.json"
INVENTORY_RECORDS = ROOT / "references/runs-inventory.jsonl"


def _policy():
    return load_retention_policy(ROOT / DEFAULT_POLICY_PATH)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                record,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


def _header(*, fingerprint: str = "c" * 64) -> dict[str, Any]:
    return {
        "schema": RETAINED_RUN_INDEX_RECORD_SCHEMA,
        "record_type": "index",
        "index_id": "synthetic-live-index",
        "policy_id": "rc053-conservative-local-manual-v1",
        "inventory_schema": RUNS_INVENTORY_SCHEMA,
        "inventory_state_fingerprint": fingerprint,
        "example": False,
    }


def _entry(
    *,
    kind: str = "artifact",
    path: str = "runs/example/failed/trace.jsonl",
    purpose_class: str = "failed",
    disposition: str = "delete_authorized",
    authorization_id: str | None = "delete-batch-1",
) -> dict[str, Any]:
    return {
        "schema": RETAINED_RUN_INDEX_RECORD_SCHEMA,
        "record_type": "entry",
        "target": {"kind": kind, "path": path},
        "purpose_class": purpose_class,
        "sensitivity": "restricted",
        "risk_labels": [
            "potential_authorization_material",
            "raw_trace_content",
        ],
        "owner": "repository-governance",
        "retention": {
            "starts_at": "2025-10-01T00:00:00Z",
            "expires_at": "2026-01-01T00:00:00Z",
            "quarantine_until": "2026-02-01T00:00:00Z",
        },
        "disposition": disposition,
        "storage": {
            "kind": "local_filesystem_outside_git_worktree",
            "location_ref": "local-archive:failed-run",
        },
        "checksums": {
            "algorithm": "sha256",
            "source": "a" * 64,
            "archive": "b" * 64,
        },
        "scrub": {
            "status": "verified",
            "report_ref": "local-reports/scrub.json",
            "source_preserved": True,
        },
        "restore": {
            "status": "verified",
            "verified_at": "2026-02-02T00:00:00Z",
        },
        "credential_review": {
            "status": "complete",
            "reviewed_at": "2026-02-02T00:00:00Z",
        },
        "deletion_authorization_id": authorization_id,
    }


def _authorization(
    *,
    kind: str = "artifact",
    path: str = "runs/example/failed/trace.jsonl",
) -> dict[str, Any]:
    return {
        "schema": RETAINED_RUN_INDEX_RECORD_SCHEMA,
        "record_type": "deletion_authorization",
        "authorization_id": "delete-batch-1",
        "authorized_by": "repository_owner",
        "authorized_at": "2026-03-01T00:00:00Z",
        "inventory_state_fingerprint": "c" * 64,
        "targets": [{"kind": kind, "path": path}],
        "preconditions": {
            "retention_elapsed": True,
            "quarantine_elapsed": True,
            "backup_checksum_verified": True,
            "temporary_restore_verified": True,
            "scrub_or_sensitivity_review_complete": True,
        },
    }


def _valid_deletion_records() -> list[dict[str, Any]]:
    return [_header(), _entry(), _authorization()]


def test_policy_locks_conservative_local_manual_defaults() -> None:
    policy = _policy()

    assert policy.policy_id == "rc053-conservative-local-manual-v1"
    assert policy.payload["schema"] == RUNS_RETENTION_POLICY_SCHEMA
    assert policy.payload["storage_policy"]["allowed_raw_location"] == (
        "local_filesystem_outside_git_worktree"
    )
    assert policy.payload["deletion_policy"]["mode"] == (
        "explicit_per_batch_user_authorization"
    )
    assert policy.payload["deletion_policy"]["wildcards_allowed"] is False
    assert policy.payload["retention_classes"] == [
        {
            "name": item.name,
            "minimum_retention_days": item.minimum_retention_days,
            "quarantine_days": item.quarantine_days,
            "expiry_disposition": item.expiry_disposition,
            "deletion_eligible": item.deletion_eligible,
        }
        for item in policy.retention_classes.values()
    ]


def test_example_index_and_schema_are_valid_and_non_destructive() -> None:
    policy = _policy()
    schema = validate_index_schema_asset(ROOT / DEFAULT_INDEX_SCHEMA_PATH)
    index = load_and_validate_index(
        ROOT / DEFAULT_EXAMPLE_INDEX_PATH,
        policy=policy,
    )

    assert schema["$defs"]["header"]["properties"]["schema"] == {
        "const": RETAINED_RUN_INDEX_RECORD_SCHEMA
    }
    assert index.header["example"] is True
    assert len(index.entries) == 2
    assert index.deletion_authorizations == ()
    assert all(
        entry["disposition"] != "delete_authorized"
        for entry in index.entries
    )
    serialized = (ROOT / DEFAULT_EXAMPLE_INDEX_PATH).read_text(encoding="utf-8")
    assert '"content":' not in serialized
    assert '"secret_value":' not in serialized
    assert '"tool_arguments":' not in serialized


def test_current_inventory_has_complete_unique_safe_coverage() -> None:
    policy = _policy()
    inventory = load_and_validate_inventory(
        summary_path=INVENTORY_SUMMARY,
        inventory_path=INVENTORY_RECORDS,
    )
    report = build_coverage_report(policy, inventory)

    assert report["schema"] == RUNS_RETENTION_COVERAGE_SCHEMA
    assert report["artifact_group_count"] == 741
    assert report["classified_group_count"] == 741
    assert report["classification_status"] == "complete"
    assert report["delete_authorized_count"] == 0
    assert sum(report["purpose_class_counts"].values()) == 741
    assert sum(report["sensitivity_counts"].values()) == 741
    assert sum(report["disposition_counts"].values()) == 741
    assert report["sensitivity_counts"] == {
        "internal": 8,
        "restricted": 733,
    }
    assert verify_tracked_coverage(
        policy=policy,
        inventory=inventory,
        coverage_path=ROOT / DEFAULT_COVERAGE_PATH,
    ) == report
    for group in inventory.groups:
        decision = classify_inventory_group(policy, group)
        assert decision.purpose_class
        assert decision.disposition != "delete_authorized"


def test_unknown_group_values_fail_closed_to_restricted_hold() -> None:
    decision = classify_inventory_group(
        _policy(),
        {
            "group_class": "future_unknown_group",
            "manifest_status": "future_unknown_status",
            "metadata": {"status": "future_unknown_terminal"},
            "sensitive_risk_labels": ["future_unknown_risk"],
        },
    )

    assert decision.purpose_class == "unclassified_hold"
    assert decision.sensitivity == "restricted"
    assert decision.disposition == "manual_review_hold"
    assert decision.rule_id == "conservative-fallback"


def test_policy_rejects_ambiguous_rules_and_external_storage(
    tmp_path: Path,
) -> None:
    payload = json.loads((ROOT / DEFAULT_POLICY_PATH).read_text(encoding="utf-8"))
    ambiguous = copy.deepcopy(payload)
    ambiguous["classification_rules"][1]["priority"] = 10
    ambiguous_path = tmp_path / "ambiguous-policy.json"
    _write_json(ambiguous_path, ambiguous)
    with pytest.raises(RunsRetentionError, match="Ambiguous"):
        load_retention_policy(ambiguous_path)

    external = copy.deepcopy(payload)
    external["storage_policy"]["allowed_raw_location"] = (
        "managed_cloud_storage"
    )
    external_path = tmp_path / "external-policy.json"
    _write_json(external_path, external)
    with pytest.raises(RunsRetentionError, match="remain local"):
        load_retention_policy(external_path)


def test_valid_explicit_deletion_batch_passes(tmp_path: Path) -> None:
    index_path = tmp_path / "valid-delete.jsonl"
    _write_jsonl(index_path, _valid_deletion_records())

    index = load_and_validate_index(index_path, policy=_policy())

    assert len(index.entries) == 1
    assert len(index.deletion_authorizations) == 1
    assert index.entries[0]["disposition"] == "delete_authorized"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_archive_checksum", "source and archive checksums"),
        ("restore_pending", "verified temporary restore"),
        ("credential_review_pending", "completed credential review"),
        ("precondition_false", "precondition"),
        ("authorization_too_early", "predates"),
        ("wildcard_target", "exact runs-relative path"),
    ],
)
def test_deletion_fails_closed_when_any_gate_is_missing(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    records = _valid_deletion_records()
    entry = records[1]
    authorization = records[2]
    if mutation == "missing_archive_checksum":
        entry["checksums"]["archive"] = None
    elif mutation == "restore_pending":
        entry["restore"] = {"status": "pending", "verified_at": None}
    elif mutation == "credential_review_pending":
        entry["credential_review"] = {
            "status": "pending",
            "reviewed_at": None,
        }
    elif mutation == "precondition_false":
        authorization["preconditions"]["temporary_restore_verified"] = False
    elif mutation == "authorization_too_early":
        authorization["authorized_at"] = "2026-01-15T00:00:00Z"
    else:
        entry["target"]["path"] = "runs/example/failed/*.jsonl"
        authorization["targets"][0]["path"] = (
            "runs/example/failed/*.jsonl"
        )
    index_path = tmp_path / f"{mutation}.jsonl"
    _write_jsonl(index_path, records)

    with pytest.raises(RunsRetentionError, match=message):
        load_and_validate_index(index_path, policy=_policy())


def test_permanent_class_and_external_storage_can_never_be_delete_entries(
    tmp_path: Path,
) -> None:
    permanent_records = _valid_deletion_records()
    permanent_records[1]["purpose_class"] = "contract_golden"
    permanent_path = tmp_path / "permanent-delete.jsonl"
    _write_jsonl(permanent_path, permanent_records)
    with pytest.raises(RunsRetentionError, match="Permanent class"):
        load_and_validate_index(permanent_path, policy=_policy())

    external_records = _valid_deletion_records()
    external_records[1]["storage"]["kind"] = "managed_cloud_storage"
    external_path = tmp_path / "external-delete.jsonl"
    _write_jsonl(external_path, external_records)
    with pytest.raises(RunsRetentionError, match="External"):
        load_and_validate_index(external_path, policy=_policy())


def test_group_entry_covers_artifacts_and_artifact_override_has_precedence(
    tmp_path: Path,
) -> None:
    fingerprint = "d" * 64
    inventory = RunsInventory(
        summary={
            "inventory_schema": RUNS_INVENTORY_SCHEMA,
            "state_fingerprint": fingerprint,
        },
        groups=(
            {
                "path": "runs/example/group",
                "group_class": "runtime_run",
                "manifest_status": "present_valid",
                "metadata": {"status": "completed"},
                "sensitive_risk_labels": [],
            },
        ),
        artifacts=(
            {
                "path": "runs/example/group/a.json",
                "parent_group": "runs/example/group",
            },
            {
                "path": "runs/example/group/b.json",
                "parent_group": "runs/example/group",
            },
        ),
    )
    group_entry = _entry(
        kind="artifact_group",
        path="runs/example/group",
        purpose_class="unclassified_hold",
        disposition="manual_review_hold",
        authorization_id=None,
    )
    group_entry["sensitivity"] = "internal"
    group_entry["risk_labels"] = []
    group_entry["retention"] = {
        "starts_at": "2026-07-18T00:00:00Z",
        "expires_at": None,
        "quarantine_until": None,
    }
    group_entry["storage"] = {"kind": "current_local", "location_ref": None}
    group_entry["credential_review"] = {
        "status": "not_required",
        "reviewed_at": None,
    }
    override = copy.deepcopy(group_entry)
    override["target"] = {
        "kind": "artifact",
        "path": "runs/example/group/b.json",
    }
    index_path = tmp_path / "covered-index.jsonl"
    _write_jsonl(
        index_path,
        [_header(fingerprint=fingerprint), group_entry, override],
    )

    index = load_and_validate_index(
        index_path,
        policy=_policy(),
        inventory=inventory,
    )
    assert len(index.entries) == 2

    duplicate_path = tmp_path / "duplicate-index.jsonl"
    _write_jsonl(
        duplicate_path,
        [_header(fingerprint=fingerprint), group_entry, group_entry],
    )
    with pytest.raises(RunsRetentionError, match="Duplicate"):
        load_and_validate_index(
            duplicate_path,
            policy=_policy(),
            inventory=inventory,
        )

    uncovered_path = tmp_path / "uncovered-index.jsonl"
    _write_jsonl(
        uncovered_path,
        [_header(fingerprint=fingerprint), override],
    )
    with pytest.raises(RunsRetentionError, match="does not cover"):
        load_and_validate_index(
            uncovered_path,
            policy=_policy(),
            inventory=inventory,
        )
