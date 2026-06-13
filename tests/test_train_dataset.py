"""Tests for TrainDataset."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.rl.tensorize import TokenizedExample
from pycodeagent.rl.tokenizer_config import IGNORE_INDEX
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "train_dataset"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def make_example(
    length: int,
    trainable: bool = True,
    task_id: str = "test_task",
) -> TokenizedExample:
    """Create a TokenizedExample with the specified length."""
    input_ids = list(range(100, 100 + length))
    attention_mask = [1] * length
    train_mask = [1 if trainable else 0] * length
    labels = input_ids if trainable else [IGNORE_INDEX] * length

    return TokenizedExample(
        input_ids=input_ids,
        attention_mask=attention_mask,
        labels=labels,
        token_train_mask=train_mask,
        metadata={"task_id": task_id},
    )


class TestTrainDatasetCreation:
    """Tests for TrainDataset creation."""

    def test_from_examples(self):
        """Should create dataset from a list of examples."""
        examples = [make_example(10), make_example(20)]
        dataset = TrainDataset.from_examples(examples)
        assert len(dataset) == 2

    def test_empty_dataset(self):
        """Should handle empty dataset."""
        dataset = TrainDataset.from_examples([])
        assert len(dataset) == 0


class TestTrainDatasetIteration:
    """Tests for dataset iteration."""

    def test_getitem(self):
        """Should access examples by index."""
        examples = [make_example(5), make_example(10), make_example(15)]
        dataset = TrainDataset.from_examples(examples)
        assert dataset[0].length == 5
        assert dataset[1].length == 10
        assert dataset[2].length == 15

    def test_iter(self):
        """Should iterate in order."""
        examples = [make_example(5, task_id="a"), make_example(10, task_id="b")]
        dataset = TrainDataset.from_examples(examples)
        items = list(dataset)
        assert len(items) == 2
        assert items[0].metadata["task_id"] == "a"
        assert items[1].metadata["task_id"] == "b"

    def test_deterministic_order(self):
        """Should always iterate in the same order."""
        examples = [make_example(i + 1, task_id=str(i)) for i in range(10)]
        dataset = TrainDataset.from_examples(examples)

        order1 = [ex.metadata["task_id"] for ex in dataset]
        order2 = [ex.metadata["task_id"] for ex in dataset]
        assert order1 == order2


class TestBatches:
    """Tests for batching."""

    def test_batches_even(self):
        """Should batch evenly when dataset size divides by batch_size."""
        examples = [make_example(5) for _ in range(10)]
        dataset = TrainDataset.from_examples(examples)

        batches = list(dataset.batches(batch_size=5))
        assert len(batches) == 2
        assert all(len(b) == 5 for b in batches)

    def test_batches_uneven(self):
        """Last batch should be smaller when dataset doesn't divide evenly."""
        examples = [make_example(5) for _ in range(7)]
        dataset = TrainDataset.from_examples(examples)

        batches = list(dataset.batches(batch_size=3))
        assert len(batches) == 3
        assert len(batches[0]) == 3
        assert len(batches[1]) == 3
        assert len(batches[2]) == 1

    def test_batches_larger_than_dataset(self):
        """Should yield one batch when batch_size > dataset size."""
        examples = [make_example(5) for _ in range(3)]
        dataset = TrainDataset.from_examples(examples)

        batches = list(dataset.batches(batch_size=10))
        assert len(batches) == 1
        assert len(batches[0]) == 3

    def test_batches_empty(self):
        """Should yield no batches for empty dataset."""
        dataset = TrainDataset.from_examples([])
        batches = list(dataset.batches(batch_size=5))
        assert len(batches) == 0


class TestCollation:
    """Tests for batch collation."""

    def test_collate_same_length(self):
        """Should collate examples of the same length."""
        examples = [make_example(5), make_example(5)]
        dataset = TrainDataset.from_examples(examples)
        batch = [dataset[0], dataset[1]]
        collated = dataset.collate_batch(batch)

        assert len(collated["input_ids"]) == 2
        assert len(collated["input_ids"][0]) == 5
        assert len(collated["attention_mask"][0]) == 5
        assert len(collated["labels"][0]) == 5

    def test_collate_different_lengths_pads(self):
        """Should pad shorter examples to match longest."""
        examples = [make_example(3), make_example(5)]
        dataset = TrainDataset.from_examples(examples)
        batch = [dataset[0], dataset[1]]
        collated = dataset.collate_batch(batch)

        # Both should have length 5 (padded)
        assert len(collated["input_ids"][0]) == 5
        assert len(collated["input_ids"][1]) == 5

        # Padded positions should have pad_token_id (0)
        assert collated["input_ids"][0][3:] == [0, 0]
        # Padded attention mask should be 0
        assert collated["attention_mask"][0][3:] == [0, 0]
        # Padded labels should be IGNORE_INDEX
        assert collated["labels"][0][3:] == [IGNORE_INDEX, IGNORE_INDEX]

    def test_collate_empty_batch(self):
        """Should handle empty batch."""
        dataset = TrainDataset.from_examples([])
        collated = dataset.collate_batch([])
        assert collated["input_ids"] == []
        assert collated["labels"] == []

    def test_collate_preserves_labels(self):
        """Trainable labels should be preserved, padded labels ignored."""
        ex1 = make_example(3, trainable=True)
        ex2 = make_example(3, trainable=False)
        dataset = TrainDataset.from_examples([ex1, ex2])
        collated = dataset.collate_batch([ex1, ex2])

        # First example: labels = input_ids
        assert collated["labels"][0] == ex1.input_ids
        # Second example: labels = IGNORE_INDEX
        assert collated["labels"][1] == [IGNORE_INDEX] * 3


class TestJsonlRoundtrip:
    """Tests for JSONL save/load."""

    def test_save_and_load_jsonl(self):
        """Should survive JSONL save/load roundtrip."""
        test_dir = _get_test_dir()
        try:
            examples = [
                make_example(5, task_id="task_1"),
                make_example(10, task_id="task_2"),
            ]
            dataset = TrainDataset.from_examples(examples)

            path = test_dir / "train.jsonl"
            dataset.save_jsonl(path)

            loaded = TrainDataset.from_jsonl(path)
            assert len(loaded) == 2
            assert loaded[0].metadata["task_id"] == "task_1"
            assert loaded[1].metadata["task_id"] == "task_2"
            assert loaded[0].input_ids == examples[0].input_ids
            assert loaded[1].input_ids == examples[1].input_ids
        finally:
            _cleanup(test_dir)

    def test_jsonl_preserves_labels(self):
        """Labels should survive JSONL roundtrip."""
        test_dir = _get_test_dir()
        try:
            ex = make_example(5, trainable=True)
            dataset = TrainDataset.from_examples([ex])

            path = test_dir / "train.jsonl"
            dataset.save_jsonl(path)

            loaded = TrainDataset.from_jsonl(path)
            assert loaded[0].labels == ex.labels
        finally:
            _cleanup(test_dir)

    def test_jsonl_empty_lines_ignored(self):
        """Should handle JSONL files with empty lines."""
        test_dir = _get_test_dir()
        try:
            path = test_dir / "train.jsonl"
            ex = make_example(3, task_id="t1")

            with open(path, "w", encoding="utf-8") as f:
                f.write(ex.model_dump_json() + "\n")
                f.write("\n")  # Empty line
                f.write(make_example(3, task_id="t2").model_dump_json() + "\n")

            loaded = TrainDataset.from_jsonl(path)
            assert len(loaded) == 2
        finally:
            _cleanup(test_dir)


class TestExamplesProperty:
    """Tests for the examples property."""

    def test_examples_access(self):
        """Should access underlying examples list."""
        examples = [make_example(5), make_example(10)]
        dataset = TrainDataset.from_examples(examples)
        assert len(dataset.examples) == 2
        assert dataset.examples[0].length == 5
