"""RC-037 governance gates for the legacy command-policy decision."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.mainline

ROOT = Path(__file__).resolve().parents[1]
DECISION_PATH = (
    ROOT / "docs/repository_cleanup/command_policy_decision.json"
)
GOALS = ROOT / "docs/repository_cleanup/goals"


def _decision() -> dict:
    return json.loads(DECISION_PATH.read_text(encoding="utf-8"))


def _frontmatter(goal_id: str) -> dict[str, str]:
    path = next(GOALS.glob(f"{goal_id}-*.md"))
    text = path.read_text(encoding="utf-8")
    block = text.split("---", 2)[1]
    result: dict[str, str] = {}
    for line in block.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            result[key] = value
    return result


def test_rc037_selects_one_delete_route_and_rc038_implements_it() -> None:
    payload = _decision()

    assert payload["schema"] == (
        "repository-cleanup-command-policy-decision/v1"
    )
    assert payload["goal_id"] == "RC-037"
    assert payload["decision"] == "delete_legacy_implementation"
    assert payload["implementation_goal"] == "RC-038"
    assert payload["implementation_status"] == "completed"
    assert _frontmatter("RC-037")["status"] == "done"
    assert _frontmatter("RC-038")["status"] == "done"
    assert _frontmatter("RC-038")["action"] == "delete"


def test_only_active_symbol_has_an_owned_replacement() -> None:
    payload = _decision()

    assert payload["current_consumers"] == [
        {
            "consumer": "pycodeagent/tools/shell_runtimes.py",
            "symbol": "normalize_workdir",
            "replacement": "pycodeagent.env.path_policy.validate_cwd",
        }
    ]
    assert set(payload["legacy_symbols_to_remove"]) >= {
        "CommandPolicyDecision",
        "CommandExecutionResult",
        "classify_command_argv",
        "normalize_workdir",
        "run_subprocess",
    }
    assert len(payload["reasons"]) >= 5
    assert len(payload["preserved_behavior"]) >= 4


def test_future_s5_contract_does_not_rebrand_the_legacy_allowlist() -> None:
    contract = _decision()["future_s5_contract"]
    required = set(contract["required_properties"])

    assert contract["reuse_legacy_data_model"] is False
    assert contract["reference"]["commit"] == (
        "0beb5c7f32cf5459a51e3f6bc01e6509d7951854"
    )
    assert set(contract["reference"]["subsystems"]) == {
        "codex-rs/execpolicy",
        "codex-rs/shell-command",
    }
    assert {
        "represent allow, prompt, and forbidden as distinct outcomes",
        "evaluate every effective segment of compound shell commands",
        "distinguish requested permission or sandbox fields from effective policy decisions",
        "emit policy facts into tool metadata and runtime traces",
    } <= required
    assert "cross-platform production sandbox" in contract["out_of_scope"]


def test_rc038_acceptance_preserves_current_enforcement_owners() -> None:
    acceptance = set(_decision()["rc038_acceptance"])

    assert "replace normalize_workdir with a direct validate_cwd import" in acceptance
    assert "delete pycodeagent/tools/command_safety.py" in acceptance
    assert (
        "freeze workspace cwd rejection and current command execution behavior"
        in acceptance
    )
