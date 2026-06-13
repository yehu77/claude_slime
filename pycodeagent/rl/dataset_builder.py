"""Batch rollout dataset builder.

Scans experiment or batch outputs, converts runs into rollout/training records
in bulk, and writes a structured dataset plus manifest.

This module is an adapter/collector layer that reuses the existing:
- Trajectory loading from artifacts
- build_training_sample()
- trajectory_to_slime_rollout()

It does NOT implement tokenization, tensorization, or training logic.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Iterator

from pydantic import ValidationError

from pycodeagent.rl.dataset_manifest import (
    DatasetManifest,
    FilterConfig,
    build_reward_summary,
    build_status_counts,
    build_verifier_counts,
)
from pycodeagent.rl.sample_builder import TrainingSample, build_training_sample
from pycodeagent.rl.slime_rollout import SlimeRolloutRecord, trajectory_to_slime_rollout
from pycodeagent.trajectory.schema import Trajectory


class DatasetBuildResult:
    """Result of building a rollout dataset.

    Attributes:
        output_dir: Path where dataset was written
        manifest: The dataset manifest
        sample_count: Number of samples written
        rollout_count: Number of rollouts written
    """

    def __init__(
        self,
        output_dir: Path,
        manifest: DatasetManifest,
        sample_count: int,
        rollout_count: int,
    ) -> None:
        self.output_dir = output_dir
        self.manifest = manifest
        self.sample_count = sample_count
        self.rollout_count = rollout_count


class TrajectoryLoadError(ValueError):
    """Raised when a run directory contains a malformed trajectory artifact."""


class RolloutDatasetBuilder:
    """Builder for creating rollout/training datasets from experiment outputs.

    This class:
    1. Discovers run directories from experiment/batch outputs
    2. Loads trajectory artifacts
    3. Applies filtering rules
    4. Converts trajectories to rollout records using existing pipeline
    5. Writes structured outputs with manifest

    Example:
        builder = RolloutDatasetBuilder()
        result = builder.build_from_experiment(
            exp_dir="experiments/exp_001",
            output_dir="datasets/ds_001",
            filter_config=FilterConfig(min_reward=0.1, include_failed=False),
        )
    """

    def __init__(self, dataset_id: str | None = None) -> None:
        """Initialize the builder.

        Args:
            dataset_id: Optional dataset ID override. When omitted, a stable
                ID is derived from the input source and filter config at build time.
        """
        self._dataset_id_override = dataset_id
        self.dataset_id = dataset_id

    def build_from_experiment(
        self,
        exp_dir: str | Path,
        output_dir: str | Path,
        *,
        filter_config: FilterConfig | None = None,
    ) -> DatasetBuildResult:
        """Build a dataset from an experiment output directory.

        Args:
            exp_dir: Path to experiment output directory
            output_dir: Path to write dataset outputs
            filter_config: Optional filter configuration

        Returns:
            DatasetBuildResult with manifest and counts
        """
        exp_dir = Path(exp_dir)
        return self._build_from_resolved_run_dirs(
            run_dirs=self._discover_run_dirs(exp_dir),
            output_dir=output_dir,
            source_type="experiment",
            source_path=str(exp_dir),
            dataset_id_source_path=str(exp_dir.resolve()),
            filter_config=filter_config,
        )

    def build_from_batch(
        self,
        batch_dir: str | Path,
        output_dir: str | Path,
        *,
        filter_config: FilterConfig | None = None,
    ) -> DatasetBuildResult:
        """Build a dataset from a batch output directory.

        Args:
            batch_dir: Path to batch output directory
            output_dir: Path to write dataset outputs
            filter_config: Optional filter configuration

        Returns:
            DatasetBuildResult with manifest and counts
        """
        batch_dir = Path(batch_dir)
        return self._build_from_resolved_run_dirs(
            run_dirs=self._discover_run_dirs_from_batch(batch_dir),
            output_dir=output_dir,
            source_type="batch",
            source_path=str(batch_dir),
            dataset_id_source_path=str(batch_dir.resolve()),
            filter_config=filter_config,
        )

    def build_from_run_dirs(
        self,
        run_dirs: list[str | Path],
        output_dir: str | Path,
        *,
        source_type: str = "runs",
        source_path: str = "",
        filter_config: FilterConfig | None = None,
    ) -> DatasetBuildResult:
        """Build a dataset from an explicit list of run directories.

        Args:
            run_dirs: List of run directory paths
            output_dir: Path to write dataset outputs
            source_type: Source type label
            source_path: Source path label
            filter_config: Optional filter configuration

        Returns:
            DatasetBuildResult with manifest and counts
        """
        return self._build_from_resolved_run_dirs(
            run_dirs=run_dirs,
            output_dir=output_dir,
            source_type=source_type,
            source_path=source_path,
            dataset_id_source_path=source_path,
            filter_config=filter_config,
        )

    def _build_from_resolved_run_dirs(
        self,
        *,
        run_dirs: Iterator[Path] | list[str | Path],
        output_dir: str | Path,
        source_type: str,
        source_path: str,
        dataset_id_source_path: str,
        filter_config: FilterConfig | None,
    ) -> DatasetBuildResult:
        """Shared implementation for all dataset-building entrypoints."""
        output_dir = Path(output_dir)
        filter_config = filter_config or FilterConfig()
        resolved_run_dirs = sorted(Path(run_dir) for run_dir in run_dirs)
        dataset_id = self._resolve_dataset_id(
            source_type=source_type,
            source_path=dataset_id_source_path,
            filter_config=filter_config,
            run_dirs=resolved_run_dirs,
        )

        (
            rollouts,
            samples,
            rewards,
            statuses,
            verifier_passed_flags,
            task_ids,
            profile_ids,
        ) = self._collect_dataset_records(resolved_run_dirs, filter_config)

        return self._write_dataset_outputs(
            output_dir=output_dir,
            dataset_id=dataset_id,
            source_type=source_type,
            source_path=source_path,
            filter_config=filter_config,
            rollouts=rollouts,
            samples=samples,
            rewards=rewards,
            statuses=statuses,
            verifier_passed_flags=verifier_passed_flags,
            task_ids=task_ids,
            profile_ids=profile_ids,
        )

    def _resolve_dataset_id(
        self,
        *,
        source_type: str,
        source_path: str,
        filter_config: FilterConfig,
        run_dirs: list[Path],
    ) -> str:
        """Resolve the dataset ID, using a stable hash when not overridden."""
        if self._dataset_id_override:
            self.dataset_id = self._dataset_id_override
            return self.dataset_id

        payload = {
            "version": 1,
            "source_type": source_type,
            "source_path": source_path,
            "filter_config": filter_config.model_dump(mode="json"),
            "run_dirs": [str(run_dir.resolve()) for run_dir in sorted(run_dirs)],
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:12]
        self.dataset_id = f"ds_{digest}"
        return self.dataset_id

    def _collect_dataset_records(
        self,
        run_dirs: list[Path],
        filter_config: FilterConfig,
    ) -> tuple[
        list[SlimeRolloutRecord],
        list[TrainingSample],
        list[float],
        list[str],
        list[bool],
        set[str],
        set[str],
    ]:
        """Load, filter, and convert trajectories into rollout/sample records."""
        rollouts: list[SlimeRolloutRecord] = []
        samples: list[TrainingSample] = []
        rewards: list[float] = []
        statuses: list[str] = []
        verifier_passed_flags: list[bool] = []
        task_ids: set[str] = set()
        profile_ids: set[str] = set()

        for run_dir in run_dirs:
            trajectory = self._load_trajectory(run_dir)
            if trajectory is None:
                continue

            if not self._passes_filters(trajectory, filter_config):
                continue

            rollouts.append(trajectory_to_slime_rollout(trajectory))
            samples.append(build_training_sample(trajectory))

            rewards.append(trajectory.reward)
            statuses.append(trajectory.status.value)
            verifier_passed_flags.append(
                trajectory.verifier.passed if trajectory.verifier else False
            )
            task_ids.add(trajectory.task_id)
            profile_ids.add(trajectory.tool_profile_id)

        return (
            rollouts,
            samples,
            rewards,
            statuses,
            verifier_passed_flags,
            task_ids,
            profile_ids,
        )

    def _write_dataset_outputs(
        self,
        *,
        output_dir: Path,
        dataset_id: str,
        source_type: str,
        source_path: str,
        filter_config: FilterConfig,
        rollouts: list[SlimeRolloutRecord],
        samples: list[TrainingSample],
        rewards: list[float],
        statuses: list[str],
        verifier_passed_flags: list[bool],
        task_ids: set[str],
        profile_ids: set[str],
    ) -> DatasetBuildResult:
        """Write rollouts, samples, and manifest for a prepared dataset."""
        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_jsonl(output_dir / "rollouts.jsonl", rollouts)
        self._write_jsonl(output_dir / "samples.jsonl", samples)

        manifest = DatasetManifest(
            dataset_id=dataset_id,
            source_type=source_type,
            source_path=source_path,
            sample_count=len(samples),
            rollout_count=len(rollouts),
            task_ids=sorted(task_ids),
            profile_ids=sorted(profile_ids),
            reward_summary=build_reward_summary(rewards),
            status_counts=build_status_counts(statuses),
            verifier_counts=build_verifier_counts(verifier_passed_flags),
            filter_config=filter_config,
            output_dir=str(output_dir),
        )
        manifest.save(output_dir / "dataset_manifest.json")

        return DatasetBuildResult(
            output_dir=output_dir,
            manifest=manifest,
            sample_count=len(samples),
            rollout_count=len(rollouts),
        )

    def _discover_run_dirs(self, exp_dir: Path) -> Iterator[Path]:
        """Discover run directories from an experiment output.

        Experiment structure:
        exp_dir/
          runs/
            seed_0/
              base/
                task_001__profile_xxx/
                task_002__profile_xxx/
              schema_only/
                ...
            seed_42/
              ...

        Args:
            exp_dir: Experiment output directory

        Yields:
            Paths to run directories
        """
        runs_dir = exp_dir / "runs"
        if not runs_dir.exists():
            return

        # Walk: runs/seed_X/mode/task__profile/
        for seed_dir in runs_dir.iterdir():
            if not seed_dir.is_dir():
                continue
            for mode_dir in seed_dir.iterdir():
                if not mode_dir.is_dir():
                    continue
                for run_dir in mode_dir.iterdir():
                    if run_dir.is_dir():
                        yield run_dir

    def _discover_run_dirs_from_batch(self, batch_dir: Path) -> Iterator[Path]:
        """Discover run directories from a batch output.

        Real BatchRunner structure (current):
        batch_dir/
          summary.json
          runs.jsonl
          task_001__profile_xxx/
            trajectory.json
          task_002__profile_xxx/
            trajectory.json

        Legacy structure (also supported):
        batch_dir/
          runs/
            task_001__profile_xxx/
            ...

        Args:
            batch_dir: Batch output directory

        Yields:
            Paths to run directories
        """
        # First try real BatchRunner layout (runs directly under batch_dir)
        has_direct_runs = False
        for item in batch_dir.iterdir():
            if item.is_dir() and (item / "trajectory.json").exists():
                has_direct_runs = True
                yield item

        # If no direct runs found, try legacy runs/ subdirectory
        if not has_direct_runs:
            runs_dir = batch_dir / "runs"
            if runs_dir.exists():
                for run_dir in runs_dir.iterdir():
                    if run_dir.is_dir():
                        yield run_dir

    def _load_trajectory(self, run_dir: Path) -> Trajectory | None:
        """Load trajectory from a run directory.

        Args:
            run_dir: Path to run directory

        Returns:
            Trajectory if found, ``None`` when the artifact is absent.

        Raises:
            TrajectoryLoadError: If the artifact exists but is malformed.
        """
        trajectory_path = run_dir / "trajectory.json"
        if not trajectory_path.exists():
            return None

        try:
            with open(trajectory_path, encoding="utf-8") as f:
                data = json.load(f)
            return Trajectory.model_validate(data)
        except json.JSONDecodeError as exc:
            raise TrajectoryLoadError(
                f"Invalid JSON in trajectory artifact: {trajectory_path}"
            ) from exc
        except ValidationError as exc:
            raise TrajectoryLoadError(
                f"Invalid trajectory schema in artifact: {trajectory_path}"
            ) from exc

    def _passes_filters(
        self,
        trajectory: Trajectory,
        filter_config: FilterConfig,
    ) -> bool:
        """Check if a trajectory passes the filter criteria.

        Args:
            trajectory: The trajectory to check
            filter_config: Filter configuration

        Returns:
            True if the trajectory passes all filters
        """
        status = trajectory.status.value

        # Filter by allowed statuses
        if filter_config.allowed_statuses is not None:
            if status not in filter_config.allowed_statuses:
                return False

        # Filter by include_failed
        if not filter_config.include_failed:
            if status != "completed":
                return False

        # Filter by verifier_passed
        if filter_config.verifier_passed is not None:
            if trajectory.verifier is None:
                # No verifier = treat as not passed
                if filter_config.verifier_passed:
                    return False
            elif trajectory.verifier.passed != filter_config.verifier_passed:
                return False

        # Filter by min_reward
        if filter_config.min_reward is not None:
            if trajectory.reward < filter_config.min_reward:
                return False

        # Filter by task_ids
        if filter_config.task_ids is not None:
            if trajectory.task_id not in filter_config.task_ids:
                return False

        # Filter by profile_ids
        if filter_config.profile_ids is not None:
            if trajectory.tool_profile_id not in filter_config.profile_ids:
                return False

        return True

    def _write_jsonl(
        self,
        path: Path,
        records: list[Any],
    ) -> None:
        """Write records to a JSONL file.

        Args:
            path: Output file path
            records: List of records (Pydantic models or dicts)
        """
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = []
        for record in records:
            if hasattr(record, "model_dump_json"):
                line = record.model_dump_json()
            else:
                line = json.dumps(record, separators=(",", ":"))
            lines.append(line)

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Convenience functions


def build_rollout_dataset(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    source_type: str = "experiment",
    filter_config: FilterConfig | None = None,
    dataset_id: str | None = None,
) -> DatasetBuildResult:
    """Build a rollout dataset from a source directory.

    Convenience function that auto-detects source type and builds dataset.

    Args:
        source_dir: Path to source directory (experiment or batch)
        output_dir: Path to write dataset outputs
        source_type: Source type ("experiment" or "batch")
        filter_config: Optional filter configuration
        dataset_id: Optional dataset ID

    Returns:
        DatasetBuildResult with manifest and counts
    """
    builder = RolloutDatasetBuilder(dataset_id=dataset_id)

    if source_type == "experiment":
        return builder.build_from_experiment(
            source_dir, output_dir, filter_config=filter_config
        )
    elif source_type == "batch":
        return builder.build_from_batch(
            source_dir, output_dir, filter_config=filter_config
        )
    else:
        raise ValueError(f"Unknown source_type: {source_type}")


def discover_run_dirs(
    source_dir: str | Path,
    *,
    source_type: str,
) -> list[Path]:
    """Discover concrete run directories for an experiment, batch, or study source."""
    source_dir = Path(source_dir)
    builder = RolloutDatasetBuilder()

    if source_type == "experiment":
        return sorted(builder._discover_run_dirs(source_dir))

    if source_type == "batch":
        return sorted(builder._discover_run_dirs_from_batch(source_dir))

    if source_type == "study":
        experiments_dir = source_dir / "experiments"
        if not experiments_dir.exists():
            raise FileNotFoundError(
                f"Study directory missing experiments/: {experiments_dir}"
            )

        run_dirs: list[Path] = []
        for experiment_dir in sorted(p for p in experiments_dir.iterdir() if p.is_dir()):
            run_dirs.extend(sorted(builder._discover_run_dirs(experiment_dir)))
        return run_dirs

    raise ValueError(f"Unknown source_type: {source_type}")
