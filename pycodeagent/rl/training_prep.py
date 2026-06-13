"""Prepare slime-compatible training inputs from study/experiment outputs.

This layer sits on top of contract verification and produces a concrete,
recommended training bundle:
- rollout/sample dataset
- tokenized training JSONL
- tokenizer config
- train config
- preparation manifest with explicit defaults and rationale
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from pycodeagent.rl.contract import (
    ContractVerificationResult,
    verify_dataset_dir,
    verify_schema_following_contract,
)
from pycodeagent.rl.dataset_builder import RolloutDatasetBuilder, discover_run_dirs
from pycodeagent.rl.dataset_manifest import FilterConfig
from pycodeagent.rl.claude_api_sft_dataset_io import read_claude_api_sft_jsonl
from pycodeagent.rl.claude_api_sft_training import (
    build_claude_api_sft_prepared_samples,
    write_claude_api_sft_prepared_samples,
)
from pycodeagent.rl.native_transformed_sft_dataset_validate import (
    validate_native_transformed_sft_dataset,
)
from pycodeagent.rl.schema_following_training import (
    build_schema_following_prepared_samples,
    load_schema_following_split,
    write_schema_following_prepared_samples,
)
from pycodeagent.rl.schema_following_from_runtime import (
    generate_schema_following_from_runtime_runs,
)
from pycodeagent.rl.slime_bridge import load_prepared_rollout_bundle
from pycodeagent.rl.tensorize import (
    tensorize_rollout,
    tensorize_schema_following_sample,
    tensorize_text,
)
from pycodeagent.rl.tokenizer import BaseTokenizerAdapter, resolve_tokenizer_adapter
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig
from pycodeagent.rl.train_config import TrainConfig
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.trajectory.schema import RunStatus


class TrainingPrepRecommendation(BaseModel):
    """Concrete recommendation for training-side data consumption."""

    source_type: str
    source_path: str
    prepared_dataset_dir: str
    canonical_rollout_input: str
    canonical_training_input: str
    include_failed: bool
    verifier_passed: bool | None
    recommended_max_length: int
    recommended_batch_size: int
    recommended_learning_rate: float
    tokenized_example_count: int
    completed_run_count: int
    excluded_run_count: int
    contract_ok: bool
    contract_report_path: str
    tokenizer_config_path: str
    train_config_path: str
    notes: list[str] = Field(default_factory=list)


class SchemaFollowingTrainingPrepRecommendation(BaseModel):
    """Concrete recommendation for schema-following training consumption."""

    source_type: str
    source_path: str
    split: str
    prepared_dataset_dir: str
    canonical_sample_input: str
    canonical_training_input: str
    recommended_max_length: int
    recommended_batch_size: int
    recommended_learning_rate: float
    prepared_sample_count: int
    tokenized_example_count: int
    contract_ok: bool
    contract_report_path: str
    tokenizer_config_path: str
    train_config_path: str
    notes: list[str] = Field(default_factory=list)


class NativeTransformedSFTTrainingPrepRecommendation(BaseModel):
    """Concrete recommendation for native-transformed Claude API SFT training."""

    source_type: str
    source_path: str
    split: str
    prepared_dataset_dir: str
    validation_ok: bool
    validation_report_path: str
    primary_sample_input: str
    primary_prepared_input: str
    primary_training_input: str
    recommended_max_length: int
    recommended_batch_size: int
    recommended_learning_rate: float
    raw_sample_count: int
    prepared_sample_count: int
    tokenized_example_count: int
    tokenizer_config_path: str
    train_config_path: str
    notes: list[str] = Field(default_factory=list)


class RuntimeObservedSchemaFollowingTrainingPrepRecommendation(BaseModel):
    """Concrete recommendation for local-runtime observed ToolView training."""

    source_type: str
    source_path: str
    split: str
    raw_dataset_dir: str
    prepared_dataset_dir: str
    canonical_sample_input: str
    canonical_training_input: str
    discovered_run_count: int
    included_run_count: int
    observed_sample_count: int
    tokenized_example_count: int
    contract_ok: bool
    raw_dataset_manifest_path: str
    raw_source_manifest_path: str
    prepared_contract_report_path: str
    tokenizer_config_path: str
    train_config_path: str
    notes: list[str] = Field(default_factory=list)


def prepare_slime_training_input(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    source_type: str = "study",
    include_failed: bool = False,
    verifier_passed: bool | None = None,
    max_length: int = 2048,
    batch_size: int = 8,
    learning_rate: float = 1e-4,
    max_steps: int = 1000,
    seed: int = 42,
    tokenizer: BaseTokenizerAdapter | None = None,
    tokenizer_config: TokenizerConfig | None = None,
    fake_tokenizer_config: FakeTokenizerConfig | None = None,
    run_id: str = "slime_contract_train",
) -> TrainingPrepRecommendation:
    """Prepare a recommended training bundle from experiment/study outputs."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)

    tokenizer, resolved_tokenizer_config = resolve_tokenizer_adapter(
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
        default_max_length=max_length,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    filter_config = FilterConfig(
        include_failed=include_failed,
        verifier_passed=verifier_passed,
    )

    dataset_builder = RolloutDatasetBuilder(dataset_id=f"{run_id}_dataset")
    run_dirs = discover_run_dirs(source_dir, source_type=source_type)
    dataset_build = dataset_builder.build_from_run_dirs(
        run_dirs,
        output_dir,
        source_type=source_type,
        source_path=str(source_dir),
        filter_config=filter_config,
    )

    tokenizer_metadata = dict(resolved_tokenizer_config.metadata)
    tokenizer_metadata.update(
        {
            "prepared_from": str(source_dir),
            "source_type": source_type,
            "canonical_rollout_input": "rollouts.jsonl",
        }
    )
    tokenizer_config = resolved_tokenizer_config.model_copy(
        update={
            "max_length": max_length,
            "truncation": True,
            "padding": "do_not_pad",
            "metadata": tokenizer_metadata,
        }
    )

    contract_result = verify_dataset_dir(
        dataset_build.output_dir,
        source_type=source_type,
        source_path=str(source_dir),
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        pack_max_length=max_length,
        write_report=True,
    )
    if not contract_result.ok:
        raise ValueError(
            "Training input preparation failed contract verification. "
            f"See {dataset_build.output_dir / 'contract_report.json'}"
        )

    rollouts = load_prepared_rollout_bundle(dataset_build.output_dir).rollouts
    tokenized_examples = [
        tensorize_rollout(rollout, tokenizer, tokenizer_config) for rollout in rollouts
    ]
    tokenized_dataset = TrainDataset.from_examples(tokenized_examples)
    tokenized_path = output_dir / "tokenized.jsonl"
    tokenized_dataset.save_jsonl(tokenized_path)

    tokenizer_config_path = output_dir / "tokenizer_config.yaml"
    tokenizer_config.save(tokenizer_config_path)

    train_output_dir = output_dir / "training_outputs"
    train_config = TrainConfig(
        run_id=run_id,
        dataset_path=str(tokenized_path),
        output_dir=str(train_output_dir),
        max_steps=max_steps,
        batch_size=batch_size,
        learning_rate=learning_rate,
        seed=seed,
        metadata={
            "prepared_from": str(source_dir),
            "source_type": source_type,
            "canonical_rollout_input": "rollouts.jsonl",
            "canonical_training_input": "tokenized.jsonl",
            "include_failed": include_failed,
            "verifier_passed": verifier_passed,
        },
    )
    train_config_path = output_dir / "train_config.json"
    train_config.save(train_config_path)

    notes = [
        "Use rollouts.jsonl as the canonical upstream export for downstream training prep.",
        "Use tokenized.jsonl as the direct TrainDataset input for the current training loop.",
        "Default include_failed=False excludes non-completed runs while preserving completed verifier-failed runs.",
        f"Current recommended max_length={max_length}; smaller values should be revalidated with verify_slime_contract.py.",
    ]

    recommendation = TrainingPrepRecommendation(
        source_type=source_type,
        source_path=str(source_dir),
        prepared_dataset_dir=str(output_dir),
        canonical_rollout_input="rollouts.jsonl",
        canonical_training_input="tokenized.jsonl",
        include_failed=include_failed,
        verifier_passed=verifier_passed,
        recommended_max_length=max_length,
        recommended_batch_size=batch_size,
        recommended_learning_rate=learning_rate,
        tokenized_example_count=len(tokenized_examples),
        completed_run_count=contract_result.status_counts.get(
            RunStatus.COMPLETED.value, 0
        ),
        excluded_run_count=len(run_dirs) - len(tokenized_examples),
        contract_ok=contract_result.ok,
        contract_report_path=str(output_dir / "contract_report.json"),
        tokenizer_config_path=str(tokenizer_config_path),
        train_config_path=str(train_config_path),
        notes=notes,
    )
    _write_recommendation(output_dir / "training_prep.json", recommendation)
    return recommendation


def prepare_native_transformed_sft_training_input(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    split: str = "train",
    max_length: int = 2048,
    batch_size: int = 8,
    learning_rate: float = 1e-4,
    max_steps: int = 1000,
    seed: int = 42,
    tokenizer: BaseTokenizerAdapter | None = None,
    tokenizer_config: TokenizerConfig | None = None,
    fake_tokenizer_config: FakeTokenizerConfig | None = None,
    run_id: str = "native_transformed_sft_train",
) -> NativeTransformedSFTTrainingPrepRecommendation:
    """Prepare training artifacts from a validated native-transformed SFT dataset.

    This intentionally reuses the existing Claude API SFT sample format. The
    source dataset stays primary; this layer only serializes, masks, tokenizes,
    and writes the current training-loop bundle.
    """
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    split_path = source_dir / f"{split}.jsonl"

    if split != "train":
        raise ValueError("Native transformed SFT training prep currently supports split='train'")

    validation = validate_native_transformed_sft_dataset(source_dir)
    if not validation.ok:
        raise ValueError(
            "Native transformed SFT training input failed validation. "
            f"See {validation.validation_report_path}"
        )

    tokenizer, resolved_tokenizer_config = resolve_tokenizer_adapter(
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
        default_max_length=max_length,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_samples = read_claude_api_sft_jsonl(split_path)
    prepared_samples = build_claude_api_sft_prepared_samples(raw_samples)
    prepared_path = output_dir / "samples.jsonl"
    write_claude_api_sft_prepared_samples(prepared_samples, prepared_path)

    tokenizer_metadata = dict(resolved_tokenizer_config.metadata)
    tokenizer_metadata.update(
        {
            "prepared_from": str(source_dir),
            "source_type": "native_transformed_claude_api_sft",
            "source_split": split,
            "primary_sample_input": f"{split}.jsonl",
            "primary_prepared_input": "samples.jsonl",
        }
    )
    tokenizer_config = resolved_tokenizer_config.model_copy(
        update={
            "max_length": max_length,
            "truncation": True,
            "padding": "do_not_pad",
            "metadata": tokenizer_metadata,
        }
    )

    tokenized_examples = [
        tensorize_text(
            sample.text,
            sample.character_mask,
            tokenizer,
            tokenizer_config,
            metadata={
                **sample.metadata,
                "sample_id": sample.sample_id,
                "sample_type": sample.sample_type,
                "source_type": "native_transformed_claude_api_sft",
                "raw_source_type": sample.source_type,
                "task_id": sample.task_id,
                "tool_profile_id": sample.tool_profile_id,
                "loss_mask_policy": sample.loss_mask_policy,
                "trainable_char_count": sample.trainable_char_count,
            },
        )
        for sample in prepared_samples
    ]
    empty_trainable_examples = [
        example.metadata.get("sample_id", "<unknown>")
        for example in tokenized_examples
        if example.trainable_token_count == 0
    ]
    if empty_trainable_examples:
        preview = ", ".join(str(sample_id) for sample_id in empty_trainable_examples[:5])
        raise ValueError(
            "Native transformed SFT training prep produced examples with no trainable "
            f"tokens after tokenization/truncation: {preview}. Increase --max-length "
            "or use a tokenizer/truncation policy that preserves assistant targets."
        )
    tokenized_dataset = TrainDataset.from_examples(tokenized_examples)
    tokenized_path = output_dir / "tokenized.jsonl"
    tokenized_dataset.save_jsonl(tokenized_path)

    tokenizer_config_path = output_dir / "tokenizer_config.yaml"
    tokenizer_config.save(tokenizer_config_path)

    train_output_dir = output_dir / "training_outputs"
    train_config = TrainConfig(
        run_id=run_id,
        dataset_path=str(tokenized_path),
        output_dir=str(train_output_dir),
        max_steps=max_steps,
        batch_size=batch_size,
        learning_rate=learning_rate,
        seed=seed,
        metadata={
            "prepared_from": str(source_dir),
            "source_type": "native_transformed_claude_api_sft",
            "source_split": split,
            "primary_sample_input": f"{split}.jsonl",
            "primary_prepared_input": "samples.jsonl",
            "primary_training_input": "tokenized.jsonl",
            "validation_report_path": validation.validation_report_path,
        },
    )
    train_config_path = output_dir / "train_config.json"
    train_config.save(train_config_path)

    recommendation = NativeTransformedSFTTrainingPrepRecommendation(
        source_type="native_transformed_claude_api_sft",
        source_path=str(source_dir),
        split=split,
        prepared_dataset_dir=str(output_dir),
        validation_ok=validation.ok,
        validation_report_path=validation.validation_report_path,
        primary_sample_input=f"{split}.jsonl",
        primary_prepared_input="samples.jsonl",
        primary_training_input="tokenized.jsonl",
        recommended_max_length=max_length,
        recommended_batch_size=batch_size,
        recommended_learning_rate=learning_rate,
        raw_sample_count=len(raw_samples),
        prepared_sample_count=len(prepared_samples),
        tokenized_example_count=len(tokenized_examples),
        tokenizer_config_path=str(tokenizer_config_path),
        train_config_path=str(train_config_path),
        notes=[
            "Use the validated native-transformed train.jsonl as the primary upstream input.",
            "No additional raw dataset format is introduced by this preparation step.",
            "Prepared samples reuse the Claude API SFT serializer and assistant-selected-block loss mask.",
            "Use tokenized.jsonl as the direct TrainDataset input for the current training loop.",
        ],
    )
    _write_recommendation(output_dir / "training_prep.json", recommendation)
    return recommendation


def prepare_schema_following_training_input(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    split: str = "train",
    max_length: int = 2048,
    batch_size: int = 8,
    learning_rate: float = 1e-4,
    max_steps: int = 1000,
    seed: int = 42,
    tokenizer: BaseTokenizerAdapter | None = None,
    tokenizer_config: TokenizerConfig | None = None,
    fake_tokenizer_config: FakeTokenizerConfig | None = None,
    run_id: str = "schema_following_train",
) -> SchemaFollowingTrainingPrepRecommendation:
    """Prepare a recommended training bundle from a schema-following dataset split."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)

    tokenizer, resolved_tokenizer_config = resolve_tokenizer_adapter(
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
        default_max_length=max_length,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_samples = load_schema_following_split(source_dir, split=split)
    prepared_samples = build_schema_following_prepared_samples(raw_samples)
    write_schema_following_prepared_samples(prepared_samples, output_dir / "samples.jsonl")

    tokenizer_metadata = dict(resolved_tokenizer_config.metadata)
    tokenizer_metadata.update(
        {
            "prepared_from": str(source_dir),
            "source_type": "schema_following",
            "source_split": split,
            "canonical_sample_input": f"{split}.jsonl",
        }
    )
    tokenizer_config = resolved_tokenizer_config.model_copy(
        update={
            "max_length": max_length,
            "truncation": True,
            "padding": "do_not_pad",
            "metadata": tokenizer_metadata,
        }
    )

    contract_result = verify_schema_following_contract(
        source_dir,
        output_dir,
        split=split,
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        pack_max_length=max_length,
        write_report=True,
    )
    if not contract_result.ok:
        raise ValueError(
            "Schema-following training input preparation failed contract verification. "
            f"See {output_dir / 'contract_report.json'}"
        )

    tokenized_examples = [
        tensorize_schema_following_sample(sample, tokenizer, tokenizer_config)
        for sample in prepared_samples
    ]
    tokenized_dataset = TrainDataset.from_examples(tokenized_examples)
    tokenized_path = output_dir / "tokenized.jsonl"
    tokenized_dataset.save_jsonl(tokenized_path)

    tokenizer_config_path = output_dir / "tokenizer_config.yaml"
    tokenizer_config.save(tokenizer_config_path)

    train_output_dir = output_dir / "training_outputs"
    train_config = TrainConfig(
        run_id=run_id,
        dataset_path=str(tokenized_path),
        output_dir=str(train_output_dir),
        max_steps=max_steps,
        batch_size=batch_size,
        learning_rate=learning_rate,
        seed=seed,
        metadata={
            "prepared_from": str(source_dir),
            "source_type": "schema_following",
            "source_split": split,
            "canonical_sample_input": f"{split}.jsonl",
            "canonical_training_input": "tokenized.jsonl",
        },
    )
    train_config_path = output_dir / "train_config.json"
    train_config.save(train_config_path)

    recommendation = SchemaFollowingTrainingPrepRecommendation(
        source_type="schema_following",
        source_path=str(source_dir),
        split=split,
        prepared_dataset_dir=str(output_dir),
        canonical_sample_input=f"{split}.jsonl",
        canonical_training_input="tokenized.jsonl",
        recommended_max_length=max_length,
        recommended_batch_size=batch_size,
        recommended_learning_rate=learning_rate,
        prepared_sample_count=len(prepared_samples),
        tokenized_example_count=len(tokenized_examples),
        contract_ok=contract_result.ok,
        contract_report_path=str(output_dir / "contract_report.json"),
        tokenizer_config_path=str(tokenizer_config_path),
        train_config_path=str(train_config_path),
        notes=[
            "Use the selected split JSONL as the canonical upstream schema-following input.",
            "Prepared samples keep only assistant_tool_call trainable under the current loss mask policy.",
            "Use tokenized.jsonl as the direct TrainDataset input for the current training loop.",
        ],
    )
    _write_recommendation(output_dir / "training_prep.json", recommendation)
    return recommendation


def prepare_runtime_observed_schema_following_training_input(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    source_type: str = "study",
    filter_config: FilterConfig | None = None,
    split: str = "train",
    max_length: int = 2048,
    batch_size: int = 8,
    learning_rate: float = 1e-4,
    max_steps: int = 1000,
    seed: int = 42,
    tokenizer: BaseTokenizerAdapter | None = None,
    tokenizer_config: TokenizerConfig | None = None,
    fake_tokenizer_config: FakeTokenizerConfig | None = None,
    run_id: str = "runtime_observed_schema_following_train",
) -> RuntimeObservedSchemaFollowingTrainingPrepRecommendation:
    """Prepare training artifacts from local runtime observed ToolView runs."""
    if split != "train":
        raise ValueError("Runtime observed schema-following prep currently supports split='train'")

    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dataset_dir = output_dir / "raw_dataset"
    prepared_dataset_dir = output_dir / "prepared"

    export_result = generate_schema_following_from_runtime_runs(
        source_dir,
        raw_dataset_dir,
        source_type=source_type,
        filter_config=filter_config,
        split_seed=seed,
    )
    prepared_recommendation = prepare_schema_following_training_input(
        raw_dataset_dir,
        prepared_dataset_dir,
        split=split,
        max_length=max_length,
        batch_size=batch_size,
        learning_rate=learning_rate,
        max_steps=max_steps,
        seed=seed,
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
        run_id=run_id,
    )

    recommendation = RuntimeObservedSchemaFollowingTrainingPrepRecommendation(
        source_type=source_type,
        source_path=str(source_dir),
        split=split,
        raw_dataset_dir=str(raw_dataset_dir),
        prepared_dataset_dir=str(prepared_dataset_dir),
        canonical_sample_input="raw_dataset/train.jsonl",
        canonical_training_input="prepared/tokenized.jsonl",
        discovered_run_count=export_result.discovered_run_count,
        included_run_count=export_result.included_run_count,
        observed_sample_count=export_result.sample_count,
        tokenized_example_count=prepared_recommendation.tokenized_example_count,
        contract_ok=prepared_recommendation.contract_ok,
        raw_dataset_manifest_path=str(raw_dataset_dir / "dataset_manifest.json"),
        raw_source_manifest_path=str(raw_dataset_dir / "source_manifest.json"),
        prepared_contract_report_path=str(prepared_dataset_dir / "contract_report.json"),
        tokenizer_config_path=prepared_recommendation.tokenizer_config_path,
        train_config_path=prepared_recommendation.train_config_path,
        notes=[
            "Use raw_dataset/train.jsonl as the canonical observed ToolView sample export.",
            "Prepared samples preserve assistant_tool_call_only masking through the existing schema-following path.",
            "runtime_trace remains an audit artifact and is not the primary exporter input in this milestone.",
        ],
    )
    _write_recommendation(output_dir / "training_prep.json", recommendation)
    return recommendation


def _write_recommendation(path: Path, recommendation: BaseModel) -> None:
    path.write_text(
        json.dumps(recommendation.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
