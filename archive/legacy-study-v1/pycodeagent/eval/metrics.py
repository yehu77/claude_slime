"""Metrics aggregation for batch evaluation.

Computes metrics from RunSummary objects, not by scraping logs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pycodeagent.eval.batch_runner import RunSummary


def compute_pass_at_1(summaries: list[Any]) -> float:
    """Compute pass@1: proportion of runs that passed verification.

    Args:
        summaries: List of run summaries.

    Returns:
        Pass rate as a float in [0, 1].
    """
    if not summaries:
        return 0.0

    passed_count = sum(1 for s in summaries if s.passed)
    return passed_count / len(summaries)


def compute_avg_reward(summaries: list[Any]) -> float:
    """Compute average reward across all runs.

    Args:
        summaries: List of run summaries.

    Returns:
        Mean reward.
    """
    if not summaries:
        return 0.0

    total = sum(s.reward for s in summaries)
    return total / len(summaries)


def compute_avg_turns(summaries: list[Any]) -> float:
    """Compute average number of assistant turns per run.

    Args:
        summaries: List of run summaries.

    Returns:
        Mean turn count.
    """
    if not summaries:
        return 0.0

    total = sum(s.turns for s in summaries)
    return total / len(summaries)


def compute_avg_tool_calls(summaries: list[Any]) -> float:
    """Compute average number of tool calls per run.

    Args:
        summaries: List of run summaries.

    Returns:
        Mean tool call count.
    """
    if not summaries:
        return 0.0

    total = sum(s.tool_calls for s in summaries)
    return total / len(summaries)


def compute_tool_call_parse_error_rate(summaries: list[Any]) -> float:
    """Compute rate of runs with tool call parse errors.

    A run has a parse error if metadata["parse_errors"] > 0.

    Args:
        summaries: List of run summaries.

    Returns:
        Parse error rate as a float in [0, 1].
    """
    if not summaries:
        return 0.0

    error_count = sum(1 for s in summaries if s.metadata.get("parse_errors", 0) > 0)
    return error_count / len(summaries)


def compute_invalid_schema_call_rate(summaries: list[Any]) -> float:
    """Compute rate of tool calls that failed schema/argument validation.

    This counts only errors with error_type in:
    - "argument_mapping" - ToolArgumentError during exposed-to-canonical mapping
    - "argument_mapping_unexpected" - Other mapping exceptions

    Args:
        summaries: List of run summaries.

    Returns:
        Invalid schema call rate as a float in [0, 1].
    """
    total_tool_calls = sum(s.tool_calls for s in summaries)
    if total_tool_calls == 0:
        return 0.0

    total_schema_errors = sum(s.metadata.get("schema_errors", 0) for s in summaries)
    return total_schema_errors / total_tool_calls


def compute_patch_apply_success_rate(summaries: list[Any]) -> float:
    """Compute rate of runs where apply_patch tool succeeded.

    A "successful patch apply" means:
    - apply_patch tool was called (canonical_name == "apply_patch")
    - The tool returned ok=True

    If apply_patch was never called, that run does not count toward success.

    Args:
        summaries: List of run summaries.

    Returns:
        Patch apply success rate as a float in [0, 1].
    """
    if not summaries:
        return 0.0

    # Count runs where apply_patch was attempted and succeeded
    success_count = sum(
        1 for s in summaries
        if s.metadata.get("apply_patch_success", False)
    )
    return success_count / len(summaries)


def compute_metrics(summaries: list[Any]) -> dict[str, float]:
    """Compute all metrics from run summaries.

    Args:
        summaries: List of run summaries.

    Returns:
        Dict mapping metric names to values.
    """
    return {
        "pass_at_1": compute_pass_at_1(summaries),
        "avg_reward": compute_avg_reward(summaries),
        "avg_turns": compute_avg_turns(summaries),
        "avg_tool_calls": compute_avg_tool_calls(summaries),
        "tool_call_parse_error_rate": compute_tool_call_parse_error_rate(summaries),
        "invalid_schema_call_rate": compute_invalid_schema_call_rate(summaries),
        "patch_apply_success_rate": compute_patch_apply_success_rate(summaries),
    }
