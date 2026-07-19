"""Batch runner for executing multiple task/profile combinations.

Provides:
- BatchRunner class for configurable batch execution
- run_batch() convenience function
- RunSummary and BatchResult data structures
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pycodeagent.env.task import CodingTask
from pycodeagent.eval.layout import run_dir_name
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.tools.bootstrap import (
    ToolStackKind,
    build_native_claude_runtime,
    build_native_codex_runtime,
)
from pycodeagent.trajectory.schema import RunStatus, Trajectory


@dataclass
class RunSummary:
    """Summary of a single run within a batch.

    Contains the key metrics and paths needed for aggregation
    and failed-case analysis.
    """

    task_id: str
    profile_id: str
    status: str
    reward: float
    passed: bool
    turns: int
    tool_calls: int
    output_dir: str
    failure_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchResult:
    """Result of a batch run.

    Contains all run summaries and the aggregated metrics.
    """

    summaries: list[RunSummary]
    metrics: dict[str, float]
    output_dir: str
    num_tasks: int
    num_profiles: int
    total_runs: int


class BatchRunner:
    """Runner for executing multiple task/profile combinations.

    Example:
        runner = BatchRunner(client_factory=lambda: FakeLLMClient(responses))
        result = runner.run(
            tasks_path="datasets/tasks/toy_tasks.jsonl",
            profile_modes=["base", "argument_rename", "schema_flat_to_nested"],
            seed=42,
            output_dir="runs/batch_001",
        )
    """

    def __init__(
        self,
        client_factory: Callable[[], Any],
        *,
        tool_stack_kind: ToolStackKind,
        sampler: ToolProfileSampler | None = None,
    ) -> None:
        """Initialize the batch runner.

        Args:
            client_factory: Factory function that creates a fresh LLM client
                           for each run.
            sampler: Optional ToolProfileSampler for generating profiles.
                    If None, creates one with seed=0.
        """
        self.client_factory = client_factory
        self._tool_stack_kind = tool_stack_kind
        self._sampler = sampler

    def run(
        self,
        tasks_path: str | Path,
        profile_modes: list[str],
        seed: int,
        output_dir: str | Path,
        *,
        max_tasks: int | None = None,
    ) -> BatchResult:
        """Run all task/profile combinations.

        Args:
            tasks_path: Path to JSONL file with task definitions.
            profile_modes: List of profile modes to run (e.g.,
                ["base", "argument_rename", "schema_flat_to_nested"]).
            seed: Random seed for profile sampling.
            output_dir: Directory to store all run outputs.
            max_tasks: Optional limit on number of tasks to run (for testing).

        Returns:
            BatchResult with all run summaries and aggregated metrics.
        """
        from pycodeagent.env.coding_env import run_coding_task
        from pycodeagent.eval.metrics import compute_metrics
        from pycodeagent.eval.report import write_batch_reports

        tasks_path = Path(tasks_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load tasks
        tasks = CodingTask.from_jsonl(tasks_path)
        if max_tasks is not None:
            tasks = tasks[:max_tasks]

        # Create sampler for this batch
        family = "claude" if self._tool_stack_kind == "native_claude" else "codex"
        sampler = self._sampler or ToolProfileSampler(seed=seed, family=family)
        if self._tool_stack_kind == "native_claude":
            _, _, runtime = build_native_claude_runtime()
        else:
            _, _, runtime = build_native_codex_runtime()

        # Run all combinations
        summaries: list[RunSummary] = []

        for task in tasks:
            for mode in profile_modes:
                expected_profile = sampler.sample(mode)
                profile_id = expected_profile.profile_id

                # Create output directory for this run
                run_dir = output_dir / run_dir_name(task.task_id, profile_id)

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
                    output_dir=str(run_dir),
                )
                summaries.append(summary)

        # Compute metrics
        metrics = compute_metrics(summaries)

        # Write reports
        write_batch_reports(output_dir, summaries, metrics)

        return BatchResult(
            summaries=summaries,
            metrics=metrics,
            output_dir=str(output_dir),
            num_tasks=len(tasks),
            num_profiles=len(profile_modes),
            total_runs=len(summaries),
        )

    def _extract_summary(
        self,
        trajectory: Trajectory,
        task_id: str,
        profile_id: str,
        output_dir: str,
    ) -> RunSummary:
        """Extract a run summary from a trajectory."""
        # Count assistant turns
        turns = sum(1 for msg in trajectory.messages if msg.role.value == "assistant")

        # Count tool calls
        tool_calls = len(trajectory.tool_calls)

        # Determine if passed
        passed = trajectory.verifier.passed if trajectory.verifier else False

        # Detect parse errors from stop_detail
        stop_detail = trajectory.metadata.get("stop_detail", "")
        has_parse_error = "Parse errors:" in stop_detail or trajectory.metadata.get("parse_errors", 0) > 0

        # Determine failure reason - prefer concrete reasons over generic status
        failure_reason = ""
        setup_error = trajectory.metadata.get("setup_error", "")
        llm_error_type = trajectory.metadata.get("llm_error_type", "")

        if setup_error:
            # Concrete setup failure (workspace copy, etc.)
            failure_reason = setup_error
        elif llm_error_type:
            failure_reason = "llm_error"
        elif has_parse_error:
            # Parse error in tool call parsing
            failure_reason = "parse_error"
        elif trajectory.status != RunStatus.COMPLETED:
            # Other non-completed status (timeout, etc.)
            failure_reason = trajectory.status.value
        elif not passed:
            # Verifier failed
            failure_reason = "verifier_failed"

        # Count schema/validation errors specifically
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
            status=trajectory.status.value,
            reward=trajectory.reward,
            passed=passed,
            turns=turns,
            tool_calls=tool_calls,
            output_dir=output_dir,
            failure_reason=failure_reason,
            metadata={
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
            },
        )


def run_batch(
    tasks_path: str | Path,
    profile_modes: list[str],
    seed: int,
    output_dir: str | Path,
    client_factory: Callable[[], Any],
    *,
    max_tasks: int | None = None,
) -> BatchResult:
    """Convenience function to run a batch.

    Args:
        tasks_path: Path to JSONL file with task definitions.
        profile_modes: List of profile modes to run.
        seed: Random seed for profile sampling.
        output_dir: Directory to store all run outputs.
        client_factory: Factory function that creates a fresh LLM client.
        max_tasks: Optional limit on number of tasks to run.

    Returns:
        BatchResult with all run summaries and aggregated metrics.
    """
    runner = BatchRunner(client_factory)
    return runner.run(
        tasks_path=tasks_path,
        profile_modes=profile_modes,
        seed=seed,
        output_dir=output_dir,
        max_tasks=max_tasks,
    )
