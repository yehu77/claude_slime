"""Export helpers for rollout records.

Provides JSON and JSONL export/import for slime rollout records.
All outputs use JSON-friendly types and are deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pycodeagent.rl.slime_rollout import SlimeRolloutRecord


def write_rollout_json(
    path: str | Path,
    rollout: SlimeRolloutRecord,
    *,
    indent: int | None = 2,
) -> None:
    """Write a single rollout record to a JSON file.

    Args:
        path: Output file path
        rollout: The rollout record to write
        indent: JSON indentation (default 2, None for compact)
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        rollout.model_dump_json(indent=indent),
        encoding="utf-8",
    )


def read_rollout_json(path: str | Path) -> dict[str, Any]:
    """Read a rollout record from a JSON file.

    Args:
        path: Input file path

    Returns:
        Dict with rollout data
    """
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_rollouts_jsonl(
    path: str | Path,
    rollouts: list[SlimeRolloutRecord],
) -> None:
    """Write multiple rollout records to a JSONL file.

    Each record is written as a single JSON line.
    Output is deterministic and stable.

    Args:
        path: Output file path
        rollouts: List of rollout records to write
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    for rollout in rollouts:
        # Use compact JSON for JSONL (no indentation)
        line = rollout.model_dump_json()
        lines.append(line)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_rollouts_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read multiple rollout records from a JSONL file.

    Args:
        path: Input file path

    Returns:
        List of dicts with rollout data
    """
    path = Path(path)
    content = path.read_text(encoding="utf-8")

    if not content.strip():
        return []

    records = []
    for line in content.strip().split("\n"):
        if line.strip():
            records.append(json.loads(line))
    return records


def append_rollout_jsonl(
    path: str | Path,
    rollout: SlimeRolloutRecord,
) -> None:
    """Append a single rollout record to a JSONL file.

    Creates the file if it doesn't exist.

    Args:
        path: Output file path
        rollout: The rollout record to append
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    line = rollout.model_dump_json()
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def export_batch_rollouts(
    output_dir: str | Path,
    rollouts: list[SlimeRolloutRecord],
    *,
    filename: str = "rollouts.jsonl",
) -> Path:
    """Export a batch of rollouts to a directory.

    Writes rollouts.jsonl and a summary with counts.

    Args:
        output_dir: Output directory
        rollouts: List of rollout records
        filename: Output filename (default: rollouts.jsonl)

    Returns:
        Path to the written JSONL file
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write rollouts
    jsonl_path = output_dir / filename
    write_rollouts_jsonl(jsonl_path, rollouts)

    # Write summary
    summary = {
        "total_count": len(rollouts),
        "completed_count": sum(1 for r in rollouts if r.status == "completed"),
        "passed_count": sum(1 for r in rollouts if r.verifier_passed),
        "total_reward": sum(r.reward for r in rollouts),
        "avg_reward": sum(r.reward for r in rollouts) / len(rollouts) if rollouts else 0.0,
        "total_trainable_chars": sum(r.trainable_char_count for r in rollouts),
        "total_chars": sum(r.total_char_count for r in rollouts),
    }
    summary_path = output_dir / "rollout_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return jsonl_path
