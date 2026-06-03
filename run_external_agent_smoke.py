"""Run a minimal external-agent smoke path and capture raw artifacts."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from pycodeagent.adapters import (
    ClaudeCodeAdapter,
    ClaudeCodeCatalogProvider,
    CodexCatalogProvider,
    CodexCliAdapter,
    KiloCodeAdapter,
    StaticManifestCatalogProvider,
)
from pycodeagent.env.task import CodingTask
from pycodeagent.harness import AgentHarness
from pycodeagent.traces import NoOpTraceNormalizer


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an external CLI agent smoke path and capture raw artifacts."
    )
    parser.add_argument("agent", choices=["codex_cli", "claude_code", "kilo_code"])
    parser.add_argument("repo_path", help="Repository to copy into the workspace")
    parser.add_argument("output_dir", help="Directory to write the run bundle")
    parser.add_argument("--prompt", required=True, help="Task prompt passed to the external agent")
    parser.add_argument(
        "--test-command",
        default="pytest -q",
        help="Verifier command executed after the external agent run",
    )
    parser.add_argument(
        "--command-prefix",
        nargs="+",
        required=True,
        help="Executable prefix for the external wrapper, e.g. python fake_wrapper.py",
    )
    parser.add_argument(
        "--exec-subcommand",
        default=None,
        help="Optional exec-style subcommand appended before the prompt",
    )
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--task-id", default="external_smoke_task")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--catalog-manifest",
        help="Optional checked-in static catalog manifest to use as ToolCatalogProvider",
    )
    return parser


def _build_adapter(agent: str, args: argparse.Namespace):
    common_kwargs = {
        "command_prefix": list(args.command_prefix),
        "exec_subcommand": args.exec_subcommand,
        "timeout_seconds": args.timeout_seconds,
    }
    if agent == "codex_cli":
        return CodexCliAdapter(**common_kwargs)
    if agent == "claude_code":
        return ClaudeCodeAdapter(**common_kwargs)
    if agent == "kilo_code":
        return KiloCodeAdapter(**common_kwargs)
    raise ValueError(f"Unsupported agent: {agent}")


def _build_catalog_provider(agent: str, args: argparse.Namespace):
    if args.catalog_manifest:
        return StaticManifestCatalogProvider(
            agent_id=agent,
            manifest_path=Path(args.catalog_manifest),
        )
    if agent == "codex_cli":
        return CodexCatalogProvider()
    if agent == "claude_code":
        return ClaudeCodeCatalogProvider()
    return None


def run_external_agent_smoke(
    *,
    agent: str,
    repo_path: str | Path,
    output_dir: str | Path,
    prompt: str,
    test_command: str = "pytest -q",
    command_prefix: list[str],
    exec_subcommand: str | None = None,
    timeout_seconds: int = 900,
    task_id: str = "external_smoke_task",
    run_id: str | None = None,
    catalog_manifest: str | Path | None = None,
) -> dict[str, object]:
    adapter_args = argparse.Namespace(
        command_prefix=command_prefix,
        exec_subcommand=exec_subcommand,
        timeout_seconds=timeout_seconds,
        catalog_manifest=str(catalog_manifest) if catalog_manifest is not None else None,
    )
    adapter = _build_adapter(agent, adapter_args)
    provider = _build_catalog_provider(agent, adapter_args)
    harness = AgentHarness(
        adapter=adapter,
        normalizer=NoOpTraceNormalizer(agent),
        tool_catalog_provider=provider,
    )
    task = CodingTask(
        task_id=task_id,
        repo_path=Path(repo_path),
        prompt=prompt,
        test_command=test_command,
    )
    resolved_run_id = run_id or f"{agent}__{uuid.uuid4().hex[:8]}"
    result = harness.run_task(task, output_dir=Path(output_dir), run_id=resolved_run_id)
    return {
        "agent": agent,
        "run_id": resolved_run_id,
        "bundle_dir": str(result.bundle_paths.run_dir),
        "status": result.run_artifacts.status.value,
        "raw_trace_path": result.run_artifacts.raw_trace_path,
        "raw_trace_summary_path": result.run_artifacts.raw_trace_summary_path,
        "tool_catalog_path": result.run_artifacts.tool_catalog_path,
        "stdout_path": result.run_artifacts.stdout_path,
        "stderr_path": result.run_artifacts.stderr_path,
        "final_diff_path": result.run_artifacts.final_diff_path,
        "verifier_result_path": result.run_artifacts.verifier_result_path,
        "sidecar_raw_trace_detected": result.run_artifacts.metadata.get(
            "sidecar_raw_trace_detected"
        ),
        "sidecar_catalog_detected": result.run_artifacts.metadata.get(
            "sidecar_catalog_detected"
        ),
    }


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    result = run_external_agent_smoke(
        agent=args.agent,
        repo_path=Path(args.repo_path),
        output_dir=Path(args.output_dir),
        prompt=args.prompt,
        test_command=args.test_command,
        command_prefix=list(args.command_prefix),
        exec_subcommand=args.exec_subcommand,
        timeout_seconds=args.timeout_seconds,
        task_id=args.task_id,
        run_id=args.run_id,
        catalog_manifest=(Path(args.catalog_manifest) if args.catalog_manifest else None),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
