"""Tests for metrics aggregation."""

from __future__ import annotations

import pytest

from pycodeagent.eval.batch_runner import RunSummary
from pycodeagent.eval.metrics import (
    compute_avg_reward,
    compute_avg_tool_calls,
    compute_avg_turns,
    compute_invalid_schema_call_rate,
    compute_metrics,
    compute_pass_at_1,
    compute_patch_apply_success_rate,
    compute_tool_call_parse_error_rate,
)


def make_summary(
    *,
    passed: bool = True,
    reward: float = 1.0,
    turns: int = 5,
    tool_calls: int = 10,
    status: str = "completed",
    failure_reason: str = "",
    has_patch: bool = True,
    parse_errors: int = 0,
    tool_errors: int = 0,
    schema_errors: int = 0,
    apply_patch_attempted: bool = False,
    apply_patch_success: bool = False,
) -> RunSummary:
    """Helper to create a RunSummary with sensible defaults."""
    return RunSummary(
        task_id="test_task",
        profile_id="base",
        status=status,
        reward=reward,
        passed=passed,
        turns=turns,
        tool_calls=tool_calls,
        output_dir="runs/test",
        failure_reason=failure_reason,
        metadata={
            "has_patch": has_patch,
            "parse_errors": parse_errors,
            "tool_errors": tool_errors,
            "schema_errors": schema_errors,
            "apply_patch_attempted": apply_patch_attempted,
            "apply_patch_success": apply_patch_success,
        },
    )


class TestPassAt1:
    """Tests for pass@1 metric."""

    def test_empty_summaries(self):
        """Empty list should return 0.0."""
        assert compute_pass_at_1([]) == 0.0

    def test_all_passed(self):
        """All passed should return 1.0."""
        summaries = [make_summary(passed=True) for _ in range(10)]
        assert compute_pass_at_1(summaries) == 1.0

    def test_all_failed(self):
        """All failed should return 0.0."""
        summaries = [make_summary(passed=False) for _ in range(10)]
        assert compute_pass_at_1(summaries) == 0.0

    def test_half_passed(self):
        """Half passed should return 0.5."""
        summaries = [
            make_summary(passed=True),
            make_summary(passed=False),
        ]
        assert compute_pass_at_1(summaries) == 0.5

    def test_single_passed(self):
        """Single passed run should return 1.0."""
        summaries = [make_summary(passed=True)]
        assert compute_pass_at_1(summaries) == 1.0


class TestAvgReward:
    """Tests for average reward metric."""

    def test_empty_summaries(self):
        """Empty list should return 0.0."""
        assert compute_avg_reward([]) == 0.0

    def test_uniform_rewards(self):
        """Uniform rewards should return that value."""
        summaries = [make_summary(reward=0.8) for _ in range(5)]
        assert compute_avg_reward(summaries) == 0.8

    def test_mixed_rewards(self):
        """Should compute correct average."""
        summaries = [
            make_summary(reward=1.0),
            make_summary(reward=0.5),
            make_summary(reward=0.0),
        ]
        assert compute_avg_reward(summaries) == pytest.approx(0.5)


class TestAvgTurns:
    """Tests for average turns metric."""

    def test_empty_summaries(self):
        """Empty list should return 0.0."""
        assert compute_avg_turns([]) == 0.0

    def test_uniform_turns(self):
        """Uniform turns should return that value."""
        summaries = [make_summary(turns=8) for _ in range(5)]
        assert compute_avg_turns(summaries) == 8

    def test_mixed_turns(self):
        """Should compute correct average."""
        summaries = [
            make_summary(turns=3),
            make_summary(turns=6),
            make_summary(turns=9),
        ]
        assert compute_avg_turns(summaries) == 6.0


class TestAvgToolCalls:
    """Tests for average tool calls metric."""

    def test_empty_summaries(self):
        """Empty list should return 0.0."""
        assert compute_avg_tool_calls([]) == 0.0

    def test_uniform_tool_calls(self):
        """Uniform tool calls should return that value."""
        summaries = [make_summary(tool_calls=15) for _ in range(5)]
        assert compute_avg_tool_calls(summaries) == 15

    def test_mixed_tool_calls(self):
        """Should compute correct average."""
        summaries = [
            make_summary(tool_calls=10),
            make_summary(tool_calls=20),
        ]
        assert compute_avg_tool_calls(summaries) == 15.0


class TestToolCallParseErrorRate:
    """Tests for tool call parse error rate."""

    def test_empty_summaries(self):
        """Empty list should return 0.0."""
        assert compute_tool_call_parse_error_rate([]) == 0.0

    def test_no_parse_errors(self):
        """No parse errors should return 0.0."""
        summaries = [make_summary() for _ in range(5)]
        assert compute_tool_call_parse_error_rate(summaries) == 0.0

    def test_parse_errors_in_metadata(self):
        """Should count runs with parse_errors > 0 in metadata."""
        summaries = [
            make_summary(parse_errors=1),
            make_summary(parse_errors=0),
            make_summary(parse_errors=3),
        ]
        # 2 out of 3 have parse_errors > 0
        assert compute_tool_call_parse_error_rate(summaries) == pytest.approx(2 / 3)

    def test_all_have_parse_errors(self):
        """All with parse errors should return 1.0."""
        summaries = [make_summary(parse_errors=1) for _ in range(5)]
        assert compute_tool_call_parse_error_rate(summaries) == 1.0


class TestInvalidSchemaCallRate:
    """Tests for invalid schema call rate."""

    def test_empty_summaries(self):
        """Empty list should return 0.0."""
        assert compute_invalid_schema_call_rate([]) == 0.0

    def test_no_tool_calls(self):
        """No tool calls should return 0.0."""
        summaries = [make_summary(tool_calls=0) for _ in range(5)]
        assert compute_invalid_schema_call_rate(summaries) == 0.0

    def test_no_schema_errors(self):
        """No schema errors should return 0.0."""
        summaries = [
            make_summary(tool_calls=10, schema_errors=0),
            make_summary(tool_calls=15, schema_errors=0),
        ]
        assert compute_invalid_schema_call_rate(summaries) == 0.0

    def test_some_schema_errors(self):
        """Should compute schema error ratio correctly."""
        summaries = [
            make_summary(tool_calls=10, schema_errors=2),
            make_summary(tool_calls=10, schema_errors=3),
        ]
        # 5 schema errors out of 20 total tool calls
        assert compute_invalid_schema_call_rate(summaries) == pytest.approx(5 / 20)

    def test_all_schema_errors(self):
        """All tool calls being schema errors should return 1.0."""
        summaries = [
            make_summary(tool_calls=5, schema_errors=5),
        ]
        assert compute_invalid_schema_call_rate(summaries) == 1.0

    def test_ignores_other_tool_errors(self):
        """Should only count schema_errors, not general tool_errors."""
        summaries = [
            make_summary(tool_calls=10, tool_errors=5, schema_errors=0),
        ]
        # No schema errors even though there are tool errors
        assert compute_invalid_schema_call_rate(summaries) == 0.0


class TestPatchApplySuccessRate:
    """Tests for patch apply success rate."""

    def test_empty_summaries(self):
        """Empty list should return 0.0."""
        assert compute_patch_apply_success_rate([]) == 0.0

    def test_all_apply_patch_success(self):
        """All with apply_patch success should return 1.0."""
        summaries = [make_summary(apply_patch_attempted=True, apply_patch_success=True) for _ in range(5)]
        assert compute_patch_apply_success_rate(summaries) == 1.0

    def test_none_applied_patch(self):
        """None attempted apply_patch should return 0.0."""
        summaries = [make_summary(apply_patch_attempted=False) for _ in range(5)]
        assert compute_patch_apply_success_rate(summaries) == 0.0

    def test_half_apply_patch_success(self):
        """Half with apply_patch success should return 0.5."""
        summaries = [
            make_summary(apply_patch_attempted=True, apply_patch_success=True),
            make_summary(apply_patch_attempted=False, apply_patch_success=False),
        ]
        assert compute_patch_apply_success_rate(summaries) == 0.5

    def test_attempted_but_failed(self):
        """Attempted but failed apply_patch should not count as success."""
        summaries = [
            make_summary(apply_patch_attempted=True, apply_patch_success=False),
        ]
        assert compute_patch_apply_success_rate(summaries) == 0.0

    def test_has_patch_ignored(self):
        """has_patch metadata should not affect the metric."""
        summaries = [
            make_summary(has_patch=True, apply_patch_attempted=False, apply_patch_success=False),
        ]
        # No apply_patch was called, so no success
        assert compute_patch_apply_success_rate(summaries) == 0.0


class TestComputeMetrics:
    """Tests for compute_metrics aggregation."""

    def test_empty_summaries(self):
        """Empty list should return all zeros."""
        metrics = compute_metrics([])
        assert metrics["pass_at_1"] == 0.0
        assert metrics["avg_reward"] == 0.0
        assert metrics["avg_turns"] == 0.0
        assert metrics["avg_tool_calls"] == 0.0
        assert metrics["tool_call_parse_error_rate"] == 0.0
        assert metrics["invalid_schema_call_rate"] == 0.0
        assert metrics["patch_apply_success_rate"] == 0.0

    def test_all_metrics_computed(self):
        """Should compute all metrics."""
        summaries = [
            make_summary(passed=True, reward=1.0, turns=5, tool_calls=10),
            make_summary(passed=False, reward=0.0, turns=3, tool_calls=8),
        ]
        metrics = compute_metrics(summaries)

        assert "pass_at_1" in metrics
        assert "avg_reward" in metrics
        assert "avg_turns" in metrics
        assert "avg_tool_calls" in metrics
        assert "tool_call_parse_error_rate" in metrics
        assert "invalid_schema_call_rate" in metrics
        assert "patch_apply_success_rate" in metrics

    def test_metric_values(self):
        """Should have correct metric values."""
        summaries = [
            make_summary(passed=True, reward=1.0, turns=6, tool_calls=10),
            make_summary(passed=True, reward=1.0, turns=4, tool_calls=10),
        ]
        metrics = compute_metrics(summaries)

        assert metrics["pass_at_1"] == 1.0
        assert metrics["avg_reward"] == 1.0
        assert metrics["avg_turns"] == 5.0
        assert metrics["avg_tool_calls"] == 10.0
