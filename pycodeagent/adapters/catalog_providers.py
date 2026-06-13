"""Static manifest-based catalog providers for real agent surfaces."""

from __future__ import annotations

from pathlib import Path

from pycodeagent.adapters.base import ToolCatalogProvider
from pycodeagent.env.task import CodingTask
from pycodeagent.traces.raw_trace import RawAgentRunResult
from pycodeagent.traces.tool_catalog import AgentToolCatalog, read_tool_catalog

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENT_CATALOG_DIR = _REPO_ROOT / "configs" / "agent_catalogs"


class StaticManifestCatalogProvider(ToolCatalogProvider):
    """Load a checked-in catalog manifest without running the agent."""

    def __init__(self, *, agent_id: str, manifest_path: str | Path) -> None:
        self._agent_id = agent_id
        self._manifest_path = Path(manifest_path)

    def agent_id(self) -> str:
        return self._agent_id

    @property
    def manifest_path(self) -> Path:
        return self._manifest_path

    def get_tool_catalog(
        self,
        *,
        task: CodingTask | None = None,
        workspace_dir: Path | None = None,
        run_artifacts: RawAgentRunResult | None = None,
    ) -> AgentToolCatalog | None:
        catalog = read_tool_catalog(self._manifest_path)
        if catalog.agent_name != self._agent_id:
            raise ValueError(
                "Catalog manifest agent_name does not match provider agent_id: "
                f"{catalog.agent_name!r} != {self._agent_id!r}"
            )
        metadata = dict(catalog.metadata)
        metadata.update(
            {
                "manifest_path": str(self._manifest_path),
                "provider_kind": "static_manifest",
            }
        )
        if task is not None:
            metadata["requested_task_id"] = task.task_id
        if workspace_dir is not None:
            metadata["requested_workspace_dir"] = str(workspace_dir)
        if run_artifacts is not None:
            metadata["requested_run_id"] = run_artifacts.run_id
        return catalog.model_copy(update={"metadata": metadata})


class CodexCatalogProvider(StaticManifestCatalogProvider):
    """Checked-in public-surface catalog for Codex CLI."""

    def __init__(self, manifest_path: str | Path | None = None) -> None:
        super().__init__(
            agent_id="codex_cli",
            manifest_path=manifest_path or (_AGENT_CATALOG_DIR / "codex_cli_public_catalog_v1.json"),
        )


class ClaudeCodeCatalogProvider(StaticManifestCatalogProvider):
    """Checked-in public-surface catalog for Claude Code."""

    def __init__(self, manifest_path: str | Path | None = None) -> None:
        super().__init__(
            agent_id="claude_code",
            manifest_path=manifest_path
            or (_AGENT_CATALOG_DIR / "claude_code_public_catalog_v1.json"),
        )
