"""Golden and adapter-boundary tests for the canonical workspace digest."""

from __future__ import annotations

from pathlib import Path

from pycodeagent.adapters.workspace_digest import (
    WORKSPACE_DIGEST_ALGORITHM,
    WORKSPACE_DIGEST_VERSION,
    compute_workspace_digest,
)


def test_workspace_digest_contract_is_explicit_and_versioned() -> None:
    assert WORKSPACE_DIGEST_ALGORITHM == "sha256-tree-v1"
    assert WORKSPACE_DIGEST_VERSION == 1


def test_workspace_digest_missing_root_golden(tmp_path: Path) -> None:
    assert compute_workspace_digest(tmp_path / "missing") == (
        "769b8995b8bf4407c89e906d67601a46266d34922a63ab1754440eecb0657aab"
    )


def test_workspace_digest_empty_and_directory_only_corpus(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert compute_workspace_digest(empty) == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )

    directories = tmp_path / "directories"
    (directories / "a" / "b").mkdir(parents=True)
    assert compute_workspace_digest(directories) == (
        "1675a4cca3296d5b1b1d2a95ffbba22695d6e7d033575d434dbd332ec182cca7"
    )


def test_workspace_digest_tree_golden_and_order_independence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "pkg").mkdir(parents=True)
    (workspace / "z.txt").write_bytes(b"last\n")
    (workspace / "pkg" / "a.bin").write_bytes(b"\x00first")

    expected = "db8728da692e0f48894fe4dee43e67b020b3a82cf573deb32285414bc986e6f0"
    assert compute_workspace_digest(workspace) == expected

    rebuilt = tmp_path / "rebuilt"
    rebuilt.mkdir()
    (rebuilt / "z.txt").write_bytes(b"last\n")
    (rebuilt / "pkg").mkdir()
    (rebuilt / "pkg" / "a.bin").write_bytes(b"\x00first")
    assert compute_workspace_digest(rebuilt) == expected


def test_workspace_digest_changes_with_path_or_content(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    original = compute_workspace_digest(workspace)

    source.write_text("value = 2\n", encoding="utf-8")
    assert compute_workspace_digest(workspace) != original
