"""Study configuration for mutation sensitivity experiments.

A study runs multiple experiments (one per profile mode) and compares
each mutated mode against a baseline mode.

The study config defines:
- Which tasks to run (tasks_path, optional task_ids/max_tasks)
- Which profile modes to compare (profile_modes)
- Which is the baseline mode (baseline_mode, default "base")
- Seeds for reproducibility
- Where to write outputs (output_root)

Example:
    config = StudyConfig(
        study_id="mutation_sensitivity_001",
        tasks_path="datasets/tasks/toy_tasks.jsonl",
        profile_modes=[
            "base",
            "argument_rename",
            "schema_flat_to_nested",
            "tool_reorder",
        ],
        seeds=[0, 42],
        output_root="studies",
    )
    config.save(path)
    loaded = StudyConfig.load(path)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class StudyConfig(BaseModel):
    """Configuration for a mutation sensitivity study.

    A study runs experiments for each profile mode and compares
    results against a designated baseline mode.

    Attributes:
        study_id: Unique identifier for this study.
        tasks_path: Path to JSONL file containing task definitions.
        profile_modes: List of profile modes to compare.
        baseline_mode: The baseline mode to compare against. Must be in profile_modes.
        seeds: List of seeds for reproducibility.
        output_root: Base directory for study outputs.
        max_tasks: Optional limit on number of tasks to run.
        task_ids: Optional explicit list of task IDs to run.
        notes: Optional human-readable notes.
        metadata: Optional arbitrary metadata.
    """

    study_id: str
    tasks_path: str
    profile_modes: list[str] = Field(default_factory=lambda: ["base"])
    baseline_mode: str = "base"
    seeds: list[int] = Field(default_factory=lambda: [0])
    output_root: str = "studies"
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
    def load(cls, path: str | Path) -> StudyConfig:
        """Load config from JSON file.

        Args:
            path: Path to load config from.

        Returns:
            Loaded StudyConfig.
        """
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    def get_output_dir(self) -> Path:
        """Get the study output directory.

        Returns:
            Path to study output directory (output_root / study_id).
        """
        return Path(self.output_root) / self.study_id

    def get_experiments_dir(self) -> Path:
        """Get the experiments subdirectory.

        Returns:
            Path to experiments directory (output_dir / "experiments").
        """
        return self.get_output_dir() / "experiments"

    def validate_baseline(self) -> None:
        """Validate that baseline_mode is in profile_modes.

        Raises:
            ValueError: If baseline_mode is not in profile_modes.
        """
        if self.baseline_mode not in self.profile_modes:
            raise ValueError(
                f"baseline_mode '{self.baseline_mode}' must be in profile_modes {self.profile_modes}"
            )

    def get_mutated_modes(self) -> list[str]:
        """Get list of non-baseline (mutated) modes.

        Returns:
            List of modes that are not the baseline.
        """
        return [m for m in self.profile_modes if m != self.baseline_mode]
