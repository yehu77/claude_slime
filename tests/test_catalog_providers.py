"""Tests for static manifest-based real catalog providers."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from pycodeagent.adapters import (
    AgentRunContext,
    ClaudeCodeCatalogProvider,
    ClaudeCodeAdapter,
    CodexCatalogProvider,
    MockTraceNormalizer,
    StaticManifestCatalogProvider,
)
from pycodeagent.adapters.mock_adapter import MockAdapter
from pycodeagent.env.task import CodingTask
from pycodeagent.harness import AgentHarness
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.traces import NoOpTraceNormalizer, RawAgentRunResult, read_tool_catalog


_TEST_NAMESPACE = "catalog_providers"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text("# Repo\n", encoding="utf-8")
    return repo


def _make_task(repo: Path) -> CodingTask:
    return CodingTask(
        task_id="task_001",
        repo_path=repo,
        prompt="Inspect the repo and run tests.",
        test_command="pytest -q",
    )


class _CodexNoCatalogAdapter(MockAdapter):
    def agent_id(self) -> str:
        return "codex_cli"

    def agent_version(self) -> str:
        return "public_catalog_v1"

    def run_task(self, task: CodingTask, context: AgentRunContext) -> RawAgentRunResult:
        return super().run_task(task, context)


class TestCatalogProviders:
    def test_static_manifest_provider_loads_codex_catalog(self) -> None:
        provider = CodexCatalogProvider()

        catalog = provider.get_tool_catalog()

        assert catalog is not None
        assert catalog.agent_name == "codex_cli"
        assert catalog.capture_mode == "static"
        assert catalog.source_kind == "checked_in_manifest"
        assert catalog.metadata["provider_kind"] == "static_manifest"
        assert any(tool.raw_tool_name == "local_shell" for tool in catalog.tools)
        assert any(tool.metadata.get("mapping_status") == "unmapped" for tool in catalog.tools)

    def test_manifest_provider_rejects_agent_name_mismatch(self) -> None:
        provider = StaticManifestCatalogProvider(
            agent_id="not_codex",
            manifest_path=Path("configs/agent_catalogs/codex_cli_public_catalog_v1.json"),
        )

        with pytest.raises(ValueError, match="agent_name does not match provider agent_id"):
            provider.get_tool_catalog()

    def test_harness_can_use_codex_catalog_provider_when_adapter_omits_catalog(self) -> None:
        tmp = _get_test_dir()
        try:
            repo = _make_repo(tmp)
            task = _make_task(repo)
            harness = AgentHarness(
                adapter=_CodexNoCatalogAdapter(emit_tool_catalog=False),
                normalizer=MockTraceNormalizer(),
                tool_catalog_provider=CodexCatalogProvider(),
            )

            result = harness.run_task(task, output_dir=tmp / "runs", run_id="run_001")

            assert result.tool_catalog is not None
            assert result.tool_catalog.agent_name == "codex_cli"
            saved = read_tool_catalog(result.bundle_paths.tool_catalog_path)
            assert saved.catalog_id == "codex_cli_public_catalog_v1"
            assert saved.metadata["provider_kind"] == "static_manifest"
        finally:
            _cleanup(tmp)

    def test_static_manifest_provider_loads_claude_catalog(self) -> None:
        provider = ClaudeCodeCatalogProvider()

        catalog = provider.get_tool_catalog()

        assert catalog is not None
        assert catalog.agent_name == "claude_code"
        assert catalog.capture_mode == "static"
        assert catalog.source_kind == "checked_in_manifest"
        assert catalog.metadata["provider_kind"] == "static_manifest"
        assert any(tool.raw_tool_name == "bash" for tool in catalog.tools)
        assert any(tool.metadata.get("mapping_status") == "unmapped" for tool in catalog.tools)

    def test_harness_can_fallback_to_claude_catalog_provider_when_adapter_omits_catalog(self) -> None:
        tmp = _get_test_dir()
        try:
            repo = _make_repo(tmp)
            task = _make_task(repo)
            script = Path("examples/external_wrappers/claude_code_sidecar_wrapper.py")
            harness = AgentHarness(
                adapter=ClaudeCodeAdapter(
                    command_prefix=[sys.executable, str(script)],
                    exec_subcommand=None,
                ),
                normalizer=NoOpTraceNormalizer("claude_code"),
                tool_catalog_provider=ClaudeCodeCatalogProvider(),
            )

            result = harness.run_task(task, output_dir=tmp / "runs", run_id="run_001")

            assert result.tool_catalog is not None
            assert result.tool_catalog.agent_name == "claude_code"
            saved = read_tool_catalog(result.bundle_paths.tool_catalog_path)
            assert saved.catalog_id == "claude_code_public_catalog_v1"
            assert saved.metadata["provider_kind"] == "static_manifest"
            assert result.run_artifacts.tool_catalog_path is None
        finally:
            _cleanup(tmp)
