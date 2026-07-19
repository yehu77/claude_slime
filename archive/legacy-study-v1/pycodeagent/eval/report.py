"""Batch report writing.

Writes structured JSON/JSONL outputs:
- summary.json: Batch-level metrics and metadata
- runs.jsonl: Per-run records
- failed_cases.jsonl: Index of failed runs
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pycodeagent.eval.batch_runner import RunSummary


def write_batch_reports(
    output_dir: Path,
    summaries: list[Any],
    metrics: dict[str, float],
    *,
    timestamp: str | None = None,
) -> None:
    """Write all batch reports to output directory.

    Args:
        output_dir: Directory to write reports to.
        summaries: List of run summaries.
        metrics: Aggregated metrics dict.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write summary.json
    write_summary_json(output_dir, summaries, metrics, timestamp=timestamp)

    # Write runs.jsonl
    write_runs_jsonl(output_dir, summaries)

    # Write failed_cases.jsonl
    write_failed_cases_jsonl(output_dir, summaries)


def write_summary_json(
    output_dir: Path,
    summaries: list[Any],
    metrics: dict[str, float],
    *,
    timestamp: str | None = None,
) -> None:
    """Write batch summary JSON.

    Contains:
    - timestamp
    - total runs
    - metrics
    - counts by status
    """
    output_dir = Path(output_dir)

    # Count by status
    status_counts: dict[str, int] = {}
    for s in summaries:
        status_counts[s.status] = status_counts.get(s.status, 0) + 1

    # Count by profile
    profile_counts: dict[str, int] = {}
    for s in summaries:
        profile_counts[s.profile_id] = profile_counts.get(s.profile_id, 0) + 1

    data = {
        "total_runs": len(summaries),
        "metrics": metrics,
        "status_counts": status_counts,
        "profile_counts": profile_counts,
        "passed_count": sum(1 for s in summaries if s.passed),
        "failed_count": sum(1 for s in summaries if not s.passed),
    }
    if timestamp is not None:
        data["timestamp"] = timestamp

    path = output_dir / "summary.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def write_runs_jsonl(output_dir: Path, summaries: list[Any]) -> None:
    """Write per-run records as JSONL.

    Each line is a JSON object with the run summary fields.
    """
    output_dir = Path(output_dir)
    path = output_dir / "runs.jsonl"

    with open(path, "w", encoding="utf-8") as f:
        for s in summaries:
            record = {
                "task_id": s.task_id,
                "profile_id": s.profile_id,
                "status": s.status,
                "reward": s.reward,
                "passed": s.passed,
                "turns": s.turns,
                "tool_calls": s.tool_calls,
                "output_dir": s.output_dir,
                "failure_reason": s.failure_reason,
                "metadata": s.metadata,
            }
            f.write(json.dumps(record) + "\n")


def write_failed_cases_jsonl(output_dir: Path, summaries: list[Any]) -> None:
    """Write failed cases manifest as JSONL.

    Includes only runs where:
    - passed is False, or
    - status is not "completed"
    """
    output_dir = Path(output_dir)
    path = output_dir / "failed_cases.jsonl"

    failed = [
        s
        for s in summaries
        if not s.passed or s.status != "completed"
    ]

    with open(path, "w", encoding="utf-8") as f:
        for s in failed:
            record = {
                "task_id": s.task_id,
                "profile_id": s.profile_id,
                "status": s.status,
                "reward": s.reward,
                "output_dir": s.output_dir,
                "failure_reason": s.failure_reason,
                "passed": s.passed,
            }
            f.write(json.dumps(record) + "\n")


def load_summary_json(path: Path) -> dict[str, Any]:
    """Load summary.json from a batch output directory.

    Args:
        path: Path to summary.json or the batch directory.

    Returns:
        The parsed summary dict.
    """
    path = Path(path)
    if path.is_dir():
        path = path / "summary.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_runs_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load runs.jsonl from a batch output directory.

    Args:
        path: Path to runs.jsonl or the batch directory.

    Returns:
        List of run record dicts.
    """
    path = Path(path)
    if path.is_dir():
        path = path / "runs.jsonl"
    runs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                runs.append(json.loads(line))
    return runs


def load_failed_cases_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load failed_cases.jsonl from a batch output directory.

    Args:
        path: Path to failed_cases.jsonl or the batch directory.

    Returns:
        List of failed case dicts.
    """
    path = Path(path)
    if path.is_dir():
        path = path / "failed_cases.jsonl"
    cases = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases
