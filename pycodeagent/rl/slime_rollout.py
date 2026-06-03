"""Slime rollout adapter for training data export.

Converts training samples/trajectories into a stable rollout format
suitable for downstream training pipelines.

Rollout record structure:
- Mirrors TrainingSample with stable JSON-friendly fields
- Includes all metadata needed for training: reward, status, verifier
- Provides character-level and span-level loss masks
- Fully JSON-serializable

This module adapts the existing training sample pipeline rather than
duplicating serialization logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from pycodeagent.rl.sample_builder import TrainingSample, build_training_sample

if TYPE_CHECKING:
    from pycodeagent.trajectory.schema import Trajectory


class SlimeRolloutSpan(BaseModel):
    """A span within the rollout text.

    Attributes:
        start: Character start index (inclusive)
        end: Character end index (exclusive)
        trainable: Whether this span should be trained on
        kind: Segment kind (system, user, assistant, etc.)
    """

    start: int
    end: int
    trainable: bool
    kind: str = ""


class SlimeRolloutRecord(BaseModel):
    """A single rollout record for training.

    This is the stable export format that captures:
    - Full serialized text with all messages
    - Character-level loss mask
    - Span-level trainability information
    - Run metadata (task, profile, reward, status, verifier)

    The structure is designed to be:
    - JSON-serializable (all basic types)
    - Deterministic (same input → same output)
    - Complete (all training-relevant info preserved)

    Attributes:
        task_id: Task identifier
        tool_profile_id: Tool profile used for this run
        reward: Final reward value
        status: Run status (completed, error, timeout, etc.)
        verifier_passed: Whether verification passed
        verifier_score: Verification score
        text: Full serialized text
        character_mask: Character-level loss mask (0 or 1 per char)
        spans: Span-level loss mask with kind information
        segments: Full segment details for reference
        trainable_char_count: Number of trainable characters
        total_char_count: Total character count
        metadata: Additional run metadata (repo, final_diff, etc.)
    """

    task_id: str
    tool_profile_id: str
    reward: float
    status: str
    verifier_passed: bool
    verifier_score: float
    text: str
    character_mask: list[int]
    spans: list[dict[str, Any]]
    segments: list[dict[str, Any]]
    trainable_char_count: int
    total_char_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_slime_rollout(
    sample: TrainingSample,
    *,
    extra_metadata: dict[str, Any] | None = None,
) -> SlimeRolloutRecord:
    """Build a slime rollout record from a training sample.

    Adapts the training sample into a stable rollout format.
    This is a straightforward conversion that preserves all fields.

    Args:
        sample: The training sample to convert
        extra_metadata: Optional additional metadata to include

    Returns:
        SlimeRolloutRecord ready for export
    """
    metadata = dict(sample.metadata)
    if extra_metadata:
        metadata.update(extra_metadata)

    return SlimeRolloutRecord(
        task_id=sample.task_id,
        tool_profile_id=sample.tool_profile_id,
        reward=sample.reward,
        status=sample.status,
        verifier_passed=sample.verifier_passed,
        verifier_score=sample.verifier_score,
        text=sample.text,
        character_mask=sample.character_mask,
        spans=sample.spans,
        segments=sample.segments,
        trainable_char_count=sample.trainable_char_count,
        total_char_count=len(sample.text),
        metadata=metadata,
    )


def trajectory_to_slime_rollout(
    trajectory: Trajectory,
    *,
    extra_metadata: dict[str, Any] | None = None,
) -> SlimeRolloutRecord:
    """Convert a trajectory directly to a slime rollout record.

    Convenience function that chains:
    trajectory -> build_training_sample -> build_slime_rollout

    Args:
        trajectory: The trajectory to convert
        extra_metadata: Optional additional metadata to include

    Returns:
        SlimeRolloutRecord ready for export
    """
    sample = build_training_sample(trajectory, extra_metadata=extra_metadata)
    return build_slime_rollout(sample)


def get_trainable_text_segments(rollout: SlimeRolloutRecord) -> list[dict[str, Any]]:
    """Extract only the trainable text segments from a rollout.

    Convenience function for downstream code that only needs
    the learnable portions.

    Computes offsets by walking segments in order, which is deterministic
    and handles multiple trainable segments of the same kind correctly.

    Args:
        rollout: The rollout record

    Returns:
        List of dicts with: kind, text, start, end
    """
    result = []
    offset = 0

    for seg in rollout.segments:
        seg_length = len(seg["text"])
        if seg.get("trainable"):
            result.append(
                {
                    "kind": seg["kind"],
                    "text": seg["text"],
                    "start": offset,
                    "end": offset + seg_length,
                }
            )
        offset += seg_length

    return result


def split_context_and_target(
    rollout: SlimeRolloutRecord,
) -> tuple[str, str, list[dict[str, Any]]]:
    """Split rollout into context (non-trainable) and target (trainable) regions.

    This is a convenience for training setups that need explicit
    prompt/response separation.

    Note: The original ordering is lost in this split. For full
    training, use the character_mask directly.

    Args:
        rollout: The rollout record

    Returns:
        Tuple of (context_text, target_text, target_spans)
        - context_text: Concatenated non-trainable segments
        - target_text: Concatenated trainable segments
        - target_spans: Spans within target_text
    """
    context_parts = []
    target_parts = []
    target_spans = []

    target_offset = 0
    for seg in rollout.segments:
        if seg.get("trainable"):
            target_parts.append(seg["text"])
            target_spans.append(
                {
                    "start": target_offset,
                    "end": target_offset + len(seg["text"]),
                    "kind": seg["kind"],
                }
            )
            target_offset += len(seg["text"])
        else:
            context_parts.append(seg["text"])

    context_text = "".join(context_parts)
    target_text = "".join(target_parts)

    return context_text, target_text, target_spans
