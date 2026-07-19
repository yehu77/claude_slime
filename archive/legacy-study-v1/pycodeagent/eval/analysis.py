"""Experiment result analysis: slicing, grouping, and aggregation.

Reads experiment outputs (runs.jsonl, experiment_manifest.json) and provides
structured slicing and grouped aggregation.

API:
    analysis = load_experiment_analysis(exp_dir)
    overall = analysis.overall()
    by_mode = analysis.group_by("mode")
    by_seed = analysis.group_by("seed")
    filtered = analysis.filter(mode="schema_only")
    by_profile = filtered.group_by("profile_id")

All metrics are aligned with compute_metrics() definitions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pycodeagent.eval.metrics import (
    compute_avg_reward,
    compute_avg_tool_calls,
    compute_avg_turns,
    compute_invalid_schema_call_rate,
    compute_pass_at_1,
    compute_patch_apply_success_rate,
    compute_tool_call_parse_error_rate,
)


@dataclass
class RunRecord:
    """A single run record loaded from experiment outputs.

    Contains all fields from runs.jsonl plus convenience accessors
    for common metadata fields.
    """

    task_id: str
    profile_id: str
    status: str
    reward: float
    passed: bool
    turns: int
    tool_calls: int
    output_dir: str
    failure_reason: str
    metadata: dict[str, Any]

    @property
    def seed(self) -> int:
        """Seed value from metadata."""
        return self.metadata.get("seed", 0)

    @property
    def mode(self) -> str:
        """Profile mode from metadata."""
        return self.metadata.get("mode", "unknown")

    @property
    def category(self) -> str:
        """Task category from metadata (empty string if not set)."""
        return self.metadata.get("category", "")

    @property
    def difficulty(self) -> str:
        """Task difficulty from metadata (empty string if not set)."""
        return self.metadata.get("difficulty", "")

    @property
    def verifier_score(self) -> float:
        """Verifier score from metadata."""
        return self.metadata.get("verifier_score", 0.0)

    @property
    def has_patch(self) -> bool:
        """Whether a patch was generated."""
        return self.metadata.get("has_patch", False)

    @property
    def parse_errors(self) -> int:
        """Number of parse errors."""
        return self.metadata.get("parse_errors", 0)

    @property
    def schema_errors(self) -> int:
        """Number of schema errors."""
        return self.metadata.get("schema_errors", 0)

    @property
    def tool_errors(self) -> int:
        """Number of tool errors."""
        return self.metadata.get("tool_errors", 0)

    @property
    def apply_patch_success(self) -> bool:
        """Whether apply_patch succeeded."""
        return self.metadata.get("apply_patch_success", False)

    @property
    def apply_patch_attempted(self) -> bool:
        """Whether apply_patch was attempted."""
        return self.metadata.get("apply_patch_attempted", False)

    @property
    def entered_execution(self) -> bool:
        """Whether the run executed at least one non-finish tool call."""
        return self.metadata.get("entered_execution", False)

    @property
    def clean_run(self) -> bool:
        """Whether the run avoided parse and schema errors."""
        return self.parse_errors == 0 and self.schema_errors == 0

    @property
    def verifier_failed(self) -> bool:
        """Whether the run reached verification but did not pass."""
        return self.failure_reason == "verifier_failed"


def compute_grouped_metrics(runs: list[RunRecord]) -> dict[str, Any]:
    """Compute metrics for a group of runs.

    Delegates to canonical metric functions in metrics.py for consistency.

    Args:
        runs: List of run records.

    Returns:
        Dict with metric values and count.
    """
    n = len(runs)
    if n == 0:
        return {
            "count": 0,
            "pass_at_1": 0.0,
            "avg_reward": 0.0,
            "avg_turns": 0.0,
            "avg_tool_calls": 0.0,
            "parse_error_rate": 0.0,
            "schema_error_rate": 0.0,
            "patch_apply_success_rate": 0.0,
            "entered_execution_rate": 0.0,
            "clean_run_count": 0,
            "clean_run_pass_at_1": 0.0,
            "verifier_failed_rate": 0.0,
        }

    clean_runs = [r for r in runs if r.clean_run]

    # Delegate to canonical metric functions
    return {
        "count": n,
        "pass_at_1": compute_pass_at_1(runs),
        "avg_reward": compute_avg_reward(runs),
        "avg_turns": compute_avg_turns(runs),
        "avg_tool_calls": compute_avg_tool_calls(runs),
        "parse_error_rate": compute_tool_call_parse_error_rate(runs),
        "schema_error_rate": compute_invalid_schema_call_rate(runs),
        "patch_apply_success_rate": compute_patch_apply_success_rate(runs),
        "entered_execution_rate": sum(1 for r in runs if r.entered_execution) / n,
        "clean_run_count": len(clean_runs),
        "clean_run_pass_at_1": compute_pass_at_1(clean_runs),
        "verifier_failed_rate": sum(1 for r in runs if r.verifier_failed) / n,
    }


class ExperimentAnalysis:
    """Analysis layer for experiment outputs.

    Provides:
    - Loading experiment outputs from directory
    - Overall metrics
    - Grouping by any field
    - Filtering before grouping
    - Deterministic, structured results
    """

    def __init__(
        self,
        runs: list[RunRecord],
        manifest: dict[str, Any],
    ) -> None:
        """Initialize analysis with loaded data.

        Args:
            runs: List of run records.
            manifest: Experiment manifest dict.
        """
        # Sort runs for deterministic ordering
        self._runs = sorted(runs, key=lambda r: (r.seed, r.mode, r.task_id))
        self._manifest = manifest

    @property
    def manifest(self) -> dict[str, Any]:
        """The experiment manifest."""
        return self._manifest

    @property
    def runs(self) -> list[RunRecord]:
        """All run records."""
        return list(self._runs)

    def overall(self) -> dict[str, Any]:
        """Compute overall metrics across all runs.

        Returns:
            Dict with all metrics and count.
        """
        return compute_grouped_metrics(self._runs)

    def filter_by(self, **criteria: Any) -> ExperimentAnalysis:
        """Filter runs by field values.

        Supports filtering on:
        - Top-level RunRecord fields (mode, seed, task_id, profile_id, status, etc.)
        - Metadata fields (category, difficulty, etc.)

        Args:
            **criteria: Field name -> value pairs.
                       Values can be single values or list/tuple/set for membership tests.

        Returns:
            New ExperimentAnalysis with filtered runs.

        Examples:
            filtered = analysis.filter_by(mode="schema_only")
            filtered = analysis.filter_by(seed=42)
            filtered = analysis.filter_by(mode=["base", "schema_only"])
            filtered = analysis.filter_by(category="bugfix", seed=42)
        """
        filtered = self._runs
        for key, value in criteria.items():
            if isinstance(value, (list, tuple, set)):
                value_set = set(value)
                filtered = [
                    r for r in filtered
                    if get_run_field(r, key) in value_set
                ]
            else:
                filtered = [
                    r for r in filtered
                    if get_run_field(r, key) == value
                ]
        return ExperimentAnalysis(filtered, self._manifest)

    def filter(self, **criteria: Any) -> ExperimentAnalysis:
        """Filter runs by field values.

        Compatibility alias for filter_by(). See filter_by() for full documentation.

        Args:
            **criteria: Field name -> value pairs.

        Returns:
            New ExperimentAnalysis with filtered runs.
        """
        return self.filter_by(**criteria)

    def group_by(self, key: str) -> dict[str, dict[str, Any]]:
        """Group runs by a field and compute metrics per group.

        Args:
            key: Field to group by. Supports:
                - "profile_id", "mode", "seed", "task_id", "status"
                - metadata fields like "category", "difficulty"

        Returns:
            Dict mapping group key (as string) to metrics dict.
            Keys are sorted for deterministic output.
        """
        groups: dict[str, list[RunRecord]] = {}
        for run in self._runs:
            group_key = str(get_run_field(run, key))
            groups.setdefault(group_key, []).append(run)

        # Sort groups by key for deterministic output
        result: dict[str, dict[str, Any]] = {}
        for group_key in sorted(groups.keys()):
            result[group_key] = compute_grouped_metrics(groups[group_key])

        return result

    def unique_values(self, key: str) -> list[str]:
        """Get sorted unique values for a field.

        Args:
            key: Field name.

        Returns:
            Sorted list of unique values as strings.
        """
        values = set()
        for run in self._runs:
            values.add(str(get_run_field(run, key)))
        return sorted(values)

    def count(self) -> int:
        """Total number of runs."""
        return len(self._runs)

    def failed_runs(self) -> list[RunRecord]:
        """Get all failed runs (not passed or not completed)."""
        return [r for r in self._runs if not r.passed or r.status != "completed"]


def get_run_field(run: RunRecord, key: str) -> Any:
    """Get a field value from a run record.

    Checks top-level fields first, then metadata.

    Args:
        run: The run record.
        key: Field name.

    Returns:
        The field value.
    """
    # Check properties first (mode, seed, category, difficulty, etc.)
    property_map = {
        "mode": run.mode,
        "seed": run.seed,
        "category": run.category,
        "difficulty": run.difficulty,
        "entered_execution": run.entered_execution,
        "clean_run": run.clean_run,
        "verifier_failed": run.verifier_failed,
    }
    if key in property_map:
        return property_map[key]

    # Check top-level fields
    top_level = {
        "task_id": run.task_id,
        "profile_id": run.profile_id,
        "status": run.status,
        "reward": run.reward,
        "passed": run.passed,
        "turns": run.turns,
        "tool_calls": run.tool_calls,
        "output_dir": run.output_dir,
        "failure_reason": run.failure_reason,
    }
    if key in top_level:
        return top_level[key]

    # Fall back to metadata
    return run.metadata.get(key, "")


def load_runs_from_jsonl(path: Path) -> list[RunRecord]:
    """Load run records from a runs.jsonl file.

    Args:
        path: Path to runs.jsonl.

    Returns:
        List of RunRecord objects.
    """
    runs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            runs.append(RunRecord(
                task_id=data["task_id"],
                profile_id=data["profile_id"],
                status=data["status"],
                reward=data["reward"],
                passed=data["passed"],
                turns=data["turns"],
                tool_calls=data["tool_calls"],
                output_dir=data.get("output_dir", ""),
                failure_reason=data.get("failure_reason", ""),
                metadata=data.get("metadata", {}),
            ))
    return runs


def load_experiment_analysis(exp_dir: str | Path) -> ExperimentAnalysis:
    """Load experiment analysis from an experiment output directory.

    Reads:
    - runs.jsonl for run records
    - experiment_manifest.json for manifest

    Args:
        exp_dir: Path to experiment output directory.

    Returns:
        ExperimentAnalysis instance.
    """
    exp_dir = Path(exp_dir)

    # Load runs
    runs_path = exp_dir / "runs.jsonl"
    if not runs_path.exists():
        raise FileNotFoundError(f"runs.jsonl not found in {exp_dir}")
    runs = load_runs_from_jsonl(runs_path)

    # Load manifest
    manifest_path = exp_dir / "experiment_manifest.json"
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {}

    return ExperimentAnalysis(runs, manifest)


def load_experiment_runs(exp_dir: str | Path) -> list[RunRecord]:
    """Load run records from an experiment output directory.

    Convenience function for when you just need the runs.

    Args:
        exp_dir: Path to experiment output directory.

    Returns:
        List of RunRecord objects.
    """
    exp_dir = Path(exp_dir)
    runs_path = exp_dir / "runs.jsonl"
    if not runs_path.exists():
        raise FileNotFoundError(f"runs.jsonl not found in {exp_dir}")
    return load_runs_from_jsonl(runs_path)


# Backward-compatible aliases for older call sites. New code should use the
# public helpers above.
_compute_grouped_metrics = compute_grouped_metrics
_get_run_field = get_run_field
_load_runs_from_jsonl = load_runs_from_jsonl
