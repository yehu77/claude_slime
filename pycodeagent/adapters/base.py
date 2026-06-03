"""Adapter and catalog-provider protocols for the scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from pycodeagent.env.task import CodingTask
from pycodeagent.traces.raw_trace import RawAgentRunResult
from pycodeagent.traces.tool_catalog import AgentToolCatalog


class AgentRunContext(BaseModel):
    """Harness-owned execution context passed into an adapter."""

    run_id: str
    task_id: str
    agent_id: str
    run_dir: Path
    workspace_dir: Path
    stdout_path: Path
    stderr_path: Path
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentAdapter(Protocol):
    """Run one agent against one task and return raw artifact paths."""

    def agent_id(self) -> str: ...

    def agent_version(self) -> str: ...

    def run_task(self, task: CodingTask, context: AgentRunContext) -> RawAgentRunResult:
        ...


class ToolCatalogProvider(Protocol):
    """Return a tool catalog when the adapter did not emit one."""

    def agent_id(self) -> str: ...

    def get_tool_catalog(
        self,
        *,
        task: CodingTask | None = None,
        workspace_dir: Path | None = None,
        run_artifacts: RawAgentRunResult | None = None,
    ) -> AgentToolCatalog | None:
        ...
