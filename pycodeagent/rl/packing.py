"""Sequence packing: combine multiple tokenized examples into fixed-length sequences.

Simple greedy packing strategy:
- Pack examples while total length ≤ max_length
- Never split a single example
- Preserve source mapping for inspection

This module does NOT implement:
- Dynamic batching
- Distributed sharding
- Curriculum sampling
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.rl.tensorize import TokenizedExample


class PackedSequence(BaseModel):
    """A packed sequence containing multiple examples.

    Attributes:
        input_ids: Concatenated token IDs
        attention_mask: Concatenated attention masks
        labels: Concatenated labels
        token_train_mask: Concatenated token train masks
        source_indices: Mapping from position to source example index
        source_spans: For each source example: (start_pos, length)
        metadata: Metadata about the packed sequence
    """

    input_ids: list[int]
    attention_mask: list[int]
    labels: list[int]
    token_train_mask: list[int]
    source_indices: list[int]  # Which source example each token belongs to
    source_spans: list[dict[str, Any]]  # Per-source: {"start": int, "length": int, "metadata": dict}
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def length(self) -> int:
        """Total number of tokens in this packed sequence."""
        return len(self.input_ids)

    @property
    def num_sources(self) -> int:
        """Number of source examples packed into this sequence."""
        return len(self.source_spans)


class PackedBatch(BaseModel):
    """A batch of packed sequences.

    Attributes:
        sequences: List of packed sequences
        max_length: Maximum length used for packing
        total_examples: Total number of source examples
        stats: Statistics about the packing
    """

    sequences: list[PackedSequence]
    max_length: int
    total_examples: int
    stats: dict[str, Any] = Field(default_factory=dict)

    @property
    def num_sequences(self) -> int:
        """Number of packed sequences."""
        return len(self.sequences)


def pack_examples(
    examples: list[TokenizedExample],
    max_length: int,
    *,
    pad_token_id: int = 0,
) -> PackedBatch:
    """Pack multiple tokenized examples into fixed-length sequences.

    Uses simple greedy packing:
    - Add examples to current sequence while they fit
    - Start a new sequence when the next example doesn't fit
    - Examples that exceed max_length are placed in their own sequence (truncated)

    Args:
        examples: List of tokenized examples to pack
        max_length: Maximum length per packed sequence
        pad_token_id: Token ID to use for padding (default 0)

    Returns:
        PackedBatch with all packed sequences and statistics
    """
    if not examples:
        return PackedBatch(
            sequences=[],
            max_length=max_length,
            total_examples=0,
            stats={"num_packed": 0, "num_oversized": 0},
        )

    sequences: list[PackedSequence] = []
    current_examples: list[TokenizedExample] = []
    current_length = 0

    num_packed = 0  # Examples that were packed with others
    num_oversized = 0  # Examples that exceed max_length alone

    for example in examples:
        example_length = example.length

        if example_length > max_length:
            # Oversized example: place in its own (truncated) sequence
            num_oversized += 1
            packed = _pack_single(example, max_length)
            sequences.append(packed)
            continue

        if current_length + example_length <= max_length:
            # Fits in current sequence
            current_examples.append(example)
            current_length += example_length
        else:
            # Doesn't fit: finalize current and start new
            if current_examples:
                num_packed += len(current_examples)
                packed = _pack_multiple(current_examples)
                sequences.append(packed)
            current_examples = [example]
            current_length = example_length

    # Finalize last sequence
    if current_examples:
        num_packed += len(current_examples)
        packed = _pack_multiple(current_examples)
        sequences.append(packed)

    stats = {
        "num_packed": num_packed,
        "num_oversized": num_oversized,
        "total_tokens": sum(s.length for s in sequences),
        "utilization": (
            sum(s.length for s in sequences) / (len(sequences) * max_length)
            if sequences
            else 0.0
        ),
    }

    return PackedBatch(
        sequences=sequences,
        max_length=max_length,
        total_examples=len(examples),
        stats=stats,
    )


def _pack_single(example: TokenizedExample, max_length: int) -> PackedSequence:
    """Pack a single (possibly oversized) example into a sequence.

    Oversized examples are truncated to max_length.

    Args:
        example: The example to pack
        max_length: Maximum length

    Returns:
        PackedSequence with the single example
    """
    # Truncate if needed
    input_ids = example.input_ids[:max_length]
    attention_mask = example.attention_mask[:max_length]
    labels = example.labels[:max_length]
    token_train_mask = example.token_train_mask[:max_length]

    length = len(input_ids)

    return PackedSequence(
        input_ids=input_ids,
        attention_mask=attention_mask,
        labels=labels,
        token_train_mask=token_train_mask,
        source_indices=[0] * length,
        source_spans=[
            {
                "start": 0,
                "length": length,
                "metadata": example.metadata,
            }
        ],
        metadata={"truncated": example.length > max_length},
    )


def _pack_multiple(examples: list[TokenizedExample]) -> PackedSequence:
    """Pack multiple examples into a single sequence.

    Args:
        examples: Examples to pack (all fit within max_length)

    Returns:
        PackedSequence with all examples
    """
    input_ids: list[int] = []
    attention_mask: list[int] = []
    labels: list[int] = []
    token_train_mask: list[int] = []
    source_indices: list[int] = []
    source_spans: list[dict[str, Any]] = []

    for idx, example in enumerate(examples):
        start = len(input_ids)
        length = example.length

        input_ids.extend(example.input_ids)
        attention_mask.extend(example.attention_mask)
        labels.extend(example.labels)
        token_train_mask.extend(example.token_train_mask)
        source_indices.extend([idx] * length)

        source_spans.append(
            {
                "start": start,
                "length": length,
                "metadata": example.metadata,
            }
        )

    return PackedSequence(
        input_ids=input_ids,
        attention_mask=attention_mask,
        labels=labels,
        token_train_mask=token_train_mask,
        source_indices=source_indices,
        source_spans=source_spans,
        metadata={},
    )


def unpack_sequence(packed: PackedSequence) -> list[TokenizedExample]:
    """Unpack a packed sequence back into individual examples.

    Useful for inspection or verification.

    Args:
        packed: The packed sequence to unpack

    Returns:
        List of TokenizedExample objects
    """
    examples: list[TokenizedExample] = []

    for span in packed.source_spans:
        start = span["start"]
        length = span["length"]

        example = TokenizedExample(
            input_ids=packed.input_ids[start : start + length],
            attention_mask=packed.attention_mask[start : start + length],
            labels=packed.labels[start : start + length],
            token_train_mask=packed.token_train_mask[start : start + length],
            metadata=span.get("metadata", {}),
        )
        examples.append(example)

    return examples
