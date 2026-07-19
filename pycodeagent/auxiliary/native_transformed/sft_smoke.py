"""Auxiliary overfit smoke runner for native-transformed SFT data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from pycodeagent.auxiliary.claude_api.sft import ClaudeApiSFTMessage, ClaudeApiSFTSample
from pycodeagent.auxiliary.claude_api.sft_dataset_io import read_claude_api_sft_jsonl
from pycodeagent.auxiliary.claude_api.sft_training import build_claude_api_sft_prepared_sample
from pycodeagent.auxiliary.native_transformed.sft_eval import (
    NativeTransformedPredictor,
    NativeTransformedToolNameComparisonReport,
    NativeTransformedToolNameEvalReport,
    compare_native_transformed_tool_name_reports,
    evaluate_native_transformed_tool_name_predictor,
    write_native_transformed_comparison_report_json,
    write_native_transformed_eval_report_json,
)
from pycodeagent.rl.schema_following_sft import (
    HFCausalLMPredictor,
    LocalCausalLMTrainingResult,
    train_local_causal_lm,
)
from pycodeagent.auxiliary.claude_api.serializer import serialize_claude_api_sft_sample
from pycodeagent.rl.tensorize import tensorize_text
from pycodeagent.rl.tokenizer import BaseTokenizerAdapter, resolve_tokenizer_adapter
from pycodeagent.rl.tokenizer_config import TokenizerConfig
from pycodeagent.rl.train_config import TrainConfig
from pycodeagent.rl.train_dataset import TrainDataset


NATIVE_TRANSFORMED_MODE_ORDER = [
    "base",
    "name_only",
    "description_only",
    "name_description",
]


class NativeTransformedSmokeTrainBundle(BaseModel):
    """Artifacts for the deterministic micro train subset."""

    selected_sample_ids: list[str]
    tokenized_train_path: str
    train_config_path: str
    train_config: TrainConfig


class NativeTransformedSFTSmokeResult(BaseModel):
    """Artifacts and summary from one native-transformed overfit smoke run."""

    dataset_dir: str
    prepared_dir: str
    output_dir: str
    probe_samples_path: str
    train_bundle: NativeTransformedSmokeTrainBundle
    training: LocalCausalLMTrainingResult
    base_model_report_path: str
    trained_model_report_path: str
    comparison_report_path: str
    smoke_run_path: str
    success: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


PredictorFactory = Callable[
    [str | Path, str | Path | None, str, int, bool],
    NativeTransformedPredictor,
]
Trainer = Callable[..., LocalCausalLMTrainingResult]


def select_native_transformed_probe_samples(
    dataset_dir: str | Path,
    *,
    per_mode_probe_count: int = 2,
) -> list[ClaudeApiSFTSample]:
    """Select a deterministic per-mode probe subset with at least one tool_use target."""
    if per_mode_probe_count < 1:
        raise ValueError("per_mode_probe_count must be >= 1")

    dataset_dir = Path(dataset_dir)
    samples = read_claude_api_sft_jsonl(dataset_dir / "train.jsonl")
    grouped: dict[str, list[ClaudeApiSFTSample]] = {}
    for sample in samples:
        if not _has_tool_use_target(sample):
            continue
        mode = sample.metadata.get("transformation_mode")
        if not isinstance(mode, str) or not mode:
            mode = "<missing>"
        grouped.setdefault(mode, []).append(sample)

    selected: list[ClaudeApiSFTSample] = []
    for mode in _ordered_modes(grouped):
        mode_samples = sorted(grouped[mode], key=lambda sample: sample.sample_id)
        selected.extend(mode_samples[:per_mode_probe_count])
    if not selected:
        raise ValueError("No native-transformed samples with tool_use targets found")
    return selected


def build_native_transformed_smoke_train_bundle(
    probe_samples: list[ClaudeApiSFTSample],
    *,
    prepared_dir: str | Path,
    output_dir: str | Path,
    max_steps: int,
    batch_size: int,
    learning_rate: float,
    seed: int,
    tokenizer: BaseTokenizerAdapter | None = None,
    tokenizer_config: TokenizerConfig | None = None,
) -> NativeTransformedSmokeTrainBundle:
    """Filter prepared tokenized output to probe sample IDs and patch TrainConfig."""
    prepared_dir = Path(prepared_dir)
    output_dir = Path(output_dir)
    train_dir = output_dir / "train"
    selected_sample_ids = [sample.sample_id for sample in probe_samples]
    if tokenizer is not None and tokenizer_config is not None:
        examples = _tensorize_smoke_samples(
            probe_samples,
            tokenizer=tokenizer,
            tokenizer_config=tokenizer_config,
        )
    else:
        selected = set(selected_sample_ids)
        dataset = TrainDataset.from_jsonl(prepared_dir / "tokenized.jsonl")
        examples_by_id = {
            str(example.metadata.get("sample_id")): example
            for example in dataset.examples
            if example.metadata.get("sample_id") in selected
        }
        found = set(examples_by_id)
        missing = [sample_id for sample_id in selected_sample_ids if sample_id not in found]
        if missing:
            preview = ", ".join(missing[:5])
            raise ValueError(f"Prepared tokenized data is missing selected samples: {preview}")
        examples = [examples_by_id[sample_id] for sample_id in selected_sample_ids]

    smoke_dataset = TrainDataset.from_examples(examples)
    tokenized_train_path = train_dir / "smoke_tokenized.jsonl"
    smoke_dataset.save_jsonl(tokenized_train_path)

    base_config = TrainConfig.load(prepared_dir / "train_config.json")
    train_config = base_config.model_copy(
        update={
            "dataset_path": str(tokenized_train_path),
            "output_dir": str(train_dir),
            "max_steps": max_steps,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "seed": seed,
        }
    )
    train_config_path = train_dir / "train_config.json"
    train_config.save(train_config_path)
    return NativeTransformedSmokeTrainBundle(
        selected_sample_ids=selected_sample_ids,
        tokenized_train_path=str(tokenized_train_path),
        train_config_path=str(train_config_path),
        train_config=train_config,
    )


def run_native_transformed_sft_smoke(
    dataset_dir: str | Path,
    prepared_dir: str | Path,
    output_dir: str | Path,
    *,
    model_name_or_path: str | Path,
    tokenizer_name_or_path: str | Path | None = None,
    device: str = "cpu",
    max_steps: int = 20,
    batch_size: int = 1,
    learning_rate: float = 1e-4,
    seed: int = 42,
    per_mode_probe_count: int = 2,
    max_new_tokens: int = 192,
    smoke_max_length: int | None = None,
    local_files_only: bool = True,
    predictor_factory: PredictorFactory | None = None,
    trainer: Trainer | None = None,
) -> NativeTransformedSFTSmokeResult:
    """Run the native-transformed overfit smoke without regenerating data."""
    dataset_dir = Path(dataset_dir)
    prepared_dir = Path(prepared_dir)
    output_dir = Path(output_dir)
    eval_dir = output_dir / "eval"
    train_dir = output_dir / "train"
    output_dir.mkdir(parents=True, exist_ok=True)

    probe_samples = select_native_transformed_probe_samples(
        dataset_dir,
        per_mode_probe_count=per_mode_probe_count,
    )
    tokenizer: BaseTokenizerAdapter | None = None
    tokenizer_config: TokenizerConfig | None = None
    if smoke_max_length is not None:
        tokenizer, tokenizer_config = _resolve_smoke_tokenizer(
            prepared_dir,
            tokenizer_name_or_path=tokenizer_name_or_path or model_name_or_path,
            smoke_max_length=smoke_max_length,
        )
        probe_samples = [
            trim_native_transformed_sample_for_smoke(
                sample,
                tokenizer=tokenizer,
                max_length=smoke_max_length,
            )
            for sample in probe_samples
        ]
    probe_samples_path = output_dir / "probe_samples.jsonl"
    _write_probe_samples(probe_samples, probe_samples_path)

    train_bundle = build_native_transformed_smoke_train_bundle(
        probe_samples,
        prepared_dir=prepared_dir,
        output_dir=output_dir,
        max_steps=max_steps,
        batch_size=batch_size,
        learning_rate=learning_rate,
        seed=seed,
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
    )

    factory = predictor_factory or _build_hf_predictor
    base_predictor = factory(
        model_name_or_path,
        tokenizer_name_or_path,
        device,
        max_new_tokens,
        local_files_only,
    )
    base_report = evaluate_native_transformed_tool_name_predictor(
        probe_samples,
        predictor=base_predictor,
        model_label="base_model",
        dataset_dir=dataset_dir,
        metadata={"model_name_or_path": str(model_name_or_path)},
    )
    base_report_path = eval_dir / "base_model_report.json"
    write_native_transformed_eval_report_json(base_report_path, base_report)

    train_fn = trainer or train_local_causal_lm
    training = train_fn(
        model_name_or_path,
        tokenizer_name_or_path=tokenizer_name_or_path,
        train_config=train_bundle.train_config,
        output_dir=train_dir,
        device=device,
        local_files_only=local_files_only,
    )

    trained_predictor = factory(
        training.model_output_path,
        training.model_output_path,
        device,
        max_new_tokens,
        local_files_only,
    )
    trained_report = evaluate_native_transformed_tool_name_predictor(
        probe_samples,
        predictor=trained_predictor,
        model_label="trained_model",
        dataset_dir=dataset_dir,
        metadata={"model_name_or_path": training.model_output_path},
    )
    trained_report_path = eval_dir / "trained_model_report.json"
    write_native_transformed_eval_report_json(trained_report_path, trained_report)

    comparison = compare_native_transformed_tool_name_reports(
        base_report,
        trained_report,
        baseline_report_path=str(base_report_path),
        trained_report_path=str(trained_report_path),
        metadata={
            "prepared_dir": str(prepared_dir),
            "probe_samples_path": str(probe_samples_path),
            "train_config_path": train_bundle.train_config_path,
        },
    )
    comparison_report_path = eval_dir / "comparison_report.json"
    write_native_transformed_comparison_report_json(comparison_report_path, comparison)

    loss_summary = _load_loss_summary(train_dir)
    train_completed = training.num_steps >= max_steps and Path(training.model_output_path).exists()
    loss_improved = loss_summary.get("loss_improved")
    loss_ok = bool(loss_improved) or loss_summary.get("loss_observation_count", 0) < 2
    success = train_completed and loss_ok and comparison.improved

    smoke_run_path = output_dir / "smoke_run.json"
    _write_smoke_run_summary(
        smoke_run_path,
        base_report=base_report,
        trained_report=trained_report,
        comparison=comparison,
        training=training,
        train_completed=train_completed,
        loss_summary=loss_summary,
        success=success,
    )

    return NativeTransformedSFTSmokeResult(
        dataset_dir=str(dataset_dir),
        prepared_dir=str(prepared_dir),
        output_dir=str(output_dir),
        probe_samples_path=str(probe_samples_path),
        train_bundle=train_bundle,
        training=training,
        base_model_report_path=str(base_report_path),
        trained_model_report_path=str(trained_report_path),
        comparison_report_path=str(comparison_report_path),
        smoke_run_path=str(smoke_run_path),
        success=success,
        metadata={
            "train_completed": train_completed,
            "loss_summary": loss_summary,
            "tool_name_accuracy_improved": comparison.improved,
            "smoke_max_length": smoke_max_length,
        },
    )


def trim_native_transformed_sample_for_smoke(
    sample: ClaudeApiSFTSample,
    *,
    tokenizer: BaseTokenizerAdapter,
    max_length: int,
) -> ClaudeApiSFTSample:
    """Trim non-trainable context while preserving tool specs and target blocks."""
    if max_length < 1:
        raise ValueError("smoke max length must be >= 1")

    original_context = _non_tool_specs_context_text(sample)
    low = 0
    high = len(original_context)
    best: ClaudeApiSFTSample | None = None
    while low <= high:
        midpoint = (low + high) // 2
        candidate = _sample_with_context_tail(sample, original_context[-midpoint:] if midpoint else "")
        prepared = build_claude_api_sft_prepared_sample(candidate)
        token_count = len(tokenizer.encode(prepared.text))
        if token_count <= max_length:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1

    if best is None:
        raise ValueError(
            f"Cannot fit smoke sample target and tool specs within {max_length} tokens: "
            f"{sample.sample_id}"
        )
    return best


def _resolve_smoke_tokenizer(
    prepared_dir: Path,
    *,
    tokenizer_name_or_path: str | Path,
    smoke_max_length: int,
) -> tuple[BaseTokenizerAdapter, TokenizerConfig]:
    config_path = prepared_dir / "tokenizer_config.yaml"
    if config_path.exists():
        tokenizer_config = TokenizerConfig.load(config_path).model_copy(
            update={
                "tokenizer_name": str(tokenizer_name_or_path),
                "max_length": smoke_max_length,
                "truncation": True,
                "padding": "do_not_pad",
            }
        )
    else:
        tokenizer_config = TokenizerConfig(
            tokenizer_name=str(tokenizer_name_or_path),
            max_length=smoke_max_length,
            truncation=True,
            padding="do_not_pad",
        )
    return resolve_tokenizer_adapter(tokenizer_config=tokenizer_config)


def _tensorize_smoke_samples(
    samples: list[ClaudeApiSFTSample],
    *,
    tokenizer: BaseTokenizerAdapter,
    tokenizer_config: TokenizerConfig,
):
    examples = []
    empty_trainable: list[str] = []
    for sample in samples:
        prepared = build_claude_api_sft_prepared_sample(sample)
        example = tensorize_text(
            prepared.text,
            prepared.character_mask,
            tokenizer,
            tokenizer_config,
            metadata={
                **prepared.metadata,
                "sample_id": prepared.sample_id,
                "sample_type": prepared.sample_type,
                "source_type": "native_transformed_claude_api_sft",
                "raw_source_type": prepared.source_type,
                "task_id": prepared.task_id,
                "tool_profile_id": prepared.tool_profile_id,
                "loss_mask_policy": prepared.loss_mask_policy,
                "trainable_char_count": prepared.trainable_char_count,
            },
        )
        if example.length > tokenizer_config.max_length:
            raise ValueError(
                f"Smoke sample exceeded max length after trimming: {sample.sample_id}"
            )
        if example.trainable_token_count == 0:
            empty_trainable.append(sample.sample_id)
        examples.append(example)
    if empty_trainable:
        preview = ", ".join(empty_trainable[:5])
        raise ValueError(f"Smoke trimming removed trainable tokens for samples: {preview}")
    return examples


def _non_tool_specs_context_text(sample: ClaudeApiSFTSample) -> str:
    serialized = serialize_claude_api_sft_sample(sample)
    return "".join(
        segment.text
        for segment in serialized.segments
        if not segment.trainable and segment.metadata.get("source") != "tool_specs"
    )


def _sample_with_context_tail(sample: ClaudeApiSFTSample, context_tail: str) -> ClaudeApiSFTSample:
    metadata = dict(sample.metadata)
    metadata.update(
        {
            "smoke_context_trimmed": True,
            "smoke_original_context_char_count": len(_non_tool_specs_context_text(sample)),
            "smoke_retained_context_char_count": len(context_tail),
            "smoke_original_tool_spec_count": len(sample.tool_specs),
            "smoke_retained_tool_spec_count": len(_target_tool_specs(sample)),
        }
    )
    content = (
        "Context tail from the original Claude Code request follows.\n\n"
        f"{context_tail}"
        if context_tail
        else "Original Claude Code request context was trimmed for this smoke run."
    )
    return sample.model_copy(
        update={
            "messages": [
                ClaudeApiSFTMessage(
                    role="user",
                    content=content,
                    metadata={"source": "smoke_context_tail"},
                )
            ],
            "tool_specs": _target_tool_specs(sample),
            "metadata": metadata,
        },
        deep=True,
    )


def _target_tool_specs(sample: ClaudeApiSFTSample) -> list[dict[str, Any]]:
    target_names = {
        block.tool_call.name
        for block in sample.target_blocks
        if block.block_type == "tool_use" and block.tool_call is not None
    }
    filtered = [
        dict(spec)
        for spec in sample.tool_specs
        if isinstance(spec.get("name"), str) and spec["name"] in target_names
    ]
    return filtered or [dict(spec) for spec in sample.tool_specs]


def _build_hf_predictor(
    model_name_or_path: str | Path,
    tokenizer_name_or_path: str | Path | None,
    device: str,
    max_new_tokens: int,
    local_files_only: bool,
) -> NativeTransformedPredictor:
    return HFCausalLMPredictor(
        model_name_or_path,
        tokenizer_name_or_path=tokenizer_name_or_path,
        device=device,
        max_new_tokens=max_new_tokens,
        local_files_only=local_files_only,
    )


def _has_tool_use_target(sample: ClaudeApiSFTSample) -> bool:
    return any(
        block.block_type == "tool_use" and block.tool_call is not None
        for block in sample.target_blocks
    )


def _ordered_modes(grouped: dict[str, list[ClaudeApiSFTSample]]) -> list[str]:
    known = [mode for mode in NATIVE_TRANSFORMED_MODE_ORDER if mode in grouped]
    extras = sorted(mode for mode in grouped if mode not in NATIVE_TRANSFORMED_MODE_ORDER)
    return known + extras


def _write_probe_samples(samples: list[ClaudeApiSFTSample], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(
                json.dumps(
                    sample.model_dump(mode="json"),
                    sort_keys=True,
                    ensure_ascii=False,
                )
            )
            handle.write("\n")


def _load_loss_summary(train_dir: Path) -> dict[str, Any]:
    steps_path = train_dir / "train_steps.jsonl"
    if not steps_path.exists():
        return {
            "loss_observation_count": 0,
            "first_logged_loss": None,
            "final_logged_loss": None,
            "loss_improved": False,
        }
    losses: list[float] = []
    with open(steps_path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            record = json.loads(line)
            loss = record.get("loss")
            if isinstance(loss, (int, float)):
                losses.append(float(loss))
    return {
        "loss_observation_count": len(losses),
        "first_logged_loss": losses[0] if losses else None,
        "final_logged_loss": losses[-1] if losses else None,
        "loss_improved": (losses[-1] < losses[0]) if len(losses) >= 2 else False,
    }


def _write_smoke_run_summary(
    path: Path,
    *,
    base_report: NativeTransformedToolNameEvalReport,
    trained_report: NativeTransformedToolNameEvalReport,
    comparison: NativeTransformedToolNameComparisonReport,
    training: LocalCausalLMTrainingResult,
    train_completed: bool,
    loss_summary: dict[str, Any],
    success: bool,
) -> None:
    payload = {
        "success": success,
        "train_completed": train_completed,
        "loss_summary": loss_summary,
        "base_tool_name_accuracy": base_report.tool_name_accuracy,
        "trained_tool_name_accuracy": trained_report.tool_name_accuracy,
        "tool_name_accuracy_delta": comparison.tool_name_accuracy_delta,
        "training": training.model_dump(mode="json"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
