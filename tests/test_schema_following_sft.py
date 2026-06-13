"""End-to-end tests for local schema-following SFT experiments."""

from __future__ import annotations

import json
from pathlib import Path

from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast

from pycodeagent.rl.schema_following_dataset import read_schema_following_jsonl
from pycodeagent.rl.schema_following_eval import build_schema_following_prompt_text
from pycodeagent.rl.schema_following_generate import generate_synthetic_schema_following_data
from pycodeagent.rl.schema_following_sft import run_schema_following_sft_experiment
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "schema_following_sft"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _build_tiny_model_bundle(model_dir: Path, dataset_dir: Path) -> None:
    corpus: list[str] = []
    for split_path in sorted(dataset_dir.glob("*.jsonl")):
        if split_path.name in {"samples.jsonl", "tokenized.jsonl"}:
            continue
        for sample in read_schema_following_jsonl(split_path):
            corpus.append(build_schema_following_prompt_text(sample))
            corpus.append(sample.target_text)

    tokenizer = Tokenizer(models.BPE(unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tokenizer.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(
        vocab_size=256,
        special_tokens=["[PAD]", "[UNK]", "[BOS]", "[EOS]"],
    )
    tokenizer.train_from_iterator(corpus, trainer=trainer)

    fast = PreTrainedTokenizerFast(
        tokenizer_object=tokenizer,
        unk_token="[UNK]",
        pad_token="[PAD]",
        bos_token="[BOS]",
        eos_token="[EOS]",
    )
    model_dir.mkdir(parents=True, exist_ok=True)
    fast.save_pretrained(model_dir)

    model = GPT2LMHeadModel(
        GPT2Config(
            vocab_size=fast.vocab_size,
            n_positions=4096,
            n_ctx=4096,
            n_embd=32,
            n_layer=1,
            n_head=2,
            bos_token_id=fast.bos_token_id,
            eos_token_id=fast.eos_token_id,
            pad_token_id=fast.pad_token_id,
        )
    )
    model.save_pretrained(model_dir)


class TestSchemaFollowingSFTExperiment:
    def test_run_schema_following_sft_experiment_writes_artifacts(self) -> None:
        tmp = _get_test_dir()
        try:
            dataset_dir = tmp / "dataset"
            model_dir = tmp / "tiny_model"
            output_dir = tmp / "experiment"

            result = generate_synthetic_schema_following_data(
                dataset_dir,
                num_intents=18,
                seed=11,
            )
            assert "train" in result.present_splits

            _build_tiny_model_bundle(model_dir, dataset_dir)

            experiment = run_schema_following_sft_experiment(
                dataset_dir,
                output_dir,
                model_name_or_path=model_dir,
                max_length=2048,
                batch_size=2,
                learning_rate=1e-4,
                max_steps=1,
                seed=3,
                device="cpu",
                max_new_tokens=48,
            )

            assert Path(experiment.prepared_dir, "tokenized.jsonl").exists()
            assert Path(experiment.training.model_output_path, "config.json").exists()
            assert Path(experiment.base_model_report_path).exists()
            assert Path(experiment.trained_model_report_path).exists()
            assert Path(experiment.comparison_report_path).exists()
            assert Path(experiment.comparison_markdown_path).exists()

            comparison = json.loads(Path(experiment.comparison_report_path).read_text(encoding="utf-8"))
            assert comparison["baseline_label"] == "base_model"
            assert comparison["trained_label"] == "trained_model"
            assert experiment.eval_splits
        finally:
            _cleanup(tmp)
