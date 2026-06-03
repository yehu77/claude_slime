"""Raw-artifact capture adapter for Claude Code style CLIs."""

from __future__ import annotations

from pycodeagent.adapters.external_cli_adapter import ExternalCliArtifactAdapter


class ClaudeCodeAdapter(ExternalCliArtifactAdapter):
    """Subprocess adapter that captures raw artifacts from Claude Code wrappers."""

    def __init__(
        self,
        *,
        command_prefix: list[str] | None = None,
        exec_subcommand: str | None = None,
        extra_args: list[str] | None = None,
        timeout_seconds: int = 900,
        environment: dict[str, str] | None = None,
        sidecar_raw_trace_name: str = "raw_trace.jsonl",
        sidecar_summary_name: str = "raw_trace_summary.json",
        sidecar_catalog_name: str = "tool_catalog.json",
    ) -> None:
        super().__init__(
            agent_id="claude_code",
            display_name="Claude Code",
            command_prefix=command_prefix or ["claude"],
            exec_subcommand=exec_subcommand,
            extra_args=extra_args,
            timeout_seconds=timeout_seconds,
            environment=environment,
            sidecar_raw_trace_name=sidecar_raw_trace_name,
            sidecar_summary_name=sidecar_summary_name,
            sidecar_catalog_name=sidecar_catalog_name,
        )
