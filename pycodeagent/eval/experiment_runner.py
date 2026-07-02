"""Experiment runner for orchestrating task/profile/seed combinations.

Sits above the batch runner and provides:
- Experiment config loading
- Cross-product execution (tasks x profiles x seeds)
- Stable directory layout
- Experiment-level manifest and summary

Example:
    config = ExperimentConfig(...)
    runner = ExperimentRunner(client_factory=...)
    result = runner.run(config)

Or using the convenience function:

    result = run_experiment(config, client_factory=...)
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.eval.experiment_config import ExperimentConfig
from pycodeagent.eval.layout import run_dir_name
from pycodeagent.eval.metrics import compute_metrics
from pycodeagent.eval.report import write_batch_reports
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.tools.bootstrap import (
    ToolStackKind,
    build_native_claude_runtime,
    build_native_codex_runtime,
)
from pycodeagent.trajectory.schema import RunStatus


@dataclass
class RunSummary:
    """Summary of a single run within an experiment.

    Contains the key metrics and paths needed for aggregation
    and failed-case analysis.
    """

    task_id: str
    profile_id: str
    seed: int
    mode: str
    status: str
    reward: float
    passed: bool
    turns: int
    tool_calls: int
    output_dir: str
    failure_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExperimentManifest:
    """Manifest for an experiment run.

    Captures the experiment configuration and run metadata.
    """

    experiment_id: str
    tasks_path: str
    task_count: int
    task_ids: list[str]
    profile_modes: list[str]
    seeds: list[int]
    start_time: str | None
    end_time: str | None
    total_runs: int
    completed_runs: int
    failed_runs: int
    output_dir: str
    runs_dir: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = {
            "experiment_id": self.experiment_id,
            "tasks_path": self.tasks_path,
            "task_count": self.task_count,
            "task_ids": self.task_ids,
            "profile_modes": self.profile_modes,
            "seeds": self.seeds,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_runs": self.total_runs,
            "completed_runs": self.completed_runs,
            "failed_runs": self.failed_runs,
            "output_dir": self.output_dir,
            "runs_dir": self.runs_dir,
        }
        return {key: value for key, value in data.items() if value is not None}


@dataclass
class ExperimentResult:
    """Result of an experiment run.

    Contains all run summaries, the manifest, and aggregated metrics.
    """

    config: ExperimentConfig
    manifest: ExperimentManifest
    summaries: list[RunSummary]
    metrics: dict[str, float]
    output_dir: str


class ExperimentRunner:
    """Runner for executing experiments.

    An experiment runs all combinations of:
    - tasks from a JSONL file
    - profile modes (e.g., base, argument_rename, schema_flat_to_nested)
    - seeds for deterministic profile sampling

    The runner:
    1. Loads tasks and filters if task_ids specified
    2. For each seed, creates a profile sampler
    3. For each mode, samples the profile
    4. For each task, runs the coding task
    5. Aggregates metrics and writes reports
    """

    def __init__(
        self,
        client_factory: Callable[[], Any],
        *,
        tool_stack_kind: ToolStackKind,
    ) -> None:
        """Initialize the experiment runner.

        Args:
            client_factory: Factory function that creates a fresh LLM client
                           for each run.
        """
        self.client_factory = client_factory
        self._tool_stack_kind = tool_stack_kind

    def run(self, config: ExperimentConfig) -> ExperimentResult:
        """Run the experiment.

        Args:
            config: Experiment configuration.

        Returns:
            ExperimentResult with all summaries and metrics.
        """
        # Create output directories
        output_dir = config.get_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        runs_dir = config.get_runs_dir()
        runs_dir.mkdir(parents=True, exist_ok=True)

        # Save config
        config.save(output_dir / "experiment_config.json")

        # Load tasks
        tasks = self._load_tasks(config)

        # Get default runtime
        family = "claude" if self._tool_stack_kind == "native_claude" else "codex"
        if self._tool_stack_kind == "native_claude":
            _, _, runtime = build_native_claude_runtime()
        else:
            _, _, runtime = build_native_codex_runtime()

        # Run all combinations
        summaries: list[RunSummary] = []

        # Deterministic iteration order: seed -> mode -> task
        for seed in sorted(config.seeds):
            sampler = ToolProfileSampler(seed=seed, family=family)

            for mode in config.profile_modes:
                expected_profile = sampler.sample(mode)
                profile_id = expected_profile.profile_id

                mode_dir = config.get_mode_dir(seed, mode)
                mode_dir.mkdir(parents=True, exist_ok=True)

                for task in tasks:
                    # Create output directory for this run
                    run_dir = mode_dir / run_dir_name(task.task_id, profile_id)

                    # Create fresh client for this run
                    client = self.client_factory()

                    # Run the task
                    trajectory = run_coding_task(
                        task,
                        client,
                        run_dir,
                        runtime=runtime,
                        profile_mode=mode,
                        profile_seed=seed,
                        tool_stack_kind=self._tool_stack_kind,
                    )
                    if trajectory.tool_profile_id != profile_id:
                        raise ValueError(
                            "Runtime returned unexpected tool_profile_id: "
                            f"expected {profile_id}, got {trajectory.tool_profile_id}"
                        )

                    # Extract summary
                    summary = self._extract_summary(
                        trajectory=trajectory,
                        task_id=task.task_id,
                        profile_id=profile_id,
                        seed=seed,
                        mode=mode,
                        output_dir=str(run_dir),
                        task_metadata=task.metadata,
                    )
                    summaries.append(summary)

        # Compute metrics
        metrics = compute_metrics(summaries)

        # Build manifest
        manifest = ExperimentManifest(
            experiment_id=config.experiment_id,
            tasks_path=config.tasks_path,
            task_count=len(tasks),
            task_ids=[t.task_id for t in tasks],
            profile_modes=config.profile_modes,
            seeds=config.seeds,
            start_time=None,
            end_time=None,
            total_runs=len(summaries),
            completed_runs=sum(1 for s in summaries if s.status == "completed"),
            failed_runs=sum(1 for s in summaries if s.status != "completed"),
            output_dir=str(output_dir),
            runs_dir=str(runs_dir),
        )

        # Write reports
        self._write_experiment_reports(output_dir, summaries, metrics, manifest)

        return ExperimentResult(
            config=config,
            manifest=manifest,
            summaries=summaries,
            metrics=metrics,
            output_dir=str(output_dir),
        )

    def build_runtime_observed_bundle(
        self,
        result: ExperimentResult,
        *,
        output_dir_override: str | Path | None = None,
        filter_config: Any | None = None,
        split: str = "train",
        max_length: int = 2048,
        batch_size: int = 8,
        learning_rate: float = 1e-4,
        max_steps: int = 1000,
        seed: int = 42,
        tokenizer: Any | None = None,
        tokenizer_config: Any | None = None,
        fake_tokenizer_config: Any | None = None,
        run_id: str = "runtime_observed_experiment_train",
    ) -> Any:
        """Build a runtime-observed post-run bundle from an experiment output."""
        from pycodeagent.eval.runtime_observed_postrun import (
            prepare_study_runtime_observed_bundle,
        )

        bundle_root = (
            Path(output_dir_override)
            if output_dir_override is not None
            else Path(result.output_dir) / "runtime_observed_bundle"
        )
        return prepare_study_runtime_observed_bundle(
            result.output_dir,
            bundle_root,
            source_type="experiment",
            filter_config=filter_config,
            split=split,
            max_length=max_length,
            batch_size=batch_size,
            learning_rate=learning_rate,
            max_steps=max_steps,
            seed=seed,
            tokenizer=tokenizer,
            tokenizer_config=tokenizer_config,
            fake_tokenizer_config=fake_tokenizer_config,
            run_id=run_id,
        )

    def _load_tasks(self, config: ExperimentConfig) -> list[CodingTask]:
        """Load and filter tasks from config.

        Args:
            config: Experiment config.

        Returns:
            List of tasks to run.
        """
        tasks = CodingTask.from_jsonl(Path(config.tasks_path))

        # Filter by task_ids if specified
        if config.task_ids is not None:
            task_id_set = set(config.task_ids)
            tasks = [t for t in tasks if t.task_id in task_id_set]

        # Apply max_tasks limit
        if config.max_tasks is not None:
            tasks = tasks[: config.max_tasks]

        # Sort by task_id for deterministic order
        tasks = sorted(tasks, key=lambda t: t.task_id)

        return tasks

    def _extract_summary(
        self,
        trajectory: Any,
        task_id: str,
        profile_id: str,
        seed: int,
        mode: str,
        output_dir: str,
        task_metadata: dict[str, Any] | None = None,
    ) -> RunSummary:
        """Extract a run summary from a trajectory."""
        task_metadata = task_metadata or {}
        # Count assistant turns
        turns = sum(1 for msg in trajectory.messages if msg.role.value == "assistant")

        # Count tool calls
        tool_calls = len(trajectory.tool_calls)

        # Determine if passed
        passed = trajectory.verifier.passed if trajectory.verifier else False

        # Detect parse errors from stop_detail
        stop_detail = trajectory.metadata.get("stop_detail", "")
        has_parse_error = "Parse errors:" in stop_detail or trajectory.metadata.get("parse_errors", 0) > 0

        # Determine failure reason
        failure_reason = ""
        setup_error = trajectory.metadata.get("setup_error", "")
        llm_error_type = trajectory.metadata.get("llm_error_type", "")

        if setup_error:
            failure_reason = setup_error
        elif llm_error_type:
            failure_reason = "llm_error"
        elif has_parse_error:
            failure_reason = "parse_error"
        elif trajectory.status != RunStatus.COMPLETED:
            failure_reason = trajectory.status.value
        elif not passed:
            failure_reason = "verifier_failed"

        # Count schema/validation errors
        schema_error_types = {"argument_mapping", "argument_mapping_unexpected"}
        schema_errors = sum(
            1 for obs in trajectory.observations
            if obs.result.is_error and obs.result.metadata.get("error_type") in schema_error_types
        )

        # Check for apply_patch outcomes
        apply_patch_success = False
        apply_patch_attempted = False
        entered_execution = False
        provider_info = trajectory.metadata.get("provider", {})
        if not isinstance(provider_info, dict):
            provider_info = {}
        for obs in trajectory.observations:
            if obs.canonical_name != "finish" and obs.tool_name != "finish":
                entered_execution = True
            if obs.canonical_name == "apply_patch" or obs.tool_name == "apply_patch":
                apply_patch_attempted = True
                if obs.result.ok:
                    apply_patch_success = True

        return RunSummary(
            task_id=task_id,
            profile_id=profile_id,
            seed=seed,
            mode=mode,
            status=trajectory.status.value,
            reward=trajectory.reward,
            passed=passed,
            turns=turns,
            tool_calls=tool_calls,
            output_dir=output_dir,
            failure_reason=failure_reason,
            metadata={
                "seed": seed,
                "mode": mode,
                "verifier_score": trajectory.verifier.score if trajectory.verifier else 0.0,
                "has_patch": bool(trajectory.final_diff.strip()),
                "parse_errors": 1 if has_parse_error else 0,
                "llm_error": trajectory.metadata.get("llm_error", ""),
                "llm_error_type": llm_error_type,
                "tool_errors": sum(
                    1 for obs in trajectory.observations if obs.result.is_error
                ),
                "schema_errors": schema_errors,
                "entered_execution": entered_execution,
                "apply_patch_attempted": apply_patch_attempted,
                "apply_patch_success": apply_patch_success,
                "provider_kind": provider_info.get("provider_kind"),
                "client_mode": provider_info.get("client_mode"),
                "model": provider_info.get("model"),
                "base_url": provider_info.get("base_url"),
                # Include task metadata (category, difficulty, etc.) for analysis
                **task_metadata,
            },
        )

    def _write_experiment_reports(
        self,
        output_dir: Path,
        summaries: list[RunSummary],
        metrics: dict[str, float],
        manifest: ExperimentManifest,
    ) -> None:
        """Write all experiment reports.

        Writes:
        - experiment_manifest.json
        - summary.json (via write_batch_reports)
        - runs.jsonl
        - failed_cases.jsonl
        """
        output_dir = Path(output_dir)

        # Write manifest
        manifest_path = output_dir / "experiment_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest.to_dict(), f, indent=2)

        # Convert summaries to batch-runner format for reuse
        # The RunSummary here has extra fields (seed, mode) but is compatible
        # with write_batch_reports which only uses the shared fields
        write_batch_reports(output_dir, summaries, metrics)


def run_experiment(
    config: ExperimentConfig,
    client_factory: Callable[[], Any],
) -> ExperimentResult:
    """Convenience function to run an experiment.

    Args:
        config: Experiment configuration.
        client_factory: Factory function that creates a fresh LLM client.

    Returns:
        ExperimentResult with all summaries and metrics.
    """
    runner = ExperimentRunner(client_factory)
    return runner.run(config)
