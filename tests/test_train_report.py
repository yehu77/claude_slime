"""Tests for training report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.rl.train_config import TrainConfig
from pycodeagent.rl.train_report import TrainReport, write_training_report
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "train_report"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


class TestTrainReport:
    """Tests for TrainReport."""

    def test_write_config(self):
        """Should write config to train_config.json."""
        test_dir = _get_test_dir()
        try:
            config = TrainConfig(
                run_id="config_test",
                dataset_path="/data/train.jsonl",
                output_dir=str(test_dir),
                max_steps=100,
            )

            report = TrainReport(test_dir)
            report.write_config(config)

            config_path = test_dir / "train_config.json"
            assert config_path.exists()

            loaded = TrainConfig.load(config_path)
            assert loaded.run_id == "config_test"
            assert loaded.max_steps == 100
        finally:
            _cleanup(test_dir)

    def test_write_metrics(self):
        """Should write metrics to train_metrics.json."""
        test_dir = _get_test_dir()
        try:
            report = TrainReport(test_dir)
            report.write_metrics(
                num_steps=100,
                final_loss=0.25,
                average_loss=0.35,
                examples_seen=800,
            )

            metrics_path = test_dir / "train_metrics.json"
            assert metrics_path.exists()

            with open(metrics_path, encoding="utf-8") as f:
                metrics = json.load(f)

            assert metrics["num_steps"] == 100
            assert metrics["final_loss"] == 0.25
            assert metrics["average_loss"] == 0.35
            assert metrics["examples_seen"] == 800
        finally:
            _cleanup(test_dir)

    def test_write_metrics_with_timestamps(self):
        """Should include timestamps when provided."""
        test_dir = _get_test_dir()
        try:
            report = TrainReport(test_dir)
            report.write_metrics(
                num_steps=50,
                final_loss=0.1,
                average_loss=0.2,
                examples_seen=400,
                start_time=0.0,
                end_time=60.0,
            )

            metrics = report.load_metrics()
            assert metrics["start_time"] == 0.0
            assert metrics["end_time"] == 60.0
            assert metrics["duration_seconds"] == 60.0
        finally:
            _cleanup(test_dir)

    def test_write_step(self):
        """Should append step records to train_steps.jsonl."""
        test_dir = _get_test_dir()
        try:
            report = TrainReport(test_dir)
            report.write_step(step=1, loss=0.5, examples_seen=8, timestamp=1.0)
            report.write_step(step=2, loss=0.4, examples_seen=16, timestamp=2.0)

            steps = report.load_steps()
            assert len(steps) == 2
            assert steps[0]["step"] == 1
            assert steps[0]["loss"] == 0.5
            assert steps[1]["step"] == 2
            assert steps[1]["loss"] == 0.4
        finally:
            _cleanup(test_dir)

    def test_load_config(self):
        """Should load config from train_config.json."""
        test_dir = _get_test_dir()
        try:
            config = TrainConfig(
                run_id="load_test",
                dataset_path="/data/train.jsonl",
                output_dir=str(test_dir),
            )

            report = TrainReport(test_dir)
            report.write_config(config)

            loaded = report.load_config()
            assert loaded.run_id == "load_test"
        finally:
            _cleanup(test_dir)

    def test_load_metrics(self):
        """Should load metrics from train_metrics.json."""
        test_dir = _get_test_dir()
        try:
            report = TrainReport(test_dir)
            report.write_metrics(
                num_steps=10,
                final_loss=0.1,
                average_loss=0.2,
                examples_seen=80,
            )

            metrics = report.load_metrics()
            assert metrics["num_steps"] == 10
        finally:
            _cleanup(test_dir)

    def test_load_steps_empty(self):
        """Should return empty list if no steps written."""
        test_dir = _get_test_dir()
        try:
            report = TrainReport(test_dir)
            steps = report.load_steps()
            assert steps == []
        finally:
            _cleanup(test_dir)


class TestWriteTrainingReport:
    """Tests for write_training_report convenience function."""

    def test_full_report(self):
        """Should write all report files."""
        test_dir = _get_test_dir()
        try:
            config = TrainConfig(
                run_id="full_report_test",
                dataset_path="/data/train.jsonl",
                output_dir=str(test_dir),
                max_steps=100,
                batch_size=8,
            )

            report = write_training_report(
                test_dir,
                config,
                num_steps=50,
                final_loss=0.15,
                average_loss=0.25,
                examples_seen=400,
            )

            # All files should exist
            assert (test_dir / "train_config.json").exists()
            assert (test_dir / "train_metrics.json").exists()
        finally:
            _cleanup(test_dir)

    def test_report_with_steps(self):
        """Should write step records when provided."""
        test_dir = _get_test_dir()
        try:
            config = TrainConfig(
                run_id="steps_test",
                dataset_path="/data/train.jsonl",
                output_dir=str(test_dir),
                batch_size=8,
            )

            step_records = [
                {"step": 1, "loss": 0.5, "examples_seen": 8, "timestamp": 1.0},
                {"step": 2, "loss": 0.4, "examples_seen": 16, "timestamp": 2.0},
                {"step": 3, "loss": 0.3, "examples_seen": 24, "timestamp": 3.0},
            ]

            report = write_training_report(
                test_dir,
                config,
                num_steps=3,
                final_loss=0.3,
                average_loss=0.4,
                examples_seen=24,
                step_records=step_records,
            )

            steps = report.load_steps()
            assert len(steps) == 3
            assert steps[0]["examples_seen"] == 8
            assert steps[1]["examples_seen"] == 16
            assert steps[2]["examples_seen"] == 24
        finally:
            _cleanup(test_dir)

    def test_roundtrip(self):
        """Should survive roundtrip through write/load."""
        test_dir = _get_test_dir()
        try:
            config = TrainConfig(
                run_id="roundtrip_test",
                dataset_path="/data/train.jsonl",
                output_dir=str(test_dir),
                max_steps=200,
                batch_size=16,
            )

            report = write_training_report(
                test_dir,
                config,
                num_steps=100,
                final_loss=0.1,
                average_loss=0.2,
                examples_seen=1600,
            )

            loaded_config = report.load_config()
            loaded_metrics = report.load_metrics()

            assert loaded_config.run_id == "roundtrip_test"
            assert loaded_config.max_steps == 200
            assert loaded_metrics["num_steps"] == 100
            assert loaded_metrics["final_loss"] == 0.1
        finally:
            _cleanup(test_dir)


class TestExtraMetadata:
    """Tests for extra metadata in metrics."""

    def test_extra_metrics(self):
        """Should include extra metrics."""
        test_dir = _get_test_dir()
        try:
            report = TrainReport(test_dir)
            report.write_metrics(
                num_steps=10,
                final_loss=0.1,
                average_loss=0.2,
                examples_seen=80,
                extra={"custom_metric": 123, "another": "value"},
            )

            metrics = report.load_metrics()
            assert metrics["custom_metric"] == 123
            assert metrics["another"] == "value"
        finally:
            _cleanup(test_dir)


class TestStepRecordAccuracy:
    """Tests for exact step record tracking."""

    def test_partial_final_batch(self):
        """Should preserve exact examples_seen for partial batches."""
        test_dir = _get_test_dir()
        try:
            config = TrainConfig(
                run_id="partial_batch_test",
                dataset_path="/data/train.jsonl",
                output_dir=str(test_dir),
                batch_size=8,
            )

            # Simulate partial batch: 8 + 8 + 3 = 19 examples
            step_records = [
                {"step": 1, "loss": 0.5, "examples_seen": 8, "timestamp": 1.0},
                {"step": 2, "loss": 0.4, "examples_seen": 16, "timestamp": 2.0},
                {"step": 3, "loss": 0.3, "examples_seen": 19, "timestamp": 3.0},  # Partial!
            ]

            report = write_training_report(
                test_dir,
                config,
                num_steps=3,
                final_loss=0.3,
                average_loss=0.4,
                examples_seen=19,
                step_records=step_records,
            )

            steps = report.load_steps()
            assert len(steps) == 3
            # Critical: last step should have exact 19, not 24 (3 * 8)
            assert steps[2]["examples_seen"] == 19
            # Not 24 which would be 3 batches * batch_size
            assert steps[2]["examples_seen"] != 24

        finally:
            _cleanup(test_dir)

    def test_non_uniform_batch_sizes(self):
        """Should preserve exact examples_seen for non-uniform batches."""
        test_dir = _get_test_dir()
        try:
            config = TrainConfig(
                run_id="non_uniform_test",
                dataset_path="/data/train.jsonl",
                output_dir=str(test_dir),
                batch_size=10,
            )

            # Simulate non-uniform batches: 7, 5, 10, 3
            step_records = [
                {"step": 1, "loss": 0.5, "examples_seen": 7, "timestamp": 1.0},
                {"step": 2, "loss": 0.4, "examples_seen": 12, "timestamp": 2.0},
                {"step": 3, "loss": 0.3, "examples_seen": 22, "timestamp": 3.0},
                {"step": 4, "loss": 0.2, "examples_seen": 25, "timestamp": 4.0},
            ]

            report = write_training_report(
                test_dir,
                config,
                num_steps=4,
                final_loss=0.2,
                average_loss=0.35,
                examples_seen=25,
                step_records=step_records,
            )

            steps = report.load_steps()
            assert len(steps) == 4
            assert steps[0]["examples_seen"] == 7
            assert steps[1]["examples_seen"] == 12
            assert steps[2]["examples_seen"] == 22
            assert steps[3]["examples_seen"] == 25

        finally:
            _cleanup(test_dir)

    def test_step_records_not_reconstructed_from_config(self):
        """Step records should come from actual training, not config."""
        test_dir = _get_test_dir()
        try:
            # Even if batch_size is set incorrectly, step_records should be accurate
            config = TrainConfig(
                run_id="no_reconstruct_test",
                dataset_path="/data/train.jsonl",
                output_dir=str(test_dir),
                batch_size=100,  # Wrong! Actual batches are smaller
            )

            # Actual training produced these records
            step_records = [
                {"step": 1, "loss": 0.5, "examples_seen": 5, "timestamp": 1.0},
                {"step": 2, "loss": 0.4, "examples_seen": 10, "timestamp": 2.0},
            ]

            report = write_training_report(
                test_dir,
                config,
                num_steps=2,
                final_loss=0.4,
                average_loss=0.45,
                examples_seen=10,
                step_records=step_records,
            )

            steps = report.load_steps()
            # Should use actual records, not reconstruct from batch_size=100
            assert steps[0]["examples_seen"] == 5
            assert steps[1]["examples_seen"] == 10

        finally:
            _cleanup(test_dir)
