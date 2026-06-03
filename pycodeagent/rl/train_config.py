"""Structured configuration for training runs.

All important training knobs live here with explicit defaults.
Deterministic and serializable for reproducibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class TrainConfig(BaseModel):
    """Configuration for a training run.

    Attributes:
        run_id: Unique identifier for this training run
        dataset_path: Path to the tokenized dataset (JSONL or directory)
        output_dir: Directory for training outputs (metrics, checkpoints)
        max_steps: Maximum number of training steps
        batch_size: Number of examples per batch
        learning_rate: Learning rate for optimization
        seed: Random seed for reproducibility
        log_every: Log metrics every N steps
        allow_empty_dataset: Allow a zero-example no-op training run
        metadata: Arbitrary metadata for logging/tracking
    """

    run_id: str
    dataset_path: str
    output_dir: str
    max_steps: int = 1000
    batch_size: int = 8
    learning_rate: float = 1e-4
    seed: int = 42
    log_every: int = 10
    allow_empty_dataset: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    def save(self, path: Path | str) -> None:
        """Save config to a JSON file.

        Args:
            path: Path to save the config
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2, sort_keys=False)

    @classmethod
    def load(cls, path: Path | str) -> TrainConfig:
        """Load config from a JSON file.

        Args:
            path: Path to load the config from

        Returns:
            TrainConfig instance
        """
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)
