"""Tests for native-transformed SFT overfit smoke utilities."""

from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.auxiliary.claude_api.sft import (
    ClaudeApiSFTMessage,
    ClaudeApiSFTSample,
    ClaudeApiSFTTargetBlock,
    ClaudeApiSFTToolCallTarget,
)
from pycodeagent.auxiliary.claude_api.sft_dataset_io import write_claude_api_sft_jsonl
from pycodeagent.auxiliary.native_transformed.sft_eval import (
    build_native_transformed_prompt_text,
    evaluate_native_transformed_tool_name_predictor,
    evaluate_native_transformed_tool_name_sample,
)
from pycodeagent.auxiliary.native_transformed.sft_smoke import (
    build_native_transformed_smoke_train_bundle,
    run_native_transformed_sft_smoke,
    select_native_transformed_probe_samples,
    trim_native_transformed_sample_for_smoke,
)
from pycodeagent.rl.schema_following_sft import LocalCausalLMTrainingResult
from pycodeagent.rl.tensorize import TokenizedExample
from pycodeagent.rl.tokenizer import FakeTokenizerAdapter
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig
from pycodeagent.rl.train_config import TrainConfig
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "native_transformed_sft_smoke"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _make_sample(
    sample_id: str,
    *,
    mode: str,
    tool_name: str = "ReadTransformed",
    with_tool_use: bool = True,
) -> ClaudeApiSFTSample:
    target_blocks: list[ClaudeApiSFTTargetBlock]
    if with_tool_use:
        target_blocks = [
            ClaudeApiSFTTargetBlock(
                block_type="tool_use",
                tool_call=ClaudeApiSFTToolCallTarget(
                    call_id=f"call_{sample_id}",
                    name=tool_name,
                    arguments={"file_path": "README.md"},
                ),
            )
        ]
    else:
        target_blocks = [ClaudeApiSFTTargetBlock(block_type="text", text="Done.")]

    return ClaudeApiSFTSample(
        sample_id=sample_id,
        sample_type="claude_api_sft",
        source_type="claude_api_trace",
        task_id=f"task_{sample_id}",
        tool_profile_id=f"profile_{mode}",
        messages=[
            ClaudeApiSFTMessage(role="system", content="You are a coding agent."),
            ClaudeApiSFTMessage(role="user", content="Inspect README.md."),
        ],
        tool_specs=[
            {
                "name": tool_name,
                "description": "Read a file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            }
        ],
        target_blocks=target_blocks,
        loss_mask_policy="assistant_selected_blocks_only",
        metadata={
            "transformation_mode": mode,
            "source_catalog_id": "catalog",
            "base_profile_id": "base",
            "target_profile_id": f"profile_{mode}",
        },
    )


def _write_dataset(dataset_dir: Path, samples: list[ClaudeApiSFTSample]) -> None:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    write_claude_api_sft_jsonl(samples, dataset_dir / "train.jsonl")


def _write_prepared(prepared_dir: Path, samples: list[ClaudeApiSFTSample]) -> None:
    examples = [
        TokenizedExample(
            input_ids=[1, 2, 3],
            attention_mask=[1, 1, 1],
            labels=[-100, 2, 3],
            token_train_mask=[0, 1, 1],
            metadata={
                "sample_id": sample.sample_id,
                "source_type": "native_transformed_claude_api_sft",
            },
        )
        for sample in samples
    ]
    TrainDataset.from_examples(examples).save_jsonl(prepared_dir / "tokenized.jsonl")
    TrainConfig(
        run_id="native_prepared",
        dataset_path=str(prepared_dir / "tokenized.jsonl"),
        output_dir=str(prepared_dir / "training_outputs"),
        max_steps=100,
        batch_size=8,
        learning_rate=1e-4,
        seed=11,
        metadata={"source_type": "native_transformed_claude_api_sft"},
    ).save(prepared_dir / "train_config.json")


class _StaticPredictor:
    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name

    def predict(self, sample: ClaudeApiSFTSample, prompt_text: str) -> str:
        assert prompt_text == build_native_transformed_prompt_text(sample)
        return (
            "<|tool|>\n"
            + json.dumps(
                {
                    "id": "predicted",
                    "name": self.tool_name,
                    "arguments": {"file_path": "README.md"},
                },
                sort_keys=True,
            )
            + "\n<|end|>\n"
        )


class TestNativeTransformedProbeSelection:
    def test_selects_tool_use_samples_per_mode_deterministically(self) -> None:
        tmp = _get_test_dir()
        try:
            dataset_dir = tmp / "dataset"
            samples = [
                _make_sample("z_name_2", mode="name_only"),
                _make_sample("text_only", mode="name_only", with_tool_use=False),
                _make_sample("a_name_1", mode="name_only"),
                _make_sample("base_1", mode="base"),
                _make_sample("desc_1", mode="description_only"),
            ]
            _write_dataset(dataset_dir, samples)

            selected = select_native_transformed_probe_samples(
                dataset_dir,
                per_mode_probe_count=1,
            )

            assert [sample.sample_id for sample in selected] == [
                "base_1",
                "a_name_1",
                "desc_1",
            ]
            assert all(
                any(block.block_type == "tool_use" for block in sample.target_blocks)
                for sample in selected
            )
        finally:
            _cleanup(tmp)


class TestNativeTransformedSmokeTrainBundle:
    def test_filters_prepared_tokenized_jsonl_and_patches_config(self) -> None:
        tmp = _get_test_dir()
        try:
            prepared_dir = tmp / "prepared"
            output_dir = tmp / "smoke"
            samples = [
                _make_sample("keep_1", mode="base"),
                _make_sample("drop_1", mode="name_only"),
                _make_sample("keep_2", mode="description_only"),
            ]
            _write_prepared(prepared_dir, samples)

            bundle = build_native_transformed_smoke_train_bundle(
                [samples[0], samples[2]],
                prepared_dir=prepared_dir,
                output_dir=output_dir,
                max_steps=7,
                batch_size=2,
                learning_rate=2e-5,
                seed=5,
            )

            dataset = TrainDataset.from_jsonl(bundle.tokenized_train_path)
            patched = TrainConfig.load(bundle.train_config_path)

            assert [example.metadata["sample_id"] for example in dataset] == [
                "keep_1",
                "keep_2",
            ]
            assert patched.dataset_path == str(output_dir / "train" / "smoke_tokenized.jsonl")
            assert patched.output_dir == str(output_dir / "train")
            assert patched.max_steps == 7
            assert patched.batch_size == 2
            assert patched.learning_rate == 2e-5
            assert patched.seed == 5
            assert patched.metadata["source_type"] == "native_transformed_claude_api_sft"
        finally:
            _cleanup(tmp)

    def test_can_rebuild_trimmed_smoke_train_set_from_raw_samples(self) -> None:
        tmp = _get_test_dir()
        try:
            prepared_dir = tmp / "prepared"
            output_dir = tmp / "smoke"
            sample = _make_sample("keep_1", mode="name_only", tool_name="InspectFile")
            sample.messages[0].content = "A" * 5000
            _write_prepared(prepared_dir, [sample])

            tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=4))
            tokenizer_config = TokenizerConfig(
                tokenizer_name="fake",
                max_length=600,
                truncation=True,
            )
            trimmed = trim_native_transformed_sample_for_smoke(
                sample,
                tokenizer=tokenizer,
                max_length=600,
            )
            bundle = build_native_transformed_smoke_train_bundle(
                [trimmed],
                prepared_dir=prepared_dir,
                output_dir=output_dir,
                max_steps=2,
                batch_size=1,
                learning_rate=1e-4,
                seed=3,
                tokenizer=tokenizer,
                tokenizer_config=tokenizer_config,
            )

            dataset = TrainDataset.from_jsonl(bundle.tokenized_train_path)

            assert len(dataset) == 1
            assert dataset[0].length <= 600
            assert dataset[0].trainable_token_count > 0
            assert dataset[0].metadata["smoke_context_trimmed"] is True
            assert dataset[0].metadata["smoke_retained_tool_spec_count"] == 1
            assert dataset[0].metadata["sample_id"] == "keep_1"
        finally:
            _cleanup(tmp)


class TestNativeTransformedToolNameEval:
    def test_builds_prompt_and_scores_transformed_tool_name(self) -> None:
        sample = _make_sample("probe_1", mode="name_only", tool_name="InspectFile")
        prompt_text = build_native_transformed_prompt_text(sample)
        predicted_text = (
            '<|tool|>\n{"arguments":{"file_path":"README.md"},"id":"x","name":"InspectFile"}\n<|end|>\n'
        )

        case = evaluate_native_transformed_tool_name_sample(
            sample,
            prompt_text=prompt_text,
            predicted_text=predicted_text,
        )

        assert "<|tool|>" not in prompt_text
        assert "InspectFile" in prompt_text
        assert case.parse_ok is True
        assert case.expected_tool_name == "InspectFile"
        assert case.predicted_tool_name == "InspectFile"
        assert case.tool_name_ok is True
        assert case.arguments_exact_match is True

    def test_records_tool_name_mismatch_and_parse_failure(self) -> None:
        sample = _make_sample("probe_1", mode="name_only", tool_name="InspectFile")

        mismatch = evaluate_native_transformed_tool_name_predictor(
            [sample],
            predictor=_StaticPredictor("Read"),
            model_label="wrong",
            dataset_dir="dataset",
        )
        parse_failure = evaluate_native_transformed_tool_name_sample(
            sample,
            prompt_text="prompt",
            predicted_text="no tool block",
        )

        assert mismatch.tool_name_accuracy == 0.0
        assert mismatch.failed_cases[0].error_code == "tool_name_mismatch"
        assert parse_failure.parse_ok is False
        assert parse_failure.error_code == "missing_tool_call_block"


class TestNativeTransformedSFTSmoke:
    def test_run_smoke_with_fake_predictors_and_trainer_writes_success_summary(self) -> None:
        tmp = _get_test_dir()
        try:
            dataset_dir = tmp / "dataset"
            prepared_dir = tmp / "prepared"
            output_dir = tmp / "smoke"
            samples = [
                _make_sample("base_1", mode="base", tool_name="Read"),
                _make_sample("name_1", mode="name_only", tool_name="InspectFile"),
            ]
            _write_dataset(dataset_dir, samples)
            _write_prepared(prepared_dir, samples)

            def predictor_factory(model_path, tokenizer_path, device, max_new_tokens, local_files_only):
                if str(model_path).endswith("trained_model"):
                    return _StaticPredictor("InspectFile")
                return _StaticPredictor("WrongTool")

            def trainer(model_path, **kwargs):
                train_output = Path(kwargs["output_dir"])
                model_output = train_output / "trained_model"
                model_output.mkdir(parents=True, exist_ok=True)
                (train_output / "train_steps.jsonl").write_text(
                    '{"step": 1, "loss": 2.0, "examples_seen": 1, "timestamp": 1.0}\n'
                    '{"step": 2, "loss": 1.0, "examples_seen": 2, "timestamp": 2.0}\n',
                    encoding="utf-8",
                )
                return LocalCausalLMTrainingResult(
                    model_input_path=str(model_path),
                    model_output_path=str(model_output),
                    train_dataset_path=kwargs["train_config"].dataset_path,
                    train_output_dir=str(train_output),
                    num_steps=2,
                    final_loss=1.0,
                    average_loss=1.5,
                    examples_seen=2,
                    train_config_path=str(train_output / "train_config.json"),
                    training_report_dir=str(train_output),
                )

            result = run_native_transformed_sft_smoke(
                dataset_dir,
                prepared_dir,
                output_dir,
                model_name_or_path=tmp / "model",
                max_steps=2,
                batch_size=1,
                learning_rate=1e-4,
                per_mode_probe_count=1,
                predictor_factory=predictor_factory,
                trainer=trainer,
            )

            comparison = json.loads(
                Path(result.comparison_report_path).read_text(encoding="utf-8")
            )
            summary = json.loads(Path(result.smoke_run_path).read_text(encoding="utf-8"))

            assert result.success is True
            assert comparison["tool_name_accuracy_delta"] > 0.0
            assert summary["success"] is True
            assert (output_dir / "probe_samples.jsonl").exists()
            assert (output_dir / "train" / "smoke_tokenized.jsonl").exists()
            assert (output_dir / "eval" / "base_model_report.json").exists()
            assert (output_dir / "eval" / "trained_model_report.json").exists()
        finally:
            _cleanup(tmp)
