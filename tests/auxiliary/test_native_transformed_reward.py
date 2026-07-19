"""Tests for native-transformed RL reward evaluation."""

from __future__ import annotations

import json

from pycodeagent.auxiliary.claude_api.sft import (
    ClaudeApiSFTMessage,
    ClaudeApiSFTSample,
    ClaudeApiSFTTargetBlock,
    ClaudeApiSFTToolCallTarget,
)
from pycodeagent.auxiliary.native_transformed.reward import (
    evaluate_native_transformed_rl_completion,
)
from pycodeagent.auxiliary.native_transformed.rl_dataset import (
    build_native_transformed_rl_prompt_sample,
)


def _tool_text(name: str, arguments: dict) -> str:
    return (
        "<|tool|>\n"
        + json.dumps(
            {"id": "predicted", "name": name, "arguments": arguments},
            sort_keys=True,
        )
        + "\n<|end|>\n"
    )


def _make_rl_sample(*, tool_specs: list[dict] | None = None):
    sample = ClaudeApiSFTSample(
        sample_id="sample_1",
        sample_type="claude_api_sft",
        source_type="claude_api_trace",
        task_id="task_1",
        tool_profile_id="profile_1",
        messages=[
            ClaudeApiSFTMessage(role="system", content="You are a coding agent."),
            ClaudeApiSFTMessage(role="user", content="Inspect README.md."),
        ],
        tool_specs=tool_specs
        if tool_specs is not None
        else [
            {
                "name": "InspectFile",
                "description": "Read a file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            }
        ],
        target_blocks=[
            ClaudeApiSFTTargetBlock(
                block_type="tool_use",
                tool_call=ClaudeApiSFTToolCallTarget(
                    call_id="call_1",
                    name="InspectFile",
                    arguments={"file_path": "README.md"},
                ),
            )
        ],
        loss_mask_policy="assistant_selected_blocks_only",
        metadata={"transformation_mode": "name_only"},
    )
    rl_sample = build_native_transformed_rl_prompt_sample(sample)
    assert rl_sample is not None
    return rl_sample


class TestNativeTransformedReward:
    def test_exact_tool_call_match_gets_full_reward(self) -> None:
        sample = _make_rl_sample()

        case = evaluate_native_transformed_rl_completion(
            sample,
            _tool_text("InspectFile", {"file_path": "README.md"}),
        )

        assert case.reward == 1.0
        assert case.parse_ok is True
        assert case.tool_name_ok is True
        assert case.arguments_exact_match is True
        assert case.schema_status == "valid"
        assert case.error_code is None

    def test_tool_name_mismatch_keeps_parse_but_loses_name_reward(self) -> None:
        sample = _make_rl_sample()

        case = evaluate_native_transformed_rl_completion(
            sample,
            _tool_text("Read", {"file_path": "README.md"}),
        )

        assert case.parse_ok is True
        assert case.tool_name_ok is False
        assert case.arguments_exact_match is True
        assert case.reward < 1.0
        assert case.error_code == "tool_name_mismatch"

    def test_arguments_mismatch_loses_argument_reward(self) -> None:
        sample = _make_rl_sample()

        case = evaluate_native_transformed_rl_completion(
            sample,
            _tool_text("InspectFile", {"file_path": "OTHER.md"}),
        )

        assert case.parse_ok is True
        assert case.tool_name_ok is True
        assert case.arguments_exact_match is False
        assert case.schema_status == "valid"
        assert case.error_code == "arguments_mismatch"

    def test_missing_tool_block_gets_zero_reward(self) -> None:
        sample = _make_rl_sample()

        case = evaluate_native_transformed_rl_completion(sample, "no tool block")

        assert case.reward == 0.0
        assert case.parse_ok is False
        assert case.error_code == "missing_tool_call_block"

    def test_invalid_json_gets_zero_reward(self) -> None:
        sample = _make_rl_sample()

        case = evaluate_native_transformed_rl_completion(
            sample,
            "<|tool|>\n{not-json}\n<|end|>\n",
        )

        assert case.reward == 0.0
        assert case.parse_ok is False
        assert case.error_code == "invalid_json"

    def test_missing_schema_does_not_block_exact_match_reward(self) -> None:
        sample = _make_rl_sample(
            tool_specs=[{"name": "InspectFile", "description": "Read a file."}]
        )

        case = evaluate_native_transformed_rl_completion(
            sample,
            _tool_text("InspectFile", {"file_path": "README.md"}),
        )

        assert case.reward == 1.0
        assert case.schema_status == "not_applicable"
        assert "schema" not in case.reward_breakdown

    def test_schema_invalid_is_reported(self) -> None:
        sample = _make_rl_sample()

        case = evaluate_native_transformed_rl_completion(
            sample,
            _tool_text("InspectFile", {"file_path": 123}),
        )

        assert case.parse_ok is True
        assert case.schema_status == "invalid"
        assert case.error_code == "schema_invalid"
        assert case.reward < 1.0
