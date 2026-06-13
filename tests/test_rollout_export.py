"""Tests for rollout export helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.rl.export import (
    append_rollout_jsonl,
    export_batch_rollouts,
    read_rollout_json,
    read_rollouts_jsonl,
    write_rollout_json,
    write_rollouts_jsonl,
)
from pycodeagent.rl.slime_rollout import SlimeRolloutRecord, trajectory_to_slime_rollout
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.trajectory.schema import (
    Message,
    Role,
    RunStatus,
    ToolCall,
    ToolResult,
    Trajectory,
    VerifyResult,
)


_TEST_NAMESPACE = "rollout_export"


def _get_unique_test_dir() -> Path:
    """Get a unique test directory."""
    return make_unique_test_dir(_TEST_NAMESPACE)


def _setup_test_dir() -> Path:
    """Create a unique test directory."""
    return _get_unique_test_dir()


def _cleanup_test_dir(path: Path) -> None:
    """Clean up a test directory."""
    cleanup_test_path(path)


def make_rollout(
    *,
    task_id: str = "task_001",
    tool_profile_id: str = "base",
    reward: float = 1.0,
    status: str = "completed",
    verifier_passed: bool = True,
    verifier_score: float = 1.0,
) -> SlimeRolloutRecord:
    """Helper to create a minimal rollout record."""
    return SlimeRolloutRecord(
        task_id=task_id,
        tool_profile_id=tool_profile_id,
        reward=reward,
        status=status,
        verifier_passed=verifier_passed,
        verifier_score=verifier_score,
        text="Test text.",
        character_mask=[0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        spans=[{"start": 0, "end": 10, "trainable": False, "kind": "system"}],
        segments=[{"kind": "system", "text": "Test text.", "trainable": False, "metadata": {}}],
        trainable_char_count=0,
        total_char_count=10,
        metadata={},
    )


def make_full_rollout() -> SlimeRolloutRecord:
    """Helper to create a full rollout from a trajectory."""
    traj = Trajectory(
        task_id="task_full",
        repo="examples/buggy_calc",
        tool_profile_id="schema_v1",
        reward=0.8,
        status=RunStatus.COMPLETED,
        verifier=VerifyResult(passed=True, score=0.8),
    )

    traj.add_system("You are a coding agent.")
    traj.add_user("Fix the division bug.")

    call = ToolCall(
        id="call_001",
        name="read_file",
        arguments={"path": "src/main.py"},
        canonical_name="read_file",
    )
    traj.add_assistant("I'll read the file.", tool_calls=[call])

    traj.add_tool_observation(
        call=call,
        result=ToolResult(ok=True, content="def divide(a, b):\n    return a * b"),
    )

    traj.add_assistant("Fixed the bug.")

    return trajectory_to_slime_rollout(traj)


class TestWriteRolloutJson:
    """Tests for write_rollout_json."""

    def test_writes_file(self):
        """Should create a JSON file."""
        output_dir = _setup_test_dir()
        try:
            path = output_dir / "rollout.json"
            rollout = make_rollout()
            write_rollout_json(path, rollout)
            assert path.exists()
        finally:
            _cleanup_test_dir(output_dir)

    def test_valid_json(self):
        """Should write valid JSON."""
        output_dir = _setup_test_dir()
        try:
            path = output_dir / "rollout.json"
            rollout = make_rollout()
            write_rollout_json(path, rollout)

            data = json.loads(path.read_text())
            assert isinstance(data, dict)
        finally:
            _cleanup_test_dir(output_dir)

    def test_contains_expected_keys(self):
        """Should contain all expected keys."""
        output_dir = _setup_test_dir()
        try:
            path = output_dir / "rollout.json"
            rollout = make_rollout()
            write_rollout_json(path, rollout)

            data = json.loads(path.read_text())
            expected_keys = {
                "task_id",
                "tool_profile_id",
                "reward",
                "status",
                "verifier_passed",
                "verifier_score",
                "text",
                "character_mask",
                "spans",
                "segments",
                "trainable_char_count",
                "total_char_count",
                "metadata",
            }
            assert expected_keys.issubset(data.keys())
        finally:
            _cleanup_test_dir(output_dir)

    def test_creates_parent_dir(self):
        """Should create parent directory if needed."""
        output_dir = _get_unique_test_dir()
        try:
            path = output_dir / "subdir" / "rollout.json"
            rollout = make_rollout()
            write_rollout_json(path, rollout)
            assert path.exists()
        finally:
            _cleanup_test_dir(output_dir)


class TestReadRolloutJson:
    """Tests for read_rollout_json."""

    def test_reads_file(self):
        """Should read a JSON file."""
        output_dir = _setup_test_dir()
        try:
            path = output_dir / "rollout.json"
            rollout = make_rollout()
            write_rollout_json(path, rollout)

            data = read_rollout_json(path)
            assert isinstance(data, dict)
        finally:
            _cleanup_test_dir(output_dir)

    def test_roundtrip(self):
        """Write then read should preserve data."""
        output_dir = _setup_test_dir()
        try:
            path = output_dir / "rollout.json"
            original = make_full_rollout()
            write_rollout_json(path, original)

            data = read_rollout_json(path)
            assert data["task_id"] == original.task_id
            assert data["reward"] == original.reward
            assert data["text"] == original.text
        finally:
            _cleanup_test_dir(output_dir)


class TestWriteRolloutsJsonl:
    """Tests for write_rollouts_jsonl."""

    def test_writes_file(self):
        """Should create a JSONL file."""
        output_dir = _setup_test_dir()
        try:
            path = output_dir / "rollouts.jsonl"
            rollouts = [make_rollout()]
            write_rollouts_jsonl(path, rollouts)
            assert path.exists()
        finally:
            _cleanup_test_dir(output_dir)

    def test_line_count(self):
        """Should have one line per record."""
        output_dir = _setup_test_dir()
        try:
            path = output_dir / "rollouts.jsonl"
            rollouts = [make_rollout(task_id=f"task_{i}") for i in range(5)]
            write_rollouts_jsonl(path, rollouts)

            lines = path.read_text().strip().split("\n")
            assert len(lines) == 5
        finally:
            _cleanup_test_dir(output_dir)

    def test_each_line_valid_json(self):
        """Each line should be valid JSON."""
        output_dir = _setup_test_dir()
        try:
            path = output_dir / "rollouts.jsonl"
            rollouts = [make_rollout(task_id=f"task_{i}") for i in range(3)]
            write_rollouts_jsonl(path, rollouts)

            for line in path.read_text().strip().split("\n"):
                data = json.loads(line)
                assert isinstance(data, dict)
                assert "task_id" in data
        finally:
            _cleanup_test_dir(output_dir)

    def test_empty_list(self):
        """Empty list should write empty file."""
        output_dir = _setup_test_dir()
        try:
            path = output_dir / "rollouts.jsonl"
            write_rollouts_jsonl(path, [])
            content = path.read_text()
            assert content == "\n"
        finally:
            _cleanup_test_dir(output_dir)


class TestReadRolloutsJsonl:
    """Tests for read_rollouts_jsonl."""

    def test_reads_file(self):
        """Should read a JSONL file."""
        output_dir = _setup_test_dir()
        try:
            path = output_dir / "rollouts.jsonl"
            rollouts = [make_rollout(task_id=f"task_{i}") for i in range(3)]
            write_rollouts_jsonl(path, rollouts)

            records = read_rollouts_jsonl(path)
            assert len(records) == 3
        finally:
            _cleanup_test_dir(output_dir)

    def test_roundtrip(self):
        """Write then read should preserve data."""
        output_dir = _setup_test_dir()
        try:
            path = output_dir / "rollouts.jsonl"
            originals = [
                make_rollout(task_id="t1", reward=0.5),
                make_rollout(task_id="t2", reward=1.0),
            ]
            write_rollouts_jsonl(path, originals)

            records = read_rollouts_jsonl(path)
            assert records[0]["task_id"] == "t1"
            assert records[0]["reward"] == 0.5
            assert records[1]["task_id"] == "t2"
            assert records[1]["reward"] == 1.0
        finally:
            _cleanup_test_dir(output_dir)

    def test_empty_file(self):
        """Empty file should return empty list."""
        output_dir = _setup_test_dir()
        try:
            path = output_dir / "rollouts.jsonl"
            path.write_text("")
            records = read_rollouts_jsonl(path)
            assert records == []
        finally:
            _cleanup_test_dir(output_dir)


class TestAppendRolloutJsonl:
    """Tests for append_rollout_jsonl."""

    def test_appends_to_existing(self):
        """Should append to existing file."""
        output_dir = _setup_test_dir()
        try:
            path = output_dir / "rollouts.jsonl"
            rollouts = [make_rollout(task_id="t1")]
            write_rollouts_jsonl(path, rollouts)

            append_rollout_jsonl(path, make_rollout(task_id="t2"))

            records = read_rollouts_jsonl(path)
            assert len(records) == 2
            assert records[0]["task_id"] == "t1"
            assert records[1]["task_id"] == "t2"
        finally:
            _cleanup_test_dir(output_dir)

    def test_creates_if_not_exists(self):
        """Should create file if it doesn't exist."""
        output_dir = _setup_test_dir()
        try:
            path = output_dir / "rollouts.jsonl"
            append_rollout_jsonl(path, make_rollout(task_id="t1"))

            records = read_rollouts_jsonl(path)
            assert len(records) == 1
        finally:
            _cleanup_test_dir(output_dir)


class TestExportBatchRollouts:
    """Tests for export_batch_rollouts."""

    def test_creates_jsonl(self):
        """Should create rollouts.jsonl."""
        output_dir = _setup_test_dir()
        try:
            rollouts = [make_rollout() for _ in range(3)]
            jsonl_path = export_batch_rollouts(output_dir, rollouts)
            assert jsonl_path.exists()
            assert jsonl_path.name == "rollouts.jsonl"
        finally:
            _cleanup_test_dir(output_dir)

    def test_creates_summary(self):
        """Should create rollout_summary.json."""
        output_dir = _setup_test_dir()
        try:
            rollouts = [
                make_rollout(reward=0.5, verifier_passed=False),
                make_rollout(reward=1.0, verifier_passed=True),
            ]
            export_batch_rollouts(output_dir, rollouts)

            summary_path = output_dir / "rollout_summary.json"
            assert summary_path.exists()

            summary = json.loads(summary_path.read_text())
            assert summary["total_count"] == 2
            assert summary["passed_count"] == 1
        finally:
            _cleanup_test_dir(output_dir)

    def test_summary_counts(self):
        """Summary should have correct counts."""
        output_dir = _setup_test_dir()
        try:
            rollouts = [
                make_rollout(reward=1.0, status="completed", verifier_passed=True),
                make_rollout(reward=0.0, status="error", verifier_passed=False),
                make_rollout(reward=0.8, status="completed", verifier_passed=True),
            ]
            export_batch_rollouts(output_dir, rollouts)

            summary = json.loads((output_dir / "rollout_summary.json").read_text())
            assert summary["total_count"] == 3
            assert summary["completed_count"] == 2
            assert summary["passed_count"] == 2
            assert summary["total_reward"] == pytest.approx(1.8)
            assert summary["avg_reward"] == pytest.approx(0.6)
        finally:
            _cleanup_test_dir(output_dir)

    def test_empty_batch(self):
        """Empty batch should produce valid output."""
        output_dir = _setup_test_dir()
        try:
            jsonl_path = export_batch_rollouts(output_dir, [])
            assert jsonl_path.exists()

            records = read_rollouts_jsonl(jsonl_path)
            assert records == []

            summary = json.loads((output_dir / "rollout_summary.json").read_text())
            assert summary["total_count"] == 0
            assert summary["avg_reward"] == 0.0
        finally:
            _cleanup_test_dir(output_dir)


class TestEndToEndExport:
    """End-to-end tests: trajectory -> rollout -> export -> load."""

    def test_full_export_pipeline(self):
        """Full pipeline with realistic trajectory."""
        output_dir = _setup_test_dir()
        try:
            # Create rollouts from trajectories
            rollouts = []
            for i in range(3):
                traj = Trajectory(
                    task_id=f"task_{i}",
                    repo="examples/repo",
                    tool_profile_id="base",
                    reward=1.0 - i * 0.2,
                    status=RunStatus.COMPLETED,
                    verifier=VerifyResult(passed=(i == 0), score=1.0 - i * 0.2),
                )
                traj.add_system("You are an agent.")
                traj.add_user(f"Task {i}.")
                traj.add_assistant(f"Response {i}.")

                rollouts.append(trajectory_to_slime_rollout(traj))

            # Export
            jsonl_path = export_batch_rollouts(output_dir, rollouts)

            # Load and verify
            records = read_rollouts_jsonl(jsonl_path)
            assert len(records) == 3

            for i, record in enumerate(records):
                assert record["task_id"] == f"task_{i}"
                assert record["reward"] == pytest.approx(1.0 - i * 0.2)
                assert "text" in record
                assert "character_mask" in record
                assert len(record["character_mask"]) == len(record["text"])

        finally:
            _cleanup_test_dir(output_dir)

    def test_export_with_tool_calls(self):
        """Export with trajectory containing tool calls."""
        output_dir = _setup_test_dir()
        try:
            rollout = make_full_rollout()

            # Write and read back
            path = output_dir / "rollout.json"
            write_rollout_json(path, rollout)

            data = read_rollout_json(path)

            # Verify structure
            assert data["task_id"] == "task_full"
            assert len(data["segments"]) > 0
            assert len(data["character_mask"]) == len(data["text"])

            # Verify segments include tool calls
            kinds = {seg["kind"] for seg in data["segments"]}
            assert "assistant" in kinds
            assert "assistant_tool_call" in kinds

        finally:
            _cleanup_test_dir(output_dir)


class TestDeterministicExport:
    """Tests for deterministic export."""

    def test_same_rollout_same_json(self):
        """Same rollout should produce identical JSON."""
        rollout = make_full_rollout()
        json1 = rollout.model_dump_json()
        json2 = rollout.model_dump_json()
        assert json1 == json2

    def test_jsonl_order_preserved(self):
        """JSONL should preserve record order."""
        output_dir = _setup_test_dir()
        try:
            rollouts = [
                make_rollout(task_id="a"),
                make_rollout(task_id="b"),
                make_rollout(task_id="c"),
            ]
            path = output_dir / "rollouts.jsonl"
            write_rollouts_jsonl(path, rollouts)

            records = read_rollouts_jsonl(path)
            assert records[0]["task_id"] == "a"
            assert records[1]["task_id"] == "b"
            assert records[2]["task_id"] == "c"
        finally:
            _cleanup_test_dir(output_dir)
