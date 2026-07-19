"""Machine checks for repository-cleanup decision inventories."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


pytestmark = pytest.mark.mainline

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs/repository_cleanup/orphan_support_modules.json"
EXPECTED_MODULES = {
    "pycodeagent/rl/train_loop.py",
    "pycodeagent/rl/export.py",
    "pycodeagent/eval/tables.py",
    "pycodeagent/traces/render.py",
}
LEGACY_STUDY_DECISION_PATH = (
    ROOT / "docs/repository_cleanup/legacy_study_route_decision.json"
)
EXPECTED_LEGACY_STUDY_MODULES = {
    "pycodeagent/eval/analysis.py",
    "pycodeagent/eval/batch_runner.py",
    "pycodeagent/eval/experiment_config.py",
    "pycodeagent/eval/experiment_runner.py",
    "pycodeagent/eval/metrics.py",
    "pycodeagent/eval/report.py",
    "pycodeagent/eval/run_study.py",
    "pycodeagent/eval/study_config.py",
    "pycodeagent/eval/study_report.py",
    "pycodeagent/eval/study_runner.py",
}
EXPECTED_LEGACY_STUDY_ENTRYPOINTS = {
    "run_first_study_mimo.py",
    "run_first_study_real_provider.py",
    "run_p3b_real_provider_compaction_acceptance.py",
    "run_schema_attribution_mimo.py",
    "run_schema_following_sft.py",
    "verify_p3b_real_provider_compaction_acceptance.py",
}


def _inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def _legacy_study_decision() -> dict:
    return json.loads(LEGACY_STUDY_DECISION_PATH.read_text(encoding="utf-8"))


def _goal_status(goal_id: str) -> str:
    matches = list(
        (ROOT / "docs/repository_cleanup/goals").glob(f"{goal_id}-*.md")
    )
    assert len(matches) == 1
    frontmatter = matches[0].read_text(encoding="utf-8").split("---", 2)[1]
    match = re.search(r"^status: ([a-z_]+)$", frontmatter, flags=re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_rc039_inventory_covers_exactly_four_modules() -> None:
    inventory = _inventory()
    assert inventory["schema"] == "repository-cleanup-orphan-support-modules/v2"
    assert inventory["goal_id"] == "RC-039"
    assert {entry["module"] for entry in inventory["modules"]} == EXPECTED_MODULES


@pytest.mark.parametrize("module_path", sorted(EXPECTED_MODULES))
def test_rc039_disposition_has_evidence_and_valid_follow_up(module_path: str) -> None:
    entry = next(
        item for item in _inventory()["modules"] if item["module"] == module_path
    )
    assert entry["owner"]
    assert entry["decision_evidence_consumers"]
    assert entry["contract_value"]
    assert entry["replacement"]
    assert entry["external_import_risk"]
    assert entry["disposition"] in {"keep", "retire"}

    child_goal = entry["child_goal"]
    if entry["disposition"] == "keep":
        assert entry["implementation_status"] == "active"
        assert entry["repository_consumers"]
        assert (ROOT / module_path).is_file()
        assert child_goal is None
        return

    assert child_goal in {"RC-056", "RC-057"}
    matches = list(
        (ROOT / "docs/repository_cleanup/goals").glob(f"{child_goal}-*.md")
    )
    assert len(matches) == 1
    goal_text = matches[0].read_text(encoding="utf-8")
    assert f"id: {child_goal}" in goal_text
    assert "RC-039" in goal_text
    if "status: done" in goal_text:
        assert entry["implementation_status"] == "retired"
        assert entry["repository_consumers"] == []
        assert not (ROOT / module_path).exists()
    else:
        assert entry["implementation_status"] == "planned"
        assert entry["repository_consumers"]
        assert (ROOT / module_path).is_file()


def test_rc024_selects_non_destructive_read_only_archive() -> None:
    payload = _legacy_study_decision()
    decision = payload["decision"]

    assert payload["schema"] == (
        "repository-cleanup-legacy-study-route-decision/v1"
    )
    assert payload["goal_id"] == "RC-024"
    assert decision == {
        "disposition": "archive_read_only_historical_reference",
        "active_mainline": False,
        "current_runtime_compatibility_required": False,
        "executable_reproducibility_required": False,
        "deletion_authorized": False,
        "archive_requirement": (
            "repository_owned_read_only_archive_outside_active_package_and_test_discovery"
        ),
        "archive_location": "selected_by_RC-025",
    }


def test_rc024_candidate_boundary_is_complete_and_non_overlapping() -> None:
    boundary = _legacy_study_decision()["candidate_boundary"]
    cluster = boundary["archive_with_study_cluster"]
    entrypoints = boundary["archive_with_root_entrypoints_via_RC-027"]

    assert set(cluster["modules"]) == EXPECTED_LEGACY_STUDY_MODULES
    assert set(entrypoints["entrypoints"]) == EXPECTED_LEGACY_STUDY_ENTRYPOINTS
    assert cluster["study_configs"] == [
        "configs/studies/first_mutation_sensitivity.json",
        "configs/studies/schema_failure_attribution_v1.json",
    ]
    assert cluster["task_packs"] == ["datasets/tasks/toy_tasks.jsonl"]
    assert boundary["separately_owned"] == [
        {
            "asset": "pycodeagent/eval/tables.py",
            "disposition": "retire",
            "owner_goal": "RC-057",
            "reason": "RC-039 assigned a separate atomic retirement after RC-031",
        }
    ]
    archive_candidate_paths = (
        cluster["modules"]
        + cluster["study_configs"]
        + cluster["task_packs"]
        + cluster["tests"]
        + entrypoints["entrypoints"]
        + entrypoints["known_entrypoint_tests"]
    )
    candidate_paths = archive_candidate_paths + [
        boundary["separately_owned"][0]["asset"]
    ]
    assert len(candidate_paths) == len(set(candidate_paths))
    assert all(
        (ROOT / path).is_file()
        or (ROOT / "archive/legacy-study-v1" / path).is_file()
        for path in archive_candidate_paths
    )
    assert _goal_status("RC-057") == "done"
    assert not (ROOT / boundary["separately_owned"][0]["asset"]).exists()


def test_rc024_protects_current_runtime_and_training_contracts() -> None:
    payload = _legacy_study_decision()
    protected = payload["protected_exclusions"]
    protected_paths = {item["asset"] for item in protected}
    candidate_text = json.dumps(payload["candidate_boundary"], sort_keys=True)

    assert {
        "pycodeagent/dev/mimo_local.py",
        "datasets/tasks/realistic_runtime_tasks.jsonl",
        "pycodeagent/eval/runtime_observed_postrun.py",
        "pycodeagent/testing/runtime_observed.py",
        "pycodeagent/rl/serializer.py",
        "pycodeagent/rl/loss_mask.py",
        "pycodeagent/rl/training_prep.py",
        "pycodeagent/cli.py",
        "pycodeagent/application/cli_services.py",
        "datasets/tasks/real_provider_smoke_tasks.jsonl",
        "pycodeagent/eval/native_family_acceptance.py",
    } == protected_paths
    assert all(item["reason"] for item in protected)
    assert all((ROOT / path).is_file() for path in protected_paths)
    assert all(path not in candidate_text for path in protected_paths)


def test_rc024_downstream_goal_statuses_match_the_decision() -> None:
    payload = _legacy_study_decision()

    assert payload["downstream"] == {
        "RC-025": "done_exact_closure_and_archive_mechanism_frozen",
        "RC-026": "done_archive_cluster",
        "RC-027": "done_archive_stage_entrypoints",
        "RC-043": "done_campaign_defined_without_legacy_study_semantics",
    }
    assert _goal_status("RC-024") == "done"
    assert _goal_status("RC-025") == "done"
    assert _goal_status("RC-026") == "done"
    assert _goal_status("RC-027") == "done"
    assert _goal_status("RC-043") == "done"
