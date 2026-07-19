"""Training-bundle preparation for auxiliary native-transformed SFT data."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from pycodeagent.auxiliary.claude_api.sft_dataset_io import read_claude_api_sft_jsonl
from pycodeagent.auxiliary.claude_api.sft_training import (
    build_claude_api_sft_prepared_samples,
)
from pycodeagent.auxiliary.native_transformed.sft_dataset_validate import (
    validate_native_transformed_sft_dataset,
)
from pycodeagent.rl.training_bundle import TrainingBundleBuilder
from pycodeagent.rl.tokenizer import BaseTokenizerAdapter
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig


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
    packed_training_input: str
    bundle_manifest_path: str
    contract_report_path: str
    recommended_max_length: int
    recommended_batch_size: int
    recommended_learning_rate: float
    raw_sample_count: int
    prepared_sample_count: int
    tokenized_example_count: int
    tokenizer_config_path: str
    train_config_path: str
    notes: list[str] = Field(default_factory=list)


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
    """Prepare training artifacts from a validated native-transformed SFT dataset."""
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

    output_dir.mkdir(parents=True, exist_ok=True)

    raw_samples = read_claude_api_sft_jsonl(split_path)
    prepared_samples = build_claude_api_sft_prepared_samples(raw_samples)
    prepared_samples = [
        sample.model_copy(
            update={
                "source_type": "native_transformed_claude_api_sft",
                "metadata": {
                    **sample.metadata,
                    "raw_source_type": sample.source_type,
                },
            }
        )
        for sample in prepared_samples
    ]
    bundle = TrainingBundleBuilder().build(
        prepared_samples,
        output_dir,
        source_type="native_transformed_claude_api_sft",
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
            "source_type": "native_transformed_claude_api_sft",
            "source_split": split,
            "primary_sample_input": f"{split}.jsonl",
            "primary_prepared_input": "samples.jsonl",
        },
        train_metadata={
            "prepared_from": str(source_dir),
            "source_type": "native_transformed_claude_api_sft",
            "source_split": split,
            "primary_sample_input": f"{split}.jsonl",
            "primary_prepared_input": "samples.jsonl",
            "primary_training_input": "tokenized.jsonl",
            "validation_report_path": validation.validation_report_path,
        },
        bundle_metadata={
            "source_adapter": "native_transformed_claude_api_sft",
            "split": split,
            "raw_validation_report": validation.validation_report_path,
        },
        source_artifacts=[
            f"{split}.jsonl",
            "dataset_manifest.json",
            "split_metrics.json",
            validation.validation_report_path,
        ],
        allow_empty=True,
    )

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
        packed_training_input="packed.jsonl",
        bundle_manifest_path=str(bundle.manifest_path),
        contract_report_path=str(bundle.contract_report_path),
        recommended_max_length=max_length,
        recommended_batch_size=batch_size,
        recommended_learning_rate=learning_rate,
        raw_sample_count=len(raw_samples),
        prepared_sample_count=bundle.manifest.sample_count,
        tokenized_example_count=bundle.manifest.tokenized_count,
        tokenizer_config_path=str(bundle.tokenizer_config_path),
        train_config_path=str(bundle.train_config_path),
        notes=[
            "Use the validated native-transformed train.jsonl as the primary upstream input.",
            "No additional raw dataset format is introduced by this preparation step.",
            "Prepared samples adapt the Claude API source policy to PreparedSample v1 assistant-tool-call-only masking.",
            "Use tokenized.jsonl as the direct TrainDataset input for a downstream training consumer.",
            "Verify bundle_manifest.json before consuming tokenized.jsonl or packed.jsonl.",
        ],
    )
    (output_dir / "training_prep.json").write_text(
        json.dumps(
            recommendation.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return recommendation
