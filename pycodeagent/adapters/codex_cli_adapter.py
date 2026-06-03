"""Raw-artifact capture adapter for Codex CLI style backends."""

from __future__ import annotations

from pathlib import Path

from pycodeagent.adapters.base import AgentRunContext
from pycodeagent.adapters.external_cli_adapter import ExternalCliArtifactAdapter
from pycodeagent.env.task import CodingTask


class CodexCliAdapter(ExternalCliArtifactAdapter):
    """Subprocess adapter that captures raw artifacts from Codex CLI wrappers."""

    def __init__(
        self,
        *,
        command_prefix: list[str] | None = None,
        exec_subcommand: str | None = "exec",
        extra_args: list[str] | None = None,
        timeout_seconds: int = 900,
        environment: dict[str, str] | None = None,
        sidecar_raw_trace_name: str = "raw_trace.jsonl",
        sidecar_summary_name: str = "raw_trace_summary.json",
        sidecar_catalog_name: str = "tool_catalog.json",
    ) -> None:
        default_extra_args = [
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
        ]
        super().__init__(
            agent_id="codex_cli",
            display_name="Codex CLI",
            command_prefix=command_prefix or ["codex"],
            exec_subcommand=exec_subcommand,
            extra_args=(default_extra_args + list(extra_args or [])),
            timeout_seconds=timeout_seconds,
            environment=environment,
            sidecar_raw_trace_name=sidecar_raw_trace_name,
            sidecar_summary_name=sidecar_summary_name,
            sidecar_catalog_name=sidecar_catalog_name,
        )

    def build_runtime_environment(
        self,
        *,
        task: CodingTask,
        context: AgentRunContext,
    ) -> dict[str, str]:
        del task
        codex_home = Path(context.run_dir) / ".codex_home"
        codex_home.mkdir(parents=True, exist_ok=True)
        return {"CODEX_HOME": str(codex_home)}
