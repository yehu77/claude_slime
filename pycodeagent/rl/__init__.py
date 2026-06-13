"""RL training data preparation module.

Provides trajectory serialization, loss-mask generation, rollout export,
tokenization, tensorization, packing, and minimal training entrypoints
for downstream supervised and RL training.
"""

from __future__ import annotations

from pycodeagent.rl.dataset_builder import (
    DatasetBuildResult,
    RolloutDatasetBuilder,
    build_rollout_dataset,
    discover_run_dirs,
)
from pycodeagent.rl.contract import (
    ContractIssue,
    ContractVerificationResult,
    NumericSummary,
    verify_dataset_dir,
    verify_schema_following_contract,
    verify_schema_following_dataset_dir,
    verify_slime_contract,
)
from pycodeagent.rl.claude_api_sft import (
    ClaudeApiSFTMessage,
    ClaudeApiSFTSample,
    ClaudeApiSFTTargetBlock,
    ClaudeApiSFTToolCallTarget,
    build_claude_api_sft_sample,
    build_claude_api_sft_samples,
)
from pycodeagent.rl.claude_api_sft_dataset import (
    ClaudeApiSFTDatasetBuildResult,
    ClaudeApiSFTFailedFile,
    build_claude_api_sft_dataset,
    discover_claude_gateway_session_files,
)
from pycodeagent.rl.claude_api_sft_dataset_io import (
    ClaudeApiSFTDatasetError,
    read_claude_api_sft_jsonl,
    validate_claude_api_sft_jsonl,
    write_claude_api_sft_jsonl,
)
from pycodeagent.rl.claude_api_sft_training import (
    ClaudeApiSFTPreparedSample,
    build_claude_api_sft_prepared_sample,
    build_claude_api_sft_prepared_samples,
    read_claude_api_sft_prepared_samples,
    write_claude_api_sft_prepared_samples,
)
from pycodeagent.rl.native_transformed_sft import (
    ToolUseRemapEntry,
    ToolUseRemapReport,
    TransformedNativeSFTBuildResult,
    build_transformed_native_sft_sample,
)
from pycodeagent.rl.native_transformed_sft_dataset import (
    NativeTransformedSFTDatasetBuildResult,
    NativeTransformedSFTFailedFile,
    build_native_transformed_sft_dataset,
)
from pycodeagent.rl.native_transformed_sft_dataset_validate import (
    NativeTransformedSFTValidationIssue,
    NativeTransformedSFTValidationReport,
    validate_native_transformed_sft_dataset,
)
from pycodeagent.rl.native_transformed_sft_eval import (
    NativeTransformedPredictor,
    NativeTransformedToolNameComparisonReport,
    NativeTransformedToolNameEvalCase,
    NativeTransformedToolNameEvalReport,
    build_native_transformed_prompt_text,
    compare_native_transformed_tool_name_reports,
    evaluate_native_transformed_tool_name_predictor,
    evaluate_native_transformed_tool_name_sample,
    write_native_transformed_comparison_report_json,
    write_native_transformed_eval_report_json,
)
from pycodeagent.rl.native_transformed_sft_smoke import (
    NativeTransformedSFTSmokeResult,
    NativeTransformedSmokeTrainBundle,
    build_native_transformed_smoke_train_bundle,
    run_native_transformed_sft_smoke,
    select_native_transformed_probe_samples,
    trim_native_transformed_sample_for_smoke,
)
from pycodeagent.rl.native_transformed_rl_dataset import (
    NativeTransformedExpectedToolCall,
    NativeTransformedRLDatasetBuildResult,
    NativeTransformedRLPromptSample,
    NativeTransformedRewardReference,
    build_native_transformed_rl_prompt_sample,
    export_native_transformed_rl_dataset,
    read_native_transformed_rl_jsonl,
    render_native_transformed_rl_prompt_text,
    write_native_transformed_rl_jsonl,
)
from pycodeagent.rl.native_transformed_reward import (
    NativeTransformedRLRewardCase,
    evaluate_native_transformed_rl_completion,
)
from pycodeagent.rl.dataset_manifest import (
    DatasetManifest,
    FilterConfig,
    RewardSummary,
    StatusCounts,
    VerifierCounts,
    build_reward_summary,
    build_status_counts,
    build_verifier_counts,
)
from pycodeagent.rl.export import (
    append_rollout_jsonl,
    export_batch_rollouts,
    read_rollout_json,
    read_rollouts_jsonl,
    write_rollout_json,
    write_rollouts_jsonl,
)
from pycodeagent.rl.loss_mask import LossMask, build_loss_mask
from pycodeagent.rl.packing import (
    PackedBatch,
    PackedSequence,
    pack_examples,
    unpack_sequence,
)
from pycodeagent.rl.schema_following import (
    CanonicalToolIntent,
    ExposedToolCallTarget,
    SchemaFollowingMessage,
    SchemaFollowingSample,
    render_exposed_tool_call_text,
)
from pycodeagent.rl.schema_following_dataset import (
    SchemaFollowingDatasetError,
    read_schema_following_jsonl,
    validate_schema_following_jsonl,
    write_schema_following_jsonl,
)
from pycodeagent.rl.schema_following_generate import (
    SyntheticProfileManifestEntry,
    SyntheticSchemaFollowingGenerationResult,
    generate_synthetic_schema_following_data,
)
from pycodeagent.rl.schema_following_from_trajectories import (
    TrajectoryDerivedGenerationResult,
    generate_schema_following_from_trajectories,
)
from pycodeagent.rl.schema_following_from_runtime import (
    RuntimeObservedGenerationResult,
    RuntimeObservedProfileManifestEntry,
    generate_schema_following_from_runtime_runs,
)
from pycodeagent.rl.schema_following_splits import (
    SCHEMA_FOLLOWING_SPLIT_ORDER,
    SyntheticProfileSpec,
    assign_synthetic_split,
    build_default_synthetic_profile_specs,
)
from pycodeagent.rl.schema_following_eval import (
    SchemaFollowingComparisonDelta,
    SchemaFollowingComparisonReport,
    SchemaFollowingEvaluationCase,
    SchemaFollowingEvaluationReport,
    SchemaFollowingPredictor,
    SchemaFollowingSplitMetrics,
    build_schema_following_prompt_text,
    compare_schema_following_reports,
    evaluate_schema_following_predictor,
    load_schema_following_profile_map,
    parse_tool_call_block,
    write_schema_following_comparison_json,
    write_schema_following_comparison_markdown,
    write_schema_following_eval_report_json,
    write_schema_following_eval_report_markdown,
)
from pycodeagent.rl.schema_following_sft import (
    HFCausalLMPredictor,
    LocalCausalLMTrainingResult,
    SchemaFollowingSFTExperimentResult,
    train_local_causal_lm,
    run_schema_following_sft_experiment,
)
from pycodeagent.rl.schema_following_training import (
    SchemaFollowingPreparedSample,
    build_schema_following_prepared_sample,
    build_schema_following_prepared_samples,
    load_schema_following_split,
    read_schema_following_prepared_samples,
    write_schema_following_prepared_samples,
)
from pycodeagent.rl.sample_builder import TrainingSample, build_training_sample
from pycodeagent.rl.serializer import (
    SerializedClaudeApiSFTSample,
    SerializedSchemaFollowingSample,
    SerializedSegment,
    SerializedTrajectory,
    serialize_claude_api_sft_sample,
    serialize_schema_following_sample,
    serialize_trajectory,
)
from pycodeagent.rl.slime_rollout import (
    SlimeRolloutRecord,
    SlimeRolloutSpan,
    build_slime_rollout,
    get_trainable_text_segments,
    split_context_and_target,
    trajectory_to_slime_rollout,
)
from pycodeagent.rl.slime_bridge import (
    PreparedRolloutBundle,
    SlimeTrainSample,
    build_slime_train_samples,
    build_tokenized_slime_train_samples,
    is_tokenized_training_path,
    load_bundle_tokenizer_config,
    load_prepared_rollout_bundle,
    map_run_status_to_slime_status,
    resolve_tokenized_jsonl_path,
    rollout_to_slime_train_sample,
    tokenized_example_to_slime_train_sample,
)
from pycodeagent.rl.tensorize import (
    TokenizedExample,
    tensorize_rollout,
    tensorize_sample,
    tensorize_schema_following_sample,
    tensorize_text,
)
from pycodeagent.rl.tokenizer import (
    BaseTokenizerAdapter,
    FakeTokenizerAdapter,
    HFTokenizerAdapter,
    resolve_tokenizer_adapter,
)
from pycodeagent.rl.tokenizer_config import (
    IGNORE_INDEX,
    FakeTokenizerConfig,
    TokenizerConfig,
)
from pycodeagent.rl.train_config import TrainConfig
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.rl.train_loop import (
    EmptyTrainingDatasetError,
    ToyModel,
    TrainMetrics,
    TrainResult,
    compute_masked_cross_entropy_loss,
    run_training,
)
from pycodeagent.rl.train_report import TrainReport, write_training_report
from pycodeagent.rl.training_prep import (
    NativeTransformedSFTTrainingPrepRecommendation,
    RuntimeObservedSchemaFollowingTrainingPrepRecommendation,
    SchemaFollowingTrainingPrepRecommendation,
    TrainingPrepRecommendation,
    prepare_native_transformed_sft_training_input,
    prepare_runtime_observed_schema_following_training_input,
    prepare_schema_following_training_input,
    prepare_slime_training_input,
)

__all__ = [
    # Serializer
    "SerializedSegment",
    "SerializedTrajectory",
    "serialize_trajectory",
    # Loss mask
    "LossMask",
    "build_loss_mask",
    # Sample builder
    "TrainingSample",
    "build_training_sample",
    # Slime rollout
    "SlimeRolloutRecord",
    "SlimeRolloutSpan",
    "build_slime_rollout",
    "trajectory_to_slime_rollout",
    "get_trainable_text_segments",
    "split_context_and_target",
    # Slime bridge
    "PreparedRolloutBundle",
    "SlimeTrainSample",
    "load_prepared_rollout_bundle",
    "load_bundle_tokenizer_config",
    "map_run_status_to_slime_status",
    "rollout_to_slime_train_sample",
    "tokenized_example_to_slime_train_sample",
    "build_slime_train_samples",
    "build_tokenized_slime_train_samples",
    "is_tokenized_training_path",
    "resolve_tokenized_jsonl_path",
    # Export
    "write_rollout_json",
    "read_rollout_json",
    "write_rollouts_jsonl",
    "read_rollouts_jsonl",
    "append_rollout_jsonl",
    "export_batch_rollouts",
    # Dataset manifest
    "DatasetManifest",
    "FilterConfig",
    "RewardSummary",
    "StatusCounts",
    "VerifierCounts",
    "build_reward_summary",
    "build_status_counts",
    "build_verifier_counts",
    # Contract verification
    "ContractIssue",
    "ContractVerificationResult",
    "NumericSummary",
    "verify_dataset_dir",
    "verify_schema_following_contract",
    "verify_schema_following_dataset_dir",
    "verify_slime_contract",
    # Claude API SFT
    "ClaudeApiSFTMessage",
    "ClaudeApiSFTSample",
    "ClaudeApiSFTTargetBlock",
    "ClaudeApiSFTToolCallTarget",
    "ClaudeApiSFTDatasetBuildResult",
    "ClaudeApiSFTDatasetError",
    "ClaudeApiSFTFailedFile",
    "build_claude_api_sft_sample",
    "build_claude_api_sft_samples",
    "build_claude_api_sft_dataset",
    "discover_claude_gateway_session_files",
    "read_claude_api_sft_jsonl",
    "validate_claude_api_sft_jsonl",
    "write_claude_api_sft_jsonl",
    "ClaudeApiSFTPreparedSample",
    "build_claude_api_sft_prepared_sample",
    "build_claude_api_sft_prepared_samples",
    "read_claude_api_sft_prepared_samples",
    "write_claude_api_sft_prepared_samples",
    "ToolUseRemapEntry",
    "ToolUseRemapReport",
    "TransformedNativeSFTBuildResult",
    "build_transformed_native_sft_sample",
    "NativeTransformedSFTDatasetBuildResult",
    "NativeTransformedSFTFailedFile",
    "build_native_transformed_sft_dataset",
    "NativeTransformedSFTValidationIssue",
    "NativeTransformedSFTValidationReport",
    "validate_native_transformed_sft_dataset",
    "NativeTransformedPredictor",
    "NativeTransformedToolNameComparisonReport",
    "NativeTransformedToolNameEvalCase",
    "NativeTransformedToolNameEvalReport",
    "build_native_transformed_prompt_text",
    "compare_native_transformed_tool_name_reports",
    "evaluate_native_transformed_tool_name_predictor",
    "evaluate_native_transformed_tool_name_sample",
    "write_native_transformed_comparison_report_json",
    "write_native_transformed_eval_report_json",
    "NativeTransformedSFTSmokeResult",
    "NativeTransformedSmokeTrainBundle",
    "build_native_transformed_smoke_train_bundle",
    "run_native_transformed_sft_smoke",
    "select_native_transformed_probe_samples",
    "trim_native_transformed_sample_for_smoke",
    "NativeTransformedExpectedToolCall",
    "NativeTransformedRewardReference",
    "NativeTransformedRLPromptSample",
    "NativeTransformedRLDatasetBuildResult",
    "build_native_transformed_rl_prompt_sample",
    "export_native_transformed_rl_dataset",
    "read_native_transformed_rl_jsonl",
    "render_native_transformed_rl_prompt_text",
    "write_native_transformed_rl_jsonl",
    "NativeTransformedRLRewardCase",
    "evaluate_native_transformed_rl_completion",
    # Dataset builder
    "DatasetBuildResult",
    "RolloutDatasetBuilder",
    "build_rollout_dataset",
    "discover_run_dirs",
    # Tokenizer config
    "TokenizerConfig",
    "FakeTokenizerConfig",
    "IGNORE_INDEX",
    # Tokenizer
    "BaseTokenizerAdapter",
    "FakeTokenizerAdapter",
    "HFTokenizerAdapter",
    "resolve_tokenizer_adapter",
    # Tensorize
    "TokenizedExample",
    "tensorize_sample",
    "tensorize_rollout",
    "tensorize_schema_following_sample",
    "tensorize_text",
    # Packing
    "PackedSequence",
    "PackedBatch",
    "pack_examples",
    "unpack_sequence",
    # Schema-following samples
    "SerializedClaudeApiSFTSample",
    "CanonicalToolIntent",
    "ExposedToolCallTarget",
    "SchemaFollowingMessage",
    "SchemaFollowingSample",
    "SerializedSchemaFollowingSample",
    "serialize_schema_following_sample",
    "serialize_claude_api_sft_sample",
    "render_exposed_tool_call_text",
    "SchemaFollowingDatasetError",
    "read_schema_following_jsonl",
    "write_schema_following_jsonl",
    "validate_schema_following_jsonl",
    "SyntheticProfileSpec",
    "SCHEMA_FOLLOWING_SPLIT_ORDER",
    "assign_synthetic_split",
    "build_default_synthetic_profile_specs",
    "SyntheticProfileManifestEntry",
    "SyntheticSchemaFollowingGenerationResult",
    "generate_synthetic_schema_following_data",
    "TrajectoryDerivedGenerationResult",
    "generate_schema_following_from_trajectories",
    "RuntimeObservedProfileManifestEntry",
    "RuntimeObservedGenerationResult",
    "generate_schema_following_from_runtime_runs",
    "SchemaFollowingPredictor",
    "SchemaFollowingEvaluationCase",
    "SchemaFollowingSplitMetrics",
    "SchemaFollowingEvaluationReport",
    "SchemaFollowingComparisonDelta",
    "SchemaFollowingComparisonReport",
    "CanonicalIntentBaselinePredictor",
    "build_schema_following_prompt_text",
    "parse_tool_call_block",
    "load_schema_following_profile_map",
    "evaluate_schema_following_predictor",
    "compare_schema_following_reports",
    "write_schema_following_eval_report_json",
    "write_schema_following_eval_report_markdown",
    "write_schema_following_comparison_json",
    "write_schema_following_comparison_markdown",
    "SchemaFollowingPreparedSample",
    "load_schema_following_split",
    "build_schema_following_prepared_sample",
    "build_schema_following_prepared_samples",
    "write_schema_following_prepared_samples",
    "read_schema_following_prepared_samples",
    # Training config
    "TrainConfig",
    # Training dataset
    "TrainDataset",
    # Training prep
    "TrainingPrepRecommendation",
    "SchemaFollowingTrainingPrepRecommendation",
    "RuntimeObservedSchemaFollowingTrainingPrepRecommendation",
    "NativeTransformedSFTTrainingPrepRecommendation",
    "prepare_slime_training_input",
    "prepare_schema_following_training_input",
    "prepare_runtime_observed_schema_following_training_input",
    "prepare_native_transformed_sft_training_input",
    "LocalCausalLMTrainingResult",
    "SchemaFollowingSFTExperimentResult",
    "HFCausalLMPredictor",
    "train_local_causal_lm",
    "run_schema_following_sft_experiment",
    # Training loop
    "ToyModel",
    "TrainMetrics",
    "TrainResult",
    "EmptyTrainingDatasetError",
    "run_training",
    "compute_masked_cross_entropy_loss",
    # Training report
    "TrainReport",
    "write_training_report",
]
