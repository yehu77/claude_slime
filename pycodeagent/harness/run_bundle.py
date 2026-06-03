"""Run bundle layout helpers for scaffold artifacts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pydantic import BaseModel

from pycodeagent.env.task import CodingTask


class RunBundlePaths(BaseModel):
    """Canonical paths for one harness-owned run bundle."""

    run_dir: Path
    workspace_dir: Path
    stdout_path: Path
    stderr_path: Path
    task_json_path: Path
    workspace_manifest_path: Path
    tool_catalog_path: Path
    raw_trace_path: Path
    raw_trace_summary_path: Path
    canonical_trace_path: Path
    normalization_report_path: Path
    verifier_path: Path
    final_diff_path: Path
    adapter_metadata_path: Path


def create_run_bundle_paths(base_dir: str | Path, *, run_id: str) -> RunBundlePaths:
    """Create the directory skeleton for one run."""
    run_dir = Path(base_dir).resolve() / run_id
    workspace_dir = run_dir / "workspace"
    run_dir.mkdir(parents=True, exist_ok=True)
    return RunBundlePaths(
        run_dir=run_dir,
        workspace_dir=workspace_dir,
        stdout_path=run_dir / "stdout.log",
        stderr_path=run_dir / "stderr.log",
        task_json_path=run_dir / "task.json",
        workspace_manifest_path=run_dir / "workspace_manifest.json",
        tool_catalog_path=run_dir / "tool_catalog.json",
        raw_trace_path=run_dir / "raw_trace.jsonl",
        raw_trace_summary_path=run_dir / "raw_trace_summary.json",
        canonical_trace_path=run_dir / "canonical_trace.json",
        normalization_report_path=run_dir / "normalization_report.json",
        verifier_path=run_dir / "verifier.json",
        final_diff_path=run_dir / "final.diff",
        adapter_metadata_path=run_dir / "adapter_metadata.json",
    )


def materialize_workspace(task: CodingTask, workspace_dir: Path) -> None:
    """Copy the task repo into an isolated workspace directory."""
    if workspace_dir.exists():
        shutil.rmtree(workspace_dir, ignore_errors=True)
    shutil.copytree(task.repo_path, workspace_dir, dirs_exist_ok=True)


def write_task_artifact(task: CodingTask, path: Path) -> Path:
    """Write task.json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(task.model_dump(mode="json"), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return path
