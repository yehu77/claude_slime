"""RC-041 gates for the unique pre-tokenization sample contract."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pycodeagent.auxiliary.claude_api.sft_training import (
    ClaudeApiSFTPreparedSample,
)
from pycodeagent.rl.prepared_sample import (
    PreparedSample,
    read_prepared_samples,
    write_prepared_samples,
)
from pycodeagent.rl.sample_builder import TrainingSample
from pycodeagent.rl.schema_following_training import SchemaFollowingPreparedSample


pytestmark = pytest.mark.mainline


def _valid_payload() -> dict[str, object]:
    context = "<user>\nRead main.py\n</user>\n"
    target = (
        '<|tool|>\n{"arguments":{"path":"main.py"},"id":"call_1",'
        '"name":"inspect_file"}\n<|end|>\n'
    )
    text = context + target
    return {
        "schema_version": 1,
        "sample_id": "sample-1",
        "sample_type": "schema_following",
        "source_type": "runtime_observed",
        "split": "train",
        "task_id": "task-1",
        "tool_profile_id": "mutated-v1",
        "mutation_category": "rename_tool",
        "loss_mask_policy": "assistant_tool_call_only",
        "text": text,
        "segments": [
            {"kind": "user", "text": context, "trainable": False, "metadata": {}},
            {
                "kind": "assistant_tool_call",
                "text": target,
                "trainable": True,
                "metadata": {
                    "tool_name": "inspect_file",
                    "canonical_name": "read_file",
                },
            },
        ],
        "character_mask": [0] * len(context) + [1] * len(target),
        "spans": [
            {"start": 0, "end": len(context), "trainable": False},
            {
                "start": len(context),
                "end": len(text),
                "trainable": True,
            },
        ],
        "trainable_char_count": len(target),
        "metadata": {
            "raw_trace_id": "trace-1",
            "canonical_intent": {"tool": "read_file"},
            "target_tool_call": {"name": "inspect_file"},
        },
    }


def test_all_prepared_sample_names_are_one_contract() -> None:
    assert TrainingSample is PreparedSample
    assert SchemaFollowingPreparedSample is PreparedSample
    assert ClaudeApiSFTPreparedSample is PreparedSample


def test_round_trip_preserves_source_evidence(tmp_path) -> None:
    sample = PreparedSample.model_validate(_valid_payload())
    output = tmp_path / "samples.jsonl"

    write_prepared_samples([sample], output)
    loaded = read_prepared_samples(output)

    assert loaded == [sample]
    assert loaded[0].metadata["raw_trace_id"] == "trace-1"
    assert loaded[0].metadata["canonical_intent"]["tool"] == "read_file"
    assert loaded[0].metadata["target_tool_call"]["name"] == "inspect_file"


def test_missing_required_identity_fails_loudly() -> None:
    payload = _valid_payload()
    del payload["task_id"]

    with pytest.raises(ValidationError, match="task_id"):
        PreparedSample.model_validate(payload)


def test_unknown_schema_version_fails_loudly() -> None:
    payload = _valid_payload()
    payload["schema_version"] = 2

    with pytest.raises(ValidationError, match="schema_version"):
        PreparedSample.model_validate(payload)


def test_mask_misalignment_fails_loudly() -> None:
    payload = _valid_payload()
    payload["character_mask"] = payload["character_mask"][:-1]

    with pytest.raises(ValidationError, match="character_mask length"):
        PreparedSample.model_validate(payload)


def test_non_tool_call_trainable_segment_fails_loudly() -> None:
    payload = _valid_payload()
    payload["segments"][0]["trainable"] = True
    context_length = len(payload["segments"][0]["text"])
    payload["spans"][0]["trainable"] = True
    payload["character_mask"][:context_length] = [1] * context_length
    payload["trainable_char_count"] += context_length

    with pytest.raises(ValidationError, match="only permits assistant_tool_call"):
        PreparedSample.model_validate(payload)


def test_jsonl_reader_reports_line_for_unknown_version(tmp_path) -> None:
    payload = _valid_payload()
    payload["schema_version"] = 99
    path = tmp_path / "samples.jsonl"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"(?s)line 1.*schema_version"):
        read_prepared_samples(path)
