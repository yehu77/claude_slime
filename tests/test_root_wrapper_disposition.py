"""RC-046 gates for the root-wrapper retirement boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.mainline

ROOT = Path(__file__).resolve().parents[1]
DISPOSITION_PATH = (
    ROOT / "docs/repository_cleanup/root_wrapper_disposition.json"
)

AUDITED_ROOT_WRAPPERS = {
    "claude_gateway_proxy.py",
    "export_claude_api_sft_dataset.py",
    "export_native_transformed_rl_dataset.py",
    "export_native_transformed_sft_dataset.py",
    "generate_schema_following_data.py",
    "prepare_native_transformed_sft_training_data.py",
    "prepare_schema_following_training_data.py",
    "prepare_slime_training_data.py",
    "run_external_agent_smoke.py",
    "run_native_family_acceptance.py",
    "run_native_transformed_sft_smoke.py",
    "run_real_provider_behavior_baseline.py",
    "run_real_provider_credibility_bundle.py",
    "run_runtime_smoke_real_provider.py",
    "run_toolview_mutation_data_generation.py",
    "validate_native_transformed_sft_dataset.py",
    "verify_slime_contract.py",
}


def _payload() -> dict:
    return json.loads(DISPOSITION_PATH.read_text(encoding="utf-8"))


def test_every_audited_root_wrapper_has_one_explicit_disposition() -> None:
    payload = _payload()
    entries = payload["entries"]
    assets = [entry["asset"] for entry in entries]

    assert payload["schema"] == "repository-cleanup-root-wrapper-disposition/v1"
    assert payload["goal_id"] == "RC-046"
    assert set(assets) == AUDITED_ROOT_WRAPPERS
    assert len(assets) == len(set(assets))
    assert all(entry["known_external_consumers"] == "unknown" for entry in entries)
    assert all(entry["rationale"] for entry in entries)


def test_retired_wrappers_are_absent_and_have_formal_replacements() -> None:
    retired = [
        entry for entry in _payload()["entries"]
        if entry["disposition"] == "delete"
    ]

    assert len(retired) == 7
    for entry in retired:
        assert entry["status"] == "retired"
        assert entry["route"] == "mainline_formal_cli"
        assert entry["known_repository_consumers"] == []
        assert entry["formal_replacement"].startswith("python -B -m pycodeagent ")
        assert not (ROOT / entry["asset"]).exists()


def test_retained_wrappers_are_route_specific_and_still_present() -> None:
    retained = [
        entry for entry in _payload()["entries"]
        if entry["disposition"] == "keep_route_specific"
    ]

    assert len(retained) == 10
    for entry in retained:
        assert entry["status"] == "active"
        assert entry["route"] != "mainline_formal_cli"
        assert entry["formal_replacement"] is None
        assert (ROOT / entry["asset"]).is_file()


def test_fixed_provider_smoke_is_a_declared_task_pack() -> None:
    path = ROOT / "datasets/tasks/real_provider_smoke_tasks.jsonl"
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert [record["task_id"] for record in records] == [
        "real_provider_smoke_read_then_finish"
    ]
    task = records[0]
    assert task["repo_path"] == "examples/runtime_rewrite_greeter"
    assert task["metadata"]["category"] == "real_provider_smoke"
    assert task["metadata"]["task_contract"]["required_capabilities"] == [
        "workspace_read",
        "validation",
    ]


def test_formal_cli_is_the_only_active_mainline_root_command_surface() -> None:
    root_python = {path.name for path in ROOT.glob("*.py")}
    forbidden_prefixes = (
        "prepare_slime",
        "verify_slime",
        "run_native_family_acceptance",
        "run_real_provider_",
        "run_runtime_smoke_real_provider",
        "run_toolview_mutation",
    )

    assert not {
        name for name in root_python if name.startswith(forbidden_prefixes)
    }
    assert (ROOT / "pycodeagent/__main__.py").is_file()
    assert (ROOT / "pycodeagent/cli.py").is_file()
