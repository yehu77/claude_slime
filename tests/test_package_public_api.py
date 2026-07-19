"""Contract gate for the intentionally narrow rl/eval package facades."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.mainline

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT / "docs/repository_cleanup/package_public_api_contract.json"
)
CONTRACT_SCHEMA = "repository-cleanup-package-public-api/v1"


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _declared_exports(package: dict) -> set[str]:
    return {
        symbol
        for owner in package["exports_by_owner"]
        for symbol in owner["symbols"]
    }


def _root_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package_roots = {"pycodeagent.rl", "pycodeagent.eval"}
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in package_roots:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(
                alias.name for alias in node.names if alias.name in package_roots
            )
    return imports


def test_machine_contract_has_fail_closed_policy_and_no_shims() -> None:
    contract = _contract()

    assert contract["schema"] == CONTRACT_SCHEMA
    assert contract["goal_id"] == "RC-031"
    assert contract["policy"] == {
        "package_roots_are": "small_stable_contract_facades",
        "operational_helpers": "import_from_owning_submodule",
        "baseline_namespace": "pycodeagent.baselines",
        "auxiliary_namespace": "pycodeagent.auxiliary",
        "compatibility_shims": "none",
        "compatibility_reason": (
            "All tracked aggregate-import consumers were migrated; direct owning "
            "submodules remain available, and retaining broad aliases would defeat "
            "the reviewed boundary."
        ),
        "external_consumer_risk": (
            "unknown_no_repository_evidence_or_declared_stable_distribution_contract"
        ),
    }
    assert set(contract["packages"]) == {"pycodeagent.rl", "pycodeagent.eval"}


@pytest.mark.parametrize("package_name", ["pycodeagent.rl", "pycodeagent.eval"])
def test_package_exports_match_contract_exactly(package_name: str) -> None:
    package_contract = _contract()["packages"][package_name]
    package = importlib.import_module(package_name)
    declared = _declared_exports(package_contract)

    assert set(package.__all__) == declared
    assert len(package.__all__) == len(declared)
    assert all(hasattr(package, symbol) for symbol in declared)
    assert all(
        not hasattr(package, symbol)
        for symbol in package_contract["forbidden_root_exports"]
    )

    star_namespace: dict[str, object] = {}
    exec(f"from {package_name} import *", star_namespace)
    assert declared <= set(star_namespace)


@pytest.mark.parametrize("package_name", ["pycodeagent.rl", "pycodeagent.eval"])
def test_every_export_has_one_existing_owning_submodule(
    package_name: str,
) -> None:
    package_contract = _contract()["packages"][package_name]
    owners: dict[str, str] = {}
    for owner in package_contract["exports_by_owner"]:
        module_name = owner["module"]
        spec = importlib.util.find_spec(module_name)
        assert spec is not None and spec.origin is not None
        assert Path(spec.origin).is_file()
        for symbol in owner["symbols"]:
            assert symbol not in owners
            owners[symbol] = module_name
            assert hasattr(importlib.import_module(module_name), symbol)

    assert set(owners) == _declared_exports(package_contract)


def test_tracked_code_has_no_package_root_aggregate_consumers() -> None:
    offenders: list[tuple[str, str]] = []
    paths = [
        *ROOT.glob("*.py"),
        *(ROOT / "pycodeagent").rglob("*.py"),
        *(ROOT / "tests").rglob("*.py"),
    ]
    for path in sorted(paths):
        relative = path.relative_to(ROOT)
        if (
            "archive" in relative.parts
            or relative.as_posix() == "tests/test_package_public_api.py"
            or relative.as_posix()
            in {
                "pycodeagent/rl/__init__.py",
                "pycodeagent/eval/__init__.py",
            }
        ):
            continue
        for package_name in _root_imports(path):
            offenders.append((relative.as_posix(), package_name))

    assert offenders == []


def test_facades_import_only_declared_owners() -> None:
    contract = _contract()
    for package_name, package_contract in contract["packages"].items():
        facade = ROOT / package_contract["facade_file"]
        tree = ast.parse(facade.read_text(encoding="utf-8"), filename=str(facade))
        observed = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module
            and node.module != "__future__"
        }
        expected = {
            owner["module"] for owner in package_contract["exports_by_owner"]
        }
        assert observed == expected, package_name


def test_retired_legacy_eval_tables_module_does_not_reappear() -> None:
    assert not (ROOT / "pycodeagent/eval/tables.py").exists()
    evaluation = importlib.import_module("pycodeagent.eval")
    for name in (
        "build_category_profile_table",
        "build_error_breakdown_table",
        "build_profile_comparison_table",
        "build_seed_comparison_table",
        "table_to_csv",
        "table_to_markdown",
    ):
        assert name not in evaluation.__all__
        assert not hasattr(evaluation, name)
