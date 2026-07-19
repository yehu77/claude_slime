"""Mainline gate from a native local runtime trace to training-ready data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.eval.runtime_observed_postrun import (
    prepare_study_runtime_observed_bundle,
)
from pycodeagent.rl.schema_following_dataset import read_schema_following_jsonl
from pycodeagent.rl.schema_following_from_runtime import (
    generate_schema_following_from_runtime_runs,
)
from pycodeagent.rl.schema_following_training import (
    read_schema_following_prepared_samples,
)
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, IGNORE_INDEX
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.rl.training_prep import prepare_schema_following_training_input
from pycodeagent.testing import (
    cleanup_test_path,
    make_runtime_observed_batch_source,
    make_runtime_observed_study_source,
    make_unique_test_dir,
)
from pycodeagent.tools import build_native_claude_profile


pytestmark = pytest.mark.mainline


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_native_claude_runtime_observed_trace_reaches_training_prep() -> None:
    """Preserve ToolView provenance and masks across the observed-data mainline."""
    tmp = make_unique_test_dir("runtime_observed_mainline")
    try:
        source = make_runtime_observed_batch_source(
            tmp,
            task_id="native_claude_runtime_observed_mainline",
            profile_mode="name_only",
            profile_seed=7,
            tool_stack_kind="native_claude",
        )
        assert source.read_call is not None

        observed_dir = tmp / "observed"
        export_result = generate_schema_following_from_runtime_runs(
            source.batch_root,
            observed_dir,
            source_type="batch",
            split_seed=42,
        )
        assert export_result.discovered_run_count == 1
        assert export_result.included_run_count == 1
        assert export_result.skipped_run_count == 0
        assert export_result.skipped_observed_call_count == 0
        assert export_result.sample_count == 1
        assert export_result.split_counts == {"train": 1}

        samples = read_schema_following_jsonl(observed_dir / "train.jsonl")
        assert len(samples) == 1
        sample = samples[0]

        trace_events = _read_jsonl(source.batch_run_dir / "runtime_trace.jsonl")
        mapping_event = next(
            event
            for event in trace_events
            if event["event_kind"] == "tool_call_mapping_completed"
            and event["tool_call_id"] == source.read_call.call_id
        )
        execution_event = next(
            event
            for event in trace_events
            if event["event_kind"] == "tool_execution_completed"
            and event["tool_call_id"] == source.read_call.call_id
        )
        mapping_data = mapping_event["data"]
        execution_data = execution_event["data"]

        assert sample.source_type == "runtime_observed"
        assert sample.task_id == source.trajectory.task_id
        assert sample.tool_profile_id == source.profile.profile_id
        assert sample.target_tool_call.call_id == source.read_call.call_id
        assert sample.target_tool_call.name == source.read_call.name
        assert sample.target_tool_call.arguments == source.read_call.arguments
        assert sample.target_tool_call.name == mapping_data["exposed_tool_name"]
        assert sample.canonical_intent.tool == mapping_data["canonical_tool_name"] == "Read"
        assert sample.canonical_intent.arguments == {"file_path": "main.py"}
        assert execution_data["canonical_tool_name"] == sample.canonical_intent.tool
        assert sample.metadata["source_exposed_tool_name"] == source.read_call.name
        assert sample.metadata["canonical_tool_name"] == "Read"
        assert sample.metadata["source_tool_call_id"] == source.read_call.call_id
        assert sample.metadata["source_family"] == "claude"
        assert sample.metadata["source_native_profile_kind"] == "native_claude"
        assert sample.metadata["source_profile_mode"] == "name_only"
        assert sample.metadata["source_profile_seed"] == 7
        assert sample.metadata["source_protocol_mode"] == "native_tool_calling"
        assert sample.metadata["source_runtime_trace_present"] is True
        assert sample.metadata["source_trace_turn_index"] == execution_event["turn_index"]
        assert (
            sample.metadata["source_trace_execution_event_kind"]
            == execution_event["event_kind"]
            == "tool_execution_completed"
        )
        assert sample.metadata["source_execution_kind"] == execution_data["execution_kind"]
        assert sample.metadata["source_policy_decision"] == execution_data["policy_decision"]
        assert sample.metadata["source_tool_result_ok"] is True
        assert sample.metadata["source_tool_result_is_error"] is False

        # The profile manifest is the current contract for the exact schema exposed
        # during this run. Do not treat the still-missing serialized request envelope
        # as an established model-visible contract here.
        profile_manifest = _read_json(observed_dir / "profile_manifest.json")
        assert profile_manifest["version"] == 1
        profiles = profile_manifest["profiles"]
        assert isinstance(profiles, list)
        assert len(profiles) == 1
        manifest_profile = profiles[0]
        assert manifest_profile["profile_id"] == source.profile.profile_id
        assert manifest_profile["family"] == "claude"
        assert manifest_profile["native_profile_kind"] == "native_claude"
        assert manifest_profile["mode"] == "name_only"
        assert manifest_profile["seed"] == 7

        native_profile = build_native_claude_profile()
        manifest_tools = manifest_profile["tools"]
        assert [tool["canonical_name"] for tool in manifest_tools] == [
            "Bash",
            "Read",
            "Edit",
            "Write",
            "Grep",
            "Glob",
        ]
        assert len(manifest_tools) == len(source.profile.tools) == len(native_profile.tools)
        for manifest_tool, observed_view, native_view in zip(
            manifest_tools,
            source.profile.tools,
            native_profile.tools,
            strict=True,
        ):
            assert manifest_tool["canonical_name"] == native_view.canonical_name
            assert manifest_tool["exposed_name"] == observed_view.exposed_name
            assert manifest_tool["description"] == native_view.description
            assert manifest_tool["input_schema"] == native_view.input_schema
            assert manifest_tool["contract_kind"] == native_view.contract_kind.value
            assert manifest_tool["input_format"] == native_view.input_format

        manifest_exposed_specs = [
            {
                "name": tool["exposed_name"],
                "description": tool["description"],
                "input_schema": tool["input_schema"],
            }
            for tool in manifest_tools
        ]
        assert manifest_exposed_specs == source.profile.get_exposed_specs()

        target_payload = json.loads(sample.target_text.splitlines()[1])
        assert target_payload == {
            "arguments": source.read_call.arguments,
            "id": source.read_call.call_id,
            "name": source.read_call.name,
        }
        assert sample.target_tool_call.name != sample.canonical_intent.tool
        assert sample.canonical_intent.tool not in sample.target_text
        assert "canonical_name" not in target_payload
        assert "canonical_tool_name" not in target_payload

        prepared_dir = tmp / "prepared"
        recommendation = prepare_schema_following_training_input(
            observed_dir,
            prepared_dir,
            split="train",
            fake_tokenizer_config=FakeTokenizerConfig(chars_per_token=4),
            max_length=4096,
            batch_size=1,
            run_id="native_claude_runtime_observed_mainline",
        )
        assert recommendation.contract_ok is True
        assert recommendation.prepared_sample_count == 1
        assert recommendation.tokenized_example_count == 1

        prepared_samples = read_schema_following_prepared_samples(
            prepared_dir / "samples.jsonl"
        )
        assert len(prepared_samples) == 1
        prepared = prepared_samples[0]
        assert prepared.loss_mask_policy == "assistant_tool_call_only"
        assert [
            segment["kind"]
            for segment in prepared.segments
            if segment["trainable"]
        ] == ["assistant_tool_call"]
        assert all(
            not segment["trainable"]
            for segment in prepared.segments
            if segment["kind"] != "assistant_tool_call"
        )
        assert prepared.segments[-1]["text"] == sample.target_text
        assert prepared.trainable_char_count == len(sample.target_text)
        assert sum(prepared.character_mask) == prepared.trainable_char_count
        target_start = len(prepared.text) - len(sample.target_text)
        assert prepared.character_mask == (
            [0] * target_start + [1] * len(sample.target_text)
        )

        tokenized = TrainDataset.from_jsonl(prepared_dir / "tokenized.jsonl")
        assert len(tokenized) == 1
        example = tokenized[0]
        assert len(example.input_ids) == len(example.attention_mask)
        assert len(example.input_ids) == len(example.labels)
        assert len(example.input_ids) == len(example.token_train_mask)
        assert set(example.attention_mask) == {1}
        assert set(example.token_train_mask) == {0, 1}
        assert example.trainable_token_count > 0
        assert example.metadata["loss_mask_policy"] == "assistant_tool_call_only"
        assert example.metadata["source_type"] == "runtime_observed"
        for token_id, label, trainable in zip(
            example.input_ids,
            example.labels,
            example.token_train_mask,
            strict=True,
        ):
            assert label == (token_id if trainable else IGNORE_INDEX)
    finally:
        cleanup_test_path(tmp)


def test_native_family_study_reaches_reconciled_training_bundle() -> None:
    """Replace legacy study goldens with a current-family generated bundle."""
    tmp = make_unique_test_dir("runtime_observed_study_mainline")
    try:
        source = make_runtime_observed_study_source(
            tmp,
            entries=[
                {
                    "task_id": "native_claude_study_mainline",
                    "profile_mode": "name_only",
                    "profile_seed": 7,
                    "tool_stack_kind": "native_claude",
                },
                {
                    "task_id": "native_codex_study_mainline",
                    "profile_mode": "tool_reorder",
                    "profile_seed": 1,
                    "tool_stack_kind": "native_codex",
                },
            ],
        )

        bundle = prepare_study_runtime_observed_bundle(
            source.study_root,
            tmp / "bundle",
            source_type="study",
            fake_tokenizer_config=FakeTokenizerConfig(chars_per_token=4),
            max_length=4096,
            batch_size=2,
            run_id="native_family_runtime_observed_study_mainline",
        )

        assert bundle.discovered_run_count == 2
        assert bundle.included_run_count == 2
        assert bundle.skipped_run_count == 0
        assert bundle.observed_sample_count == 2
        assert bundle.tokenized_example_count == 2
        assert bundle.sample_count_by_family == {"claude": 1, "codex": 1}
        assert bundle.sample_count_by_native_profile_kind == {
            "native_claude": 1,
            "native_codex": 1,
        }
        assert bundle.sample_count_by_contract_kind == {
            "freeform": 1,
            "function": 1,
        }
        assert bundle.runtime_trace_present_count == 2
        assert bundle.runtime_trace_coverage_rate == 1.0
        assert bundle.trace_backed_sample_count == 2
        assert bundle.trace_backed_sample_rate == 1.0
        assert bundle.reconciliation_ok_count == 2
        assert bundle.reconciliation_error_count == 0
        assert bundle.critical_reconciliation_error_count == 0
        assert bundle.contract_ok is True

        raw_samples = read_schema_following_jsonl(
            Path(bundle.raw_dataset_dir) / "train.jsonl"
        )
        assert {sample.canonical_intent.tool for sample in raw_samples} == {
            "Read",
            "apply_patch",
        }
        assert {
            sample.metadata["source_family"] for sample in raw_samples
        } == {"claude", "codex"}
        assert all(
            sample.metadata["source_native_profile_kind"] != "legacy"
            for sample in raw_samples
        )

        manifest = _read_json(Path(bundle.study_observed_manifest_path))
        summary = _read_json(Path(bundle.study_observed_summary_path))
        reconciliation = _read_json(
            Path(bundle.runtime_execution_reconciliation_path)
        )
        assert manifest["contract_ok"] is True
        assert manifest["observed_sample_count"] == 2
        assert summary["sample_count_by_family"] == {"claude": 1, "codex": 1}
        assert reconciliation["summary"]["critical_reconciliation_error_count"] == 0
    finally:
        cleanup_test_path(tmp)
