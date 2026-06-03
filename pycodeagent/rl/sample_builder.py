"""Training sample builder.

Combines serialized trajectory and loss mask into a final training sample
object suitable for downstream export (e.g., to slime rollout format).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from pycodeagent.rl.loss_mask import LossMask, build_loss_mask
from pycodeagent.rl.serializer import SerializedTrajectory, serialize_trajectory

if TYPE_CHECKING:
    from pycodeagent.trajectory.schema import Trajectory


class TrainingSample(BaseModel):
    """Complete training sample built from a trajectory.

    Contains all information needed for supervised or RL training:
    - Serialized text and segments
    - Loss mask for computing gradients
    - Run metadata (task, profile, reward, status, verifier)

    Attributes:
        task_id: Task identifier
        tool_profile_id: Tool profile used for this run
        reward: Final reward value
        status: Run status (completed, error, timeout, etc.)
        verifier_passed: Whether verification passed
        verifier_score: Verification score
        text: Full serialized text
        segments: List of serialized segments with trainability
        character_mask: Character-level loss mask (0 or 1 per char)
        spans: Span-level loss mask
        trainable_char_count: Number of trainable characters
        metadata: Additional run metadata
    """

    task_id: str
    tool_profile_id: str
    reward: float
    status: str
    verifier_passed: bool
    verifier_score: float
    text: str
    segments: list[dict[str, Any]]
    character_mask: list[int]
    spans: list[dict[str, Any]]
    trainable_char_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_training_sample(
    trajectory: Trajectory,
    *,
    extra_metadata: dict[str, Any] | None = None,
) -> TrainingSample:
    """Build a training sample from a trajectory.

    Combines serialization and loss mask into a single object
    suitable for training data export.

    Args:
        trajectory: The trajectory to convert
        extra_metadata: Optional additional metadata to include

    Returns:
        TrainingSample with all fields populated
    """
    # Serialize trajectory
    serialized = serialize_trajectory(trajectory)

    # Build loss mask
    loss_mask = build_loss_mask(serialized)

    # Combine metadata
    metadata = dict(serialized.metadata)
    if extra_metadata:
        metadata.update(extra_metadata)

    return TrainingSample(
        task_id=serialized.task_id,
        tool_profile_id=serialized.tool_profile_id,
        reward=serialized.reward,
        status=serialized.status,
        verifier_passed=serialized.verifier_passed,
        verifier_score=serialized.verifier_score,
        text=serialized.text,
        segments=[seg.model_dump() for seg in serialized.segments],
        character_mask=loss_mask.character_mask,
        spans=[span.model_dump() for span in loss_mask.spans],
        trainable_char_count=loss_mask.trainable_char_count,
        metadata=metadata,
    )


def build_training_sample_from_serialized(
    serialized: SerializedTrajectory,
    *,
    extra_metadata: dict[str, Any] | None = None,
) -> TrainingSample:
    """Build a training sample from an already-serialized trajectory.

    Useful when serialization was done separately and loss mask
    needs to be computed.

    Args:
        serialized: The serialized trajectory
        extra_metadata: Optional additional metadata to include

    Returns:
        TrainingSample with all fields populated
    """
    # Build loss mask
    loss_mask = build_loss_mask(serialized)

    # Combine metadata
    metadata = dict(serialized.metadata)
    if extra_metadata:
        metadata.update(extra_metadata)

    return TrainingSample(
        task_id=serialized.task_id,
        tool_profile_id=serialized.tool_profile_id,
        reward=serialized.reward,
        status=serialized.status,
        verifier_passed=serialized.verifier_passed,
        verifier_score=serialized.verifier_score,
        text=serialized.text,
        segments=[seg.model_dump() for seg in serialized.segments],
        character_mask=loss_mask.character_mask,
        spans=[span.model_dump() for span in loss_mask.spans],
        trainable_char_count=loss_mask.trainable_char_count,
        metadata=metadata,
    )
