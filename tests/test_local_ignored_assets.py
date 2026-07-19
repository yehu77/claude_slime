"""RC-050 governance gates for ignored local reference assets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.mainline

ROOT = Path(__file__).resolve().parents[1]
DECISION_PATH = (
    ROOT / "docs/repository_cleanup/claude_code_tree_decision.json"
)
EVIDENCE_PATH = ROOT / "references/claude-code-local-reference.json"
GOALS = ROOT / "docs/repository_cleanup/goals"


def _decision() -> dict:
    return json.loads(DECISION_PATH.read_text(encoding="utf-8"))


def _goal_status(goal_id: str) -> str:
    path = next(GOALS.glob(f"{goal_id}-*.md"))
    block = path.read_text(encoding="utf-8").split("---", 2)[1]
    for line in block.splitlines():
        if line.startswith("status: "):
            return line.removeprefix("status: ")
    raise AssertionError(f"Missing status for {goal_id}")


def test_rc050_selects_and_rc051_completes_local_externalization() -> None:
    payload = _decision()

    assert payload["schema"] == "repository-cleanup-local-reference-decision/v1"
    assert payload["goal_id"] == "RC-050"
    assert payload["decision"] == "externalize_to_local_reference_store"
    assert payload["implementation_goal"] == "RC-051"
    assert payload["implementation_status"] == "completed"
    assert payload["implementation_evidence"] == (
        "references/claude-code-local-reference.json"
    )
    assert _goal_status("RC-050") == "done"
    assert _goal_status("RC-051") == "done"


def test_audit_does_not_turn_the_ignored_tree_into_a_dependency() -> None:
    payload = _decision()
    dependency = payload["dependency_audit"]

    assert payload["asset"]["git_state"] == "ignored_untracked"
    assert payload["asset"]["tracked_file_count"] == 0
    assert dependency["tracked_path_consumers"] == []
    assert dependency["runtime_dependency"] is False
    assert dependency["adapter_resolution"] == "PATH executable named claude"
    assert (
        dependency["semantic_agent_id_references_are_path_dependencies"]
        is False
    )
    assert "claude_code/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_destination_is_local_durable_and_outside_the_worktree() -> None:
    destination = _decision()["destination"]

    assert destination["root_expression"] == (
        "${XDG_DATA_HOME:-$HOME/.local/share}/pycodeagent/references"
    )
    assert destination["relative_path"] == (
        "claude-code/2.1.88/research-tree"
    )
    assert destination["inside_git_worktree"] is False
    assert destination["external_storage_allowed"] is False
    assert "durable" in destination["purpose"]


def test_rc051_is_fail_closed_and_does_not_authorize_deletion() -> None:
    payload = _decision()
    preconditions = set(payload["rc051_preconditions"])
    recovery = payload["recovery"]

    assert {
        "require the exact destination to be absent before copying",
        "compute a deterministic full-tree digest and entry count before the move",
        "verify the destination digest and entry count before removing the source path",
        "abort and retain the source on any copy or verification mismatch",
    } <= preconditions
    assert recovery["retain_external_tree"] is True
    assert recovery["destructive_delete_authorized"] is False


def test_sanitized_externalization_evidence_freezes_verified_identity() -> None:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))

    assert evidence["schema"] == (
        "pycodeagent-local-reference-externalization/v1"
    )
    assert evidence["goal_id"] == "RC-051"
    assert evidence["source"] == {
        "former_worktree_path": "claude_code",
        "source_absent_after_externalization": True,
        "git_state_before_externalization": "ignored_untracked",
    }
    assert evidence["identity"] == {
        "package_name": "@anthropic-ai/claude-code",
        "package_version": "2.1.88",
        "digest_algorithm": "sha256-tree-manifest-v1",
        "tree_sha256": (
            "fe875b60f7df36978d5ee06d9e10823510a3c503664f619ddbb432b74e44bccb"
        ),
        "entry_count": 1927,
        "regular_file_count": 1927,
        "directory_count_including_root": 323,
        "symlink_count": 0,
        "total_regular_file_bytes": 133151295,
    }
    assert evidence["verification"] == {
        "source_digest_captured_before_copy": True,
        "destination_absent_before_copy": True,
        "destination_matched_before_source_removal": True,
        "destination_matched_after_source_removal": True,
        "copy_or_verification_mismatch": False,
    }
    assert evidence["content_boundary"]["sanitized_metadata_only"] is True
    assert evidence["destination"]["absolute_path_tracked"] is False
    assert not (ROOT / "claude_code").exists()


def test_ignored_asset_documentation_states_the_non_dependency_boundary() -> None:
    doc = (ROOT / "docs/local_ignored_assets.md").read_text(encoding="utf-8")

    for required in (
        "no tracked module, test, or",
        "invokes the executable",
        "through PATH",
        "local-machine-only",
        "worktree source is now absent",
        "machine-specific absolute destination",
        "Never interpret `.gitignore` as deletion authorization",
    ):
        assert required in doc
