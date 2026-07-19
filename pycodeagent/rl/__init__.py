"""Stable training-data contract facade.

Operational helpers, controlled baselines, auxiliary routes, tokenizers, and
evaluation utilities must be imported from their owning submodules. This
package root intentionally exposes only the cross-route data contracts that
the repository treats as stable.
"""

from __future__ import annotations

from pycodeagent.rl.loss_mask import LossMask, build_loss_mask
from pycodeagent.rl.prepared_sample import (
    ASSISTANT_TOOL_CALL_ONLY,
    PREPARED_SAMPLE_SCHEMA_VERSION,
    PreparedSample,
    read_prepared_samples,
    write_prepared_samples,
)
from pycodeagent.rl.serializer import (
    SerializedSchemaFollowingSample,
    SerializedSegment,
    SerializedTrajectory,
    serialize_schema_following_sample,
    serialize_trajectory,
)
from pycodeagent.rl.training_bundle import (
    TRAINING_BUNDLE_SCHEMA,
    TRAINING_BUNDLE_VERSION,
    TrainingBundleArtifact,
    TrainingBundleBuilder,
    TrainingBundleBuildResult,
    TrainingBundleManifest,
    verify_training_bundle_manifest,
)
from pycodeagent.rl.training_prep import (
    RuntimeObservedSchemaFollowingTrainingPrepRecommendation,
    SchemaFollowingTrainingPrepRecommendation,
    TrainingPrepRecommendation,
    prepare_runtime_observed_schema_following_training_input,
    prepare_schema_following_training_input,
    prepare_slime_training_input,
)

__all__ = [
    "ASSISTANT_TOOL_CALL_ONLY",
    "PREPARED_SAMPLE_SCHEMA_VERSION",
    "TRAINING_BUNDLE_SCHEMA",
    "TRAINING_BUNDLE_VERSION",
    "LossMask",
    "PreparedSample",
    "RuntimeObservedSchemaFollowingTrainingPrepRecommendation",
    "SchemaFollowingTrainingPrepRecommendation",
    "SerializedSchemaFollowingSample",
    "SerializedSegment",
    "SerializedTrajectory",
    "TrainingBundleArtifact",
    "TrainingBundleBuildResult",
    "TrainingBundleBuilder",
    "TrainingBundleManifest",
    "TrainingPrepRecommendation",
    "build_loss_mask",
    "prepare_runtime_observed_schema_following_training_input",
    "prepare_schema_following_training_input",
    "prepare_slime_training_input",
    "read_prepared_samples",
    "serialize_schema_following_sample",
    "serialize_trajectory",
    "verify_training_bundle_manifest",
    "write_prepared_samples",
]
