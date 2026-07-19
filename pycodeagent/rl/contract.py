"""Contract verification for slime-compatible training data.

Verifies that the existing pipeline:
trajectory -> rollout/sample -> tokenized example -> packed sequence
produces stable, consumable artifacts.

This module is intentionally focused on data contract validation rather than
model quality. It checks that fields are preserved, masks align, and the
resulting JSONL outputs can be loaded by the training-side dataset layer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.rl.dataset_builder import build_rollout_dataset
from pycodeagent.rl.dataset_manifest import FilterConfig
from pycodeagent.rl.packing import PackedBatch, pack_examples, unpack_sequence
from pycodeagent.rl.prepared_sample import PreparedSample
from pycodeagent.rl.schema_following_training import (
    SchemaFollowingPreparedSample,
    build_schema_following_prepared_samples,
    load_schema_following_split,
)
from pycodeagent.rl.sample_builder import TrainingSample
from pycodeagent.rl.slime_rollout import SlimeRolloutRecord
from pycodeagent.rl.tensorize import (
    TokenizedExample,
    tensorize_rollout,
    tensorize_schema_following_sample,
)
from pycodeagent.rl.tokenizer import BaseTokenizerAdapter, resolve_tokenizer_adapter
from pycodeagent.rl.tokenizer_config import (
    IGNORE_INDEX,
    FakeTokenizerConfig,
    TokenizerConfig,
)
from pycodeagent.rl.train_dataset import TrainDataset


class ContractIssue(BaseModel):
    """A single contract validation issue."""

    code: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)


class NumericSummary(BaseModel):
    """Summary statistics for a numeric series."""

    count: int = 0
    min: int | float = 0
    max: int | float = 0
    mean: float = 0.0


class ContractVerificationResult(BaseModel):
    """Result of verifying a slime-compatible data contract."""

    source_type: str
    source_path: str
    dataset_dir: str
    sample_count: int
    rollout_count: int
    tokenized_count: int
    packed_sequence_count: int
    loaded_example_count: int
    task_ids: list[str] = Field(default_factory=list)
    profile_ids: list[str] = Field(default_factory=list)
    status_counts: dict[str, int] = Field(default_factory=dict)
    reward_summary: NumericSummary = Field(default_factory=NumericSummary)
    token_length_summary: NumericSummary = Field(default_factory=NumericSummary)
    trainable_token_summary: NumericSummary = Field(default_factory=NumericSummary)
    issues: list[ContractIssue] = Field(default_factory=list)
    children: list["ContractVerificationResult"] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues and all(child.ok for child in self.children)


def verify_prepared_bundle(
    samples: list[PreparedSample],
    tokenized_examples: list[TokenizedExample],
    packed: PackedBatch,
    *,
    source_type: str,
    source_path: str,
    dataset_dir: str | Path,
    rollout_count: int = 0,
    initial_issues: list[ContractIssue] | None = None,
    allow_empty: bool = False,
) -> ContractVerificationResult:
    """Verify the shared RC-042 PreparedSample training-bundle boundary."""
    issues = list(initial_issues or [])
    if not samples and not allow_empty:
        issues.append(
            ContractIssue(
                code="prepared_empty_bundle",
                message="Training bundle must contain at least one PreparedSample",
            )
        )
    sample_ids = [sample.sample_id for sample in samples]
    duplicate_ids = sorted(
        sample_id for sample_id in set(sample_ids) if sample_ids.count(sample_id) > 1
    )
    if duplicate_ids:
        issues.append(
            ContractIssue(
                code="prepared_duplicate_sample_id",
                message="PreparedSample sample_id values must be unique within a bundle",
                context={"duplicate_sample_ids": duplicate_ids},
            )
        )

    if len(samples) != len(tokenized_examples):
        issues.append(
            ContractIssue(
                code="prepared_tokenized_count_mismatch",
                message="Prepared and tokenized example counts differ",
                context={
                    "prepared_count": len(samples),
                    "tokenized_count": len(tokenized_examples),
                },
            )
        )

    for index, example in enumerate(tokenized_examples):
        _validate_tokenized_example(example, issues, index)
        if index >= len(samples):
            continue
        sample = samples[index]
        for field_name in ("task_id", "tool_profile_id", "sample_id", "source_type"):
            if example.metadata.get(field_name) != getattr(sample, field_name):
                issues.append(
                    ContractIssue(
                        code=f"prepared_{field_name}_not_preserved",
                        message=(
                            f"Tokenized metadata did not preserve PreparedSample "
                            f"{field_name}"
                        ),
                        context={
                            "index": index,
                            "expected": getattr(sample, field_name),
                            "actual": example.metadata.get(field_name),
                        },
                    )
                )

    loaded_examples = _roundtrip_tokenized_examples(tokenized_examples)
    if [item.model_dump(mode="json") for item in loaded_examples] != [
        item.model_dump(mode="json") for item in tokenized_examples
    ]:
        issues.append(
            ContractIssue(
                code="prepared_tokenized_roundtrip_mismatch",
                message="Tokenized JSONL round-trip changed bundle content",
            )
        )

    if packed.total_examples != len(tokenized_examples):
        issues.append(
            ContractIssue(
                code="prepared_packed_example_count_mismatch",
                message="Packed batch total_examples does not match tokenized count",
                context={
                    "packed_total_examples": packed.total_examples,
                    "tokenized_count": len(tokenized_examples),
                },
            )
        )
    unpacked_count = 0
    for sequence_index, sequence in enumerate(packed.sequences):
        unpacked = unpack_sequence(sequence)
        unpacked_count += len(unpacked)
        if len(unpacked) != len(sequence.source_spans):
            issues.append(
                ContractIssue(
                    code="prepared_packed_source_count_mismatch",
                    message="Packed sequence source spans do not round-trip",
                    context={"sequence_index": sequence_index},
                )
            )
        for unpacked_index, example in enumerate(unpacked):
            _validate_tokenized_example(
                example,
                issues,
                unpacked_index,
                prefix=f"prepared_packed_seq_{sequence_index}",
            )
    if unpacked_count != len(tokenized_examples):
        issues.append(
            ContractIssue(
                code="prepared_unpack_count_mismatch",
                message="Unpacked source count does not match tokenized count",
                context={
                    "unpacked_count": unpacked_count,
                    "tokenized_count": len(tokenized_examples),
                },
            )
        )

    statuses = [sample.status for sample in samples if sample.status is not None]
    status_counts = {
        status: statuses.count(status)
        for status in sorted(set(statuses))
    }
    rewards = [sample.reward for sample in samples if sample.reward is not None]
    return ContractVerificationResult(
        source_type=source_type,
        source_path=source_path,
        dataset_dir=str(dataset_dir),
        sample_count=len(samples),
        rollout_count=rollout_count,
        tokenized_count=len(tokenized_examples),
        packed_sequence_count=len(packed.sequences),
        loaded_example_count=len(loaded_examples),
        task_ids=sorted({sample.task_id for sample in samples}),
        profile_ids=sorted({sample.tool_profile_id for sample in samples}),
        status_counts=status_counts,
        reward_summary=_summarize(rewards),
        token_length_summary=_summarize(
            [example.length for example in tokenized_examples]
        ),
        trainable_token_summary=_summarize(
            [example.trainable_token_count for example in tokenized_examples]
        ),
        issues=issues,
    )


def validate_rollout_dataset_source(
    dataset_dir: str | Path,
) -> tuple[list[TrainingSample], list[SlimeRolloutRecord], list[ContractIssue]]:
    """Validate rollout-specific artifacts without tokenizing or packing."""
    dataset_dir = Path(dataset_dir)
    manifest_path = dataset_dir / "dataset_manifest.json"
    rollouts_path = dataset_dir / "rollouts.jsonl"
    samples_path = dataset_dir / "samples.jsonl"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing dataset manifest: {manifest_path}")
    if not rollouts_path.exists():
        raise FileNotFoundError(f"Missing rollouts file: {rollouts_path}")
    if not samples_path.exists():
        raise FileNotFoundError(f"Missing samples file: {samples_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rollouts = _load_jsonl(rollouts_path, SlimeRolloutRecord)
    samples = _load_jsonl(samples_path, TrainingSample)
    issues: list[ContractIssue] = []
    if manifest.get("rollout_count") != len(rollouts):
        issues.append(
            ContractIssue(
                code="manifest_rollout_count_mismatch",
                message="Manifest rollout_count does not match rollouts.jsonl",
                context={
                    "manifest_rollout_count": manifest.get("rollout_count"),
                    "actual_rollout_count": len(rollouts),
                },
            )
        )
    if manifest.get("sample_count") != len(samples):
        issues.append(
            ContractIssue(
                code="manifest_sample_count_mismatch",
                message="Manifest sample_count does not match samples.jsonl",
                context={
                    "manifest_sample_count": manifest.get("sample_count"),
                    "actual_sample_count": len(samples),
                },
            )
        )
    if len(rollouts) != len(samples):
        issues.append(
            ContractIssue(
                code="sample_rollout_count_mismatch",
                message="samples.jsonl and rollouts.jsonl have different counts",
                context={"sample_count": len(samples), "rollout_count": len(rollouts)},
            )
        )
    for index in range(min(len(rollouts), len(samples))):
        _validate_sample(samples[index], issues, index)
        _validate_rollout(rollouts[index], issues, index)
        _validate_pair(samples[index], rollouts[index], issues, index)
    return samples, rollouts, issues


def validate_schema_following_source(
    dataset_dir: str | Path,
    *,
    split: str = "train",
) -> tuple[list[SchemaFollowingPreparedSample], list[ContractIssue]]:
    """Validate schema-following source artifacts without tokenizing or packing."""
    dataset_dir = Path(dataset_dir)
    manifest_path = dataset_dir / "dataset_manifest.json"
    split_path = dataset_dir / f"{split}.jsonl"
    split_metrics_path = dataset_dir / "split_metrics.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing schema-following manifest: {manifest_path}")
    if not split_path.exists():
        raise FileNotFoundError(f"Missing schema-following split file: {split_path}")
    if not split_metrics_path.exists():
        raise FileNotFoundError(
            f"Missing schema-following split metrics: {split_metrics_path}"
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    split_metrics = json.loads(split_metrics_path.read_text(encoding="utf-8"))
    raw_samples = load_schema_following_split(dataset_dir, split=split)
    prepared_samples = build_schema_following_prepared_samples(raw_samples)
    issues: list[ContractIssue] = []
    expected_split_count = split_metrics.get("split_counts", {}).get(split)
    if expected_split_count != len(raw_samples):
        issues.append(
            ContractIssue(
                code="schema_following_split_count_mismatch",
                message="split_metrics.json does not match the selected split JSONL count",
                context={
                    "split": split,
                    "expected_count": expected_split_count,
                    "actual_count": len(raw_samples),
                },
            )
        )
    if manifest.get("loss_mask_policy") != "assistant_tool_call_only":
        issues.append(
            ContractIssue(
                code="schema_following_loss_mask_policy_mismatch",
                message="dataset_manifest.json must declare assistant_tool_call_only",
                context={"manifest_loss_mask_policy": manifest.get("loss_mask_policy")},
            )
        )
    for index, sample in enumerate(prepared_samples):
        _validate_schema_following_prepared_sample(sample, issues, index)
    return prepared_samples, issues


def verify_slime_contract(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    source_type: str = "experiment",
    filter_config: FilterConfig | None = None,
    tokenizer: BaseTokenizerAdapter | None = None,
    tokenizer_config: TokenizerConfig | None = None,
    fake_tokenizer_config: FakeTokenizerConfig | None = None,
    pack_max_length: int | None = None,
    dataset_id: str | None = None,
    materialize_tokenized: bool = False,
    write_report: bool = False,
) -> ContractVerificationResult:
    """Verify slime compatibility for an experiment, batch, or study output.

    For study inputs, each child experiment is verified independently and
    aggregated into a single root result.
    """
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)

    if source_type == "study":
        return _verify_study_contract(
            source_dir=source_dir,
            output_dir=output_dir,
            filter_config=filter_config,
            tokenizer=tokenizer,
            tokenizer_config=tokenizer_config,
            fake_tokenizer_config=fake_tokenizer_config,
            pack_max_length=pack_max_length,
            dataset_id=dataset_id,
            materialize_tokenized=materialize_tokenized,
            write_report=write_report,
        )

    build_result = build_rollout_dataset(
        source_dir,
        output_dir,
        source_type=source_type,
        filter_config=filter_config,
        dataset_id=dataset_id,
    )
    return verify_dataset_dir(
        build_result.output_dir,
        source_type=source_type,
        source_path=str(source_dir),
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
        pack_max_length=pack_max_length,
        materialize_tokenized=materialize_tokenized,
        write_report=write_report,
    )


def verify_dataset_dir(
    dataset_dir: str | Path,
    *,
    source_type: str = "dataset",
    source_path: str = "",
    tokenizer: BaseTokenizerAdapter | None = None,
    tokenizer_config: TokenizerConfig | None = None,
    fake_tokenizer_config: FakeTokenizerConfig | None = None,
    pack_max_length: int | None = None,
    materialize_tokenized: bool = False,
    write_report: bool = False,
) -> ContractVerificationResult:
    """Verify an already-built dataset directory."""
    dataset_dir = Path(dataset_dir)
    samples, rollouts, issues = validate_rollout_dataset_source(dataset_dir)

    tokenizer, tokenizer_config = resolve_tokenizer_adapter(
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
        default_max_length=pack_max_length or 2048,
    )
    if pack_max_length is None:
        pack_max_length = tokenizer_config.max_length

    tokenized_examples = [
        tensorize_rollout(rollout, tokenizer, tokenizer_config) for rollout in rollouts
    ]
    for idx, example in enumerate(tokenized_examples):
        _validate_tokenized_example(example, issues, idx)

    loaded_examples = _roundtrip_tokenized_examples(tokenized_examples)
    loaded_dataset = TrainDataset.from_examples(loaded_examples)

    if len(loaded_dataset) != len(tokenized_examples):
        issues.append(
            ContractIssue(
                code="train_dataset_roundtrip_count_mismatch",
                message="TrainDataset JSONL roundtrip changed example count",
                context={
                    "written_count": len(tokenized_examples),
                    "loaded_count": len(loaded_dataset),
                },
            )
        )
    else:
        for idx, (expected, loaded) in enumerate(
            zip(tokenized_examples, loaded_dataset, strict=False)
        ):
            if expected.model_dump(mode="json") != loaded.model_dump(mode="json"):
                issues.append(
                    ContractIssue(
                        code="train_dataset_roundtrip_content_mismatch",
                        message="TrainDataset JSONL roundtrip changed tokenized content",
                        context={"index": idx},
                    )
                )

    if materialize_tokenized:
        tokenized_path = dataset_dir / "tokenized.jsonl"
        tokenized_dataset = TrainDataset.from_examples(tokenized_examples)
        tokenized_dataset.save_jsonl(tokenized_path)

    packed = pack_examples(tokenized_examples, max_length=pack_max_length)
    for seq_idx, sequence in enumerate(packed.sequences):
        unpacked = unpack_sequence(sequence)
        if len(unpacked) != len(sequence.source_spans):
            issues.append(
                ContractIssue(
                    code="packed_unpacked_source_count_mismatch",
                    message="Packed sequence unpack count does not match source span count",
                    context={
                        "sequence_index": seq_idx,
                        "unpacked_count": len(unpacked),
                        "source_span_count": len(sequence.source_spans),
                    },
                )
            )
        for unpacked_idx, unpacked_example in enumerate(unpacked):
            _validate_tokenized_example(
                unpacked_example,
                issues,
                unpacked_idx,
                prefix=f"packed_seq_{seq_idx}",
            )

    result = ContractVerificationResult(
        source_type=source_type,
        source_path=source_path or str(dataset_dir),
        dataset_dir=str(dataset_dir),
        sample_count=len(samples),
        rollout_count=len(rollouts),
        tokenized_count=len(tokenized_examples),
        packed_sequence_count=len(packed.sequences),
        loaded_example_count=len(loaded_dataset),
        task_ids=sorted({sample.task_id for sample in samples}),
        profile_ids=sorted({sample.tool_profile_id for sample in samples}),
        status_counts=_count_statuses(samples),
        reward_summary=_summarize([sample.reward for sample in samples]),
        token_length_summary=_summarize([example.length for example in tokenized_examples]),
        trainable_token_summary=_summarize(
            [example.trainable_token_count for example in tokenized_examples]
        ),
        issues=issues,
    )
    if write_report:
        _write_report(dataset_dir / "contract_report.json", result)
    return result


def verify_schema_following_contract(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    split: str = "train",
    tokenizer: BaseTokenizerAdapter | None = None,
    tokenizer_config: TokenizerConfig | None = None,
    fake_tokenizer_config: FakeTokenizerConfig | None = None,
    pack_max_length: int | None = None,
    materialize_tokenized: bool = False,
    write_report: bool = False,
) -> ContractVerificationResult:
    """Verify a schema-following dataset split against the training contract."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    dataset_dir = _resolve_schema_following_source_path(source_dir)
    result = verify_schema_following_dataset_dir(
        dataset_dir,
        split=split,
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
        pack_max_length=pack_max_length,
        materialize_tokenized=materialize_tokenized,
        output_dir=output_dir,
    )
    if write_report:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_report(output_dir / "contract_report.json", result)
    return result


def verify_schema_following_dataset_dir(
    dataset_dir: str | Path,
    *,
    split: str = "train",
    tokenizer: BaseTokenizerAdapter | None = None,
    tokenizer_config: TokenizerConfig | None = None,
    fake_tokenizer_config: FakeTokenizerConfig | None = None,
    pack_max_length: int | None = None,
    materialize_tokenized: bool = False,
    output_dir: str | Path | None = None,
) -> ContractVerificationResult:
    """Verify an existing schema-following dataset directory."""
    dataset_dir = Path(dataset_dir)
    resolved_output_dir = Path(output_dir) if output_dir is not None else dataset_dir
    prepared_samples, issues = validate_schema_following_source(
        dataset_dir,
        split=split,
    )

    tokenizer, tokenizer_config = resolve_tokenizer_adapter(
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
        default_max_length=pack_max_length or 2048,
    )
    if pack_max_length is None:
        pack_max_length = tokenizer_config.max_length

    tokenized_examples = [
        tensorize_schema_following_sample(sample, tokenizer, tokenizer_config)
        for sample in prepared_samples
    ]
    for index, example in enumerate(tokenized_examples):
        _validate_tokenized_example(example, issues, index)

    loaded_examples = _roundtrip_tokenized_examples(tokenized_examples)
    loaded_dataset = TrainDataset.from_examples(loaded_examples)

    if len(loaded_dataset) != len(tokenized_examples):
        issues.append(
            ContractIssue(
                code="schema_following_train_dataset_roundtrip_count_mismatch",
                message="Schema-following tokenized JSONL roundtrip changed example count",
                context={
                    "written_count": len(tokenized_examples),
                    "loaded_count": len(loaded_dataset),
                },
            )
        )
    else:
        for index, (expected, loaded) in enumerate(
            zip(tokenized_examples, loaded_dataset, strict=False)
        ):
            if expected.model_dump(mode="json") != loaded.model_dump(mode="json"):
                issues.append(
                    ContractIssue(
                        code="schema_following_train_dataset_roundtrip_content_mismatch",
                        message="Schema-following tokenized JSONL roundtrip changed content",
                        context={"index": index},
                    )
                )

    if materialize_tokenized:
        resolved_output_dir.mkdir(parents=True, exist_ok=True)
        TrainDataset.from_examples(tokenized_examples).save_jsonl(
            resolved_output_dir / "tokenized.jsonl"
        )

    packed = pack_examples(tokenized_examples, max_length=pack_max_length)
    for seq_idx, sequence in enumerate(packed.sequences):
        unpacked = unpack_sequence(sequence)
        if len(unpacked) != len(sequence.source_spans):
            issues.append(
                ContractIssue(
                    code="schema_following_packed_unpacked_source_count_mismatch",
                    message="Packed schema-following sequence unpack count does not match source span count",
                    context={
                        "sequence_index": seq_idx,
                        "unpacked_count": len(unpacked),
                        "source_span_count": len(sequence.source_spans),
                    },
                )
            )
        for unpacked_idx, unpacked_example in enumerate(unpacked):
            _validate_tokenized_example(
                unpacked_example,
                issues,
                unpacked_idx,
                prefix=f"schema_following_packed_seq_{seq_idx}",
            )

    return ContractVerificationResult(
        source_type="schema_following",
        source_path=str(dataset_dir),
        dataset_dir=str(resolved_output_dir),
        sample_count=len(prepared_samples),
        rollout_count=0,
        tokenized_count=len(tokenized_examples),
        packed_sequence_count=len(packed.sequences),
        loaded_example_count=len(loaded_dataset),
        task_ids=sorted({sample.task_id for sample in prepared_samples}),
        profile_ids=sorted({sample.tool_profile_id for sample in prepared_samples}),
        status_counts={},
        reward_summary=NumericSummary(),
        token_length_summary=_summarize([example.length for example in tokenized_examples]),
        trainable_token_summary=_summarize(
            [example.trainable_token_count for example in tokenized_examples]
        ),
        issues=issues,
    )


def _verify_study_contract(
    *,
    source_dir: Path,
    output_dir: Path,
    filter_config: FilterConfig | None,
    tokenizer: BaseTokenizerAdapter | None,
    tokenizer_config: TokenizerConfig | None,
    fake_tokenizer_config: FakeTokenizerConfig | None,
    pack_max_length: int | None,
    dataset_id: str | None,
    materialize_tokenized: bool,
    write_report: bool,
) -> ContractVerificationResult:
    experiments_dir = source_dir / "experiments"
    if not experiments_dir.exists():
        raise FileNotFoundError(f"Study directory missing experiments/: {experiments_dir}")

    child_results: list[ContractVerificationResult] = []
    for experiment_dir in sorted(p for p in experiments_dir.iterdir() if p.is_dir()):
        child_output = output_dir / experiment_dir.name
        child_result = verify_slime_contract(
            experiment_dir,
            child_output,
            source_type="experiment",
            filter_config=filter_config,
            tokenizer=tokenizer,
            tokenizer_config=tokenizer_config,
            fake_tokenizer_config=fake_tokenizer_config,
            pack_max_length=pack_max_length,
            dataset_id=dataset_id,
            materialize_tokenized=materialize_tokenized,
            write_report=write_report,
        )
        child_results.append(child_result)

    child_issues = [
        ContractIssue(
            code="study_child_verification_failed",
            message="One or more child experiments failed contract verification",
            context={
                "failed_children": [
                    {
                        "source_path": child.source_path,
                        "dataset_dir": child.dataset_dir,
                        "issue_count": len(child.issues),
                    }
                    for child in child_results
                    if not child.ok
                ]
            },
        )
    ] if any(not child.ok for child in child_results) else []

    result = ContractVerificationResult(
        source_type="study",
        source_path=str(source_dir),
        dataset_dir=str(output_dir),
        sample_count=sum(child.sample_count for child in child_results),
        rollout_count=sum(child.rollout_count for child in child_results),
        tokenized_count=sum(child.tokenized_count for child in child_results),
        packed_sequence_count=sum(
            child.packed_sequence_count for child in child_results
        ),
        loaded_example_count=sum(child.loaded_example_count for child in child_results),
        task_ids=sorted({task_id for child in child_results for task_id in child.task_ids}),
        profile_ids=sorted(
            {profile_id for child in child_results for profile_id in child.profile_ids}
        ),
        status_counts=_merge_status_counts([child.status_counts for child in child_results]),
        reward_summary=_summarize_from_children(
            child_results, field_name="reward_summary"
        ),
        token_length_summary=_summarize_from_children(
            child_results, field_name="token_length_summary"
        ),
        trainable_token_summary=_summarize_from_children(
            child_results, field_name="trainable_token_summary"
        ),
        issues=child_issues,
        children=child_results,
    )
    if write_report:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_report(output_dir / "contract_report.json", result)
    return result


def _validate_sample(
    sample: TrainingSample,
    issues: list[ContractIssue],
    index: int,
) -> None:
    if len(sample.text) != len(sample.character_mask):
        issues.append(
            ContractIssue(
                code="sample_mask_length_mismatch",
                message="Training sample character mask length does not match text length",
                context={
                    "index": index,
                    "task_id": sample.task_id,
                    "text_length": len(sample.text),
                    "mask_length": len(sample.character_mask),
                },
            )
        )

    if sum(sample.character_mask) != sample.trainable_char_count:
        issues.append(
            ContractIssue(
                code="sample_trainable_char_count_mismatch",
                message="Training sample trainable_char_count does not match mask sum",
                context={
                    "index": index,
                    "task_id": sample.task_id,
                    "mask_sum": sum(sample.character_mask),
                    "trainable_char_count": sample.trainable_char_count,
                },
            )
        )

    segment_text = "".join(segment["text"] for segment in sample.segments)
    if segment_text != sample.text:
        issues.append(
            ContractIssue(
                code="sample_segment_text_mismatch",
                message="Training sample segments do not reconstruct full text",
                context={"index": index, "task_id": sample.task_id},
            )
        )

    _validate_spans(
        sample.spans,
        issues,
        index=index,
        text_length=len(sample.text),
        task_id=sample.task_id,
        prefix="sample",
    )


def _validate_rollout(
    rollout: SlimeRolloutRecord,
    issues: list[ContractIssue],
    index: int,
) -> None:
    if len(rollout.text) != len(rollout.character_mask):
        issues.append(
            ContractIssue(
                code="rollout_mask_length_mismatch",
                message="Rollout character mask length does not match text length",
                context={
                    "index": index,
                    "task_id": rollout.task_id,
                    "text_length": len(rollout.text),
                    "mask_length": len(rollout.character_mask),
                },
            )
        )

    if len(rollout.text) != rollout.total_char_count:
        issues.append(
            ContractIssue(
                code="rollout_total_char_count_mismatch",
                message="Rollout total_char_count does not match text length",
                context={
                    "index": index,
                    "task_id": rollout.task_id,
                    "text_length": len(rollout.text),
                    "total_char_count": rollout.total_char_count,
                },
            )
        )

    if sum(rollout.character_mask) != rollout.trainable_char_count:
        issues.append(
            ContractIssue(
                code="rollout_trainable_char_count_mismatch",
                message="Rollout trainable_char_count does not match mask sum",
                context={
                    "index": index,
                    "task_id": rollout.task_id,
                    "mask_sum": sum(rollout.character_mask),
                    "trainable_char_count": rollout.trainable_char_count,
                },
            )
        )

    segment_text = "".join(segment["text"] for segment in rollout.segments)
    if segment_text != rollout.text:
        issues.append(
            ContractIssue(
                code="rollout_segment_text_mismatch",
                message="Rollout segments do not reconstruct full text",
                context={"index": index, "task_id": rollout.task_id},
            )
        )

    _validate_spans(
        rollout.spans,
        issues,
        index=index,
        text_length=len(rollout.text),
        task_id=rollout.task_id,
        prefix="rollout",
    )


def _validate_schema_following_prepared_sample(
    sample: SchemaFollowingPreparedSample,
    issues: list[ContractIssue],
    index: int,
) -> None:
    if len(sample.text) != len(sample.character_mask):
        issues.append(
            ContractIssue(
                code="schema_following_mask_length_mismatch",
                message="Prepared schema-following mask length does not match text length",
                context={
                    "index": index,
                    "sample_id": sample.sample_id,
                    "text_length": len(sample.text),
                    "mask_length": len(sample.character_mask),
                },
            )
        )

    if sum(sample.character_mask) != sample.trainable_char_count:
        issues.append(
            ContractIssue(
                code="schema_following_trainable_char_count_mismatch",
                message="Prepared schema-following trainable_char_count does not match mask sum",
                context={
                    "index": index,
                    "sample_id": sample.sample_id,
                    "mask_sum": sum(sample.character_mask),
                    "trainable_char_count": sample.trainable_char_count,
                },
            )
        )

    segment_text = "".join(segment["text"] for segment in sample.segments)
    if segment_text != sample.text:
        issues.append(
            ContractIssue(
                code="schema_following_segment_text_mismatch",
                message="Prepared schema-following segments do not reconstruct full text",
                context={"index": index, "sample_id": sample.sample_id},
            )
        )

    trainable_segments = [
        segment for segment in sample.segments if segment.get("trainable") is True
    ]
    if len(trainable_segments) != 1:
        issues.append(
            ContractIssue(
                code="schema_following_trainable_segment_count_mismatch",
                message="Prepared schema-following sample must contain exactly one trainable segment",
                context={
                    "index": index,
                    "sample_id": sample.sample_id,
                    "trainable_segment_count": len(trainable_segments),
                },
            )
        )
    elif trainable_segments[0].get("kind") != "assistant_tool_call":
        issues.append(
            ContractIssue(
                code="schema_following_trainable_segment_kind_error",
                message="Prepared schema-following trainable segment must be assistant_tool_call",
                context={
                    "index": index,
                    "sample_id": sample.sample_id,
                    "kind": trainable_segments[0].get("kind"),
                },
            )
        )

    _validate_spans(
        sample.spans,
        issues,
        index=index,
        text_length=len(sample.text),
        task_id=sample.sample_id,
        prefix="schema_following",
    )


def _validate_pair(
    sample: TrainingSample,
    rollout: SlimeRolloutRecord,
    issues: list[ContractIssue],
    index: int,
) -> None:
    keys = [
        "task_id",
        "tool_profile_id",
        "reward",
        "status",
        "verifier_passed",
        "verifier_score",
        "text",
        "character_mask",
        "trainable_char_count",
    ]
    for key in keys:
        if getattr(sample, key) != getattr(rollout, key):
            issues.append(
                ContractIssue(
                    code="sample_rollout_field_mismatch",
                    message="Training sample and rollout diverged on shared field",
                    context={
                        "index": index,
                        "task_id": sample.task_id,
                        "field": key,
                    },
                )
            )


def _validate_spans(
    spans: list[dict[str, Any]],
    issues: list[ContractIssue],
    *,
    index: int,
    text_length: int,
    task_id: str,
    prefix: str,
) -> None:
    last_end = 0
    for span_index, span in enumerate(spans):
        start = span.get("start")
        end = span.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            issues.append(
                ContractIssue(
                    code=f"{prefix}_span_type_error",
                    message="Span start/end must be integers",
                    context={
                        "index": index,
                        "task_id": task_id,
                        "span_index": span_index,
                    },
                )
            )
            continue
        if start < 0 or end < start or end > text_length:
            issues.append(
                ContractIssue(
                    code=f"{prefix}_span_bounds_error",
                    message="Span is outside text bounds",
                    context={
                        "index": index,
                        "task_id": task_id,
                        "span_index": span_index,
                        "start": start,
                        "end": end,
                        "text_length": text_length,
                    },
                )
            )
        if start < last_end:
            issues.append(
                ContractIssue(
                    code=f"{prefix}_span_order_error",
                    message="Spans are not in non-decreasing order",
                    context={
                        "index": index,
                        "task_id": task_id,
                        "span_index": span_index,
                        "start": start,
                        "previous_end": last_end,
                    },
                )
            )
        last_end = max(last_end, end)


def _validate_tokenized_example(
    example: TokenizedExample,
    issues: list[ContractIssue],
    index: int,
    *,
    prefix: str = "tokenized",
) -> None:
    lengths = {
        "input_ids": len(example.input_ids),
        "attention_mask": len(example.attention_mask),
        "labels": len(example.labels),
        "token_train_mask": len(example.token_train_mask),
    }
    if len(set(lengths.values())) != 1:
        issues.append(
            ContractIssue(
                code=f"{prefix}_length_mismatch",
                message="Tokenized example fields have different lengths",
                context={"index": index, "lengths": lengths},
            )
        )

    for token_index, (token_id, label, trainable) in enumerate(
        zip(example.input_ids, example.labels, example.token_train_mask)
    ):
        if trainable not in (0, 1):
            issues.append(
                ContractIssue(
                    code=f"{prefix}_train_mask_value_error",
                    message="token_train_mask must contain only 0/1 values",
                    context={"index": index, "token_index": token_index},
                )
            )
        if trainable == 0 and label != IGNORE_INDEX:
            issues.append(
                ContractIssue(
                    code=f"{prefix}_label_mask_mismatch",
                    message="Non-trainable token has non-ignored label",
                    context={
                        "index": index,
                        "token_index": token_index,
                        "label": label,
                    },
                )
            )
        if trainable == 1 and label != token_id:
            issues.append(
                ContractIssue(
                    code=f"{prefix}_label_token_mismatch",
                    message="Trainable token label does not match input token id",
                    context={
                        "index": index,
                        "token_index": token_index,
                        "token_id": token_id,
                        "label": label,
                    },
                )
            )

    trainable_char_count = int(example.metadata.get("trainable_char_count", 0))
    if (
        prefix == "tokenized"
        and trainable_char_count > 0
        and example.trainable_token_count == 0
    ):
        issues.append(
            ContractIssue(
                code=f"{prefix}_no_trainable_tokens",
                message=(
                    "Example has trainable characters but no trainable tokens after "
                    "tokenization/truncation"
                ),
                context={
                    "index": index,
                    "trainable_char_count": trainable_char_count,
                    "token_length": example.length,
                },
            )
        )


def _load_jsonl(path: Path, model_type: type[BaseModel]) -> list[Any]:
    records: list[Any] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(model_type.model_validate(json.loads(line)))
    return records


def _roundtrip_tokenized_examples(
    examples: list[TokenizedExample],
) -> list[TokenizedExample]:
    """Validate JSONL serialization without mutating the dataset directory."""
    lines = [example.model_dump_json() for example in examples]
    return [
        TokenizedExample.model_validate(json.loads(line))
        for line in lines
        if line.strip()
    ]


def _resolve_schema_following_source_path(source_dir: Path) -> Path:
    if not source_dir.exists():
        raise FileNotFoundError(f"Schema-following source directory not found: {source_dir}")
    return source_dir


def _count_statuses(samples: list[TrainingSample]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in samples:
        counts[sample.status] = counts.get(sample.status, 0) + 1
    return counts


def _merge_status_counts(status_count_dicts: list[dict[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for counts in status_count_dicts:
        for key, value in counts.items():
            merged[key] = merged.get(key, 0) + value
    return merged


def _summarize(values: list[int | float]) -> NumericSummary:
    if not values:
        return NumericSummary()
    return NumericSummary(
        count=len(values),
        min=min(values),
        max=max(values),
        mean=sum(values) / len(values),
    )


def _summarize_from_children(
    children: list[ContractVerificationResult],
    *,
    field_name: str,
) -> NumericSummary:
    summaries = [
        getattr(child, field_name)
        for child in children
        if getattr(child, field_name).count > 0
    ]
    if not summaries:
        return NumericSummary()

    total_count = sum(summary.count for summary in summaries)
    weighted_sum = sum(summary.mean * summary.count for summary in summaries)
    return NumericSummary(
        count=total_count,
        min=min(summary.min for summary in summaries),
        max=max(summary.max for summary in summaries),
        mean=weighted_sum / total_count,
    )


def _write_report(path: Path, result: ContractVerificationResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
