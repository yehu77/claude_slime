"""Mainline contract tests for the optional codex-rs reference tree."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from pycodeagent.dev.codex_reference import (
    DEFAULT_LOCK_PATH,
    REFERENCE_LOCK_SCHEMA,
    TREE_DIGEST_ALGORITHM,
    CodexReferenceError,
    bootstrap_reference,
    digest_reference_tree,
    load_reference_lock,
    verify_reference,
)


pytestmark = pytest.mark.mainline

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_lock(repo_root: Path, source_tree: Path) -> Path:
    expected_symlinks = {"vendor/LICENSE": "COPYING"}
    digest = digest_reference_tree(
        source_tree,
        expected_symlinks=expected_symlinks,
    )
    lock_path = repo_root / DEFAULT_LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "schema": REFERENCE_LOCK_SCHEMA,
                "reference_id": "test-codex-rs",
                "purpose": "implementation_reference_only",
                "runtime_dependency": False,
                "source": {
                    "repository_url": "https://example.invalid/codex.git",
                    "commit": "a" * 40,
                    "subtree": "codex-rs",
                    "archive_url": "https://example.invalid/archive.tar.gz",
                },
                "license": {
                    "spdx": "Apache-2.0",
                    "source_path": "LICENSE",
                    "url": "https://example.invalid/LICENSE",
                },
                "materialization": {
                    "path": "codex-rs",
                    "digest_algorithm": TREE_DIGEST_ALGORITHM,
                    "tree_sha256": digest.sha256,
                    "entry_count": digest.entry_count,
                    "expected_symlinks": expected_symlinks,
                },
                "bootstrap": {
                    "command": (
                        "python -B -m pycodeagent.dev.codex_reference bootstrap"
                    )
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return lock_path


def _make_source_tree(root: Path) -> Path:
    source = root / "source"
    (source / "core").mkdir(parents=True)
    (source / "vendor").mkdir()
    (source / "core/runtime.rs").write_text("pub fn run() {}\n", encoding="utf-8")
    (source / "vendor/COPYING").write_text("license\n", encoding="utf-8")
    (source / "vendor/LICENSE").symlink_to("COPYING")
    return source


def test_tracked_lock_is_immutable_reference_only_contract() -> None:
    lock = load_reference_lock(_PROJECT_ROOT / DEFAULT_LOCK_PATH)

    assert lock.reference_id == "openai-codex-rs"
    assert lock.repository_url == "https://github.com/openai/codex.git"
    assert lock.commit == "0beb5c7f32cf5459a51e3f6bc01e6509d7951854"
    assert lock.subtree == "codex-rs"
    assert lock.license_spdx == "Apache-2.0"
    assert lock.materialized_path == "codex-rs"
    assert lock.entry_count == 4477
    assert lock.expected_symlinks == {
        "vendor/bubblewrap/LICENSE": "COPYING"
    }


def test_repository_reference_is_optional_but_verified_when_present() -> None:
    report = verify_reference(_PROJECT_ROOT)

    assert report.status in {"missing", "ok"}
    if report.status == "missing":
        assert "runtime and tests do not depend on it" in report.message
        assert "bootstrap" in report.message
    else:
        assert report.actual_sha256 == report.expected_sha256
        assert report.actual_entry_count == report.expected_entry_count


def test_missing_reference_has_actionable_non_dependency_diagnostic(
    tmp_path: Path,
) -> None:
    source = _make_source_tree(tmp_path)
    repo_root = tmp_path / "repo"
    _write_lock(repo_root, source)

    report = verify_reference(repo_root)

    assert report.status == "missing"
    assert report.actual_sha256 is None
    assert "Optional codex-rs reference tree is absent" in report.message
    assert "runtime and tests do not depend on it" in report.message
    assert "pycodeagent.dev.codex_reference bootstrap" in report.message


def test_present_reference_accepts_declared_portable_symlink_placeholder(
    tmp_path: Path,
) -> None:
    source = _make_source_tree(tmp_path)
    repo_root = tmp_path / "repo"
    _write_lock(repo_root, source)
    materialized = repo_root / "codex-rs"
    materialized.mkdir(parents=True)
    (materialized / "core").mkdir()
    (materialized / "vendor").mkdir()
    (materialized / "core/runtime.rs").write_text(
        "pub fn run() {}\n",
        encoding="utf-8",
    )
    (materialized / "vendor/COPYING").write_text("license\n", encoding="utf-8")
    (materialized / "vendor/LICENSE").write_text("COPYING", encoding="utf-8")

    report = verify_reference(repo_root)

    assert report.status == "ok"
    assert report.portable_symlink_placeholders == ("vendor/LICENSE",)


def test_wrong_reference_version_reports_expected_and_actual_digest(
    tmp_path: Path,
) -> None:
    source = _make_source_tree(tmp_path)
    repo_root = tmp_path / "repo"
    _write_lock(repo_root, source)
    materialized = repo_root / "codex-rs"
    materialized.mkdir(parents=True)
    (materialized / "runtime.rs").write_text("drift\n", encoding="utf-8")

    report = verify_reference(repo_root)

    assert report.status == "mismatch"
    assert report.actual_sha256 != report.expected_sha256
    assert report.actual_entry_count != report.expected_entry_count
    assert "does not match the locked commit" in report.message
    assert "Move the local tree aside" in report.message


def test_bootstrap_extracts_only_locked_subtree_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    source = _make_source_tree(tmp_path)
    repo_root = tmp_path / "repo"
    _write_lock(repo_root, source)
    archive_path = tmp_path / "source.tar.gz"
    with tarfile.open(archive_path, "w:gz", dereference=False) as archive:
        archive.add(source, arcname="codex-test/codex-rs")
        outside = tmp_path / "outside.txt"
        outside.write_text("not part of subtree\n", encoding="utf-8")
        archive.add(outside, arcname="codex-test/outside.txt")

    report = bootstrap_reference(repo_root, archive_path=archive_path)

    assert report.status == "ok"
    assert (repo_root / "codex-rs/core/runtime.rs").is_file()
    assert not (repo_root / "outside.txt").exists()
    with pytest.raises(CodexReferenceError, match="Refusing to overwrite"):
        bootstrap_reference(repo_root, archive_path=archive_path)
