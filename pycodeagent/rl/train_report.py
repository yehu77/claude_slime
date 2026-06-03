"""Structured report writing for training runs.

Writes training outputs to JSON files for downstream analysis:
- train_config.json: The training configuration
- train_metrics.json: Final training metrics
- train_steps.jsonl: Per-step metrics (optional)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pycodeagent.rl.train_config import TrainConfig


class TrainReport:
    """Structured training report writer.

    Writes training outputs to a directory:
    - train_config.json
    - train_metrics.json
    - train_steps.jsonl (optional, per-step records)
    """

    def __init__(self, output_dir: Path | str) -> None:
        """Initialize the report writer.

        Args:
            output_dir: Directory to write reports
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._steps_written = False

    def write_config(self, config: TrainConfig) -> None:
        """Write the training configuration.

        Args:
            config: Training configuration
        """
        path = self.output_dir / "train_config.json"
        config.save(path)

    def write_metrics(
        self,
        num_steps: int,
        final_loss: float,
        average_loss: float,
        examples_seen: int,
        *,
        start_time: float | None = None,
        end_time: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Write final training metrics.

        Args:
            num_steps: Number of training steps
            final_loss: Loss at final step
            average_loss: Average loss over all steps
            examples_seen: Total examples seen
            start_time: Start timestamp (optional)
            end_time: End timestamp (optional)
            extra: Additional metrics to include
        """
        metrics: dict[str, Any] = {
            "num_steps": num_steps,
            "final_loss": final_loss,
            "average_loss": average_loss,
            "examples_seen": examples_seen,
        }

        if start_time is not None:
            metrics["start_time"] = start_time
        if end_time is not None:
            metrics["end_time"] = end_time
            if start_time is not None:
                metrics["duration_seconds"] = end_time - start_time

        if extra:
            metrics.update(extra)

        path = self.output_dir / "train_metrics.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2, sort_keys=False)

    def write_step(
        self,
        step: int,
        loss: float,
        examples_seen: int,
        timestamp: float,
    ) -> None:
        """Append a step record to train_steps.jsonl.

        Args:
            step: Step number
            loss: Loss at this step
            examples_seen: Examples seen so far
            timestamp: Timestamp for this step
        """
        path = self.output_dir / "train_steps.jsonl"
        record = {
            "step": step,
            "loss": loss,
            "examples_seen": examples_seen,
            "timestamp": timestamp,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        self._steps_written = True

    def load_config(self) -> TrainConfig:
        """Load the training configuration from train_config.json.

        Returns:
            TrainConfig instance
        """
        path = self.output_dir / "train_config.json"
        return TrainConfig.load(path)

    def load_metrics(self) -> dict[str, Any]:
        """Load the training metrics from train_metrics.json.

        Returns:
            Metrics dict
        """
        path = self.output_dir / "train_metrics.json"
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def load_steps(self) -> list[dict[str, Any]]:
        """Load the per-step metrics from train_steps.jsonl.

        Returns:
            List of step records
        """
        path = self.output_dir / "train_steps.jsonl"
        if not path.exists():
            return []
        steps: list[dict[str, Any]] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    steps.append(json.loads(line))
        return steps


def write_training_report(
    output_dir: Path | str,
    config: TrainConfig,
    num_steps: int,
    final_loss: float,
    average_loss: float,
    examples_seen: int,
    *,
    start_time: float | None = None,
    end_time: float | None = None,
    step_records: list[dict[str, Any]] | None = None,
) -> TrainReport:
    """Write a complete training report.

    Convenience function that writes all report files.

    Args:
        output_dir: Directory to write reports
        config: Training configuration
        num_steps: Number of training steps
        final_loss: Loss at final step
        average_loss: Average loss over all steps
        examples_seen: Total examples seen
        start_time: Start timestamp (optional)
        end_time: End timestamp (optional)
        step_records: List of step records with step, loss, examples_seen, timestamp (optional)

    Returns:
        TrainReport instance
    """
    report = TrainReport(output_dir)
    report.write_config(config)
    report.write_metrics(
        num_steps,
        final_loss,
        average_loss,
        examples_seen,
        start_time=start_time,
        end_time=end_time,
    )

    # Write step records if provided
    if step_records is not None:
        for rec in step_records:
            report.write_step(
                step=rec["step"],
                loss=rec["loss"],
                examples_seen=rec["examples_seen"],
                timestamp=rec["timestamp"],
            )

    return report
