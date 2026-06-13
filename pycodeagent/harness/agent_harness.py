"""Agent-agnostic scaffold harness."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from pycodeagent.adapters.base import AgentRunContext, ToolCatalogProvider
from pycodeagent.env.task import CodingTask
from pycodeagent.traces import (
    AgentToolCatalog,
    NormalizationResult,
    RawAgentRunResult,
    RawAgentTrace,
    TraceNormalizer,
    read_raw_trace,
    read_tool_catalog,
    write_canonical_trace,
    write_normalization_report,
    write_tool_catalog,
)

from .run_bundle import RunBundlePaths, create_run_bundle_paths, materialize_workspace, write_task_artifact


class HarnessRunResult(BaseModel):
    """Final harness view of one scaffold run."""

    run_artifacts: RawAgentRunResult
    tool_catalog: AgentToolCatalog | None
    raw_trace: RawAgentTrace
    normalization: NormalizationResult
    bundle_paths: RunBundlePaths


class AgentHarness:
    """Minimal harness for phase-one mock scaffold runs."""

    def __init__(
        self,
        *,
        adapter,
        normalizer: TraceNormalizer,
        tool_catalog_provider: ToolCatalogProvider | None = None,
    ) -> None:
        self._adapter = adapter
        self._normalizer = normalizer
        self._tool_catalog_provider = tool_catalog_provider

    def run_task(
        self,
        task: CodingTask,
        *,
        output_dir: str | Path,
        run_id: str,
    ) -> HarnessRunResult:
        bundle = create_run_bundle_paths(output_dir, run_id=run_id)
        materialize_workspace(task, bundle.workspace_dir)
        write_task_artifact(task, bundle.task_json_path)

        run_context = AgentRunContext(
            run_id=run_id,
            task_id=task.task_id,
            agent_id=self._adapter.agent_id(),
            run_dir=bundle.run_dir,
            workspace_dir=bundle.workspace_dir,
            stdout_path=bundle.stdout_path,
            stderr_path=bundle.stderr_path,
        )
        run_result = self._adapter.run_task(task, run_context)
        _validate_artifact_paths(run_result, bundle.run_dir)
        raw_trace = _load_raw_trace(run_result)
        tool_catalog = self._resolve_tool_catalog(task, bundle, run_result)
        normalization = self._normalizer.normalize(raw_trace, tool_catalog=tool_catalog)

        write_canonical_trace(normalization.canonical_trace, bundle.canonical_trace_path)
        write_normalization_report(normalization.report, bundle.normalization_report_path)

        bundle.workspace_manifest_path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "task_id": task.task_id,
                    "workspace_dir": str(bundle.workspace_dir),
                    "workspace_before_hash": run_result.workspace_before_hash,
                    "workspace_after_hash": run_result.workspace_after_hash,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return HarnessRunResult(
            run_artifacts=run_result,
            tool_catalog=tool_catalog,
            raw_trace=raw_trace,
            normalization=normalization,
            bundle_paths=bundle,
        )

    def _resolve_tool_catalog(
        self,
        task: CodingTask,
        bundle: RunBundlePaths,
        run_result: RawAgentRunResult,
    ) -> AgentToolCatalog | None:
        if run_result.tool_catalog_path is not None:
            return read_tool_catalog(run_result.tool_catalog_path)
        if self._tool_catalog_provider is None:
            return None
        catalog = self._tool_catalog_provider.get_tool_catalog(
            task=task,
            workspace_dir=bundle.workspace_dir,
            run_artifacts=run_result,
        )
        if catalog is not None:
            write_tool_catalog(catalog, bundle.tool_catalog_path)
        return catalog


def _load_raw_trace(run_result: RawAgentRunResult) -> RawAgentTrace:
    if run_result.raw_trace_path is None or run_result.raw_trace_summary_path is None:
        raise ValueError("Run result is missing raw trace artifact paths")
    raw_trace = read_raw_trace(
        run_result.raw_trace_path,
        run_result.raw_trace_summary_path,
    )
    return raw_trace


def _validate_artifact_paths(run_result: RawAgentRunResult, run_dir: Path) -> None:
    expected_root = run_dir.resolve()
    for path_text in (
        run_result.tool_catalog_path,
        run_result.raw_trace_path,
        run_result.raw_trace_summary_path,
        run_result.stdout_path,
        run_result.stderr_path,
        run_result.final_diff_path,
        run_result.verifier_result_path,
    ):
        if path_text is None:
            continue
        path = Path(path_text).resolve()
        try:
            path.relative_to(expected_root)
        except ValueError as exc:
            raise ValueError(f"Artifact path escapes run bundle: {path}") from exc
