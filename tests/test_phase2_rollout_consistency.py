"""Phase-2 guardrail: trajectory -> sample -> rollout -> export consistency.

Tests that:
1. A real trajectory can become a training sample
2. The sample can become a rollout
3. Rollout export/import preserves core fields
4. Reward/status/verifier/trainable mask survive the whole path

This guards against changes to serializer, sample_builder, slime_rollout,
or export that would silently break the training data pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.rl.export import (
    export_batch_rollouts,
    read_rollout_json,
    read_rollouts_jsonl,
    write_rollout_json,
    write_rollouts_jsonl,
)
from pycodeagent.rl.sample_builder import TrainingSample, build_training_sample
from pycodeagent.rl.slime_rollout import (
    SlimeRolloutRecord,
    build_slime_rollout,
    get_trainable_text_segments,
    split_context_and_target,
    trajectory_to_slime_rollout,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.trajectory.schema import (
    Message,
    Role,
    RunStatus,
    ToolCall,
    ToolResult,
    ToolObservation,
    Trajectory,
    VerifyResult,
)


_TEST_NAMESPACE = "phase2_rollout_consistency"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _make_simple_trajectory(
    *,
    task_id: str = "task_001",
    reward: float = 1.0,
    status: RunStatus = RunStatus.COMPLETED,
    verifier_passed: bool = True,
    verifier_score: float = 1.0,
) -> Trajectory:
    """Create a minimal trajectory with system/user/assistant messages."""
    traj = Trajectory(
        task_id=task_id,
        repo="test_repo",
        tool_profile_id="base",
        reward=reward,
        status=status,
        verifier=VerifyResult(passed=verifier_passed, score=verifier_score),
    )
    traj.add_system("You are a coding agent.")
    traj.add_user("Fix the bug.")
    traj.add_assistant("I will help you fix the bug.")
    return traj


def _make_trajectory_with_tool_calls() -> Trajectory:
    """Create a trajectory with tool calls."""
    traj = Trajectory(
        task_id="task_tools",
        repo="test_repo",
        tool_profile_id="schema_v1",
        reward=0.8,
        status=RunStatus.COMPLETED,
        verifier=VerifyResult(passed=True, score=0.8),
    )

    traj.add_system("You are a coding agent.")
    traj.add_user("Read the file and fix the bug.")

    call1 = ToolCall(
        id="call_001",
        name="read_file",
        arguments={"path": "src/main.py"},
        canonical_name="read_file",
    )
    traj.add_assistant("I'll read the file.", tool_calls=[call1])

    traj.add_tool_observation(
        call=call1,
        result=ToolResult(ok=True, content="def add(a, b):\n    return a - b"),
    )

    call2 = ToolCall(
        id="call_002",
        name="apply_patch",
        arguments={"diff": "--- a/src/main.py\n+++ b/src/main.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b"},
        canonical_name="apply_patch",
    )
    traj.add_assistant("I'll apply a patch.", tool_calls=[call2])

    traj.add_tool_observation(
        call=call2,
        result=ToolResult(ok=True, content="Patch applied successfully."),
    )

    traj.add_assistant("The bug is fixed.")

    return traj


class TestTrajectoryToSample:
    """Verify trajectory -> TrainingSample conversion."""

    def test_preserves_task_id(self):
        traj = _make_simple_trajectory(task_id="my_task")
        sample = build_training_sample(traj)
        assert sample.task_id == "my_task"

    def test_preserves_reward(self):
        traj = _make_simple_trajectory(reward=0.75)
        sample = build_training_sample(traj)
        assert sample.reward == pytest.approx(0.75)

    def test_preserves_status(self):
        traj = _make_simple_trajectory(status=RunStatus.ERROR)
        sample = build_training_sample(traj)
        assert sample.status == "error"

    def test_preserves_verifier_info(self):
        traj = _make_simple_trajectory(verifier_passed=True, verifier_score=0.9)
        sample = build_training_sample(traj)
        assert sample.verifier_passed is True
        assert sample.verifier_score == pytest.approx(0.9)

    def test_produces_non_empty_text(self):
        traj = _make_simple_trajectory()
        sample = build_training_sample(traj)
        assert len(sample.text) > 0

    def test_produces_character_mask(self):
        traj = _make_simple_trajectory()
        sample = build_training_sample(traj)
        assert len(sample.character_mask) == len(sample.text)
        # All values should be 0 or 1
        assert all(m in (0, 1) for m in sample.character_mask)

    def test_produces_segments(self):
        traj = _make_simple_trajectory()
        sample = build_training_sample(traj)
        assert len(sample.segments) > 0
        # Each segment should have required fields
        for seg in sample.segments:
            assert "kind" in seg
            assert "text" in seg
            assert "trainable" in seg

    def test_trainable_segments_have_correct_mask(self):
        traj = _make_simple_trajectory()
        sample = build_training_sample(traj)

        # Compute expected trainable chars from segments
        trainable_count = 0
        offset = 0
        for seg in sample.segments:
            if seg.get("trainable"):
                trainable_count += len(seg["text"])
            offset += len(seg["text"])

        assert sample.trainable_char_count == trainable_count


class TestSampleToRollout:
    """Verify TrainingSample -> SlimeRolloutRecord conversion."""

    def test_preserves_task_id(self):
        traj = _make_simple_trajectory(task_id="task_xyz")
        sample = build_training_sample(traj)
        rollout = build_slime_rollout(sample)
        assert rollout.task_id == "task_xyz"

    def test_preserves_reward(self):
        traj = _make_simple_trajectory(reward=0.6)
        sample = build_training_sample(traj)
        rollout = build_slime_rollout(sample)
        assert rollout.reward == pytest.approx(0.6)

    def test_preserves_status(self):
        traj = _make_simple_trajectory(status=RunStatus.TIMEOUT)
        sample = build_training_sample(traj)
        rollout = build_slime_rollout(sample)
        assert rollout.status == "timeout"

    def test_preserves_verifier_info(self):
        traj = _make_simple_trajectory(verifier_passed=False, verifier_score=0.3)
        sample = build_training_sample(traj)
        rollout = build_slime_rollout(sample)
        assert rollout.verifier_passed is False
        assert rollout.verifier_score == pytest.approx(0.3)

    def test_preserves_text(self):
        traj = _make_simple_trajectory()
        sample = build_training_sample(traj)
        rollout = build_slime_rollout(sample)
        assert rollout.text == sample.text

    def test_preserves_character_mask(self):
        traj = _make_simple_trajectory()
        sample = build_training_sample(traj)
        rollout = build_slime_rollout(sample)
        assert rollout.character_mask == sample.character_mask

    def test_total_char_count_matches_text(self):
        traj = _make_simple_trajectory()
        sample = build_training_sample(traj)
        rollout = build_slime_rollout(sample)
        assert rollout.total_char_count == len(rollout.text)


class TestRolloutExportImport:
    """Verify rollout export/import preserves fields."""

    def test_json_roundtrip(self):
        output_dir = _get_test_dir()
        try:
            traj = _make_trajectory_with_tool_calls()
            rollout = trajectory_to_slime_rollout(traj)

            path = output_dir / "rollout.json"
            write_rollout_json(path, rollout)

            data = read_rollout_json(path)

            assert data["task_id"] == rollout.task_id
            assert data["reward"] == rollout.reward
            assert data["status"] == rollout.status
            assert data["verifier_passed"] == rollout.verifier_passed
            assert data["verifier_score"] == rollout.verifier_score
            assert data["text"] == rollout.text
            assert data["character_mask"] == rollout.character_mask
        finally:
            _cleanup(output_dir)

    def test_jsonl_roundtrip(self):
        output_dir = _get_test_dir()
        try:
            traj1 = _make_simple_trajectory(task_id="t1", reward=0.5)
            traj2 = _make_simple_trajectory(task_id="t2", reward=1.0)
            rollouts = [
                trajectory_to_slime_rollout(traj1),
                trajectory_to_slime_rollout(traj2),
            ]

            path = output_dir / "rollouts.jsonl"
            write_rollouts_jsonl(path, rollouts)

            records = read_rollouts_jsonl(path)
            assert len(records) == 2
            assert records[0]["task_id"] == "t1"
            assert records[0]["reward"] == pytest.approx(0.5)
            assert records[1]["task_id"] == "t2"
            assert records[1]["reward"] == pytest.approx(1.0)
        finally:
            _cleanup(output_dir)


class TestFullPipelineConsistency:
    """Verify the full trajectory -> sample -> rollout -> export path."""

    def test_reward_survives_full_path(self):
        output_dir = _get_test_dir()
        try:
            traj = _make_simple_trajectory(reward=0.85)
            sample = build_training_sample(traj)
            rollout = build_slime_rollout(sample)

            path = output_dir / "rollout.json"
            write_rollout_json(path, rollout)

            data = read_rollout_json(path)
            assert data["reward"] == pytest.approx(0.85)
        finally:
            _cleanup(output_dir)

    def test_status_survives_full_path(self):
        output_dir = _get_test_dir()
        try:
            traj = _make_simple_trajectory(status=RunStatus.TIMEOUT)
            sample = build_training_sample(traj)
            rollout = build_slime_rollout(sample)

            path = output_dir / "rollout.json"
            write_rollout_json(path, rollout)

            data = read_rollout_json(path)
            assert data["status"] == "timeout"
        finally:
            _cleanup(output_dir)

    def test_verifier_survives_full_path(self):
        output_dir = _get_test_dir()
        try:
            traj = _make_simple_trajectory(verifier_passed=True, verifier_score=0.95)
            sample = build_training_sample(traj)
            rollout = build_slime_rollout(sample)

            path = output_dir / "rollout.json"
            write_rollout_json(path, rollout)

            data = read_rollout_json(path)
            assert data["verifier_passed"] is True
            assert data["verifier_score"] == pytest.approx(0.95)
        finally:
            _cleanup(output_dir)

    def test_trainable_mask_survives_full_path(self):
        output_dir = _get_test_dir()
        try:
            traj = _make_trajectory_with_tool_calls()
            sample = build_training_sample(traj)
            rollout = build_slime_rollout(sample)

            path = output_dir / "rollout.json"
            write_rollout_json(path, rollout)

            data = read_rollout_json(path)
            assert len(data["character_mask"]) == len(data["text"])
            # Verify there are trainable segments (mask=1)
            assert 1 in data["character_mask"]
            # Verify there are non-trainable segments (mask=0)
            assert 0 in data["character_mask"]
        finally:
            _cleanup(output_dir)


class TestTrainableTextSegments:
    """Verify get_trainable_text_segments works after full pipeline."""

    def test_returns_segments_with_offsets(self):
        traj = _make_trajectory_with_tool_calls()
        rollout = trajectory_to_slime_rollout(traj)
        segments = get_trainable_text_segments(rollout)

        assert len(segments) > 0
        for seg in segments:
            assert "kind" in seg
            assert "text" in seg
            assert "start" in seg
            assert "end" in seg
            assert seg["end"] == seg["start"] + len(seg["text"])

    def test_offsets_match_rollout_text(self):
        traj = _make_trajectory_with_tool_calls()
        rollout = trajectory_to_slime_rollout(traj)
        segments = get_trainable_text_segments(rollout)

        for seg in segments:
            # Extract text from rollout at these offsets
            extracted = rollout.text[seg["start"] : seg["end"]]
            assert extracted == seg["text"]


class TestSplitContextAndTarget:
    """Verify split_context_and_target works after full pipeline."""

    def test_splits_correctly(self):
        traj = _make_trajectory_with_tool_calls()
        rollout = trajectory_to_slime_rollout(traj)
        context, target, target_spans = split_context_and_target(rollout)

        # Context should be non-empty (system + user + tool observations)
        assert len(context) > 0
        # Target should be non-empty (assistant content + tool calls)
        assert len(target) > 0
        # Spans should describe the target
        for span in target_spans:
            assert "start" in span
            assert "end" in span
            assert "kind" in span


class TestBatchExportConsistency:
    """Verify batch export preserves consistency."""

    def test_batch_export_creates_valid_files(self):
        output_dir = _get_test_dir()
        try:
            traj1 = _make_simple_trajectory(task_id="t1", reward=0.7)
            traj2 = _make_simple_trajectory(task_id="t2", reward=0.9)
            rollouts = [
                trajectory_to_slime_rollout(traj1),
                trajectory_to_slime_rollout(traj2),
            ]

            jsonl_path = export_batch_rollouts(output_dir, rollouts)

            assert jsonl_path.exists()
            assert (output_dir / "rollout_summary.json").exists()

            # Load and verify
            records = read_rollouts_jsonl(jsonl_path)
            assert len(records) == 2

            summary = json.loads((output_dir / "rollout_summary.json").read_text())
            assert summary["total_count"] == 2
            assert summary["avg_reward"] == pytest.approx(0.8)
        finally:
            _cleanup(output_dir)

    def test_batch_summary_counts_trainable_chars(self):
        output_dir = _get_test_dir()
        try:
            traj = _make_trajectory_with_tool_calls()
            rollout = trajectory_to_slime_rollout(traj)
            rollouts = [rollout]

            export_batch_rollouts(output_dir, rollouts)

            summary = json.loads((output_dir / "rollout_summary.json").read_text())
            assert "total_trainable_chars" in summary
            assert "total_chars" in summary
            assert summary["total_trainable_chars"] > 0
            assert summary["total_chars"] > summary["total_trainable_chars"]
        finally:
            _cleanup(output_dir)


class TestDeterministicPipeline:
    """Verify pipeline is deterministic."""

    def test_same_trajectory_same_rollout(self):
        traj = _make_trajectory_with_tool_calls()
        rollout1 = trajectory_to_slime_rollout(traj)
        rollout2 = trajectory_to_slime_rollout(traj)

        assert rollout1.text == rollout2.text
        assert rollout1.character_mask == rollout2.character_mask
        assert rollout1.model_dump_json() == rollout2.model_dump_json()

    def test_export_is_deterministic(self):
        output_dir = _get_test_dir()
        try:
            traj = _make_trajectory_with_tool_calls()
            rollout = trajectory_to_slime_rollout(traj)

            path = output_dir / "rollout.json"
            write_rollout_json(path, rollout)
            content1 = path.read_text()

            write_rollout_json(path, rollout)
            content2 = path.read_text()

            assert content1 == content2
        finally:
            _cleanup(output_dir)
