"""Mainline checks for the installed legacy-study read-only archive."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from pycodeagent.dev.legacy_study_boundary import (
    ARCHIVE_MANIFEST_SCHEMA,
    BOUNDARY_SCHEMA,
    DEFAULT_BOUNDARY_PATH,
    LegacyStudyBoundaryError,
    load_boundary,
    verify_boundary,
)


pytestmark = pytest.mark.mainline

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY_PATH = ROOT / DEFAULT_BOUNDARY_PATH
MANIFEST_PATH = ROOT / "archive/legacy-study-v1/archive_manifest.json"


def _payload() -> dict:
    return json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _write_boundary(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_boundary_verifies_complete_installed_archive() -> None:
    payload = load_boundary(BOUNDARY_PATH)
    result = verify_boundary(ROOT)

    assert payload["schema"] == BOUNDARY_SCHEMA
    assert payload["goal_id"] == "RC-025"
    assert result.implementation_state == "archived"
    assert result.asset_count == 36
    assert result.archive_asset_count == 29
    assert result.archive_manifest_entry_count == 29
    assert result.frozen_edge_count == 65
    assert result.edge_count == 0
    assert result.active_reverse_dependency_count == 0
    assert payload["post_archive_edges"] == []


def test_every_asset_has_one_owner_disposition_and_destination() -> None:
    assets = _payload()["assets"]
    by_disposition: dict[str, list[dict]] = {}
    for asset in assets:
        by_disposition.setdefault(asset["disposition"], []).append(asset)
        assert asset["owner"]
        assert asset["reason"]
        if asset["disposition"].startswith("archive_"):
            assert not (ROOT / asset["path"]).exists()
            assert (ROOT / asset["archive_path"]).is_file()
        elif asset["disposition"] == "retired_rc057":
            assert not (ROOT / asset["path"]).exists()
        else:
            assert (ROOT / asset["path"]).is_file()

    assert {key: len(value) for key, value in by_disposition.items()} == {
        "archive_rc026": 22,
        "archive_rc027": 7,
        "edit_rc026": 3,
        "edit_rc027": 3,
        "retired_rc057": 1,
    }


def test_archive_manifest_has_exact_coverage_and_checksums() -> None:
    manifest = _manifest()
    assets = {
        asset["path"]: asset
        for asset in _payload()["assets"]
        if asset["disposition"].startswith("archive_")
    }

    assert manifest["schema"] == ARCHIVE_MANIFEST_SCHEMA
    assert manifest["archive_id"] == "legacy-study-readonly-v1"
    assert manifest["execution_status"] == "historical_reference_only"
    assert manifest["source_count"] == 29
    assert len(manifest["entries"]) == 29
    assert {entry["source"] for entry in manifest["entries"]} == set(assets)

    for entry in manifest["entries"]:
        asset = assets[entry["source"]]
        archive_path = ROOT / entry["archive_path"]
        assert entry["archive_path"] == asset["archive_path"]
        assert entry["implementation_goal"] == asset["implementation_goal"]
        assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == (
            entry["sha256"]
        )


def test_archive_is_outside_import_and_pytest_discovery_boundaries() -> None:
    pytest_config = (ROOT / "pytest.ini").read_text(encoding="utf-8")

    assert "\n    archive\n" in pytest_config
    assert not (ROOT / "archive/__init__.py").exists()
    assert not (ROOT / "archive/legacy-study-v1/__init__.py").exists()


def test_boundary_rejects_frozen_dependency_edge_drift(tmp_path: Path) -> None:
    payload = _payload()
    payload["edges"] = payload["edges"][:-1]
    boundary_path = tmp_path / "edge-drift.json"
    _write_boundary(boundary_path, payload)

    with pytest.raises(
        LegacyStudyBoundaryError,
        match="Historical dependency edges drift",
    ):
        verify_boundary(ROOT, boundary_path=boundary_path)


def test_boundary_rejects_a_stale_post_archive_dependency(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["post_archive_edges"] = [
        {
            "source": "pycodeagent/eval/tables.py",
            "target": "pycodeagent/eval/analysis.py",
            "kind": "python_import",
        }
    ]
    boundary_path = tmp_path / "stale-post-archive-edge.json"
    _write_boundary(boundary_path, payload)

    with pytest.raises(
        LegacyStudyBoundaryError,
        match="post-archive dependency edges drift",
    ):
        verify_boundary(ROOT, boundary_path=boundary_path)


def test_boundary_rejects_archive_destination_or_protection_drift(
    tmp_path: Path,
) -> None:
    wrong_destination = _payload()
    wrong_destination["assets"][0]["archive_path"] = (
        "archive/legacy-study-v1/colliding.py"
    )
    destination_path = tmp_path / "wrong-destination.json"
    _write_boundary(destination_path, wrong_destination)
    with pytest.raises(LegacyStudyBoundaryError, match="preserve source path"):
        verify_boundary(ROOT, boundary_path=destination_path)

    protected_overlap = copy.deepcopy(_payload())
    protected_overlap["protected_shared_dependencies"][0]["path"] = (
        protected_overlap["assets"][0]["path"]
    )
    protected_path = tmp_path / "protected-overlap.json"
    _write_boundary(protected_path, protected_overlap)
    with pytest.raises(LegacyStudyBoundaryError, match="overlaps"):
        verify_boundary(ROOT, boundary_path=protected_path)
