"""Minimal training dataset loader.

Loads tokenized examples or packed sequences from JSON/JSONL files
produced by the existing dataset builder / tensorization pipeline.
Provides deterministic iteration and basic batching/collation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from pycodeagent.rl.tensorize import TokenizedExample


class TrainDataset:
    """A minimal training dataset loaded from JSONL.

    Loads TokenizedExample records from a JSONL file and provides:
    - Deterministic ordered iteration
    - Batching into fixed-size batches
    - Collation into lists suitable for tensor conversion

    The dataset is intentionally simple:
    - All data loaded into memory (no lazy loading)
    - No distributed sharding
    - No dynamic sampling
    """

    def __init__(self, examples: list[TokenizedExample]) -> None:
        """Initialize from a list of tokenized examples.

        Args:
            examples: List of TokenizedExample objects
        """
        self._examples = list(examples)

    @classmethod
    def from_jsonl(cls, path: Path | str) -> TrainDataset:
        """Load dataset from a JSONL file of TokenizedExample records.

        Args:
            path: Path to the JSONL file

        Returns:
            TrainDataset instance
        """
        path = Path(path)
        examples: list[TokenizedExample] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                examples.append(TokenizedExample.model_validate(data))
        return cls(examples)

    @classmethod
    def from_examples(cls, examples: list[TokenizedExample]) -> TrainDataset:
        """Create dataset from a list of examples.

        Args:
            examples: List of TokenizedExample objects

        Returns:
            TrainDataset instance
        """
        return cls(examples)

    def save_jsonl(self, path: Path | str) -> None:
        """Save dataset to a JSONL file.

        Args:
            path: Path to save the JSONL file
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for example in self._examples:
                f.write(example.model_dump_json() + "\n")

    def __len__(self) -> int:
        """Number of examples in the dataset."""
        return len(self._examples)

    def __getitem__(self, idx: int) -> TokenizedExample:
        """Get a single example by index."""
        return self._examples[idx]

    def __iter__(self) -> Iterator[TokenizedExample]:
        """Iterate over examples in order."""
        return iter(self._examples)

    @property
    def examples(self) -> list[TokenizedExample]:
        """Access the underlying list of examples."""
        return self._examples

    def batches(self, batch_size: int) -> Iterator[list[TokenizedExample]]:
        """Iterate over batches of examples.

        Yields batches of size `batch_size`, with the last batch
        potentially smaller.

        Args:
            batch_size: Number of examples per batch

        Yields:
            Lists of TokenizedExample objects
        """
        for i in range(0, len(self._examples), batch_size):
            yield self._examples[i : i + batch_size]

    def collate_batch(
        self, batch: list[TokenizedExample], *, pad_token_id: int = 0
    ) -> dict[str, list[list[int]]]:
        """Collate a batch of examples into aligned lists.

        Pads all sequences to the length of the longest in the batch.

        Args:
            batch: List of TokenizedExample objects
            pad_token_id: Token ID to use for padding

        Returns:
            Dict with keys: input_ids, attention_mask, labels,
            token_train_mask — each a list of lists of ints
        """
        if not batch:
            return {
                "input_ids": [],
                "attention_mask": [],
                "labels": [],
                "token_train_mask": [],
            }

        max_len = max(ex.length for ex in batch)

        input_ids: list[list[int]] = []
        attention_mask: list[list[int]] = []
        labels: list[list[int]] = []
        token_train_mask: list[list[int]] = []

        for ex in batch:
            pad_len = max_len - ex.length
            input_ids.append(
                ex.input_ids + [pad_token_id] * pad_len
            )
            attention_mask.append(
                ex.attention_mask + [0] * pad_len
            )
            # Labels: pad with IGNORE_INDEX so padding doesn't contribute to loss
            from pycodeagent.rl.tokenizer_config import IGNORE_INDEX

            labels.append(
                ex.labels + [IGNORE_INDEX] * pad_len
            )
            token_train_mask.append(
                ex.token_train_mask + [0] * pad_len
            )

        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "labels": labels,
            "token_train_mask": token_train_mask,
        }
