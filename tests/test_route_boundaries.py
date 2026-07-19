"""Architecture gates for runtime, baseline, and auxiliary source routes."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

import pycodeagent.auxiliary as auxiliary
import pycodeagent.baselines as baselines
import pycodeagent.traces as traces
from pycodeagent.auxiliary.policy import (
    AUXILIARY_POLICY_VERSION,
    AUXILIARY_ROUTES,
    SHARED_KERNEL_PREFIXES,
)


pytestmark = pytest.mark.mainline

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PUBLIC_API_CONTRACT = (
    _PROJECT_ROOT
    / "docs/repository_cleanup/package_public_api_contract.json"
)
_MAINLINE_FILES = (
    "pycodeagent/agent/runner.py",
    "pycodeagent/env/coding_env.py",
    "pycodeagent/eval/native_family_acceptance.py",
    "pycodeagent/eval/real_provider_behavior_baseline.py",
    "pycodeagent/eval/real_provider_credibility_bundle.py",
    "pycodeagent/eval/runtime_observed_postrun.py",
    "pycodeagent/eval/toolview_mutation_data_generation.py",
    "pycodeagent/rl/schema_following_from_runtime.py",
    "pycodeagent/runtime_trace/writer.py",
)
_BASELINE_EXPORTS = {
    "SCHEMA_FOLLOWING_SPLIT_ORDER",
    "SyntheticProfileManifestEntry",
    "SyntheticProfileSpec",
    "SyntheticSchemaFollowingGenerationResult",
    "TrajectoryDerivedGenerationResult",
    "assign_synthetic_split",
    "build_default_synthetic_profile_specs",
    "generate_schema_following_from_trajectories",
    "generate_synthetic_schema_following_data",
}
_AUXILIARY_EXPORTS = {
    "ClaudeApiRequest",
    "ClaudeApiSFTSample",
    "NativeTransformedRLPromptSample",
    "build_claude_api_sft_dataset",
    "build_native_transformed_sft_dataset",
    "prepare_native_transformed_sft_training_input",
    "read_claude_api_session",
    "serialize_claude_api_sft_sample",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _module_path(module_name: str) -> Path:
    spec = importlib.util.find_spec(module_name)
    assert spec is not None and spec.origin is not None, module_name
    return Path(spec.origin)


def _rl_root_exports() -> set[str]:
    contract = json.loads(_PUBLIC_API_CONTRACT.read_text(encoding="utf-8"))
    owners = contract["packages"]["pycodeagent.rl"]["exports_by_owner"]
    return {
        symbol
        for owner in owners
        for symbol in owner["symbols"]
    }


def test_controlled_baseline_has_a_dedicated_low_priority_api() -> None:
    assert set(baselines.__all__) == _BASELINE_EXPORTS
    rl_exports = _rl_root_exports()
    for name in _BASELINE_EXPORTS:
        assert hasattr(baselines, name)
        assert name not in rl_exports

    root_entrypoint = (_PROJECT_ROOT / "generate_schema_following_data.py").read_text(
        encoding="utf-8"
    )
    assert "from pycodeagent.baselines import" in root_entrypoint
    assert "controlled schema-following baseline datasets" in root_entrypoint


def test_baseline_manifests_declare_route_role_and_owner(tmp_path: Path) -> None:
    synthetic_dir = tmp_path / "synthetic"
    baselines.generate_synthetic_schema_following_data(
        synthetic_dir,
        family="claude",
        num_intents=1,
        seed=7,
    )
    synthetic_manifest = json.loads(
        (synthetic_dir / "dataset_manifest.json").read_text(encoding="utf-8")
    )

    trajectory_source = tmp_path / "empty_runs"
    trajectory_source.mkdir()
    trajectory_dir = tmp_path / "trajectory"
    baselines.generate_schema_following_from_trajectories(
        trajectory_source,
        trajectory_dir,
        source_type="batch",
        family="claude",
        seed=7,
    )
    trajectory_manifest = json.loads(
        (trajectory_dir / "dataset_manifest.json").read_text(encoding="utf-8")
    )
    source_manifest = json.loads(
        (trajectory_dir / "source_manifest.json").read_text(encoding="utf-8")
    )

    for manifest in (synthetic_manifest, trajectory_manifest, source_manifest):
        assert manifest["route_role"] == "controlled_baseline"
        assert manifest["artifact_owner"] == "pycodeagent.baselines"


def test_auxiliary_registry_is_low_exposure_and_complete() -> None:
    assert AUXILIARY_POLICY_VERSION == 2
    assert auxiliary.__all__ == []
    assert {route.route_id for route in AUXILIARY_ROUTES} == {
        "claude_api_ingestion",
        "native_transformed",
    }
    for route in AUXILIARY_ROUTES:
        assert route.status == "migrated"
        assert route.migration_goal == "RC-030"
        assert route.modules
        assert route.entrypoints
        assert route.tests
        assert route.fixtures
        assert route.artifact_prefixes
        for module_name in route.modules:
            assert _module_path(module_name).is_file()
        for entrypoint in route.entrypoints:
            assert (_PROJECT_ROOT / entrypoint).is_file()
        for test_path in route.tests:
            assert (_PROJECT_ROOT / test_path).is_file()
        for fixture_path in route.fixtures:
            assert (_PROJECT_ROOT / fixture_path).is_file()

    rl_exports = _rl_root_exports()
    for name in _AUXILIARY_EXPORTS:
        assert name not in rl_exports
        assert name not in traces.__all__
        assert not hasattr(traces, name)


def test_mainline_does_not_import_baseline_or_auxiliary_namespaces() -> None:
    for relative_path in _MAINLINE_FILES:
        imports = _imports(_PROJECT_ROOT / relative_path)
        forbidden = sorted(
            name
            for name in imports
            if name == "pycodeagent.baselines"
            or name.startswith("pycodeagent.baselines.")
            or name == "pycodeagent.auxiliary"
            or name.startswith("pycodeagent.auxiliary.")
        )
        assert forbidden == [], (relative_path, forbidden)


def test_shared_packages_do_not_reverse_import_auxiliary_namespace() -> None:
    package_root = _PROJECT_ROOT / "pycodeagent"
    for path in package_root.rglob("*.py"):
        if "auxiliary" in path.relative_to(package_root).parts:
            continue
        imports = _imports(path)
        forbidden = sorted(
            name
            for name in imports
            if name == "pycodeagent.auxiliary"
            or name.startswith("pycodeagent.auxiliary.")
        )
        assert forbidden == [], (path.relative_to(_PROJECT_ROOT).as_posix(), forbidden)


def test_auxiliary_implementation_dependencies_point_to_shared_kernel() -> None:
    auxiliary_root = _PROJECT_ROOT / "pycodeagent/auxiliary"
    for path in auxiliary_root.rglob("*.py"):
        for imported in _imports(path):
            if not imported.startswith("pycodeagent."):
                continue
            assert imported.startswith("pycodeagent.auxiliary") or imported.startswith(
                SHARED_KERNEL_PREFIXES
            ), (path.relative_to(_PROJECT_ROOT).as_posix(), imported)


def test_route_boundary_document_matches_machine_policy() -> None:
    document = (_PROJECT_ROOT / "docs/source_route_boundaries.md").read_text(
        encoding="utf-8"
    )
    for required_text in (
        "Runtime-observed mainline",
        "Controlled baseline",
        "Auxiliary route",
        "The mainline must not import `pycodeagent.baselines`",
        'route_role = "controlled_baseline"',
        'artifact_owner = "pycodeagent.baselines"',
        "RC-030 completed their physical migration",
        "RC-031 subsequently removed the remaining broad legacy package",
        "Stable Package Facades",
        "package_public_api_contract.json",
    ):
        assert required_text in document
    for route in AUXILIARY_ROUTES:
        assert f"`{route.route_id}`" in document


def test_retired_runtime_helpers_do_not_reappear() -> None:
    from pycodeagent.adapters import mock_adapter
    from pycodeagent.agent import prompt, runner

    assert not hasattr(runner, "_meaningful_progress_observed")
    assert not hasattr(runner, "_active_recent_failure_kind")
    assert not hasattr(runner, "_sync_session_pending_issue")
    assert not hasattr(prompt, "format_history_for_prompt")
    assert not hasattr(mock_adapter, "read_mock_raw_trace")


def test_workspace_digest_and_mutation_loader_have_single_owners() -> None:
    mock_source = (_PROJECT_ROOT / "pycodeagent/adapters/mock_adapter.py").read_text(
        encoding="utf-8"
    )
    external_source = (
        _PROJECT_ROOT / "pycodeagent/adapters/external_cli_adapter.py"
    ).read_text(encoding="utf-8")
    sampler_source = (
        _PROJECT_ROOT / "pycodeagent/mutations/profile_sampler.py"
    ).read_text(encoding="utf-8")

    assert "def hash_workspace" not in mock_source
    assert "def hash_workspace" not in external_source
    assert "compute_workspace_digest" in mock_source
    assert "compute_workspace_digest" in external_source
    assert "def _load_mutation_config" not in sampler_source
    assert "yaml.safe_load" not in sampler_source
    assert "load_mutation_config" in sampler_source
