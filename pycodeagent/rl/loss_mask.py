"""Loss mask generation for training data.

Computes which portions of a serialized trajectory should be included
in the loss computation during training.

Loss mask policy:
- system content: mask out (loss = 0)
- user content: mask out (loss = 0)
- assistant content: mask out (loss = 0)
- assistant tool calls: trainable (loss = 1)
- tool observations: mask out (loss = 0)

This module provides character-level and segment-level masks,
avoiding dependency on any specific tokenizer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from pycodeagent.rl.serializer import SerializedTrajectory


class TrainableSpan(BaseModel):
    """A span of trainable content within the serialized text.

    Attributes:
        start: Character start index (inclusive)
        end: Character end index (exclusive)
        trainable: Whether this span should be trained on
    """

    start: int
    end: int
    trainable: bool


class LossMask(BaseModel):
    """Loss mask for a serialized trajectory.

    Provides both character-level and span-level representations.

    Attributes:
        total_length: Total character length of serialized text
        character_mask: List of 0/1 values per character
        spans: List of TrainableSpan objects
        trainable_char_count: Number of trainable characters
        non_trainable_char_count: Number of non-trainable characters
    """

    total_length: int
    character_mask: list[int]
    spans: list[TrainableSpan]
    trainable_char_count: int
    non_trainable_char_count: int


def build_loss_mask(serialized: SerializedTrajectory) -> LossMask:
    """Build a loss mask from a serialized trajectory.

    Creates character-level and span-level masks based on the
    trainability of each segment.

    Args:
        serialized: The serialized trajectory

    Returns:
        LossMask with character-level mask and span information
    """
    character_mask: list[int] = []
    spans: list[TrainableSpan] = []

    current_offset = 0

    for segment in serialized.segments:
        seg_length = len(segment.text)
        seg_trainable = 1 if segment.trainable else 0

        # Build character mask for this segment
        character_mask.extend([seg_trainable] * seg_length)

        # Build span for this segment
        spans.append(
            TrainableSpan(
                start=current_offset,
                end=current_offset + seg_length,
                trainable=segment.trainable,
            )
        )

        current_offset += seg_length

    # Count trainable vs non-trainable
    trainable_count = sum(character_mask)
    non_trainable_count = len(character_mask) - trainable_count

    return LossMask(
        total_length=len(character_mask),
        character_mask=character_mask,
        spans=spans,
        trainable_char_count=trainable_count,
        non_trainable_char_count=non_trainable_count,
    )


def get_trainable_segments(serialized: SerializedTrajectory) -> list[dict]:
    """Extract only the trainable segments from a serialized trajectory.

    Convenience function for downstream processing that only needs
    the learnable portions.

    Args:
        serialized: The serialized trajectory

    Returns:
        List of dicts with segment info (kind, text, start, end)
    """
    result = []
    offset = 0

    for segment in serialized.segments:
        if segment.trainable:
            result.append(
                {
                    "kind": segment.kind,
                    "text": segment.text,
                    "start": offset,
                    "end": offset + len(segment.text),
                    "metadata": segment.metadata,
                }
            )
        offset += len(segment.text)

    return result
