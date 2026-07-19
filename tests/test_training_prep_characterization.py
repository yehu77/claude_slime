"""RC-040 golden characterization for the four training-prep paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.auxiliary.claude_api.sft import (
    ClaudeApiSFTMessage,
    ClaudeApiSFTSample,
    ClaudeApiSFTTargetBlock,
    ClaudeApiSFTToolCallTarget,
)
from pycodeagent.auxiliary.claude_api.sft_dataset_io import (
    write_claude_api_sft_jsonl,
)
from pycodeagent.auxiliary.native_transformed.training_prep import (
    prepare_native_transformed_sft_training_input,
)
from pycodeagent.rl.schema_following import (
    CanonicalToolIntent,
    ExposedToolCallTarget,
    SchemaFollowingMessage,
    SchemaFollowingSample,
)
from pycodeagent.rl.schema_following_dataset import write_schema_following_jsonl
from pycodeagent.rl.tokenizer_config import (
    IGNORE_INDEX,
    FakeTokenizerConfig,
    TokenizerConfig,
)
from pycodeagent.rl.train_config import TrainConfig
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.rl.training_bundle import verify_training_bundle_manifest
from pycodeagent.rl.training_prep import (
    prepare_runtime_observed_schema_following_training_input,
    prepare_schema_following_training_input,
    prepare_slime_training_input,
)
from pycodeagent.testing import make_runtime_observed_batch_source
from pycodeagent.trajectory.schema import (
    Message,
    Role,
    RunStatus,
    ToolCall,
    Trajectory,
    VerifyResult,
)


pytestmark = pytest.mark.mainline

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = (
    ROOT / "docs/repository_cleanup/training_prep_characterization.json"
)


def _golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _relative_files(root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    )


def _assert_prepared_and_tokenized_contract(
    prepared_path: Path,
    tokenized_path: Path,
    *,
    expected_count: int,
    expected_trainable_kinds: list[str],
    expected_metadata_fields: list[str],
) -> None:
    prepared_records = _jsonl(prepared_path)
    assert len(prepared_records) == expected_count
    observed_trainable_kinds: set[str] = set()
    for record in prepared_records:
        assert record["text"] == "".join(
            segment["text"] for segment in record["segments"]
        )
        assert len(record["text"]) == len(record["character_mask"])
        assert sum(record["character_mask"]) == record["trainable_char_count"]
        observed_trainable_kinds.update(
            segment["kind"]
            for segment in record["segments"]
            if segment["trainable"]
        )
    assert sorted(observed_trainable_kinds) == sorted(expected_trainable_kinds)

    dataset = TrainDataset.from_jsonl(tokenized_path)
    assert len(dataset) == expected_count
    for example in dataset:
        assert len(example.input_ids) == len(example.attention_mask)
        assert len(example.input_ids) == len(example.labels)
        assert len(example.input_ids) == len(example.token_train_mask)
        assert set(expected_metadata_fields).issubset(example.metadata)
        assert example.trainable_token_count > 0
        for token_id, label, trainable in zip(
            example.input_ids,
            example.labels,
            example.token_train_mask,
            strict=True,
        ):
            assert label == (token_id if trainable else IGNORE_INDEX)


def _write_rollout_corpus(source_dir: Path) -> None:
    for task_id, status, reward, passed in [
        ("prep_success", RunStatus.COMPLETED, 1.0, True),
        ("prep_failure", RunStatus.ERROR, -0.5, False),
    ]:
        call = ToolCall(
            id=f"{task_id}_call",
            name="inspect_file",
            canonical_name="Read",
            arguments={"path": "main.py"},
        )
        trajectory = Trajectory(
            task_id=task_id,
            repo="characterization",
            tool_profile_id="toolview_name_only",
            messages=[
                Message(role=Role.SYSTEM, content="Use the exposed tools."),
                Message(role=Role.USER, content="Inspect main.py."),
                Message(
                    role=Role.ASSISTANT,
                    content="I will inspect the file.",
                    tool_calls=[call],
                ),
                Message(
                    role=Role.TOOL,
                    content="print('ok')",
                    tool_call_id=call.id,
                    tool_name=call.name,
                    canonical_name=call.canonical_name,
                ),
            ],
            tool_calls=[call],
            reward=reward,
            status=status,
            verifier=VerifyResult(passed=passed, score=1.0 if passed else 0.0),
        )
        run_dir = source_dir / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "trajectory.json").write_text(
            trajectory.model_dump_json(),
            encoding="utf-8",
        )


def _schema_sample(*, sample_id: str, source_type: str) -> SchemaFollowingSample:
    target = ExposedToolCallTarget(
        call_id=f"{sample_id}_call",
        name="inspect_file",
        arguments={"path": "main.py"},
    )
    return SchemaFollowingSample(
        sample_id=sample_id,
        sample_type="schema_following",
        source_type=source_type,
        split="train",
        task_id="prep_success" if source_type == "synthetic" else "prep_failure",
        tool_profile_id="toolview_name_only",
        mutation_category="name_only",
        messages=[
            SchemaFollowingMessage(role="system", content="Use the exposed tools."),
            SchemaFollowingMessage(role="user", content="Inspect main.py."),
        ],
        canonical_intent=CanonicalToolIntent(
            tool="Read",
            arguments={"file_path": "main.py"},
        ),
        target_tool_call=target,
        target_text=target.render_text(),
        loss_mask_policy="assistant_tool_call_only",
        metadata={
            "case_kind": (
                "success" if source_type == "synthetic" else "corrected_failure"
            )
        },
    )


def _write_schema_corpus(source_dir: Path) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    samples = [
        _schema_sample(sample_id="schema_success", source_type="synthetic"),
        _schema_sample(sample_id="schema_failure", source_type="hard_negative"),
    ]
    write_schema_following_jsonl(samples, source_dir / "train.jsonl")
    _write_json(
        source_dir / "dataset_manifest.json",
        {
            "dataset_type": "schema_following_characterization",
            "version": 1,
            "sample_count": 2,
            "loss_mask_policy": "assistant_tool_call_only",
            "present_splits": ["train"],
        },
    )
    _write_json(
        source_dir / "split_metrics.json",
        {"version": 1, "split_counts": {"train": 2}},
    )


def _write_native_corpus(source_dir: Path, *, include_manifest: bool = True) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    sample = ClaudeApiSFTSample(
        sample_id="native_transformed_success",
        sample_type="claude_api_sft",
        source_type="claude_api_trace",
        task_id="prep_success",
        tool_profile_id="toolview_name_only",
        messages=[
            ClaudeApiSFTMessage(role="system", content="Use the exposed tools."),
            ClaudeApiSFTMessage(role="user", content="Inspect main.py."),
        ],
        tool_specs=[
            {
                "name": "inspect_file",
                "description": "Inspect one file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        ],
        target_blocks=[
            ClaudeApiSFTTargetBlock(
                block_type="text",
                text="I will inspect the file.",
            ),
            ClaudeApiSFTTargetBlock(
                block_type="tool_use",
                tool_call=ClaudeApiSFTToolCallTarget(
                    call_id="native_call",
                    name="inspect_file",
                    arguments={"path": "main.py"},
                ),
            ),
        ],
        loss_mask_policy="assistant_selected_blocks_only",
        metadata={
            "transformation_mode": "name_only",
            "source_trace_path": "trace.jsonl",
            "source_request_id": "request_1",
            "source_catalog_id": "catalog_1",
            "base_profile_id": "claude_native",
            "target_profile_id": "toolview_name_only",
            "tool_use_remap_report": {
                "unmapped_tool_uses": 0,
                "dropped_tool_uses": 0,
            },
        },
    )
    write_claude_api_sft_jsonl([sample], source_dir / "train.jsonl")
    if include_manifest:
        _write_json(
            source_dir / "dataset_manifest.json",
            {
                "dataset_type": "native_transformed_claude_api_sft",
                "primary_sample_input": "train.jsonl",
                "present_splits": ["train"],
                "sample_count": 1,
            },
        )
    _write_json(
        source_dir / "split_metrics.json",
        {"version": 1, "split_counts": {"train": 1}},
    )


def _assert_config_roundtrip(output_dir: Path) -> None:
    tokenizer_config = TokenizerConfig.load(output_dir / "tokenizer_config.yaml")
    train_config = TrainConfig.load(output_dir / "train_config.json")
    assert tokenizer_config.max_length == 1024
    assert train_config.dataset_path == str(output_dir / "tokenized.jsonl")


def _assert_shared_bundle(output_dir: Path, *, expected_count: int) -> None:
    manifest = verify_training_bundle_manifest(output_dir)
    assert manifest.format == "pycodeagent-training-bundle/v1"
    assert manifest.sample_count == expected_count
    assert manifest.tokenized_count == expected_count
    assert manifest.packed_sequence_count > 0
    assert manifest.contract_ok is True


def test_characterization_manifest_has_four_classified_paths() -> None:
    golden = _golden()
    assert golden["schema"] == "repository-cleanup-training-prep-characterization/v3"
    assert golden["goal_id"] == "RC-040"
    assert set(golden["paths"]) == {
        "rollout",
        "schema_following",
        "runtime_observed",
        "native_transformed",
    }
    assert {
        path["difference_classification"] for path in golden["paths"].values()
    } == {
        "shared_bundle_source_adapter",
        "shared_bundle_nested_source_adapter",
    }


def test_rollout_training_prep_golden(tmp_path: Path) -> None:
    expected = _golden()["paths"]["rollout"]
    source_dir = tmp_path / "rollout_source"
    output_dir = tmp_path / "rollout_prepared"
    _write_rollout_corpus(source_dir)

    recommendation = prepare_slime_training_input(
        source_dir,
        output_dir,
        source_type="batch",
        include_failed=True,
        fake_tokenizer_config=FakeTokenizerConfig(),
        max_length=1024,
        run_id="rc040_rollout",
    )

    assert recommendation.tokenized_example_count == expected["expected_sample_count"]
    assert _relative_files(output_dir) == expected["expected_output_files"]
    _assert_prepared_and_tokenized_contract(
        output_dir / "samples.jsonl",
        output_dir / "tokenized.jsonl",
        expected_count=expected["expected_sample_count"],
        expected_trainable_kinds=expected["trainable_segment_kinds"],
        expected_metadata_fields=expected["token_metadata_fields"],
    )
    report = json.loads(
        (output_dir / "contract_report.json").read_text(encoding="utf-8")
    )
    assert report["packed_sequence_count"] > 0
    assert report["status_counts"] == {"completed": 1, "error": 1}
    tokenized = TrainDataset.from_jsonl(output_dir / "tokenized.jsonl")
    failed = next(item for item in tokenized if item.metadata["status"] == "error")
    assert failed.metadata["reward"] == -0.5
    assert failed.metadata["verifier_passed"] is False
    _assert_config_roundtrip(output_dir)
    _assert_shared_bundle(
        output_dir,
        expected_count=expected["expected_sample_count"],
    )


def test_schema_following_training_prep_golden(tmp_path: Path) -> None:
    expected = _golden()["paths"]["schema_following"]
    source_dir = tmp_path / "schema_source"
    output_dir = tmp_path / "schema_prepared"
    _write_schema_corpus(source_dir)

    recommendation = prepare_schema_following_training_input(
        source_dir,
        output_dir,
        fake_tokenizer_config=FakeTokenizerConfig(),
        max_length=1024,
        run_id="rc040_schema",
    )

    assert recommendation.tokenized_example_count == expected["expected_sample_count"]
    assert _relative_files(output_dir) == expected["expected_output_files"]
    _assert_prepared_and_tokenized_contract(
        output_dir / "samples.jsonl",
        output_dir / "tokenized.jsonl",
        expected_count=expected["expected_sample_count"],
        expected_trainable_kinds=expected["trainable_segment_kinds"],
        expected_metadata_fields=expected["token_metadata_fields"],
    )
    report = json.loads(
        (output_dir / "contract_report.json").read_text(encoding="utf-8")
    )
    assert report["packed_sequence_count"] > 0
    assert report["status_counts"] == {}
    assert report["reward_summary"]["count"] == 0
    _assert_config_roundtrip(output_dir)
    _assert_shared_bundle(
        output_dir,
        expected_count=expected["expected_sample_count"],
    )


def test_runtime_observed_training_prep_golden(tmp_path: Path) -> None:
    expected = _golden()["paths"]["runtime_observed"]
    source = make_runtime_observed_batch_source(
        tmp_path / "runtime_source",
        task_id="prep_success",
        profile_mode="name_only",
        profile_seed=7,
        tool_stack_kind="native_claude",
    )
    output_dir = tmp_path / "runtime_prepared"

    recommendation = prepare_runtime_observed_schema_following_training_input(
        source.batch_root,
        output_dir,
        source_type="batch",
        fake_tokenizer_config=FakeTokenizerConfig(),
        max_length=1024,
        run_id="rc040_runtime",
    )

    assert recommendation.tokenized_example_count == expected["expected_sample_count"]
    assert _relative_files(output_dir) == expected["expected_output_files"]
    _assert_prepared_and_tokenized_contract(
        output_dir / "prepared/samples.jsonl",
        output_dir / "prepared/tokenized.jsonl",
        expected_count=expected["expected_sample_count"],
        expected_trainable_kinds=expected["trainable_segment_kinds"],
        expected_metadata_fields=expected["token_metadata_fields"],
    )
    report = json.loads(
        (output_dir / "prepared/contract_report.json").read_text(encoding="utf-8")
    )
    assert report["packed_sequence_count"] > 0
    _assert_config_roundtrip(output_dir / "prepared")
    _assert_shared_bundle(
        output_dir / "prepared",
        expected_count=expected["expected_sample_count"],
    )


def test_native_transformed_training_prep_golden(tmp_path: Path) -> None:
    expected = _golden()["paths"]["native_transformed"]
    source_dir = tmp_path / "native_source"
    output_dir = tmp_path / "native_prepared"
    _write_native_corpus(source_dir)

    recommendation = prepare_native_transformed_sft_training_input(
        source_dir,
        output_dir,
        fake_tokenizer_config=FakeTokenizerConfig(),
        max_length=1024,
        run_id="rc040_native",
    )

    assert recommendation.tokenized_example_count == expected["expected_sample_count"]
    assert _relative_files(output_dir) == expected["expected_output_files"]
    assert (output_dir / "contract_report.json").exists()
    _assert_prepared_and_tokenized_contract(
        output_dir / "samples.jsonl",
        output_dir / "tokenized.jsonl",
        expected_count=expected["expected_sample_count"],
        expected_trainable_kinds=expected["trainable_segment_kinds"],
        expected_metadata_fields=expected["token_metadata_fields"],
    )
    _assert_config_roundtrip(output_dir)
    _assert_shared_bundle(
        output_dir,
        expected_count=expected["expected_sample_count"],
    )


def test_four_path_failure_boundaries_are_frozen(tmp_path: Path) -> None:
    rollout_source = tmp_path / "failure_rollout"
    _write_rollout_corpus(rollout_source)
    with pytest.raises(ValueError, match="Explicit tokenizer selection is required"):
        prepare_slime_training_input(
            rollout_source,
            tmp_path / "failure_rollout_output",
            source_type="batch",
        )

    schema_source = tmp_path / "failure_schema"
    _write_schema_corpus(schema_source)
    manifest = json.loads(
        (schema_source / "dataset_manifest.json").read_text(encoding="utf-8")
    )
    manifest["loss_mask_policy"] = "assistant_all"
    _write_json(schema_source / "dataset_manifest.json", manifest)
    with pytest.raises(ValueError, match="failed contract verification"):
        prepare_schema_following_training_input(
            schema_source,
            tmp_path / "failure_schema_output",
            fake_tokenizer_config=FakeTokenizerConfig(),
        )

    with pytest.raises(ValueError, match="supports split='train'"):
        prepare_runtime_observed_schema_following_training_input(
            tmp_path / "unused_runtime",
            tmp_path / "failure_runtime_output",
            source_type="batch",
            split="eval_seen",
            fake_tokenizer_config=FakeTokenizerConfig(),
        )

    native_source = tmp_path / "failure_native"
    _write_native_corpus(native_source, include_manifest=False)
    with pytest.raises(ValueError, match="failed validation"):
        prepare_native_transformed_sft_training_input(
            native_source,
            tmp_path / "failure_native_output",
            fake_tokenizer_config=FakeTokenizerConfig(),
        )
