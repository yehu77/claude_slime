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
    validate_rollout_dataset_source,
    validate_schema_following_source,
)
from pycodeagent.rl.dataset_builder import RolloutDatasetBuilder, discover_run_dirs
from pycodeagent.rl.dataset_manifest import FilterConfig
from pycodeagent.rl.schema_following_from_runtime import (
    generate_schema_following_from_runtime_runs,
)
from pycodeagent.rl.training_bundle import TrainingBundleBuilder
from pycodeagent.rl.tokenizer import BaseTokenizerAdapter
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig
from pycodeagent.trajectory.schema import RunStatus


class TrainingPrepRecommendation(BaseModel):
    """Concrete recommendation for training-side data consumption."""

    source_type: str
    source_path: str
    prepared_dataset_dir: str
    canonical_rollout_input: str
    canonical_training_input: str
    packed_training_input: str
    bundle_manifest_path: str
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
    packed_training_input: str
    bundle_manifest_path: str
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


class RuntimeObservedSchemaFollowingTrainingPrepRecommendation(BaseModel):
    """Concrete recommendation for local-runtime observed ToolView training."""

    source_type: str
    source_path: str
    split: str
    raw_dataset_dir: str
    prepared_dataset_dir: str
    canonical_sample_input: str
    canonical_training_input: str
    packed_training_input: str
    bundle_manifest_path: str
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

    prepared_samples, rollouts, source_issues = validate_rollout_dataset_source(
        dataset_build.output_dir
    )
    bundle = TrainingBundleBuilder().build(
        prepared_samples,
        output_dir,
        source_type=source_type,
        source_path=source_dir,
        run_id=run_id,
        max_length=max_length,
        batch_size=batch_size,
        learning_rate=learning_rate,
        max_steps=max_steps,
        seed=seed,
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
        tokenizer_metadata={
            "prepared_from": str(source_dir),
            "source_type": source_type,
            "canonical_rollout_input": "rollouts.jsonl",
        },
        train_metadata={
            "prepared_from": str(source_dir),
            "source_type": source_type,
            "canonical_rollout_input": "rollouts.jsonl",
            "canonical_training_input": "tokenized.jsonl",
            "include_failed": include_failed,
            "verifier_passed": verifier_passed,
        },
        bundle_metadata={
            "source_adapter": "rollout_dataset",
            "include_failed": include_failed,
            "verifier_passed": verifier_passed,
        },
        source_artifacts=["dataset_manifest.json", "rollouts.jsonl"],
        source_issues=source_issues,
        rollout_count=len(rollouts),
        allow_empty=True,
    )

    notes = [
        "Use rollouts.jsonl as the canonical upstream export for downstream training prep.",
        "Use tokenized.jsonl as the direct TrainDataset input for a downstream training consumer.",
        "Use packed.jsonl for the checksummed packed representation; verify bundle_manifest.json before consumption.",
        "Default include_failed=False excludes non-completed runs while preserving completed verifier-failed runs.",
        f"Current recommended max_length={max_length}; smaller values should be revalidated with python -B -m pycodeagent verify.",
    ]

    recommendation = TrainingPrepRecommendation(
        source_type=source_type,
        source_path=str(source_dir),
        prepared_dataset_dir=str(output_dir),
        canonical_rollout_input="rollouts.jsonl",
        canonical_training_input="tokenized.jsonl",
        packed_training_input="packed.jsonl",
        bundle_manifest_path=str(bundle.manifest_path),
        include_failed=include_failed,
        verifier_passed=verifier_passed,
        recommended_max_length=max_length,
        recommended_batch_size=batch_size,
        recommended_learning_rate=learning_rate,
        tokenized_example_count=bundle.manifest.tokenized_count,
        completed_run_count=bundle.contract_result.status_counts.get(
            RunStatus.COMPLETED.value, 0
        ),
        excluded_run_count=len(run_dirs) - bundle.manifest.sample_count,
        contract_ok=bundle.contract_result.ok,
        contract_report_path=str(bundle.contract_report_path),
        tokenizer_config_path=str(bundle.tokenizer_config_path),
        train_config_path=str(bundle.train_config_path),
        notes=notes,
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
    allow_empty: bool = False,
) -> SchemaFollowingTrainingPrepRecommendation:
    """Prepare a recommended training bundle from a schema-following dataset split."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    prepared_samples, source_issues = validate_schema_following_source(
        source_dir,
        split=split,
    )
    bundle = TrainingBundleBuilder().build(
        prepared_samples,
        output_dir,
        source_type="schema_following",
        source_path=source_dir,
        run_id=run_id,
        max_length=max_length,
        batch_size=batch_size,
        learning_rate=learning_rate,
        max_steps=max_steps,
        seed=seed,
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
        tokenizer_metadata={
            "prepared_from": str(source_dir),
            "source_type": "schema_following",
            "source_split": split,
            "canonical_sample_input": f"{split}.jsonl",
        },
        train_metadata={
            "prepared_from": str(source_dir),
            "source_type": "schema_following",
            "source_split": split,
            "canonical_sample_input": f"{split}.jsonl",
            "canonical_training_input": "tokenized.jsonl",
        },
        bundle_metadata={
            "source_adapter": "schema_following",
            "split": split,
        },
        source_artifacts=[
            f"{split}.jsonl",
            "dataset_manifest.json",
            "split_metrics.json",
        ],
        source_issues=source_issues,
        allow_empty=allow_empty,
    )

    recommendation = SchemaFollowingTrainingPrepRecommendation(
        source_type="schema_following",
        source_path=str(source_dir),
        split=split,
        prepared_dataset_dir=str(output_dir),
        canonical_sample_input=f"{split}.jsonl",
        canonical_training_input="tokenized.jsonl",
        packed_training_input="packed.jsonl",
        bundle_manifest_path=str(bundle.manifest_path),
        recommended_max_length=max_length,
        recommended_batch_size=batch_size,
        recommended_learning_rate=learning_rate,
        prepared_sample_count=bundle.manifest.sample_count,
        tokenized_example_count=bundle.manifest.tokenized_count,
        contract_ok=bundle.contract_result.ok,
        contract_report_path=str(bundle.contract_report_path),
        tokenizer_config_path=str(bundle.tokenizer_config_path),
        train_config_path=str(bundle.train_config_path),
        notes=[
            "Use the selected split JSONL as the canonical upstream schema-following input.",
            "Prepared samples keep only assistant_tool_call trainable under the current loss mask policy.",
            "Use tokenized.jsonl as the direct TrainDataset input for a downstream training consumer.",
            "packed.jsonl and bundle_manifest.json are produced by the shared training-bundle contract.",
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
        allow_empty=True,
    )

    recommendation = RuntimeObservedSchemaFollowingTrainingPrepRecommendation(
        source_type=source_type,
        source_path=str(source_dir),
        split=split,
        raw_dataset_dir=str(raw_dataset_dir),
        prepared_dataset_dir=str(prepared_dataset_dir),
        canonical_sample_input="raw_dataset/train.jsonl",
        canonical_training_input="prepared/tokenized.jsonl",
        packed_training_input="prepared/packed.jsonl",
        bundle_manifest_path=str(prepared_dataset_dir / "bundle_manifest.json"),
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
            "The prepared directory is a shared checksummed bundle; raw_dataset remains source-owned evidence.",
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
