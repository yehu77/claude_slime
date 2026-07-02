"""Tests for first-class schema-following sample models and JSONL helpers."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pycodeagent.rl.schema_following import (
    CanonicalToolIntent,
    ExposedToolCallTarget,
    SchemaFollowingMessage,
    SchemaFollowingSample,
    render_exposed_tool_call_text,
)
from pycodeagent.rl.schema_following_dataset import (
    SchemaFollowingDatasetError,
    read_schema_following_jsonl,
    validate_schema_following_jsonl,
    write_schema_following_jsonl,
)
from pycodeagent.testing.temp_artifacts import make_request_test_dir


def make_target(
    *,
    call_id: str = "call_1",
    name: str = "inspect_source",
    arguments: dict | None = None,
) -> ExposedToolCallTarget:
    return ExposedToolCallTarget(
        call_id=call_id,
        name=name,
        arguments=arguments
        or {
            "target": {
                "file": "src/calculator.py",
                "span": {"begin": 1, "end": 80},
            }
        },
    )


def make_messages() -> list[SchemaFollowingMessage]:
    return [
        SchemaFollowingMessage(
            role="system",
            content="Use only the exact tool names and argument shapes shown.",
        ),
        SchemaFollowingMessage(
            role="user",
            content=(
                "Inspect src/calculator.py.\n\n"
                "<tools>\n"
                "inspect_source: Read a file segment from the current workspace.\n"
                "</tools>"
            ),
        ),
    ]


def make_sample(
    *,
    sample_id: str = "sf__synthetic__seed42__profile_nested__intent0001",
    source_type: str = "synthetic",
    split: str = "train",
    mutation_category: str = "schema_flat_to_nested",
) -> SchemaFollowingSample:
    target = make_target()
    return SchemaFollowingSample(
        sample_id=sample_id,
        sample_type="schema_following",
        source_type=source_type,
        split=split,
        task_id="task_001",
        tool_profile_id="profile_nested",
        mutation_category=mutation_category,
        messages=make_messages(),
        canonical_intent=CanonicalToolIntent(
            tool="read_file",
            arguments={
                "path": "src/calculator.py",
                "start_line": 1,
                "end_line": 80,
            },
        ),
        target_tool_call=target,
        target_text=target.render_text(),
        loss_mask_policy="assistant_tool_call_only",
        metadata={"requires_nested_args": True},
    )


class TestRenderExposedToolCallText:
    def test_renders_canonical_tool_block(self):
        text = render_exposed_tool_call_text(
            call_id="call_1",
            name="inspect_source",
            arguments={"path": "src/main.py", "start_line": 1},
        )
        assert text.startswith("<|tool|>\n")
        assert text.endswith("\n<|end|>\n")

    def test_renders_deterministic_sorted_json(self):
        text = render_exposed_tool_call_text(
            call_id="call_1",
            name="inspect_source",
            arguments={"b": 2, "a": 1},
        )
        payload = text[len("<|tool|>\n") : -len("\n<|end|>\n")]
        assert payload == json.dumps(
            {
                "arguments": {"b": 2, "a": 1},
                "id": "call_1",
                "name": "inspect_source",
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    def test_renders_freeform_input_text_payload(self):
        text = render_exposed_tool_call_text(
            call_id="call_1",
            name="apply_patch",
            input_text="*** Begin Patch\n*** End Patch\n",
        )
        payload = text[len("<|tool|>\n") : -len("\n<|end|>\n")]
        assert payload == json.dumps(
            {
                "id": "call_1",
                "name": "apply_patch",
                "payload_kind": "input_text",
                "input_text": "*** Begin Patch\n*** End Patch\n",
            },
            sort_keys=True,
            ensure_ascii=False,
        )


class TestSchemaFollowingSample:
    def test_model_roundtrip(self):
        sample = make_sample()
        loaded = SchemaFollowingSample.model_validate(sample.model_dump(mode="json"))
        assert loaded == sample

    def test_target_text_must_match_target_tool_call(self):
        target = make_target()
        with pytest.raises(ValidationError, match="target_text does not match"):
            SchemaFollowingSample(
                sample_id="sf__synthetic__x__base__001",
                sample_type="schema_following",
                source_type="synthetic",
                split="train",
                task_id="task_001",
                tool_profile_id="profile_nested",
                mutation_category="schema_flat_to_nested",
                messages=make_messages(),
                canonical_intent=CanonicalToolIntent(
                    tool="read_file",
                    arguments={"path": "src/calculator.py"},
                ),
                target_tool_call=target,
                target_text="<tool_call>\n{}\n</tool_call>",
                loss_mask_policy="assistant_tool_call_only",
            )

    def test_invalid_split_fails(self):
        with pytest.raises(ValidationError):
            make_sample(split="eval_unknown")

    def test_invalid_sample_type_fails(self):
        data = make_sample().model_dump(mode="json")
        data["sample_type"] = "rollout"
        with pytest.raises(ValidationError):
            SchemaFollowingSample.model_validate(data)

    def test_missing_required_field_fails(self):
        data = make_sample().model_dump(mode="json")
        del data["target_tool_call"]
        with pytest.raises(ValidationError):
            SchemaFollowingSample.model_validate(data)

    def test_trajectory_derived_style_sample_is_valid(self):
        sample = make_sample(
            sample_id="sf__trajectory_derived__run001__profile_nested__step0003",
            source_type="trajectory_derived",
            split="eval_seen",
            mutation_category="rename_light",
        )
        sample.metadata.update(
            {
                "source_run_dir": "runs/studies/example/run_001",
                "source_tool_call_id": "call_17",
                "source_step_index": 3,
            }
        )
        validated = SchemaFollowingSample.model_validate(sample.model_dump(mode="json"))
        assert validated.source_type == "trajectory_derived"
        assert validated.metadata["source_tool_call_id"] == "call_17"

    def test_runtime_observed_style_sample_is_valid(self):
        sample = make_sample(
            sample_id="sf__runtime_observed__run001__profile_nested__step0001",
            source_type="runtime_observed",
            split="train",
            mutation_category="name_description_schema",
        )
        sample.metadata.update(
            {
                "source_run_dir": "outputs/study/example/run_001",
                "source_profile_mode": "name_description_schema",
                "source_profile_seed": 0,
                "source_exposed_tool_name": "open_source",
                "source_runtime_trace_present": True,
            }
        )
        validated = SchemaFollowingSample.model_validate(sample.model_dump(mode="json"))
        assert validated.source_type == "runtime_observed"
        assert validated.metadata["source_exposed_tool_name"] == "open_source"

    def test_freeform_runtime_observed_style_sample_is_valid(self):
        target = ExposedToolCallTarget(
            call_id="call_patch",
            name="apply_patch",
            input_text="*** Begin Patch\n*** End Patch\n",
        )
        sample = SchemaFollowingSample(
            sample_id="sf__runtime_observed__run001__profile_codex__step0001",
            sample_type="schema_following",
            source_type="runtime_observed",
            split="train",
            task_id="task_patch",
            tool_profile_id="native_codex_mutation_base_x",
            mutation_category="base",
            messages=make_messages(),
            canonical_intent=CanonicalToolIntent(
                tool="apply_patch",
                input_text="*** Begin Patch\n*** End Patch\n",
            ),
            target_tool_call=target,
            target_text=target.render_text(),
            loss_mask_policy="assistant_tool_call_only",
            metadata={
                "source_family": "codex",
                "source_contract_kind": "freeform",
            },
        )
        validated = SchemaFollowingSample.model_validate(sample.model_dump(mode="json"))
        assert validated.target_tool_call.input_text is not None
        assert validated.canonical_intent.input_text is not None
        assert '"payload_kind": "input_text"' in validated.target_text


class TestSchemaFollowingJsonl:
    def test_write_and_read_roundtrip(self, request):
        path = make_request_test_dir("schema_following_sample", request) / "schema_following.jsonl"
        expected = [
            make_sample(),
            make_sample(
                sample_id="sf__synthetic__seed42__profile_rename__intent0002",
                mutation_category="rename_light",
            ),
        ]
        write_schema_following_jsonl(expected, path)
        loaded = read_schema_following_jsonl(path)
        assert loaded == expected

    def test_validate_schema_following_jsonl_accepts_valid_file(self, request):
        path = make_request_test_dir("schema_following_sample", request) / "schema_following.jsonl"
        write_schema_following_jsonl([make_sample()], path)
        validate_schema_following_jsonl(path)

    def test_read_schema_following_jsonl_reports_json_line_number(self, request):
        path = make_request_test_dir("schema_following_sample", request) / "schema_following.jsonl"
        path.write_text('{"sample_id":"ok"}\n{"bad"\n', encoding="utf-8")
        with pytest.raises(SchemaFollowingDatasetError, match=r"line 1|line 2"):
            read_schema_following_jsonl(path)

    def test_read_schema_following_jsonl_reports_validation_line_number(self, request):
        path = make_request_test_dir("schema_following_sample", request) / "schema_following.jsonl"
        invalid_record = {
            "sample_id": "sf__synthetic__seed42__profile_nested__intent0001",
            "sample_type": "schema_following",
            "source_type": "synthetic",
            "split": "train",
            "task_id": "task_001",
            "tool_profile_id": "profile_nested",
            "mutation_category": "schema_flat_to_nested",
            "messages": [{"role": "system", "content": "x"}],
            "canonical_intent": {"tool": "read_file", "arguments": {"path": "x"}},
            "target_tool_call": {
                "call_id": "call_1",
                "name": "inspect_source",
                "arguments": {"target": {"file": "x"}},
            },
            "target_text": "<tool_call>\n{}\n</tool_call>",
            "loss_mask_policy": "assistant_tool_call_only",
            "metadata": {},
        }
        path.write_text(json.dumps(invalid_record, ensure_ascii=False) + "\n", encoding="utf-8")
        with pytest.raises(SchemaFollowingDatasetError, match=r"line 1"):
            read_schema_following_jsonl(path)
