"""Training sample builder.

Combines serialized trajectory and loss mask into a final training sample
object suitable for downstream export (e.g., to slime rollout format).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pycodeagent.rl.loss_mask import build_loss_mask
from pycodeagent.rl.prepared_sample import PreparedSample
from pycodeagent.rl.serializer import SerializedTrajectory, serialize_trajectory

if TYPE_CHECKING:
    from pycodeagent.trajectory.schema import Trajectory


# Compatibility name for callers that predate the unified RC-041 contract.
TrainingSample = PreparedSample


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
        sample_id=f"trajectory::{serialized.task_id}::{serialized.tool_profile_id}",
        sample_type="trajectory",
        source_type="trajectory",
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
        sample_id=f"trajectory::{serialized.task_id}::{serialized.tool_profile_id}",
        sample_type="trajectory",
        source_type="trajectory",
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
