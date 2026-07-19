"""RC-042 gates for the single deterministic training-bundle builder."""

from __future__ import annotations

import hashlib
import json

import pytest

from pycodeagent.rl.packing import PackedSequence
from pycodeagent.rl.prepared_sample import PreparedSample, read_prepared_samples
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.rl.training_bundle import (
    TRAINING_BUNDLE_ORDERING,
    TrainingBundleBuilder,
    TrainingBundleManifest,
    verify_training_bundle_manifest,
)


pytestmark = pytest.mark.mainline


def _sample(*, sample_id: str, task_id: str) -> PreparedSample:
    context = f"<user>\n{task_id}\n</user>\n"
    target = (
        '<|tool|>\n{"arguments":{"path":"main.py"},'
        f'"id":"{sample_id}-call","name":"inspect_file"}}\n<|end|>\n'
    )
    text = context + target
    return PreparedSample(
        sample_id=sample_id,
        sample_type="schema_following",
        source_type="runtime_observed",
        task_id=task_id,
        tool_profile_id="toolview-name-only",
        mutation_category="name_only",
        text=text,
        segments=[
            {"kind": "user", "text": context, "trainable": False, "metadata": {}},
            {
                "kind": "assistant_tool_call",
                "text": target,
                "trainable": True,
                "metadata": {"tool_name": "inspect_file"},
            },
        ],
        character_mask=[0] * len(context) + [1] * len(target),
        spans=[
            {"start": 0, "end": len(context), "trainable": False},
            {"start": len(context), "end": len(text), "trainable": True},
        ],
        trainable_char_count=len(target),
        metadata={"raw_trace_id": f"trace-{sample_id}"},
    )


def test_builder_sorts_and_writes_complete_verified_bundle(tmp_path) -> None:
    output_dir = tmp_path / "bundle"
    result = TrainingBundleBuilder().build(
        [
            _sample(sample_id="sample-b", task_id="task-b"),
            _sample(sample_id="sample-a", task_id="task-a"),
        ],
        output_dir,
        source_type="runtime_observed",
        source_path=tmp_path / "raw",
        run_id="rc042",
        max_length=512,
        fake_tokenizer_config=FakeTokenizerConfig(),
        source_artifacts=["source_manifest.json", "runtime_trace.jsonl"],
    )

    assert result.contract_result.ok
    assert [sample.sample_id for sample in read_prepared_samples(result.samples_path)] == [
        "sample-a",
        "sample-b",
    ]
    assert len(TrainDataset.from_jsonl(result.tokenized_path)) == 2
    packed = [
        PackedSequence.model_validate_json(line)
        for line in result.packed_path.read_text(encoding="utf-8").splitlines()
    ]
    assert packed

    manifest = TrainingBundleManifest.model_validate_json(
        result.manifest_path.read_text(encoding="utf-8")
    )
    assert manifest.format == "pycodeagent-training-bundle/v1"
    assert manifest.ordering == TRAINING_BUNDLE_ORDERING
    assert manifest.prepared_sample_schema_version == 1
    assert manifest.sample_count == manifest.tokenized_count == 2
    assert manifest.packed_sequence_count == len(packed)
    assert manifest.source_artifacts == [
        "runtime_trace.jsonl",
        "source_manifest.json",
    ]
    assert set(manifest.artifacts) == {
        "contract_report.json",
        "packed.jsonl",
        "samples.jsonl",
        "tokenized.jsonl",
        "tokenizer_config.yaml",
        "train_config.json",
    }
    verify_training_bundle_manifest(output_dir)


def test_rebuild_is_byte_deterministic(tmp_path) -> None:
    output_dir = tmp_path / "bundle"
    builder = TrainingBundleBuilder()
    samples = [
        _sample(sample_id="sample-b", task_id="task-b"),
        _sample(sample_id="sample-a", task_id="task-a"),
    ]
    first = builder.build(
        samples,
        output_dir,
        source_type="schema_following",
        source_path=tmp_path / "raw",
        run_id="deterministic",
        fake_tokenizer_config=FakeTokenizerConfig(),
    )
    first_manifest_bytes = first.manifest_path.read_bytes()
    first_digests = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in output_dir.iterdir()
        if path.is_file()
    }

    second = builder.build(
        list(reversed(samples)),
        output_dir,
        source_type="schema_following",
        source_path=tmp_path / "raw",
        run_id="deterministic",
        fake_tokenizer_config=FakeTokenizerConfig(),
    )

    assert second.manifest_path.read_bytes() == first_manifest_bytes
    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in output_dir.iterdir()
        if path.is_file()
    } == first_digests


def test_checksum_verifier_rejects_tampered_artifact(tmp_path) -> None:
    output_dir = tmp_path / "bundle"
    result = TrainingBundleBuilder().build(
        [_sample(sample_id="sample-a", task_id="task-a")],
        output_dir,
        source_type="schema_following",
        source_path=tmp_path / "raw",
        run_id="checksum",
        fake_tokenizer_config=FakeTokenizerConfig(),
    )
    with open(result.tokenized_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"tampered": True}) + "\n")

    with pytest.raises(ValueError, match="checksum mismatch for tokenized.jsonl"):
        verify_training_bundle_manifest(output_dir)


def test_duplicate_sample_id_writes_failure_report_without_manifest(tmp_path) -> None:
    output_dir = tmp_path / "bundle"
    with pytest.raises(ValueError, match="failed contract verification"):
        TrainingBundleBuilder().build(
            [
                _sample(sample_id="duplicate", task_id="task-a"),
                _sample(sample_id="duplicate", task_id="task-b"),
            ],
            output_dir,
            source_type="schema_following",
            source_path=tmp_path / "raw",
            run_id="duplicate",
            fake_tokenizer_config=FakeTokenizerConfig(),
        )

    report = json.loads(
        (output_dir / "contract_report.json").read_text(encoding="utf-8")
    )
    assert {issue["code"] for issue in report["issues"]} == {
        "prepared_duplicate_sample_id"
    }
    assert not (output_dir / "bundle_manifest.json").exists()
