"""Local small-model SFT runner for schema-following experiments."""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.rl.schema_following_eval import (
    CanonicalIntentBaselinePredictor,
    SchemaFollowingComparisonReport,
    SchemaFollowingEvaluationReport,
    compare_schema_following_reports,
    evaluate_schema_following_predictor,
    write_schema_following_comparison_json,
    write_schema_following_comparison_markdown,
    write_schema_following_eval_report_json,
    write_schema_following_eval_report_markdown,
)
from pycodeagent.rl.tokenizer_config import TokenizerConfig
from pycodeagent.rl.train_config import TrainConfig
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.rl.train_report import write_training_report
from pycodeagent.rl.training_prep import (
    SchemaFollowingTrainingPrepRecommendation,
    prepare_schema_following_training_input,
)


class LocalCausalLMTrainingResult(BaseModel):
    """Artifacts and metrics from one local HF fine-tuning run."""

    model_input_path: str
    model_output_path: str
    train_dataset_path: str
    train_output_dir: str
    num_steps: int
    final_loss: float
    average_loss: float
    examples_seen: int
    train_config_path: str
    training_report_dir: str


class SchemaFollowingSFTExperimentResult(BaseModel):
    """End-to-end result for a schema-following local SFT experiment."""

    dataset_dir: str
    prepared_dir: str
    eval_splits: list[str]
    canonical_baseline_report_path: str
    base_model_report_path: str
    trained_model_report_path: str
    comparison_report_path: str
    comparison_markdown_path: str
    training: LocalCausalLMTrainingResult
    metadata: dict[str, Any] = Field(default_factory=dict)


class HFCausalLMPredictor:
    """Autoregressive local predictor backed by a Hugging Face causal LM."""

    def __init__(
        self,
        model_name_or_path: str | Path,
        *,
        tokenizer_name_or_path: str | Path | None = None,
        device: str = "cpu",
        max_new_tokens: int = 192,
        local_files_only: bool = True,
    ) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._torch = torch
        self._device = torch.device(device)
        self._max_new_tokens = max_new_tokens
        tokenizer_path = str(tokenizer_name_or_path or model_name_or_path)
        self._tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_path,
            local_files_only=local_files_only,
        )
        self._model = AutoModelForCausalLM.from_pretrained(
            str(model_name_or_path),
            local_files_only=local_files_only,
        )
        self._ensure_padding_token()
        self._model.to(self._device)
        self._model.eval()

    def predict(self, sample: Any, prompt_text: str) -> str:
        del sample
        encoded = self._tokenizer(prompt_text, return_tensors="pt", add_special_tokens=False)
        input_ids = encoded["input_ids"].to(self._device)
        attention_mask = encoded["attention_mask"].to(self._device)

        with self._torch.no_grad():
            generated = self._model.generate(
                input_ids=input_ids,
                attention_mask=attention_mask,
                max_new_tokens=self._max_new_tokens,
                do_sample=False,
                pad_token_id=self._tokenizer.pad_token_id,
                eos_token_id=self._tokenizer.eos_token_id,
            )
        continuation = generated[0][input_ids.shape[1] :].tolist()
        return self._tokenizer.decode(continuation, skip_special_tokens=False)

    def _ensure_padding_token(self) -> None:
        if self._tokenizer.pad_token_id is None:
            if self._tokenizer.eos_token_id is not None:
                self._tokenizer.pad_token = self._tokenizer.eos_token
            else:
                self._tokenizer.add_special_tokens({"pad_token": "<|pad|>"})
                self._model.resize_token_embeddings(len(self._tokenizer))
        if self._model.config.pad_token_id is None:
            self._model.config.pad_token_id = self._tokenizer.pad_token_id


def train_local_causal_lm(
    model_name_or_path: str | Path,
    *,
    tokenizer_name_or_path: str | Path | None = None,
    train_config: TrainConfig,
    output_dir: str | Path,
    device: str = "cpu",
    local_files_only: bool = True,
) -> LocalCausalLMTrainingResult:
    """Fine-tune a local causal LM on tokenized schema-following data."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_output_dir = output_dir / "trained_model"
    tokenizer_path = str(tokenizer_name_or_path or model_name_or_path)

    dataset = TrainDataset.from_jsonl(train_config.dataset_path)
    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_path,
        local_files_only=local_files_only,
    )
    model = AutoModelForCausalLM.from_pretrained(
        str(model_name_or_path),
        local_files_only=local_files_only,
    )
    if tokenizer.pad_token_id is None:
        if tokenizer.eos_token_id is not None:
            tokenizer.pad_token = tokenizer.eos_token
        else:
            tokenizer.add_special_tokens({"pad_token": "<|pad|>"})
            model.resize_token_embeddings(len(tokenizer))
    if model.config.pad_token_id is None:
        model.config.pad_token_id = tokenizer.pad_token_id

    torch.manual_seed(train_config.seed)
    random.seed(train_config.seed)

    model.to(device)
    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=train_config.learning_rate)

    indices = list(range(len(dataset)))
    if len(indices) == 0:
        raise ValueError("Schema-following training dataset is empty.")

    step_records: list[dict[str, Any]] = []
    step_losses: list[float] = []
    start_time = time.time()
    examples_seen = 0
    step = 0

    while step < train_config.max_steps:
        random.shuffle(indices)
        for batch_start in range(0, len(indices), train_config.batch_size):
            if step >= train_config.max_steps:
                break

            batch_indices = indices[batch_start : batch_start + train_config.batch_size]
            batch = [dataset[index] for index in batch_indices]
            collated = dataset.collate_batch(batch, pad_token_id=tokenizer.pad_token_id or 0)

            input_ids = torch.tensor(collated["input_ids"], dtype=torch.long, device=device)
            attention_mask = torch.tensor(
                collated["attention_mask"],
                dtype=torch.long,
                device=device,
            )
            labels = torch.tensor(collated["labels"], dtype=torch.long, device=device)

            optimizer.zero_grad(set_to_none=True)
            outputs = model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                labels=labels,
            )
            loss = outputs.loss
            loss.backward()
            optimizer.step()

            step += 1
            examples_seen += len(batch)
            loss_value = float(loss.detach().cpu().item())
            step_losses.append(loss_value)
            step_records.append(
                {
                    "step": step,
                    "loss": loss_value,
                    "examples_seen": examples_seen,
                    "timestamp": time.time(),
                }
            )

    end_time = time.time()
    model.save_pretrained(model_output_dir)
    tokenizer.save_pretrained(model_output_dir)

    training_report = write_training_report(
        output_dir,
        train_config,
        num_steps=step,
        final_loss=step_losses[-1] if step_losses else 0.0,
        average_loss=(sum(step_losses) / len(step_losses)) if step_losses else 0.0,
        examples_seen=examples_seen,
        start_time=start_time,
        end_time=end_time,
        step_records=step_records,
    )
    return LocalCausalLMTrainingResult(
        model_input_path=str(model_name_or_path),
        model_output_path=str(model_output_dir),
        train_dataset_path=train_config.dataset_path,
        train_output_dir=str(output_dir),
        num_steps=step,
        final_loss=step_losses[-1] if step_losses else 0.0,
        average_loss=(sum(step_losses) / len(step_losses)) if step_losses else 0.0,
        examples_seen=examples_seen,
        train_config_path=str(output_dir / "train_config.json"),
        training_report_dir=str(training_report.output_dir),
    )


def run_schema_following_sft_experiment(
    dataset_dir: str | Path,
    output_dir: str | Path,
    *,
    model_name_or_path: str | Path,
    tokenizer_name_or_path: str | Path | None = None,
    train_split: str = "train",
    eval_splits: list[str] | None = None,
    max_length: int = 2048,
    batch_size: int = 8,
    learning_rate: float = 1e-4,
    max_steps: int = 100,
    seed: int = 42,
    device: str = "cpu",
    max_new_tokens: int = 192,
    local_files_only: bool = True,
) -> SchemaFollowingSFTExperimentResult:
    """Run a complete local schema-following experiment with before/after eval."""
    dataset_dir = Path(dataset_dir)
    output_dir = Path(output_dir)
    prepared_dir = output_dir / "prepared"
    eval_dir = output_dir / "eval"
    train_dir = output_dir / "train"
    output_dir.mkdir(parents=True, exist_ok=True)

    tokenizer_path = str(tokenizer_name_or_path or model_name_or_path)
    prep = prepare_schema_following_training_input(
        dataset_dir,
        prepared_dir,
        split=train_split,
        max_length=max_length,
        batch_size=batch_size,
        learning_rate=learning_rate,
        max_steps=max_steps,
        seed=seed,
        tokenizer_config=TokenizerConfig(
            tokenizer_name=tokenizer_path,
            max_length=max_length,
        ),
        run_id="schema_following_sft",
    )
    eval_splits = eval_splits or _default_eval_splits(dataset_dir)

    canonical_report = evaluate_schema_following_predictor(
        dataset_dir,
        predictor=CanonicalIntentBaselinePredictor(),
        model_label="canonical_baseline",
        splits=eval_splits,
        metadata={"train_split": train_split},
    )
    canonical_json = eval_dir / "canonical_baseline.json"
    canonical_md = eval_dir / "canonical_baseline.md"
    write_schema_following_eval_report_json(canonical_json, canonical_report)
    write_schema_following_eval_report_markdown(canonical_md, canonical_report)

    base_predictor = HFCausalLMPredictor(
        model_name_or_path,
        tokenizer_name_or_path=tokenizer_name_or_path,
        device=device,
        max_new_tokens=max_new_tokens,
        local_files_only=local_files_only,
    )
    base_report = evaluate_schema_following_predictor(
        dataset_dir,
        predictor=base_predictor,
        model_label="base_model",
        splits=eval_splits,
        metadata={"model_name_or_path": str(model_name_or_path), "train_split": train_split},
    )
    base_json = eval_dir / "base_model.json"
    base_md = eval_dir / "base_model.md"
    write_schema_following_eval_report_json(base_json, base_report)
    write_schema_following_eval_report_markdown(base_md, base_report)

    train_config = TrainConfig.load(prepared_dir / "train_config.json")
    trained = train_local_causal_lm(
        model_name_or_path,
        tokenizer_name_or_path=tokenizer_name_or_path,
        train_config=train_config,
        output_dir=train_dir,
        device=device,
        local_files_only=local_files_only,
    )

    trained_predictor = HFCausalLMPredictor(
        trained.model_output_path,
        tokenizer_name_or_path=trained.model_output_path,
        device=device,
        max_new_tokens=max_new_tokens,
        local_files_only=local_files_only,
    )
    trained_report = evaluate_schema_following_predictor(
        dataset_dir,
        predictor=trained_predictor,
        model_label="trained_model",
        splits=eval_splits,
        metadata={
            "model_name_or_path": trained.model_output_path,
            "train_split": train_split,
        },
    )
    trained_json = eval_dir / "trained_model.json"
    trained_md = eval_dir / "trained_model.md"
    write_schema_following_eval_report_json(trained_json, trained_report)
    write_schema_following_eval_report_markdown(trained_md, trained_report)

    comparison = compare_schema_following_reports(
        base_report,
        trained_report,
        baseline_report_path=str(base_json),
        trained_report_path=str(trained_json),
        metadata={
            "canonical_baseline_report_path": str(canonical_json),
            "prepared_dir": str(prepared_dir),
            "training_prep_path": str(prepared_dir / "training_prep.json"),
        },
    )
    comparison_json = eval_dir / "base_vs_trained.json"
    comparison_md = eval_dir / "base_vs_trained.md"
    write_schema_following_comparison_json(comparison_json, comparison)
    write_schema_following_comparison_markdown(comparison_md, comparison)

    return SchemaFollowingSFTExperimentResult(
        dataset_dir=str(dataset_dir),
        prepared_dir=str(prepared_dir),
        eval_splits=eval_splits,
        canonical_baseline_report_path=str(canonical_json),
        base_model_report_path=str(base_json),
        trained_model_report_path=str(trained_json),
        comparison_report_path=str(comparison_json),
        comparison_markdown_path=str(comparison_md),
        training=trained,
        metadata={
            "train_split": train_split,
            "max_length": max_length,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "max_steps": max_steps,
            "seed": seed,
            "device": device,
            "local_files_only": local_files_only,
            "prepared_recommendation": prep.model_dump(mode="json"),
        },
    )


def _default_eval_splits(dataset_dir: Path) -> list[str]:
    manifest_path = dataset_dir / "dataset_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [split for split in payload.get("present_splits", []) if split != "train"]
