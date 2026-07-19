"""Mainline guard for the repository-owned documentation taxonomy."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pycodeagent.dev.docs_taxonomy import (
    DocumentationTaxonomyError,
    check_relative_markdown_links,
    validate_documentation_taxonomy,
)


pytestmark = pytest.mark.mainline

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_NATIVE_FAMILY_ADR = "docs/adr/0001-native-family-runtime-boundary.md"
_RC015_ARCHIVE = "docs/archive/2026-07-16-local-runtime"
_RC015_ARCHIVED_FILES = (
    "P3plan.md",
    "local_runtime_85_maturity_execution_plan.md",
    "local_runtime_maturation_plan.md",
    "local_runtime_realism_mainline_plan.md",
    "runtime_r1_implementation_note.md",
    "runtime_r3_implementation_note.md",
)
_RC016_ARCHIVE = "docs/archive/2026-07-16-tool-runtime"
_RC016_ARCHIVED_FILES = (
    "tool_runtime_family_split_implementation_plan.md",
    "tool_runtime_legacy_demotion_followup_plan.md",
    "tool_runtime_step_a_shared_process_primitives_plan.md",
    "tool_runtime_step_b_shell_runtime_integration_plan.md",
    "tool_runtime_step_c0_native_tool_contract_expansion_plan.md",
    "tool_runtime_step_c_canonical_tool_definitions_plan.md",
    "tool_runtime_step_d_native_family_profiles_plan.md",
    "tool_runtime_step_e_bootstrap_registry_selection_plan.md",
    "tool_runtime_step_f_native_family_mutation_data_integration_plan.md",
    "toolview_mutation_data_generation_plan.md",
)
_ADR_CONSUMERS = (
    "docs/codex_rs_subsystem_implementation_plan.md",
    "docs/local_runtime_industrial_gap_roadmap.md",
    "docs/tool_runtime_native_family_acceptance_and_regression_plan.md",
    "docs/real_provider_runtime_usage.md",
    *(
        f"{_RC016_ARCHIVE}/{filename}"
        for filename in _RC016_ARCHIVED_FILES
    ),
)


def test_documentation_inventory_covers_current_docs_and_links() -> None:
    report = validate_documentation_taxonomy(_PROJECT_ROOT)

    assert report.local_link_count > 0
    assert "docs/repository_cleanup/goals/RC-013-establish-docs-taxonomy.md" in (
        report.document_paths
    )
    assert sum(
        entry.category == "current-driver" for entry in report.inventory_entries
    ) == 1
    assert any(
        entry.pattern == "docs/codex_rs_subsystem_implementation_plan.md"
        and entry.category == "current-driver"
        for entry in report.inventory_entries
    )


def test_taxonomy_rejects_an_unclassified_document(tmp_path: Path) -> None:
    shutil.copytree(_PROJECT_ROOT / "docs", tmp_path / "docs")
    (tmp_path / "docs" / "unclassified.md").write_text(
        "# Unclassified\n",
        encoding="utf-8",
    )

    with pytest.raises(DocumentationTaxonomyError, match="coverage drift"):
        validate_documentation_taxonomy(tmp_path)


def test_link_gate_rejects_missing_relative_target(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "[missing](./does-not-exist.md)\n",
        encoding="utf-8",
    )

    with pytest.raises(DocumentationTaxonomyError, match="missing local link target"):
        check_relative_markdown_links(tmp_path)


def test_agent_instructions_have_one_tool_neutral_source() -> None:
    canonical_path = _PROJECT_ROOT / "AGENTS.md"
    claude_entrypoint = _PROJECT_ROOT / "CLAUDE.md"
    legacy_entrypoint = _PROJECT_ROOT / "CLAUDE.MD"
    canonical = canonical_path.read_text(encoding="utf-8")
    claude = claude_entrypoint.read_text(encoding="utf-8")

    assert "# Repository Agent Instructions" in canonical
    assert "tool-neutral source of truth" in canonical
    assert claude_entrypoint.is_file()
    assert not legacy_entrypoint.exists()
    assert "[AGENTS.md](./AGENTS.md)" in claude
    assert "no Claude-specific project overrides" in claude
    assert len(claude.splitlines()) <= 20
    for duplicated_heading in (
        "## Project Goal",
        "## Current Primary Objective",
        "## Immediate Next Milestones",
        "## Non-Goals",
        "## Decision Rule For Future Work",
    ):
        assert duplicated_heading in canonical
        assert duplicated_heading not in claude


def test_scaffold_phase_one_doc_matches_the_single_golden_contract() -> None:
    doc = (_PROJECT_ROOT / "docs/scaffold_phase1.md").read_text(encoding="utf-8")
    golden_dir = _PROJECT_ROOT / "examples/multi_agent_mock_run"
    manifest = json.loads(
        (golden_dir / "golden_manifest.json").read_text(encoding="utf-8")
    )
    expected_files = set(manifest["artifacts"]) | {"golden_manifest.json"}

    assert manifest["schema_version"] == 1
    assert expected_files == {entry.name for entry in golden_dir.iterdir()}
    for filename in expected_files:
        assert f"`{filename}`" in doc
    assert "../examples/multi_agent_mock_run/README.md" in doc
    assert "--write --output-dir" in doc
    assert "--check --output-dir" in doc
    assert "no top-level `schema_version`" in doc
    assert "not a phase-one acceptance dependency" in doc
    assert "tests/fixtures/multi_agent_mock_bundle" not in doc
    legacy_fixture = _PROJECT_ROOT / "tests/fixtures/multi_agent_mock_bundle"
    assert not legacy_fixture.exists() or not any(legacy_fixture.rglob("*"))


def test_real_provider_runbook_matches_formal_native_family_entrypoints() -> None:
    runbook = (_PROJECT_ROOT / "docs/real_provider_runtime_usage.md").read_text(
        encoding="utf-8"
    )
    retired_wrapper_paths = (
        "run_runtime_smoke_real_provider.py",
        "run_real_provider_behavior_baseline.py",
        "run_toolview_mutation_data_generation.py",
        "run_real_provider_credibility_bundle.py",
        "run_native_family_acceptance.py",
    )

    for wrapper_path in retired_wrapper_paths:
        assert not (_PROJECT_ROOT / wrapper_path).exists()
        assert f"python -B {wrapper_path}" not in runbook

    for required_text in (
        "Provider transport and model-visible tool family are separate choices.",
        '`tool_stack_kind="native_claude"`',
        "python -B -m pycodeagent acceptance",
        "python -B -m pycodeagent run",
        "python -B -m pycodeagent campaign",
        "datasets/tasks/real_provider_smoke_tasks.jsonl",
        "--family native_claude",
        "Unable to resolve runtime provider config",
        "Missing API key for runtime provider config",
        "real_provider_credibility_manifest.json",
        "toolview_mutation_data_generation_manifest.json",
        "Do not commit `.env`",
        "tool_stack_kind=\"native_claude\"",
        "do not prove provider parity",
    ):
        assert required_text in runbook

    for stale_text in (
        "read_file -> finish",
        "run_first_study_real_provider.py",
        "run_study_from_provider_config",
        "first_mutation_sensitivity",
    ):
        assert stale_text not in runbook


def test_native_family_adr_is_canonical_and_linked_by_related_docs() -> None:
    adr_path = _PROJECT_ROOT / _NATIVE_FAMILY_ADR
    adr_text = adr_path.read_text(encoding="utf-8")

    for required_heading in (
        "## Decision",
        "### 1. Terminology and abstraction boundary",
        "### 2. Family-neutral task contract",
        "### 3. Selection and fallback rules",
        "### 4. Artifact and provenance contract",
        "### 5. Acceptance boundary",
        "## Superseded planning records",
    ):
        assert required_heading in adr_text
    for contract_text in (
        "CanonicalTool -> ToolView -> ToolAdapter -> ToolRuntime",
            "tool_stack_kind",
            "text_fallback_allowed=false",
            "stabilized=true",
            "metadata.task_contract",
            "required_capabilities",
            "tasks without `task_contract` load as legacy v0",
            "RC-022 migrated the realistic runtime pack to v1",
        ):
        assert contract_text in adr_text

    for relative_path in _ADR_CONSUMERS:
        text = (_PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "adr/0001-native-family-runtime-boundary.md" in text, relative_path


def test_rc015_local_runtime_plans_are_manifested_outside_active_docs() -> None:
    archive_dir = _PROJECT_ROOT / _RC015_ARCHIVE
    manifest = (archive_dir / "README.md").read_text(encoding="utf-8")

    assert "Completion at archive time" in manifest
    assert "Replacement" in manifest
    assert "Why retained" in manifest
    for filename in _RC015_ARCHIVED_FILES:
        assert not (_PROJECT_ROOT / "docs" / filename).exists()
        archived_path = archive_dir / filename
        assert archived_path.is_file()
        assert f"`docs/{filename}`" in manifest
        assert "Archived by RC-015 on 2026-07-16" in archived_path.read_text(
            encoding="utf-8"
        )


def test_rc016_tool_runtime_plans_are_manifested_outside_active_docs() -> None:
    archive_dir = _PROJECT_ROOT / _RC016_ARCHIVE
    manifest = (archive_dir / "README.md").read_text(encoding="utf-8")

    assert "Status at archive time" in manifest
    assert "Superseded by" in manifest
    assert "Why retained" in manifest
    for filename in _RC016_ARCHIVED_FILES:
        assert not (_PROJECT_ROOT / "docs" / filename).exists()
        archived_path = archive_dir / filename
        assert archived_path.is_file()
        assert f"`docs/{filename}`" in manifest
        assert "Archived by RC-016 on 2026-07-16" in archived_path.read_text(
            encoding="utf-8"
        )


def test_run_campaign_contract_is_versioned_documented_and_mainline_gated() -> None:
    contract = (_PROJECT_ROOT / "docs/run_campaign_contract.md").read_text(
        encoding="utf-8"
    )
    workflow = (
        _PROJECT_ROOT / ".github/workflows/mainline-tests.yml"
    ).read_text(encoding="utf-8")
    cleanup_ledger = (
        _PROJECT_ROOT / "docs/repository_cleanup/README.md"
    ).read_text(encoding="utf-8")

    for required_text in (
        "Status: active, version 1, defined by RC-043",
        "task × native tool family × ToolView mode × ToolView seed × provider × repeat",
        "campaign_spec.json",
        "campaign_artifact_index.json",
        "campaign_failure_summary.json",
        "append-only",
        "post-write interruption recovery",
        "RC-044",
        "execute_profile_run_campaigns",
        "profile_campaign_group_manifest.json",
        "Old orchestration fields",
        "terminal `campaign_run_record.json`",
    ):
        assert required_text in contract
    assert "RC-043 does not migrate" not in contract
    assert "tests/test_run_campaign.py" in workflow
    assert "tests/test_run_campaign.py" in cleanup_ledger


def test_formal_cli_contract_freezes_precedence_outputs_and_handoff() -> None:
    contract = (_PROJECT_ROOT / "docs/formal_cli.md").read_text(
        encoding="utf-8"
    )
    workflow = (
        _PROJECT_ROOT / ".github/workflows/mainline-tests.yml"
    ).read_text(encoding="utf-8")
    config = json.loads(
        (
            _PROJECT_ROOT
            / "configs/local/pycodeagent_cli.acceptance.example.json"
        ).read_text(encoding="utf-8")
    )

    for required_text in (
        "Status: active, contract version 1, defined by RC-045",
        "| `run` |",
        "| `campaign` |",
        "built-in defaults < config.arguments < explicit CLI options",
        "pycodeagent-cli-result/v1",
        "pycodeagent-cli-error/v1",
        "pycodeagent-cli-manifest/v1",
        "`130`",
        "RC-046",
        "calls exactly one service",
    ):
        assert required_text in contract
    assert config["schema"] == "pycodeagent-cli-config/v1"
    assert config["command"] == "acceptance"
    assert config["arguments"]["local_only"] is True
    assert "tests/test_formal_cli.py" in workflow
