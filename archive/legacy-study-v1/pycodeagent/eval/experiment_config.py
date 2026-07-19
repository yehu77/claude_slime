"""Experiment configuration model.

Defines the structure of an experiment: which tasks, which profile modes,
which seeds, and where to put outputs.

The config is:
- JSON-serializable (roundtrip-safe)
- Deterministic (same fields -> same JSON)
- Self-validating (required fields checked)

Timestamps are NOT part of the config definition. They belong in
ExperimentManifest which captures runtime metadata (start_time, end_time).

Example:
    config = ExperimentConfig(
        experiment_id="exp_001",
        tasks_path="datasets/tasks/toy_tasks.jsonl",
        profile_modes=[
            "base",
            "argument_rename",
            "schema_flat_to_nested",
            "tool_reorder",
        ],
        seeds=[0, 42],
        output_root="experiments",
    )
    config.save(path)
    loaded = ExperimentConfig.load(path)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.eval.layout import mode_dir_name


class ExperimentConfig(BaseModel):
    """Configuration for an experiment run.

    An experiment runs multiple combinations of:
    - tasks (from a JSONL file)
    - profile modes (e.g., base, argument_rename, schema_flat_to_nested)
    - seeds (for deterministic profile sampling)

    This class represents the experiment DEFINITION, not runtime metadata.
    Timestamps are intentionally excluded - they belong in ExperimentManifest.

    Attributes:
        experiment_id: Unique identifier for this experiment.
        tasks_path: Path to JSONL file containing task definitions.
        profile_modes: List of profile modes to test.
        seeds: List of seeds for profile sampling.
        output_root: Base directory for experiment outputs.
        max_tasks: Optional limit on number of tasks to run.
        task_ids: Optional explicit list of task IDs to run (filters tasks_path).
        notes: Optional human-readable notes.
        metadata: Optional arbitrary metadata.
    """

    experiment_id: str
    tasks_path: str
    profile_modes: list[str] = Field(default_factory=lambda: ["base"])
    seeds: list[int] = Field(default_factory=lambda: [0])
    output_root: str = "experiments"
    max_tasks: int | None = None
    task_ids: list[str] | None = None
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def save(self, path: str | Path) -> None:
        """Save config to JSON file.

        Args:
            path: Path to write config to.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> ExperimentConfig:
        """Load config from JSON file.

        Args:
            path: Path to load config from.

        Returns:
            Loaded ExperimentConfig.
        """
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    def get_output_dir(self) -> Path:
        """Get the experiment output directory.

        Returns:
            Path to experiment output directory (output_root / experiment_id).
        """
        return Path(self.output_root) / self.experiment_id

    def get_runs_dir(self) -> Path:
        """Get the runs subdirectory.

        Returns:
            Path to runs directory (output_dir / "runs").
        """
        return self.get_output_dir() / "runs"

    def get_seed_dir(self, seed: int) -> Path:
        """Get the directory for a specific seed.

        Args:
            seed: The seed value.

        Returns:
            Path to seed directory (runs_dir / f"seed_{seed}").
        """
        return self.get_runs_dir() / f"seed_{seed}"

    def get_mode_dir(self, seed: int, mode: str) -> Path:
        """Get the directory for a specific seed and mode combination.

        Args:
            seed: The seed value.
            mode: The profile mode.

        Returns:
            Path to short mode directory (seed_dir / mode_dir_name(mode)).
        """
        return self.get_seed_dir(seed) / mode_dir_name(mode)

    def count_combinations(self, task_count: int) -> int:
        """Count total number of task/profile/seed combinations.

        Args:
            task_count: Number of tasks (after filtering if task_ids is set).

        Returns:
            Total combinations (tasks * modes * seeds).
        """
        return task_count * len(self.profile_modes) * len(self.seeds)
