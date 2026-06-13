"""Minimal supervised training loop with masked-token cross-entropy loss.

Provides a simple training entrypoint that:
- Iterates over batches from TrainDataset
- Computes masked cross-entropy loss (ignoring IGNORE_INDEX labels)
- Logs step metrics
- Supports deterministic seeding

This is intentionally minimal:
- No distributed training
- No advanced schedulers
- No gradient checkpointing
- No mixed precision
"""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path
from typing import Any, Protocol

from pycodeagent.rl.tokenizer_config import IGNORE_INDEX
from pycodeagent.rl.train_config import TrainConfig
from pycodeagent.rl.train_dataset import TrainDataset


class TrainableModel(Protocol):
    """Protocol for a trainable model.

    A model must implement:
    - forward: compute loss for a batch
    - train_step: perform one gradient update and return loss

    For testing, use ToyModel which implements this protocol.
    For real training, wrap a PyTorch/HuggingFace model.
    """

    def forward(
        self,
        input_ids: list[list[int]],
        labels: list[list[int]],
    ) -> float:
        """Compute loss for a batch.

        Args:
            input_ids: Batch of input token IDs (list of lists)
            labels: Batch of label token IDs (list of lists)

        Returns:
            Scalar loss value
        """
        ...

    def train_step(
        self,
        input_ids: list[list[int]],
        labels: list[list[int]],
        learning_rate: float,
    ) -> float:
        """Perform one training step and return loss.

        Args:
            input_ids: Batch of input token IDs
            labels: Batch of label token IDs
            learning_rate: Learning rate for this step

        Returns:
            Scalar loss value after the step
        """
        ...


class TrainMetrics:
    """Accumulated training metrics."""

    def __init__(self) -> None:
        self.step_losses: list[float] = []
        self.step_timestamps: list[float] = []
        self.step_examples_seen: list[int] = []  # Cumulative examples seen per step
        self.examples_seen: int = 0
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    @property
    def num_steps(self) -> int:
        return len(self.step_losses)

    @property
    def final_loss(self) -> float:
        return self.step_losses[-1] if self.step_losses else 0.0

    @property
    def average_loss(self) -> float:
        if not self.step_losses:
            return 0.0
        return sum(self.step_losses) / len(self.step_losses)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "num_steps": self.num_steps,
            "final_loss": self.final_loss,
            "average_loss": self.average_loss,
            "examples_seen": self.examples_seen,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.end_time - self.start_time,
        }

    def get_step_records(self) -> list[dict[str, Any]]:
        """Get structured step records for reporting.

        Returns:
            List of dicts with step, loss, examples_seen, timestamp
        """
        records: list[dict[str, Any]] = []
        for i in range(self.num_steps):
            records.append({
                "step": i + 1,
                "loss": self.step_losses[i],
                "examples_seen": self.step_examples_seen[i],
                "timestamp": self.step_timestamps[i],
            })
        return records


class TrainResult:
    """Result of a training run."""

    def __init__(
        self,
        metrics: TrainMetrics,
        output_dir: Path,
    ) -> None:
        self.metrics = metrics
        self.output_dir = output_dir

    @property
    def num_steps(self) -> int:
        return self.metrics.num_steps

    @property
    def final_loss(self) -> float:
        return self.metrics.final_loss

    @property
    def average_loss(self) -> float:
        return self.metrics.average_loss

    @property
    def examples_seen(self) -> int:
        return self.metrics.examples_seen

    @property
    def step_records(self) -> list[dict[str, Any]]:
        """Structured step records with loss, examples_seen, timestamp."""
        return self.metrics.get_step_records()


class EmptyTrainingDatasetError(ValueError):
    """Raised when training is requested with no examples by default."""


def run_training(
    model: TrainableModel,
    dataset: TrainDataset,
    config: TrainConfig,
) -> TrainResult:
    """Run a minimal training loop.

    Args:
        model: A trainable model implementing the TrainableModel protocol
        dataset: Training dataset
        config: Training configuration

    Returns:
        TrainResult with metrics and output paths
    """
    # Set up output directory
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Set seed for reproducibility
    random.seed(config.seed)

    # Initialize metrics
    metrics = TrainMetrics()
    metrics.start_time = time.time()

    if len(dataset) == 0:
        if not config.allow_empty_dataset:
            raise EmptyTrainingDatasetError(
                "Training dataset is empty. Refusing to consume max_steps with no "
                "examples. Set allow_empty_dataset=True to allow a zero-step "
                "no-op training run."
            )

        metrics.end_time = time.time()
        _write_final_metrics(output_dir, metrics)
        return TrainResult(metrics, output_dir)

    # Shuffle dataset examples for training
    indices = list(range(len(dataset)))
    random.shuffle(indices)

    step = 0
    examples_seen = 0

    while step < config.max_steps:
        # Build batches from shuffled indices
        for batch_start in range(0, len(indices), config.batch_size):
            if step >= config.max_steps:
                break

            batch_indices = indices[batch_start : batch_start + config.batch_size]
            batch = [dataset[i] for i in batch_indices]

            # Collate batch
            collated = dataset.collate_batch(batch)

            # Perform training step
            loss = model.train_step(
                collated["input_ids"],
                collated["labels"],
                config.learning_rate,
            )

            step += 1
            examples_seen += len(batch)

            # Record metrics
            metrics.step_losses.append(loss)
            metrics.step_timestamps.append(time.time())
            metrics.step_examples_seen.append(examples_seen)

            # Log step metrics
            if config.log_every > 0 and step % config.log_every == 0:
                _write_step_metrics(
                    output_dir,
                    step,
                    loss,
                    examples_seen,
                    metrics.step_timestamps[-1],
                )

        # If we've gone through all examples, reshuffle for next epoch
        if step < config.max_steps:
            random.shuffle(indices)

    metrics.end_time = time.time()
    metrics.examples_seen = examples_seen

    # Write final metrics
    _write_final_metrics(output_dir, metrics)

    return TrainResult(metrics, output_dir)


def _write_step_metrics(
    output_dir: Path,
    step: int,
    loss: float,
    examples_seen: int,
    timestamp: float,
) -> None:
    """Append step metrics to train_steps.jsonl."""
    steps_path = output_dir / "train_steps.jsonl"
    record = {
        "step": step,
        "loss": loss,
        "examples_seen": examples_seen,
        "timestamp": timestamp,
    }
    with open(steps_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _write_final_metrics(output_dir: Path, metrics: TrainMetrics) -> None:
    """Write final metrics to train_metrics.json."""
    metrics_path = output_dir / "train_metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics.to_dict(), f, indent=2, sort_keys=False)


def compute_masked_cross_entropy_loss(
    logits: list[list[list[float]]],
    labels: list[list[int]],
    ignore_index: int = IGNORE_INDEX,
) -> float:
    """Compute masked cross-entropy loss.

    This is a reference implementation for computing cross-entropy loss
    with label masking. Used by ToyModel and for testing.

    Args:
        logits: Batch of logits [batch_size, seq_len, vocab_size]
        labels: Batch of label token IDs [batch_size, seq_len]
        ignore_index: Label value to ignore in loss computation

    Returns:
        Scalar loss value
    """
    batch_size = len(logits)
    if batch_size == 0:
        return 0.0

    total_loss = 0.0
    total_count = 0

    for b in range(batch_size):
        seq_len = len(labels[b])
        for s in range(seq_len):
            label = labels[b][s]
            if label == ignore_index:
                continue

            # Compute cross-entropy for this position
            # Cross-entropy = -log(softmax(logits)[label])
            # = -logits[label] + log(sum(exp(logits)))
            seq_logits = logits[b][s]
            max_logit = max(seq_logits)
            log_sum_exp = max_logit + math.log(
                sum(math.exp(l - max_logit) for l in seq_logits)
            )
            loss = -seq_logits[label] + log_sum_exp

            total_loss += loss
            total_count += 1

    if total_count == 0:
        return 0.0

    return total_loss / total_count


class ToyModel:
    """A tiny toy model for testing the training loop.

    This is NOT a real model — it's only for testing.
    It has a tiny embedding table and uses simple SGD updates.

    The model:
    - Has a vocab of size `vocab_size`
    - Embeds each token into `hidden_dim` dimensions
    - Projects back to vocab_size for logits
    - Uses mean squared error on softmax probs as a simple loss proxy
      (NOT real cross-entropy, but sufficient for testing the loop)
    """

    def __init__(
        self,
        vocab_size: int = 100,
        hidden_dim: int = 8,
        seed: int = 42,
    ) -> None:
        """Initialize the toy model.

        Args:
            vocab_size: Vocabulary size
            hidden_dim: Hidden dimension
            seed: Random seed for initialization
        """
        self.vocab_size = vocab_size
        self.hidden_dim = hidden_dim

        rng = random.Random(seed)

        # Initialize embeddings [vocab_size, hidden_dim]
        self.embeddings = [
            [rng.gauss(0, 0.1) for _ in range(hidden_dim)]
            for _ in range(vocab_size)
        ]

        # Initialize output projection [hidden_dim, vocab_size]
        self.output_proj = [
            [rng.gauss(0, 0.1) for _ in range(vocab_size)]
            for _ in range(hidden_dim)
        ]

    def _get_logits(self, input_ids: list[int]) -> list[list[float]]:
        """Get logits for a single sequence."""
        # Embed input tokens
        embedded = [self.embeddings[tid] for tid in input_ids]
        seq_len = len(input_ids)

        # Project to logits
        logits: list[list[float]] = []
        for s in range(seq_len):
            pos_logits: list[float] = []
            for v in range(self.vocab_size):
                logit = sum(
                    embedded[s][h] * self.output_proj[h][v]
                    for h in range(self.hidden_dim)
                )
                pos_logits.append(logit)
            logits.append(pos_logits)

        return logits

    def forward(
        self,
        input_ids: list[list[int]],
        labels: list[list[int]],
    ) -> float:
        """Compute masked cross-entropy loss for a batch."""
        batch_size = len(input_ids)
        if batch_size == 0:
            return 0.0

        total_loss = 0.0
        total_count = 0

        for b in range(batch_size):
            logits = self._get_logits(input_ids[b])
            seq_labels = labels[b]
            seq_len = len(seq_labels)

            for s in range(seq_len):
                label = seq_labels[s]
                if label == IGNORE_INDEX:
                    continue

                # Compute cross-entropy loss
                seq_logits = logits[s]
                max_logit = max(seq_logits)
                log_sum_exp = max_logit + math.log(
                    sum(math.exp(l - max_logit) for l in seq_logits)
                )
                loss = -seq_logits[label] + log_sum_exp

                total_loss += loss
                total_count += 1

        if total_count == 0:
            return 0.0

        return total_loss / total_count

    def train_step(
        self,
        input_ids: list[list[int]],
        labels: list[list[int]],
        learning_rate: float,
    ) -> float:
        """Perform one training step and return loss.

        For testing purposes, this uses a simplified update:
        - Computes loss
        - Makes a small random perturbation to weights
        - This is NOT real training, just enough to test the loop
        """
        # Compute current loss
        loss = self.forward(input_ids, labels)

        # For testing, we just make a tiny random perturbation
        # This is NOT real SGD, but proves the training loop works
        # and allows tests to verify determinism with fixed seed
        batch_size = len(input_ids)
        if batch_size == 0:
            return loss

        # Get unique token IDs from input
        seen_tokens: set[int] = set()
        for seq in input_ids:
            for tid in seq:
                if 0 <= tid < self.vocab_size:
                    seen_tokens.add(tid)

        # Nudge embeddings for seen tokens slightly
        for tid in seen_tokens:
            for h in range(self.hidden_dim):
                # Use a deterministic perturbation based on current embedding value
                # This ensures tests can verify behavior
                self.embeddings[tid][h] -= learning_rate * 0.01 * self.embeddings[tid][h]

        return loss
