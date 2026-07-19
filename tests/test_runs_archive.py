"""Non-destructive archive and scrub tests for RC-054."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from pycodeagent.dev.runs_archive import (
    RUNS_ARCHIVE_CLASSIFICATION_SCHEMA,
    RunsArchiveError,
    archive_runs,
    load_archive_classification,
    verify_archive,
)
from pycodeagent.dev.runs_inventory import (
    load_and_validate_inventory,
    scan_runs,
    write_inventory,
)
from pycodeagent.dev.runs_retention import (
    load_and_validate_index,
    load_retention_policy,
)


pytestmark = pytest.mark.mainline

ROOT = Path(__file__).resolve().parents[1]
EXECUTION_TIME = "2030-07-18T00:00:00Z"


def _snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    result: dict[str, tuple[int, int, str]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        payload = path.read_bytes()
        file_stat = path.stat()
        result[path.relative_to(root).as_posix()] = (
            file_stat.st_size,
            file_stat.st_mtime_ns,
            hashlib.sha256(payload).hexdigest(),
        )
    return result


def _prepare_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    run = repo / "runs/test_campaign/run-a"
    payloads = run / "payloads"
    workspace = run / "workspace"
    payloads.mkdir(parents=True)
    workspace.mkdir()
    (run / "trajectory.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "run-a",
                "task_id": "task-a",
                "tool_profile_id": "native-codex",
                "tool_stack_kind": "native-codex",
                "status": "completed",
                "authorization": "Bearer SUPER_SECRET_TOKEN",
                "operator": "alice@example.com",
                "workspace": "/home/alice/project",
            }
        ),
        encoding="utf-8",
    )
    (payloads / "000001.json").write_text(
        '{"api_key":"DO_NOT_KEEP","already":{"redacted":true}}\n',
        encoding="utf-8",
    )
    (workspace / "code.py").write_text(
        'path = "/Users/alice/project"\n'
        'token = "access_token=SECOND_SECRET"\n',
        encoding="utf-8",
    )
    cache = workspace / "__pycache__"
    cache.mkdir()
    (cache / "code.cpython-313.pyc").write_bytes(b"\x00\xffbinary-cache")
    references = repo / "references"
    references.mkdir()
    shutil.copyfile(
        ROOT / "references/runs-retention-policy.json",
        references / "runs-retention-policy.json",
    )
    shutil.copyfile(
        ROOT / "references/retained-run-index.schema.json",
        references / "retained-run-index.schema.json",
    )
    inventory = scan_runs(repo)
    write_inventory(
        inventory,
        summary_path=references / "runs-inventory.summary.json",
        inventory_path=references / "runs-inventory.jsonl",
    )
    classification = {
        "schema": RUNS_ARCHIVE_CLASSIFICATION_SCHEMA,
        "classification_id": "synthetic-owner-classification",
        "policy_id": "rc053-conservative-local-manual-v1",
        "inventory_state_fingerprint": inventory.summary[
            "state_fingerprint"
        ],
        "archive_id": "synthetic-rc054",
        "storage_location_ref": "local-archive:synthetic-rc054",
        "delete_authorized_count": 0,
        "campaigns": [
            {
                "campaign": "test_campaign",
                "purpose_class": "debug",
                "owner": "test-maintainers",
                "provider_payload_override": False,
            }
        ],
    }
    (references / "runs-archive-classification.json").write_text(
        json.dumps(classification, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return repo, tmp_path / "local-archive"


def test_archive_scrubs_derivative_preserves_source_and_verifies_restore(
    tmp_path: Path,
) -> None:
    repo, destination = _prepare_repo(tmp_path)
    before = _snapshot(repo / "runs")

    result = archive_runs(
        repo,
        destination=destination,
        execution_time=EXECUTION_TIME,
    )

    assert result.artifact_count == 4
    assert result.artifact_group_count == 4
    assert result.changed_file_count == 4
    assert _snapshot(repo / "runs") == before
    assert destination.is_dir()

    archived_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((destination / "payload/runs").rglob("*"))
        if path.is_file()
    )
    for secret in (
        "SUPER_SECRET_TOKEN",
        "DO_NOT_KEEP",
        "SECOND_SECRET",
        "alice@example.com",
        "/home/alice",
        "/Users/alice",
    ):
        assert secret not in archived_text
    assert "<redacted>" in archived_text
    assert "<redacted-email>" in archived_text
    assert "$HOME" in archived_text
    assert "compiled_cache_omitted" in archived_text

    policy = load_retention_policy(
        repo / "references/runs-retention-policy.json"
    )
    index = load_and_validate_index(
        repo / "references/retained-runs.index.jsonl",
        policy=policy,
        inventory=scan_runs(repo),
    )
    assert len(index.entries) == 4
    assert index.deletion_authorizations == ()
    assert all(entry["purpose_class"] == "debug" for entry in index.entries)
    assert all(
        entry["disposition"] != "delete_authorized"
        for entry in index.entries
    )
    report = verify_archive(repo, destination=destination)
    assert report["restore_status"] == "verified"
    assert report["restore_verified_artifact_count"] == 4
    assert report["delete_authorized_count"] == 0


def test_archive_rejects_existing_destination_and_source_symlink(
    tmp_path: Path,
) -> None:
    repo, destination = _prepare_repo(tmp_path)
    destination.mkdir()
    with pytest.raises(RunsArchiveError, match="already exists"):
        archive_runs(
            repo,
            destination=destination,
            execution_time=EXECUTION_TIME,
        )

    destination.rmdir()
    source = repo / "runs/test_campaign/run-a/workspace/link.py"
    source.symlink_to("code.py")
    inventory = scan_runs(repo)
    write_inventory(
        inventory,
        summary_path=repo / "references/runs-inventory.summary.json",
        inventory_path=repo / "references/runs-inventory.jsonl",
    )
    classification_path = repo / "references/runs-archive-classification.json"
    classification = json.loads(classification_path.read_text(encoding="utf-8"))
    classification["inventory_state_fingerprint"] = inventory.summary[
        "state_fingerprint"
    ]
    classification_path.write_text(
        json.dumps(classification, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RunsArchiveError, match="regular source files"):
        archive_runs(
            repo,
            destination=destination,
            execution_time=EXECUTION_TIME,
        )


def test_verify_detects_archive_drift(tmp_path: Path) -> None:
    repo, destination = _prepare_repo(tmp_path)
    archive_runs(
        repo,
        destination=destination,
        execution_time=EXECUTION_TIME,
    )
    archived = destination / "payload/runs/test_campaign/run-a/trajectory.json"
    archived.write_bytes(archived.read_bytes() + b"\n")

    with pytest.raises(RunsArchiveError, match="checksum drift"):
        verify_archive(repo, destination=destination)


def test_owner_classification_exactly_covers_current_inventory() -> None:
    policy = load_retention_policy(
        ROOT / "references/runs-retention-policy.json"
    )
    inventory = scan_runs(ROOT)
    classification = load_archive_classification(
        ROOT / "references/runs-archive-classification.json",
        policy=policy,
        inventory=inventory,
    )

    assert len(classification.campaigns) == 12
    assert classification.delete_authorized_count == 0
    assert classification.campaigns[
        "native_family_acceptance_final_v4"
    ].purpose_class == "unique_research_evidence"
    assert classification.campaigns[
        "real_provider_smoke"
    ].purpose_class == "debug"
    assert classification.campaigns[
        "native_family_acceptance_final_v3"
    ].purpose_class == "superseded"


def test_tracked_rc054_index_and_reports_close_current_inventory() -> None:
    policy = load_retention_policy(
        ROOT / "references/runs-retention-policy.json"
    )
    inventory = load_and_validate_inventory(
        summary_path=ROOT / "references/runs-inventory.summary.json",
        inventory_path=ROOT / "references/runs-inventory.jsonl",
    )
    index_path = ROOT / "references/retained-runs.index.jsonl"
    index = load_and_validate_index(
        index_path,
        policy=policy,
        inventory=inventory,
    )
    archive_report = json.loads(
        (ROOT / "references/runs-archive-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    scrub_report = json.loads(
        (ROOT / "references/runs-archive-scrub-report.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(index.entries) == len(inventory.groups) == 741
    assert index.deletion_authorizations == ()
    assert archive_report["artifact_count"] == len(inventory.artifacts) == 8855
    assert archive_report["artifact_group_count"] == 741
    assert archive_report["restore_verified_artifact_count"] == 8855
    assert archive_report["restore_verified_group_count"] == 741
    assert archive_report["contract_metadata_match_count"] == 8855
    assert archive_report["delete_authorized_count"] == 0
    assert archive_report["source_preserved"] is True
    assert archive_report["inventory_state_fingerprint"] == (
        inventory.summary["state_fingerprint"]
    )
    assert hashlib.sha256(index_path.read_bytes()).hexdigest() == (
        archive_report["retained_index_sha256"]
    )
    assert scrub_report["scanned_file_count"] == 8855
    assert scrub_report["source_preserved"] is True
    assert scrub_report["post_scrub_idempotency_failure_count"] == 0
    assert scrub_report["replacement_counts"] == {
        "absolute_user_path": 2760,
        "compiled_cache_omitted": 261,
    }
    assert all(
        entry["disposition"] != "delete_authorized"
        for entry in index.entries
    )
    serialized_reports = json.dumps(
        [archive_report, scrub_report],
        sort_keys=True,
    )
    for forbidden in (
        "secret_value",
        "payload_text",
        "tool_arguments",
        "tool_results",
    ):
        assert forbidden not in serialized_reports
