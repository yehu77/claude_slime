"""Tests for training loop."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from pycodeagent.rl.tensorize import TokenizedExample
from pycodeagent.rl.tokenizer_config import IGNORE_INDEX
from pycodeagent.rl.train_config import TrainConfig
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.rl.train_loop import (
    EmptyTrainingDatasetError,
    ToyModel,
    TrainMetrics,
    compute_masked_cross_entropy_loss,
    run_training,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "train_loop"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def make_example(
    length: int,
    trainable: bool = True,
    vocab_size: int = 100,
) -> TokenizedExample:
    """Create a TokenizedExample with the specified length."""
    input_ids = [10 + i for i in range(length)]
    attention_mask = [1] * length
    train_mask = [1 if trainable else 0] * length
    labels = input_ids if trainable else [IGNORE_INDEX] * length

    return TokenizedExample(
        input_ids=input_ids,
        attention_mask=attention_mask,
        labels=labels,
        token_train_mask=train_mask,
        metadata={"task_id": "test"},
    )


class TestComputeMaskedCrossEntropyLoss:
    """Tests for masked cross-entropy loss computation."""

    def test_empty_batch(self):
        """Empty batch should return 0 loss."""
        loss = compute_masked_cross_entropy_loss([], [])
        assert loss == 0.0

    def test_all_labels_ignored(self):
        """All-ignored labels should return 0 loss."""
        logits = [[[0.1, 0.2, 0.3] for _ in range(3)]]
        labels = [[IGNORE_INDEX, IGNORE_INDEX, IGNORE_INDEX]]
        loss = compute_masked_cross_entropy_loss(logits, labels)
        assert loss == 0.0

    def test_single_position(self):
        """Single trainable position should compute correct cross-entropy."""
        # Logits where class 0 has highest prob
        logits = [[[2.0, 0.0, 0.0]]]  # shape [1, 1, 3]
        labels = [[0]]  # correct label is 0

        loss = compute_masked_cross_entropy_loss(logits, labels)
        # Softmax: exp(2)/sum = ~0.67 for class 0
        # Cross-entropy: -log(0.67) ≈ 0.41
        assert loss > 0
        assert loss < 1.0  # Not too large since prediction is correct

    def test_mixed_trainable_and_ignored(self):
        """Should only count trainable positions."""
        logits = [
            [[0.0, 1.0, 0.0], [0.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
        ]  # 3 positions
        labels = [[1, IGNORE_INDEX, IGNORE_INDEX]]  # Only first is trainable

        loss = compute_masked_cross_entropy_loss(logits, labels)
        # Only position 0 contributes, label is 1, logit for 1 is 1.0
        # Should be finite positive
        assert loss > 0

    def test_correct_prediction_low_loss(self):
        """Correct prediction should have low loss."""
        # Model predicts class 1 strongly
        logits = [[[-10.0, 10.0, -10.0]]]
        labels = [[1]]  # Correct

        loss = compute_masked_cross_entropy_loss(logits, labels)
        # Very confident correct prediction → very low loss
        assert loss < 0.1

    def test_wrong_prediction_high_loss(self):
        """Wrong prediction should have high loss."""
        # Model predicts class 0 strongly
        logits = [[[10.0, -10.0, -10.0]]]
        labels = [[1]]  # Wrong, label is 1

        loss = compute_masked_cross_entropy_loss(logits, labels)
        # Confident wrong prediction → high loss
        assert loss > 5.0


class TestToyModel:
    """Tests for the ToyModel."""

    def test_forward_empty_batch(self):
        """Forward on empty batch should return 0."""
        model = ToyModel(vocab_size=100, hidden_dim=8)
        loss = model.forward([], [])
        assert loss == 0.0

    def test_forward_all_ignored(self):
        """Forward with all ignored labels should return 0."""
        model = ToyModel(vocab_size=100, hidden_dim=8)
        input_ids = [[1, 2, 3]]
        labels = [[IGNORE_INDEX, IGNORE_INDEX, IGNORE_INDEX]]
        loss = model.forward(input_ids, labels)
        assert loss == 0.0

    def test_forward_produces_finite_loss(self):
        """Forward should produce finite loss for valid input."""
        model = ToyModel(vocab_size=100, hidden_dim=8)
        input_ids = [[1, 2, 3, 4, 5]]
        labels = [[2, 3, 4, 5, 6]]  # Shifted by 1

        loss = model.forward(input_ids, labels)
        assert math.isfinite(loss)
        assert loss >= 0

    def test_train_step_produces_finite_loss(self):
        """Train step should return finite loss."""
        model = ToyModel(vocab_size=100, hidden_dim=8)
        input_ids = [[1, 2, 3]]
        labels = [[2, 3, 4]]

        loss = model.train_step(input_ids, labels, learning_rate=0.01)
        assert math.isfinite(loss)
        assert loss >= 0

    def test_deterministic_forward(self):
        """Same model + same input should give same forward output."""
        model = ToyModel(vocab_size=100, hidden_dim=8, seed=42)
        input_ids = [[1, 2, 3]]
        labels = [[2, 3, 4]]

        loss1 = model.forward(input_ids, labels)
        loss2 = model.forward(input_ids, labels)
        assert loss1 == loss2


class TestTrainMetrics:
    """Tests for TrainMetrics."""

    def test_empty_metrics(self):
        """Empty metrics should have sensible defaults."""
        metrics = TrainMetrics()
        assert metrics.num_steps == 0
        assert metrics.final_loss == 0.0
        assert metrics.average_loss == 0.0
        assert metrics.examples_seen == 0
        assert metrics.step_examples_seen == []

    def test_single_step(self):
        """Single step should be recorded correctly."""
        metrics = TrainMetrics()
        metrics.step_losses.append(0.5)
        metrics.step_timestamps.append(1.0)
        metrics.step_examples_seen.append(8)
        metrics.examples_seen = 8

        assert metrics.num_steps == 1
        assert metrics.final_loss == 0.5
        assert metrics.average_loss == 0.5

    def test_multiple_steps(self):
        """Multiple steps should compute correct average."""
        metrics = TrainMetrics()
        metrics.step_losses = [0.5, 0.4, 0.3, 0.2]
        metrics.step_examples_seen = [8, 16, 24, 32]
        metrics.examples_seen = 32

        assert metrics.num_steps == 4
        assert metrics.final_loss == 0.2
        assert metrics.average_loss == 0.35  # (0.5 + 0.4 + 0.3 + 0.2) / 4

    def test_to_dict(self):
        """Should serialize to dict."""
        metrics = TrainMetrics()
        metrics.step_losses = [0.5, 0.3]
        metrics.step_examples_seen = [8, 16]
        metrics.examples_seen = 16
        metrics.start_time = 0.0
        metrics.end_time = 10.0

        data = metrics.to_dict()
        assert data["num_steps"] == 2
        assert data["final_loss"] == 0.3
        assert data["average_loss"] == 0.4
        assert data["examples_seen"] == 16
        assert data["duration_seconds"] == 10.0

    def test_get_step_records(self):
        """Should produce structured step records."""
        metrics = TrainMetrics()
        metrics.step_losses = [0.5, 0.3]
        metrics.step_examples_seen = [8, 16]
        metrics.step_timestamps = [1.0, 2.0]

        records = metrics.get_step_records()
        assert len(records) == 2
        assert records[0] == {"step": 1, "loss": 0.5, "examples_seen": 8, "timestamp": 1.0}
        assert records[1] == {"step": 2, "loss": 0.3, "examples_seen": 16, "timestamp": 2.0}

    def test_get_step_records_empty(self):
        """Empty metrics should produce empty step records."""
        metrics = TrainMetrics()
        assert metrics.get_step_records() == []


class TestRunTraining:
    """Tests for run_training."""

    def test_minimal_training(self):
        """Should run minimal training without error."""
        test_dir = _get_test_dir()
        try:
            # Create small dataset
            examples = [make_example(5) for _ in range(4)]
            dataset = TrainDataset.from_examples(examples)

            # Config
            config = TrainConfig(
                run_id="minimal_test",
                dataset_path="dummy",
                output_dir=str(test_dir),
                max_steps=2,
                batch_size=2,
                seed=42,
            )

            # Model
            model = ToyModel(vocab_size=100, hidden_dim=8, seed=42)

            # Run
            result = run_training(model, dataset, config)

            assert result.num_steps == 2
            assert result.examples_seen == 4
            assert math.isfinite(result.final_loss)
        finally:
            _cleanup(test_dir)

    def test_step_counting(self):
        """Should count steps correctly."""
        test_dir = _get_test_dir()
        try:
            examples = [make_example(3) for _ in range(8)]
            dataset = TrainDataset.from_examples(examples)

            config = TrainConfig(
                run_id="step_test",
                dataset_path="dummy",
                output_dir=str(test_dir),
                max_steps=5,
                batch_size=2,
                seed=42,
                log_every=0,  # Disable step logging
            )

            model = ToyModel(vocab_size=100, hidden_dim=8)
            result = run_training(model, dataset, config)

            assert result.num_steps == 5
        finally:
            _cleanup(test_dir)

    def test_examples_seen(self):
        """Should track examples seen."""
        test_dir = _get_test_dir()
        try:
            # 8 examples, batch_size=4, so 2 batches per epoch = 2 steps
            examples = [make_example(3) for _ in range(8)]
            dataset = TrainDataset.from_examples(examples)

            config = TrainConfig(
                run_id="examples_test",
                dataset_path="dummy",
                output_dir=str(test_dir),
                max_steps=3,
                batch_size=4,
                seed=42,
                log_every=0,
            )

            model = ToyModel(vocab_size=100, hidden_dim=8)
            result = run_training(model, dataset, config)

            # 3 steps: first epoch has 2 batches (8 examples),
            # second epoch starts, first batch has 4 examples = 12 total
            assert result.examples_seen == 12
        finally:
            _cleanup(test_dir)

    def test_metrics_written(self):
        """Should write metrics to output directory."""
        test_dir = _get_test_dir()
        try:
            examples = [make_example(3) for _ in range(4)]
            dataset = TrainDataset.from_examples(examples)

            config = TrainConfig(
                run_id="metrics_test",
                dataset_path="dummy",
                output_dir=str(test_dir),
                max_steps=2,
                batch_size=2,
                seed=42,
                log_every=0,
            )

            model = ToyModel(vocab_size=100, hidden_dim=8)
            run_training(model, dataset, config)

            # Check metrics file exists
            metrics_path = test_dir / "train_metrics.json"
            assert metrics_path.exists()
        finally:
            _cleanup(test_dir)

    def test_step_logging(self):
        """Should write step metrics when log_every > 0."""
        test_dir = _get_test_dir()
        try:
            examples = [make_example(3) for _ in range(4)]
            dataset = TrainDataset.from_examples(examples)

            config = TrainConfig(
                run_id="step_log_test",
                dataset_path="dummy",
                output_dir=str(test_dir),
                max_steps=5,
                batch_size=2,
                seed=42,
                log_every=2,  # Log every 2 steps
            )

            model = ToyModel(vocab_size=100, hidden_dim=8)
            run_training(model, dataset, config)

            # Should have step records
            steps_path = test_dir / "train_steps.jsonl"
            assert steps_path.exists()
        finally:
            _cleanup(test_dir)

    def test_deterministic_with_same_seed(self):
        """Same seed should produce same results."""
        test_dir = _get_test_dir()
        try:
            examples = [make_example(3) for _ in range(4)]
            dataset = TrainDataset.from_examples(examples)

            config = TrainConfig(
                run_id="determinism_test",
                dataset_path="dummy",
                output_dir=str(test_dir),
                max_steps=3,
                batch_size=2,
                seed=123,
                log_every=0,
            )

            # Run twice with same seed
            model1 = ToyModel(vocab_size=100, hidden_dim=8, seed=123)
            result1 = run_training(model1, dataset, config)

            model2 = ToyModel(vocab_size=100, hidden_dim=8, seed=123)
            result2 = run_training(model2, dataset, config)

            # Final losses should be identical
            assert result1.final_loss == result2.final_loss
        finally:
            _cleanup(test_dir)

    def test_empty_dataset_raises_by_default(self):
        """Empty datasets should fail fast unless explicitly allowed."""
        test_dir = _get_test_dir()
        try:
            dataset = TrainDataset.from_examples([])

            config = TrainConfig(
                run_id="empty_test",
                dataset_path="dummy",
                output_dir=str(test_dir),
                max_steps=2,
                batch_size=2,
                seed=42,
                log_every=0,
            )

            model = ToyModel(vocab_size=100, hidden_dim=8)
            with pytest.raises(EmptyTrainingDatasetError, match="Training dataset is empty"):
                run_training(model, dataset, config)
        finally:
            _cleanup(test_dir)

    def test_empty_dataset_noop_when_explicitly_allowed(self):
        """Explicitly allowed empty datasets should return a zero-step no-op result."""
        test_dir = _get_test_dir()
        try:
            dataset = TrainDataset.from_examples([])

            config = TrainConfig(
                run_id="empty_allowed_test",
                dataset_path="dummy",
                output_dir=str(test_dir),
                max_steps=2,
                batch_size=2,
                seed=42,
                log_every=0,
                allow_empty_dataset=True,
            )

            model = ToyModel(vocab_size=100, hidden_dim=8)
            result = run_training(model, dataset, config)

            assert result.num_steps == 0
            assert result.examples_seen == 0
            assert result.final_loss == 0.0
        finally:
            _cleanup(test_dir)

    def test_step_records_exposed(self):
        """TrainResult should expose step_records with exact examples_seen."""
        test_dir = _get_test_dir()
        try:
            examples = [make_example(3) for _ in range(8)]
            dataset = TrainDataset.from_examples(examples)

            config = TrainConfig(
                run_id="step_records_test",
                dataset_path="dummy",
                output_dir=str(test_dir),
                max_steps=3,
                batch_size=4,
                seed=42,
                log_every=0,
            )

            model = ToyModel(vocab_size=100, hidden_dim=8)
            result = run_training(model, dataset, config)

            # Check step_records are exposed and correct
            records = result.step_records
            assert len(records) == 3
            # Each record should have correct structure
            for i, rec in enumerate(records):
                assert rec["step"] == i + 1
                assert "loss" in rec
                assert "timestamp" in rec
                assert "examples_seen" in rec
            # examples_seen should be cumulative and exact
            assert records[0]["examples_seen"] == 4  # First batch: 4 examples
            assert records[1]["examples_seen"] == 8  # Second batch: 8 total
            assert records[2]["examples_seen"] == 12  # Third batch (epoch 2): 12 total
        finally:
            _cleanup(test_dir)

    def test_step_records_consistency(self):
        """Step records should be internally consistent with final metrics."""
        test_dir = _get_test_dir()
        try:
            examples = [make_example(3) for _ in range(10)]
            dataset = TrainDataset.from_examples(examples)

            config = TrainConfig(
                run_id="consistency_test",
                dataset_path="dummy",
                output_dir=str(test_dir),
                max_steps=5,
                batch_size=3,  # Not evenly divisible
                seed=42,
                log_every=0,
            )

            model = ToyModel(vocab_size=100, hidden_dim=8)
            result = run_training(model, dataset, config)

            # Final examples_seen should match last step record
            records = result.step_records
            assert records[-1]["examples_seen"] == result.examples_seen

            # Step losses should match
            for i, rec in enumerate(records):
                assert rec["loss"] == result.metrics.step_losses[i]

            # examples_seen should be monotonically non-decreasing
            for i in range(1, len(records)):
                assert records[i]["examples_seen"] >= records[i - 1]["examples_seen"]
        finally:
            _cleanup(test_dir)


class TestIgnoreLabelMasking:
    """Tests that IGNORE_INDEX labels are properly masked."""

    def test_non_trainable_tokens_zero_contribution(self):
        """Non-trainable tokens should contribute 0 to loss."""
        model = ToyModel(vocab_size=100, hidden_dim=8, seed=42)

        # Example with only non-trainable tokens
        input_ids = [[1, 2, 3]]
        labels = [[IGNORE_INDEX, IGNORE_INDEX, IGNORE_INDEX]]

        loss = model.forward(input_ids, labels)
        assert loss == 0.0

    def test_mixed_trainability(self):
        """Mixed trainable/non-trainable should only count trainable."""
        model = ToyModel(vocab_size=100, hidden_dim=8, seed=42)

        # Two identical sequences, one all trainable, one partially
        input_ids = [[1, 2, 3], [1, 2, 3]]
        labels_all = [[2, 3, 4], [2, 3, 4]]
        labels_partial = [[2, IGNORE_INDEX, IGNORE_INDEX], [IGNORE_INDEX, IGNORE_INDEX, IGNORE_INDEX]]

        loss_all = model.forward(input_ids, labels_all)
        loss_partial = model.forward(input_ids, labels_partial)

        # Partial should have lower loss (fewer positions contribute)
        # Or at least different loss
        assert loss_all != loss_partial
