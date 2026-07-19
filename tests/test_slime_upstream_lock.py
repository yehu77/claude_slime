"""Mainline provenance tests for the vendored slime upstream baseline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pycodeagent.dev.codex_reference import (
    TREE_DIGEST_ALGORITHM,
    digest_reference_tree,
)
from pycodeagent.dev.slime_vendor import (
    DEFAULT_LOCK_PATH,
    SLIME_UPSTREAM_LOCK_SCHEMA,
    load_slime_upstream_lock,
    verify_slime_upstream_projection,
)


pytestmark = pytest.mark.mainline

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BASELINE_REPORT_PATH = Path("references/slime-vendor-baseline-report.json")
_EXPECTED_OVERLAY_CANDIDATES = {
    "VENDORING.md",
    "examples/pycodeagent_offline/README.md",
    "examples/pycodeagent_offline/convert_qwen3_0p6b_to_torch_dist.sh",
    "examples/pycodeagent_offline/run_qwen3_0p6b_native_transformed_rl_smoke.sh",
    "examples/pycodeagent_offline/run_qwen3_0p6b_native_transformed_smoke.sh",
    "examples/pycodeagent_offline/run_qwen3_0p6b_offline.sh",
    "examples/pycodeagent_offline/run_qwen3_4b_offline.sh",
    "slime/rollout/pycodeagent_native_rl.py",
    "slime/rollout/pycodeagent_offline.py",
}


def _write_test_lock(repo_root: Path, upstream_tree: Path) -> None:
    overlay_paths = ["local_bridge.py"]
    ignored_globs = ["**/__pycache__/*.pyc"]
    expected_symlinks = {".agents/skills": "../.claude/skills"}
    digest = digest_reference_tree(
        upstream_tree,
        expected_symlinks=expected_symlinks,
        excluded_paths=overlay_paths,
        excluded_globs=ignored_globs,
    )
    license_sha256 = hashlib.sha256(
        (upstream_tree / "LICENSE").read_bytes()
    ).hexdigest()
    lock_path = repo_root / DEFAULT_LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
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
                    "sha256": license_sha256,
                },
                "upstream_tree": {
                    "digest_algorithm": TREE_DIGEST_ALGORITHM,
                    "tree_sha256": digest.sha256,
                    "entry_count": digest.entry_count,
                    "expected_symlinks": expected_symlinks,
                },
                "local_projection": {
                    "overlay_candidate_paths": overlay_paths,
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


def _make_test_vendor(repo_root: Path) -> Path:
    vendor = repo_root / "slime-main"
    (vendor / ".agents").mkdir(parents=True)
    (vendor / "src").mkdir()
    (vendor / "cache/__pycache__").mkdir(parents=True)
    (vendor / ".agents/skills").write_text(
        "../.claude/skills",
        encoding="utf-8",
    )
    (vendor / "LICENSE").write_text("Apache test license\n", encoding="utf-8")
    (vendor / "src/runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    (vendor / "local_bridge.py").write_text("LOCAL = 1\n", encoding="utf-8")
    (vendor / "cache/__pycache__/ignored.pyc").write_bytes(b"cache")
    return vendor


def test_tracked_slime_lock_freezes_official_commit_and_license() -> None:
    lock = load_slime_upstream_lock(_PROJECT_ROOT / DEFAULT_LOCK_PATH)

    assert lock.vendor_id == "thudm-slime"
    assert lock.vendor_path == "slime-main"
    assert lock.repository_url == "https://github.com/THUDM/slime.git"
    assert lock.commit == "16924b697e86adab96eded3a3d0bf6098a943bb4"
    assert lock.acquired_at == "2026-06-03T16:36:43+08:00"
    assert (
        lock.acquisition_evidence_commit
        == "c92d21a72dd86dae8838fffa4ec6a7c4d8e8d5f2"
    )
    assert lock.license_spdx == "Apache-2.0"
    assert lock.entry_count == 465
    assert set(lock.overlay_candidate_paths) == _EXPECTED_OVERLAY_CANDIDATES


def test_current_vendor_upstream_projection_matches_lock() -> None:
    report = verify_slime_upstream_projection(_PROJECT_ROOT)

    assert report.status == "ok"
    assert report.actual_sha256 == report.expected_sha256
    assert report.actual_entry_count == 465
    assert report.portable_symlink_placeholders == (".agents/skills",)
    assert "remain governed by RC-048" in report.message


def test_baseline_report_has_no_unexplained_or_modified_upstream_paths() -> None:
    report = json.loads(
        (_PROJECT_ROOT / _BASELINE_REPORT_PATH).read_text(encoding="utf-8")
    )
    lock = load_slime_upstream_lock(_PROJECT_ROOT / DEFAULT_LOCK_PATH)
    classification = report["classification"]

    assert report["source_lock"] == DEFAULT_LOCK_PATH.as_posix()
    assert report["comparison"]["upstream_commit"] == lock.commit
    assert report["comparison"]["upstream_tree_sha256"] == lock.tree_sha256
    assert report["comparison"]["tracked_vendor_entry_count"] == 474
    assert classification["unchanged_upstream_entries"] == lock.entry_count
    assert classification["modified_upstream_paths"] == []
    assert classification["missing_upstream_paths"] == []
    assert classification["unknown_source_paths"] == []
    assert set(classification["overlay_candidate_paths"]) == set(
        lock.overlay_candidate_paths
    )
    assert report["boundary"]["overlay_candidates_are_final_manifest"] is True
    assert (
        report["boundary"]["overlay_manifest"]
        == "references/slime-overlay.manifest.json"
    )


def test_every_overlay_candidate_exists_and_vendor_runbook_names_both_bridges() -> None:
    lock = load_slime_upstream_lock(_PROJECT_ROOT / DEFAULT_LOCK_PATH)
    vendor_root = _PROJECT_ROOT / lock.vendor_path
    runbook = (vendor_root / "VENDORING.md").read_text(encoding="utf-8")

    assert all((vendor_root / path).is_file() for path in lock.overlay_candidate_paths)
    assert "slime/rollout/pycodeagent_offline.py" in runbook
    assert "slime/rollout/pycodeagent_native_rl.py" in runbook
    assert lock.commit in runbook
    assert "pycodeagent.dev.slime_vendor verify" in runbook
    assert "RC-048" in runbook


def test_projection_ignores_declared_overlay_and_cache_but_detects_upstream_drift(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    vendor = _make_test_vendor(repo_root)
    _write_test_lock(repo_root, vendor)

    assert verify_slime_upstream_projection(repo_root).status == "ok"
    (vendor / "local_bridge.py").write_text("LOCAL = 2\n", encoding="utf-8")
    (vendor / "cache/__pycache__/ignored.pyc").write_bytes(b"changed cache")
    assert verify_slime_upstream_projection(repo_root).status == "ok"

    (vendor / "src/runtime.py").write_text("VALUE = 2\n", encoding="utf-8")
    drift = verify_slime_upstream_projection(repo_root)
    assert drift.status == "mismatch"
    assert drift.actual_sha256 != drift.expected_sha256
    assert "does not match locked commit" in drift.message
