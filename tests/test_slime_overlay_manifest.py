"""Mainline reconstruction and drift tests for the slime vendor overlay."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import tarfile
from pathlib import Path

import pytest

from pycodeagent.dev.codex_reference import (
    TREE_DIGEST_ALGORITHM,
    digest_reference_tree,
)
from pycodeagent.dev.slime_vendor import (
    DEFAULT_LOCK_PATH,
    DEFAULT_OVERLAY_MANIFEST_PATH,
    SLIME_OVERLAY_MANIFEST_SCHEMA,
    SLIME_UPSTREAM_LOCK_SCHEMA,
    SlimeVendorError,
    load_slime_overlay_manifest,
    rebuild_slime_vendor,
    verify_slime_vendor,
)


pytestmark = pytest.mark.mainline

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _copy_current_contract(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    shutil.copytree(
        _PROJECT_ROOT / "slime-main",
        repo_root / "slime-main",
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (repo_root / "references").mkdir(parents=True)
    shutil.copyfile(
        _PROJECT_ROOT / DEFAULT_LOCK_PATH,
        repo_root / DEFAULT_LOCK_PATH,
    )
    shutil.copyfile(
        _PROJECT_ROOT / DEFAULT_OVERLAY_MANIFEST_PATH,
        repo_root / DEFAULT_OVERLAY_MANIFEST_PATH,
    )
    return repo_root


def _write_synthetic_contract(repo_root: Path, pristine: Path) -> None:
    vendor = repo_root / "slime-main"
    overlay_path = "local_bridge.py"
    overlay_source = vendor / overlay_path
    overlay_source.write_text("LOCAL = 1\n", encoding="utf-8")
    overlay_source.chmod(0o644)
    expected_symlinks = {".agents/skills": "../.claude/skills"}
    ignored_globs = ["**/__pycache__/*.pyc"]
    pristine_digest = digest_reference_tree(
        pristine,
        expected_symlinks=expected_symlinks,
    )
    final_digest = digest_reference_tree(
        vendor,
        expected_symlinks=expected_symlinks,
        excluded_globs=ignored_globs,
    )
    references = repo_root / "references"
    references.mkdir(parents=True)
    (references / "slime-upstream.lock.json").write_text(
        json.dumps(
            {
                "schema": SLIME_UPSTREAM_LOCK_SCHEMA,
                "vendor_id": "test-slime",
                "vendor_path": "slime-main",
                "purpose": "vendored_upstream_baseline",
                "source": {
                    "repository_url": "https://example.invalid/slime.git",
                    "commit": "a" * 40,
                    "archive_url": "https://example.invalid/archive.tar.gz",
                },
                "acquisition": {
                    "acquired_at": "2026-01-01T00:00:00Z",
                    "repository_import_commit": "b" * 40,
                },
                "license": {
                    "spdx": "Apache-2.0",
                    "vendor_path": "slime-main/LICENSE",
                    "sha256": hashlib.sha256(
                        (pristine / "LICENSE").read_bytes()
                    ).hexdigest(),
                },
                "upstream_tree": {
                    "digest_algorithm": TREE_DIGEST_ALGORITHM,
                    "tree_sha256": pristine_digest.sha256,
                    "entry_count": pristine_digest.entry_count,
                    "expected_symlinks": expected_symlinks,
                },
                "local_projection": {
                    "overlay_candidate_paths": [overlay_path],
                    "ignored_ephemeral_globs": ignored_globs,
                },
                "evidence": {
                    "baseline_report": (
                        "references/slime-vendor-baseline-report.json"
                    )
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    overlay_bytes = overlay_source.read_bytes()
    (references / "slime-overlay.manifest.json").write_text(
        json.dumps(
            {
                "schema": SLIME_OVERLAY_MANIFEST_SCHEMA,
                "vendor_id": "test-slime",
                "purpose": "repo_owned_slime_integration_overlay",
                "upstream_lock": "references/slime-upstream.lock.json",
                "upstream_commit": "a" * 40,
                "vendor_path": "slime-main",
                "files": [
                    {
                        "path": overlay_path,
                        "operation": "add",
                        "owner": "test-maintainers",
                        "reason": "Exercise deterministic overlay reconstruction.",
                        "source_path": f"slime-main/{overlay_path}",
                        "mode": "0644",
                        "size": len(overlay_bytes),
                        "sha256": hashlib.sha256(overlay_bytes).hexdigest(),
                    }
                ],
                "expected_tree": {
                    "digest_algorithm": TREE_DIGEST_ALGORITHM,
                    "tree_sha256": final_digest.sha256,
                    "entry_count": final_digest.entry_count,
                    "ignored_ephemeral_globs": ignored_globs,
                },
                "rebuild": {
                    "command": (
                        "python -B -m pycodeagent.dev.slime_vendor rebuild"
                    )
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _make_synthetic_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    pristine = tmp_path / "pristine"
    (pristine / ".agents").mkdir(parents=True)
    (pristine / ".claude/skills").mkdir(parents=True)
    (pristine / "src").mkdir()
    (pristine / ".agents/skills").symlink_to("../.claude/skills")
    (pristine / ".claude/skills/example.md").write_text(
        "skill\n",
        encoding="utf-8",
    )
    (pristine / "LICENSE").write_text("Apache test license\n", encoding="utf-8")
    (pristine / "src/runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    shutil.copytree(pristine, repo_root / "slime-main", symlinks=True)
    _write_synthetic_contract(repo_root, pristine)

    archive_path = tmp_path / "upstream.tar.gz"
    with tarfile.open(archive_path, "w:gz", dereference=False) as archive:
        archive.add(pristine, arcname="slime-test")
    return repo_root, archive_path


def test_manifest_classifies_every_overlay_with_owner_reason_mode_and_checksum() -> None:
    manifest = load_slime_overlay_manifest(
        _PROJECT_ROOT / DEFAULT_OVERLAY_MANIFEST_PATH
    )

    assert manifest.vendor_id == "thudm-slime"
    assert manifest.upstream_commit == "16924b697e86adab96eded3a3d0bf6098a943bb4"
    assert len(manifest.files) == 9
    assert manifest.entry_count == 474
    assert manifest.tree_sha256 == (
        "9849ce4d920ee0b39f0a741ec21af66393deccb179fca8cf54b160a17011cdcd"
    )
    for overlay in manifest.files:
        assert overlay.operation == "add"
        assert overlay.owner
        assert overlay.reason
        assert overlay.mode == 0o644
        source = _PROJECT_ROOT / overlay.source_path
        assert source.is_file()
        assert len(source.read_bytes()) == overlay.size
        assert hashlib.sha256(source.read_bytes()).hexdigest() == overlay.sha256


def test_current_vendor_matches_complete_overlay_contract() -> None:
    report = verify_slime_vendor(_PROJECT_ROOT)

    assert report.status == "ok"
    assert report.upstream_status == "ok"
    assert report.overlay_file_count == 9
    assert report.actual_sha256 == report.expected_sha256
    assert report.actual_entry_count == report.expected_entry_count == 474
    assert report.issues == ()


def test_verifier_detects_overlay_mode_and_unknown_file_drift(
    tmp_path: Path,
) -> None:
    repo_root = _copy_current_contract(tmp_path)
    bridge = repo_root / "slime-main/slime/rollout/pycodeagent_offline.py"
    original_bridge = bridge.read_bytes()

    bridge.write_bytes(original_bridge + b"\n# drift\n")
    overlay_drift = verify_slime_vendor(repo_root)
    assert overlay_drift.status == "mismatch"
    assert any("overlay checksum drift" in issue for issue in overlay_drift.issues)

    bridge.write_bytes(original_bridge)
    unknown = repo_root / "slime-main/unknown-source.txt"
    unknown.write_text("unknown\n", encoding="utf-8")
    unknown_drift = verify_slime_vendor(repo_root)
    assert unknown_drift.status == "mismatch"
    assert any("unknown" in issue for issue in unknown_drift.issues)

    unknown.unlink()
    vendoring = repo_root / "slime-main/VENDORING.md"
    vendoring.chmod(0o755)
    mode_drift = verify_slime_vendor(repo_root)
    assert mode_drift.status == "mismatch"
    assert any("overlay mode drift" in issue for issue in mode_drift.issues)


def test_rebuild_applies_verified_overlay_and_refuses_existing_destination(
    tmp_path: Path,
) -> None:
    repo_root, archive_path = _make_synthetic_repo(tmp_path)
    destination = tmp_path / "rebuilt"

    report = rebuild_slime_vendor(
        repo_root,
        archive_path=archive_path,
        destination=destination,
    )

    assert report.status == "ok"
    assert report.destination == destination
    assert report.entry_count == 5
    assert (destination / "local_bridge.py").read_text(encoding="utf-8") == (
        "LOCAL = 1\n"
    )
    assert stat.S_IMODE((destination / "local_bridge.py").stat().st_mode) == 0o644
    assert digest_reference_tree(
        destination,
        expected_symlinks={".agents/skills": "../.claude/skills"},
    ).sha256 == report.tree_sha256

    with pytest.raises(SlimeVendorError, match="Refusing to overwrite"):
        rebuild_slime_vendor(
            repo_root,
            archive_path=archive_path,
            destination=destination,
        )


def test_rebuild_rejects_drifted_overlay_source_before_touching_destination(
    tmp_path: Path,
) -> None:
    repo_root, archive_path = _make_synthetic_repo(tmp_path)
    destination = tmp_path / "must-not-exist"
    (repo_root / "slime-main/local_bridge.py").write_text(
        "LOCAL = 2\n",
        encoding="utf-8",
    )

    with pytest.raises(SlimeVendorError, match="drifted overlay sources"):
        rebuild_slime_vendor(
            repo_root,
            archive_path=archive_path,
            destination=destination,
        )
    assert not destination.exists()
