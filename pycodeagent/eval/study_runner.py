"""Mutation sensitivity study runner.

Orchestrates multiple experiments (one per profile mode) and computes
structured comparisons against a baseline mode.

Reuses ExperimentRunner for actual execution and ExperimentAnalysis
for metric computation.

Example:
    runner = MutationStudyRunner(client_factory=my_client_factory)
    result = runner.run(study_config)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pycodeagent.eval.analysis import (
    RunRecord,
    compute_grouped_metrics,
    load_runs_from_jsonl as load_analysis_runs_jsonl,
)
from pycodeagent.eval.experiment_config import ExperimentConfig
from pycodeagent.eval.experiment_runner import (
    ExperimentManifest,
    ExperimentResult,
    ExperimentRunner,
    RunSummary,
)
from pycodeagent.eval.layout import experiment_dir_name
from pycodeagent.eval.metrics import compute_metrics
from pycodeagent.eval.report import load_runs_jsonl, load_summary_json
from pycodeagent.eval.study_config import StudyConfig


@dataclass
class ModeComparison:
    """Comparison of a single mode against the baseline.

    All delta fields are (mode_value - baseline_value).
    """

    mode: str
    count: int
    pass_at_1: float
    avg_reward: float
    parse_error_rate: float
    schema_error_rate: float
    patch_apply_success_rate: float
    entered_execution_rate: float
    clean_run_pass_at_1: float
    verifier_failed_rate: float
    delta_pass_at_1: float
    delta_avg_reward: float
    delta_parse_error_rate: float
    delta_schema_error_rate: float
    delta_patch_apply_success_rate: float
    delta_entered_execution_rate: float
    delta_clean_run_pass_at_1: float
    delta_verifier_failed_rate: float


@dataclass
class SeedComparison:
    """Metrics for a single seed across all modes."""

    seed: int
    count: int
    pass_at_1: float
    avg_reward: float
    parse_error_rate: float
    schema_error_rate: float
    entered_execution_rate: float
    clean_run_pass_at_1: float
    verifier_failed_rate: float


@dataclass
class SeedVariability:
    """Variability of metrics across seeds for a given mode."""

    mode: str
    seed_count: int
    pass_at_1_values: list[float]
    avg_reward_values: list[float]
    pass_at_1_range: float
    avg_reward_range: float


@dataclass
class StudyResult:
    """Result of a mutation sensitivity study.

    Contains:
    - The study config
    - Per-experiment results
    - Baseline metrics
    - Mode comparisons (each mutated mode vs baseline)
    - Seed comparisons
    - Seed variability summaries
    - Output directory
    """

    config: StudyConfig
    experiment_results: dict[str, ExperimentResult]
    baseline_metrics: dict[str, Any]
    mode_comparisons: list[ModeComparison]
    seed_comparisons: list[SeedComparison]
    seed_variability: list[SeedVariability]
    output_dir: str
    task_count: int


class MutationStudyRunner:
    """Runner for mutation sensitivity studies.

    Runs one experiment per profile mode, then computes structured
    comparisons against the baseline mode.
    """

    def __init__(
        self,
        client_factory: Callable[[], Any],
    ) -> None:
        """Initialize the study runner.

        Args:
            client_factory: Factory function that creates a fresh LLM client.
        """
        self.client_factory = client_factory

    def run(
        self,
        config: StudyConfig,
        *,
        output_dir_override: str | Path | None = None,
    ) -> StudyResult:
        """Run the mutation sensitivity study.

        Args:
            config: Study configuration.
            output_dir_override: Optional override for the final output directory.
                               If provided, outputs are written here instead of
                               config.get_output_dir(). The study_id is NOT changed.

        Returns:
            StudyResult with comparisons and experiment outputs.
        """
        config.validate_baseline()

        # Use override if provided, otherwise use config's default
        if output_dir_override is not None:
            output_dir = Path(output_dir_override)
        else:
            output_dir = config.get_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        experiments_dir = output_dir / "experiments"
        experiments_dir.mkdir(parents=True, exist_ok=True)

        # Run one experiment per profile mode
        experiment_results: dict[str, ExperimentResult] = {}
        all_runs: dict[str, list[RunRecord]] = {}

        for mode in config.profile_modes:
            exp_id = f"{config.study_id}__{mode}"
            exp_dir = experiment_dir_name(exp_id, mode)
            exp_config = ExperimentConfig(
                experiment_id=exp_dir,
                tasks_path=config.tasks_path,
                profile_modes=[mode],
                seeds=config.seeds,
                output_root=str(experiments_dir),
                max_tasks=config.max_tasks,
                task_ids=config.task_ids,
                notes=f"Study {config.study_id}, mode={mode}",
                metadata={
                    "study_id": config.study_id,
                    "logical_experiment_id": exp_id,
                    "mode": mode,
                },
            )

            exp_result = self._load_completed_experiment(exp_config)
            if exp_result is None:
                runner = ExperimentRunner(self.client_factory)
                exp_result = runner.run(exp_config)
            experiment_results[mode] = exp_result

            # Load run records for analysis
            runs_dir = exp_result.manifest.runs_dir
            runs_path = Path(runs_dir).parent / "runs.jsonl"
            # The experiment runner writes runs.jsonl to output_dir
            runs_path = Path(exp_result.output_dir) / "runs.jsonl"
            if runs_path.exists():
                mode_runs = load_analysis_runs_jsonl(runs_path)
            else:
                # Build RunRecords from summaries
                mode_runs = self._summaries_to_run_records(exp_result)
            all_runs[mode] = mode_runs

        # Compute task count (from any experiment)
        task_count = experiment_results[config.baseline_mode].manifest.task_count

        # Compute baseline metrics
        baseline_runs = all_runs.get(config.baseline_mode, [])
        baseline_metrics = self._compute_metrics(baseline_runs)

        # Compute mode comparisons
        mode_comparisons = self._compute_mode_comparisons(
            baseline_runs=baseline_runs,
            all_runs=all_runs,
            baseline_mode=config.baseline_mode,
        )

        # Compute seed comparisons (across all modes)
        all_runs_flat = [r for runs in all_runs.values() for r in runs]
        seed_comparisons = self._compute_seed_comparisons(all_runs_flat)

        # Compute seed variability per mode
        seed_variability = self._compute_seed_variability(all_runs, config.seeds)

        return StudyResult(
            config=config,
            experiment_results=experiment_results,
            baseline_metrics=baseline_metrics,
            mode_comparisons=mode_comparisons,
            seed_comparisons=seed_comparisons,
            seed_variability=seed_variability,
            output_dir=str(output_dir),
            task_count=task_count,
        )

    def _load_completed_experiment(
        self,
        config: ExperimentConfig,
    ) -> ExperimentResult | None:
        """Load a completed experiment from disk if it matches the config.

        This makes long studies resumable: re-running a study will skip modes
        whose experiment outputs already contain a complete manifest and run
        records for the same tasks/profile mode/seeds.
        """
        output_dir = config.get_output_dir()
        manifest_path = output_dir / "experiment_manifest.json"
        runs_path = output_dir / "runs.jsonl"
        summary_path = output_dir / "summary.json"

        if not (manifest_path.exists() and runs_path.exists() and summary_path.exists()):
            return None

        with open(manifest_path, encoding="utf-8") as f:
            manifest_data = json.load(f)

        if manifest_data.get("tasks_path") != config.tasks_path:
            return None
        if manifest_data.get("profile_modes") != config.profile_modes:
            return None
        if manifest_data.get("seeds") != config.seeds:
            return None

        expected_runs = manifest_data.get("task_count", 0) * len(config.seeds)
        runs = load_runs_jsonl(output_dir)
        if manifest_data.get("total_runs") != expected_runs:
            return None
        if len(runs) != expected_runs:
            return None

        summaries = [
            RunSummary(
                task_id=r["task_id"],
                profile_id=r["profile_id"],
                seed=r.get("metadata", {}).get("seed", config.seeds[0] if config.seeds else 0),
                mode=r.get("metadata", {}).get("mode", config.profile_modes[0]),
                status=r["status"],
                reward=r["reward"],
                passed=r["passed"],
                turns=r["turns"],
                tool_calls=r["tool_calls"],
                output_dir=r["output_dir"],
                failure_reason=r.get("failure_reason", ""),
                metadata=r.get("metadata", {}),
            )
            for r in runs
        ]

        manifest = ExperimentManifest(**manifest_data)
        metrics = load_summary_json(output_dir).get("metrics") or compute_metrics(summaries)

        return ExperimentResult(
            config=config,
            manifest=manifest,
            summaries=summaries,
            metrics=metrics,
            output_dir=str(output_dir),
        )

    def _summaries_to_run_records(
        self, exp_result: ExperimentResult
    ) -> list[RunRecord]:
        """Convert experiment RunSummary objects to RunRecord objects.

        Args:
            exp_result: Experiment result with summaries.

        Returns:
            List of RunRecord objects.
        """
        records = []
        for s in exp_result.summaries:
            records.append(
                RunRecord(
                    task_id=s.task_id,
                    profile_id=s.profile_id,
                    status=s.status,
                    reward=s.reward,
                    passed=s.passed,
                    turns=s.turns,
                    tool_calls=s.tool_calls,
                    output_dir=s.output_dir,
                    failure_reason=s.failure_reason,
                    metadata=s.metadata,
                )
            )
        return records

    def _compute_metrics(self, runs: list[RunRecord]) -> dict[str, Any]:
        """Compute aggregate metrics for a set of runs.

        Args:
            runs: List of run records.

        Returns:
            Dict with metric values.
        """
        n = len(runs)
        if n == 0:
            return {
                "count": 0,
                "pass_at_1": 0.0,
                "avg_reward": 0.0,
                "parse_error_rate": 0.0,
                "schema_error_rate": 0.0,
                "patch_apply_success_rate": 0.0,
                "entered_execution_rate": 0.0,
                "clean_run_count": 0,
                "clean_run_pass_at_1": 0.0,
                "verifier_failed_rate": 0.0,
            }
        return compute_grouped_metrics(runs)

    def _compute_mode_comparisons(
        self,
        baseline_runs: list[RunRecord],
        all_runs: dict[str, list[RunRecord]],
        baseline_mode: str,
    ) -> list[ModeComparison]:
        """Compute per-mode comparisons against baseline.

        Args:
            baseline_runs: Run records for the baseline mode.
            all_runs: Dict mapping mode name to run records.
            baseline_mode: Name of the baseline mode.

        Returns:
            List of ModeComparison objects.
        """
        baseline_metrics = self._compute_metrics(baseline_runs)
        comparisons: list[ModeComparison] = []

        for mode, runs in sorted(all_runs.items()):
            metrics = self._compute_metrics(runs)
            comparisons.append(
                ModeComparison(
                    mode=mode,
                    count=metrics["count"],
                    pass_at_1=metrics["pass_at_1"],
                    avg_reward=metrics["avg_reward"],
                    parse_error_rate=metrics["parse_error_rate"],
                    schema_error_rate=metrics["schema_error_rate"],
                    patch_apply_success_rate=metrics["patch_apply_success_rate"],
                    entered_execution_rate=metrics["entered_execution_rate"],
                    clean_run_pass_at_1=metrics["clean_run_pass_at_1"],
                    verifier_failed_rate=metrics["verifier_failed_rate"],
                    delta_pass_at_1=metrics["pass_at_1"] - baseline_metrics["pass_at_1"],
                    delta_avg_reward=metrics["avg_reward"] - baseline_metrics["avg_reward"],
                    delta_parse_error_rate=metrics["parse_error_rate"] - baseline_metrics["parse_error_rate"],
                    delta_schema_error_rate=metrics["schema_error_rate"] - baseline_metrics["schema_error_rate"],
                    delta_patch_apply_success_rate=metrics["patch_apply_success_rate"] - baseline_metrics["patch_apply_success_rate"],
                    delta_entered_execution_rate=metrics["entered_execution_rate"] - baseline_metrics["entered_execution_rate"],
                    delta_clean_run_pass_at_1=metrics["clean_run_pass_at_1"] - baseline_metrics["clean_run_pass_at_1"],
                    delta_verifier_failed_rate=metrics["verifier_failed_rate"] - baseline_metrics["verifier_failed_rate"],
                )
            )

        return comparisons

    def _compute_seed_comparisons(
        self, runs: list[RunRecord]
    ) -> list[SeedComparison]:
        """Compute metrics per seed across all modes.

        Args:
            runs: All run records.

        Returns:
            List of SeedComparison objects.
        """
        by_seed: dict[int, list[RunRecord]] = {}
        for r in runs:
            by_seed.setdefault(r.seed, []).append(r)

        comparisons: list[SeedComparison] = []
        for seed in sorted(by_seed.keys()):
            metrics = self._compute_metrics(by_seed[seed])
            comparisons.append(
                SeedComparison(
                    seed=seed,
                    count=metrics["count"],
                    pass_at_1=metrics["pass_at_1"],
                    avg_reward=metrics["avg_reward"],
                    parse_error_rate=metrics["parse_error_rate"],
                    schema_error_rate=metrics["schema_error_rate"],
                    entered_execution_rate=metrics["entered_execution_rate"],
                    clean_run_pass_at_1=metrics["clean_run_pass_at_1"],
                    verifier_failed_rate=metrics["verifier_failed_rate"],
                )
            )

        return comparisons

    def _compute_seed_variability(
        self,
        all_runs: dict[str, list[RunRecord]],
        seeds: list[int],
    ) -> list[SeedVariability]:
        """Compute seed variability per mode.

        For each mode, computes the range (max - min) of pass_at_1 and
        avg_reward across seeds.

        Args:
            all_runs: Dict mapping mode name to run records.
            seeds: List of seeds used.

        Returns:
            List of SeedVariability objects.
        """
        results: list[SeedVariability] = []

        for mode, runs in sorted(all_runs.items()):
            # Group by seed
            by_seed: dict[int, list[RunRecord]] = {}
            for r in runs:
                by_seed.setdefault(r.seed, []).append(r)

            pass_at_1_values: list[float] = []
            avg_reward_values: list[float] = []

            for seed in sorted(seeds):
                seed_runs = by_seed.get(seed, [])
                if seed_runs:
                    metrics = self._compute_metrics(seed_runs)
                    pass_at_1_values.append(metrics["pass_at_1"])
                    avg_reward_values.append(metrics["avg_reward"])

            if pass_at_1_values:
                results.append(
                    SeedVariability(
                        mode=mode,
                        seed_count=len(pass_at_1_values),
                        pass_at_1_values=pass_at_1_values,
                        avg_reward_values=avg_reward_values,
                        pass_at_1_range=max(pass_at_1_values) - min(pass_at_1_values),
                        avg_reward_range=max(avg_reward_values) - min(avg_reward_values),
                    )
                )

        return results
