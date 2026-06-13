"""Comparison table builders for experiment analysis.

Produces structured (dict-based) comparison tables from experiment runs.

Tables:
- Profile comparison: metrics grouped by profile_id or mode
- Seed comparison: metrics grouped by seed
- Category × profile table: cross-tabulation of task category and profile mode
- Error breakdown: error counts by type and group

All outputs are machine-readable (dicts/lists), suitable for further
processing or optional rendering.
"""

from __future__ import annotations

from typing import Any

from pycodeagent.eval.analysis import (
    RunRecord,
    compute_grouped_metrics,
    get_run_field,
)


def build_profile_comparison_table(
    runs: list[RunRecord],
    group_key: str = "mode",
) -> list[dict[str, Any]]:
    """Build a profile comparison table.

    Groups runs by the given key (default: "mode") and computes metrics
    per group.

    Args:
        runs: List of run records.
        group_key: Field to group by. Default "mode".

    Returns:
        List of dicts, each with the group key and all metrics.
        Sorted by group key.
    """
    groups: dict[str, list[RunRecord]] = {}
    for run in runs:
        key = str(get_run_field(run, group_key))
        groups.setdefault(key, []).append(run)

    result = []
    for key in sorted(groups.keys()):
        metrics = compute_grouped_metrics(groups[key])
        row = {group_key: key, **metrics}
        result.append(row)

    return result


def build_seed_comparison_table(
    runs: list[RunRecord],
) -> list[dict[str, Any]]:
    """Build a seed comparison table.

    Groups runs by seed and computes metrics per seed.

    Args:
        runs: List of run records.

    Returns:
        List of dicts, each with "seed" and all metrics.
        Sorted by seed.
    """
    groups: dict[str, list[RunRecord]] = {}
    for run in runs:
        key = str(run.seed)
        groups.setdefault(key, []).append(run)

    result = []
    for key in sorted(groups.keys()):
        metrics = compute_grouped_metrics(groups[key])
        row = {"seed": int(key), **metrics}
        result.append(row)

    return result


def build_category_profile_table(
    runs: list[RunRecord],
    profile_key: str = "mode",
) -> list[dict[str, Any]]:
    """Build a category × profile cross-tabulation table.

    For each (category, profile) combination, computes pass@1 and avg_reward.

    Args:
        runs: List of run records.
        profile_key: Field to use as profile dimension. Default "mode".

    Returns:
        List of dicts with category/profile columns plus grouped metrics.
        Sorted by (category, profile key).
    """
    groups: dict[tuple[str, str], list[RunRecord]] = {}
    for run in runs:
        category = run.category or "uncategorized"
        profile = str(get_run_field(run, profile_key))
        groups.setdefault((category, profile), []).append(run)

    result = []
    for (category, profile) in sorted(groups.keys()):
        metrics = compute_grouped_metrics(groups[(category, profile)])
        row = {
            "category": category,
            profile_key: profile,
            **metrics,
        }
        result.append(row)

    return result


def build_error_breakdown_table(
    runs: list[RunRecord],
    group_key: str = "mode",
) -> list[dict[str, Any]]:
    """Build an error breakdown table.

    For each group, counts errors by type.

    Error types:
    - parse_errors: runs with tool call parse errors
    - schema_errors: total schema/argument mapping errors
    - verifier_failed: runs that reached verification but did not pass
    - tool_errors: total tool execution errors
    - patch_failures: runs where apply_patch was attempted but failed

    Args:
        runs: List of run records.
        group_key: Field to group by. Default "mode".

    Returns:
        List of dicts with group key, count, and error counts/rates.
        Sorted by group key.
    """
    groups: dict[str, list[RunRecord]] = {}
    for run in runs:
        key = str(get_run_field(run, group_key))
        groups.setdefault(key, []).append(run)

    result = []
    for key in sorted(groups.keys()):
        group_runs = groups[key]
        n = len(group_runs)

        parse_error_count = sum(1 for r in group_runs if r.parse_errors > 0)
        total_schema_errors = sum(r.schema_errors for r in group_runs)
        total_tool_errors = sum(r.tool_errors for r in group_runs)
        verifier_failed_count = sum(1 for r in group_runs if r.verifier_failed)
        total_tool_calls = sum(r.tool_calls for r in group_runs)

        # Patch failures: attempted but not successful
        patch_failures = sum(
            1 for r in group_runs
            if r.apply_patch_attempted and not r.apply_patch_success
        )
        patch_attempts = sum(1 for r in group_runs if r.apply_patch_attempted)

        row = {
            group_key: key,
            "count": n,
            "parse_error_count": parse_error_count,
            "parse_error_rate": parse_error_count / n if n > 0 else 0.0,
            "schema_error_count": total_schema_errors,
            "schema_error_rate": total_schema_errors / total_tool_calls if total_tool_calls > 0 else 0.0,
            "verifier_failed_count": verifier_failed_count,
            "verifier_failed_rate": verifier_failed_count / n if n > 0 else 0.0,
            "tool_error_count": total_tool_errors,
            "tool_error_rate": total_tool_errors / total_tool_calls if total_tool_calls > 0 else 0.0,
            "patch_failure_count": patch_failures,
            "patch_failure_rate": patch_failures / patch_attempts if patch_attempts > 0 else 0.0,
        }
        result.append(row)

    return result


def table_to_markdown(
    table: list[dict[str, Any]],
    *,
    float_format: str = ".4f",
) -> str:
    """Convert a table (list of dicts) to a Markdown string.

    Args:
        table: List of row dicts.
        float_format: Format string for float values.

    Returns:
        Markdown-formatted table string.
    """
    if not table:
        return ""

    # Collect all keys in order of first appearance
    keys = []
    for row in table:
        for key in row:
            if key not in keys:
                keys.append(key)

    # Format values
    def fmt(v: Any) -> str:
        if isinstance(v, float):
            return f"{v:{float_format}}"
        return str(v)

    # Build header
    header = "| " + " | ".join(keys) + " |"
    separator = "| " + " | ".join("-" * len(k) for k in keys) + " |"

    # Build rows
    rows = []
    for row in table:
        cells = [fmt(row.get(k, "")) for k in keys]
        rows.append("| " + " | ".join(cells) + " |")

    return "\n".join([header, separator] + rows)


def table_to_csv(
    table: list[dict[str, Any]],
    *,
    float_format: str = ".6f",
) -> str:
    """Convert a table (list of dicts) to CSV string.

    Args:
        table: List of row dicts.
        float_format: Format string for float values.

    Returns:
        CSV-formatted string.
    """
    if not table:
        return ""

    import csv
    import io

    keys = []
    for row in table:
        for key in row:
            if key not in keys:
                keys.append(key)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=keys, extrasaction="ignore")
    writer.writeheader()

    for row in table:
        formatted = {}
        for k, v in row.items():
            if isinstance(v, float):
                formatted[k] = f"{v:{float_format}}"
            else:
                formatted[k] = v
        writer.writerow(formatted)

    return output.getvalue().strip()
