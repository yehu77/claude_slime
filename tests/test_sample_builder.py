"""Tests for training sample builder."""

from __future__ import annotations

import pytest

from pycodeagent.rl.sample_builder import TrainingSample, build_training_sample, build_training_sample_from_serialized
from pycodeagent.rl.serializer import serialize_trajectory
from pycodeagent.trajectory.schema import (
    Message,
    Role,
    RunStatus,
    ToolCall,
    ToolResult,
    Trajectory,
    VerifyResult,
)


def make_tool_call(
    *,
    id: str = "call_001",
    name: str = "read_file",
    arguments: dict | None = None,
    canonical_name: str | None = None,
) -> ToolCall:
    """Helper to create a ToolCall."""
    return ToolCall(
        id=id,
        name=name,
        arguments=arguments or {"path": "src/main.py"},
        canonical_name=canonical_name,
    )


def make_minimal_trajectory(
    *,
    task_id: str = "task_001",
    tool_profile_id: str = "base",
    reward: float = 1.0,
    status: RunStatus = RunStatus.COMPLETED,
    verifier: VerifyResult | None = None,
) -> Trajectory:
    """Helper to create a minimal trajectory."""
    if verifier is None:
        verifier = VerifyResult(passed=True, score=1.0)
    return Trajectory(
        task_id=task_id,
        repo="examples/buggy_calc",
        tool_profile_id=tool_profile_id,
        messages=[
            Message(role=Role.SYSTEM, content="You are a coding agent."),
            Message(role=Role.USER, content="Fix the failing tests."),
        ],
        reward=reward,
        status=status,
        verifier=verifier,
    )


def make_full_trajectory() -> Trajectory:
    """Helper to create a trajectory with all message types."""
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

    call = make_tool_call(name="read_file", canonical_name="read_file")
    traj.add_assistant("I'll read the file.", tool_calls=[call])

    traj.add_tool_observation(
        call=call,
        result=ToolResult(ok=True, content="def divide(a, b):\n    return a * b"),
    )

    traj.add_assistant("Fixed the bug.")

    return traj


class TestBuildTrainingSample:
    """Tests for build_training_sample."""

    def test_returns_training_sample(self):
        """Should return TrainingSample object."""
        traj = make_minimal_trajectory()
        sample = build_training_sample(traj)
        assert isinstance(sample, TrainingSample)

    def test_preserves_task_id(self):
        """Should preserve task_id."""
        traj = make_minimal_trajectory(task_id="my_task")
        sample = build_training_sample(traj)
        assert sample.task_id == "my_task"

    def test_preserves_tool_profile_id(self):
        """Should preserve tool_profile_id."""
        traj = make_minimal_trajectory(tool_profile_id="mutation_v1")
        sample = build_training_sample(traj)
        assert sample.tool_profile_id == "mutation_v1"

    def test_preserves_reward(self):
        """Should preserve reward."""
        traj = make_minimal_trajectory(reward=0.5)
        sample = build_training_sample(traj)
        assert sample.reward == 0.5

    def test_preserves_status(self):
        """Should preserve status as string."""
        traj = make_minimal_trajectory(status=RunStatus.ERROR)
        sample = build_training_sample(traj)
        assert sample.status == "error"

    def test_preserves_verifier_passed(self):
        """Should preserve verifier passed."""
        traj = make_minimal_trajectory(verifier=VerifyResult(passed=False, score=0.2))
        sample = build_training_sample(traj)
        assert sample.verifier_passed is False

    def test_preserves_verifier_score(self):
        """Should preserve verifier score."""
        traj = make_minimal_trajectory(verifier=VerifyResult(passed=False, score=0.3))
        sample = build_training_sample(traj)
        assert sample.verifier_score == 0.3

    def test_has_text(self):
        """Should have serialized text."""
        traj = make_minimal_trajectory()
        sample = build_training_sample(traj)
        assert isinstance(sample.text, str)
        assert len(sample.text) > 0

    def test_has_segments(self):
        """Should have segments list."""
        traj = make_minimal_trajectory()
        sample = build_training_sample(traj)
        assert isinstance(sample.segments, list)
        assert len(sample.segments) == 2  # system + user

    def test_has_character_mask(self):
        """Should have character-level loss mask."""
        traj = make_minimal_trajectory()
        sample = build_training_sample(traj)
        assert isinstance(sample.character_mask, list)
        assert len(sample.character_mask) == len(sample.text)

    def test_has_spans(self):
        """Should have span-level mask."""
        traj = make_minimal_trajectory()
        sample = build_training_sample(traj)
        assert isinstance(sample.spans, list)
        assert len(sample.spans) == len(sample.segments)

    def test_trainable_char_count(self):
        """Should have correct trainable char count."""
        traj = make_minimal_trajectory()
        sample = build_training_sample(traj)
        expected_count = sum(sample.character_mask)
        assert sample.trainable_char_count == expected_count


class TestBuildTrainingSampleFull:
    """Tests for full trajectory sample building."""

    def test_full_trajectory_sample(self):
        """Full trajectory should produce complete sample."""
        traj = make_full_trajectory()
        sample = build_training_sample(traj)

        assert sample.task_id == "task_full"
        assert sample.tool_profile_id == "schema_v1"
        assert sample.reward == 0.8
        assert sample.status == "completed"
        assert sample.verifier_passed is True
        assert sample.verifier_score == 0.8

    def test_segments_include_all_types(self):
        """Segments should include all message types from trajectory."""
        traj = make_full_trajectory()
        sample = build_training_sample(traj)
        kinds = {seg["kind"] for seg in sample.segments}
        assert "system" in kinds
        assert "user" in kinds
        assert "assistant" in kinds
        assert "tool" in kinds

    def test_mask_matches_trainability(self):
        """Character mask should match segment trainability."""
        traj = make_full_trajectory()
        sample = build_training_sample(traj)

        # Reconstruct mask from segments
        offset = 0
        for seg in sample.segments:
            expected = 1 if seg["trainable"] else 0
            for i in range(offset, offset + len(seg["text"])):
                assert sample.character_mask[i] == expected
            offset += len(seg["text"])

    def test_spans_aligned_with_segments(self):
        """Spans should be aligned with segments."""
        traj = make_full_trajectory()
        sample = build_training_sample(traj)

        offset = 0
        for seg, span in zip(sample.segments, sample.spans):
            assert span["start"] == offset
            assert span["end"] == offset + len(seg["text"])
            assert span["trainable"] == seg["trainable"]
            offset += len(seg["text"])


class TestBuildTrainingSampleMetadata:
    """Tests for metadata in training sample."""

    def test_includes_repo(self):
        """Should include repo in metadata."""
        traj = make_full_trajectory()
        sample = build_training_sample(traj)
        assert sample.metadata["repo"] == "examples/buggy_calc"

    def test_includes_final_diff(self):
        """Should include final_diff in metadata."""
        traj = make_full_trajectory()
        traj.final_diff = "--- a/f.py\n+++ b/f.py\n"
        sample = build_training_sample(traj)
        assert sample.metadata["final_diff"] == traj.final_diff

    def test_includes_tool_versions(self):
        """Should include tool_versions in metadata."""
        traj = make_full_trajectory()
        traj.tool_versions = {"read_file": {"version": "2.0"}}
        sample = build_training_sample(traj)
        assert sample.metadata["tool_versions"] == {"read_file": {"version": "2.0"}}

    def test_extra_metadata(self):
        """Should include extra_metadata when provided."""
        traj = make_minimal_trajectory()
        sample = build_training_sample(traj, extra_metadata={"batch_id": "batch_001"})
        assert sample.metadata["batch_id"] == "batch_001"

    def test_extra_metadata_does_not_overwrite_core(self):
        """Extra metadata should not overwrite core fields."""
        traj = make_minimal_trajectory()
        # core metadata has 'repo' - extra should not override
        sample = build_training_sample(traj, extra_metadata={"repo": "other"})
        # Extra metadata wins on conflict (standard dict.update behavior)
        assert sample.metadata["repo"] == "other"


class TestBuildTrainingSampleFromSerialized:
    """Tests for build_training_sample_from_serialized."""

    def test_from_serialized(self):
        """Should build sample from already-serialized trajectory."""
        traj = make_full_trajectory()
        serialized = serialize_trajectory(traj)
        sample = build_training_sample_from_serialized(serialized)

        assert isinstance(sample, TrainingSample)
        assert sample.task_id == serialized.task_id
        assert sample.text == serialized.text

    def test_from_serialized_with_extra_metadata(self):
        """Should include extra metadata when provided."""
        traj = make_minimal_trajectory()
        serialized = serialize_trajectory(traj)
        sample = build_training_sample_from_serialized(
            serialized, extra_metadata={"source": "replay"}
        )
        assert sample.metadata["source"] == "replay"


class TestBuildTrainingSampleEdgeCases:
    """Tests for edge cases."""

    def test_empty_trajectory(self):
        """Empty trajectory should produce valid sample."""
        traj = Trajectory(
            task_id="empty",
            repo="r",
            tool_profile_id="p",
        )
        sample = build_training_sample(traj)

        assert sample.task_id == "empty"
        assert sample.text == ""
        assert sample.segments == []
        assert sample.character_mask == []
        assert sample.spans == []
        assert sample.trainable_char_count == 0

    def test_error_trajectory(self):
        """Error/failure trajectory should still serialize stably."""
        traj = Trajectory(
            task_id="error_task",
            repo="r",
            tool_profile_id="p",
            reward=-0.2,
            status=RunStatus.ERROR,
            verifier=VerifyResult(passed=False, score=0.0),
        )
        traj.add_system("You are an agent.")
        traj.add_user("Fix this.")
        traj.add_assistant("I encountered an error.")

        sample = build_training_sample(traj)

        assert sample.status == "error"
        assert sample.reward == -0.2
        assert sample.verifier_passed is False
        assert sample.verifier_score == 0.0

    def test_timeout_trajectory(self):
        """Timeout trajectory should serialize correctly."""
        traj = Trajectory(
            task_id="timeout_task",
            repo="r",
            tool_profile_id="p",
            reward=0.0,
            status=RunStatus.TIMEOUT,
        )
        traj.add_system("You are an agent.")
        traj.add_user("Fix this.")
        call = make_tool_call(name="run_command")
        traj.add_assistant("Running tests...", tool_calls=[call])
        traj.add_tool_observation(
            call=call,
            result=ToolResult(ok=False, content="TIMEOUT", is_error=True),
        )

        sample = build_training_sample(traj)
        assert sample.status == "timeout"
        # The assistant content and tool call should be trainable
        trainable_segs = [s for s in sample.segments if s["trainable"]]
        assert len(trainable_segs) == 2  # assistant + assistant_tool_call


class TestEndToEndIntegration:
    """End-to-end integration test with realistic trajectory."""

    def test_complete_pipeline(self):
        """Full pipeline: trajectory -> serialize -> mask -> sample."""
        # Build realistic trajectory
        traj = Trajectory(
            task_id="bugfix_001",
            repo="examples/buggy_calculator",
            tool_profile_id="mutation_v2",
            reward=1.0,
            status=RunStatus.COMPLETED,
            verifier=VerifyResult(passed=True, score=1.0, stdout="2 passed"),
        )

        traj.add_system("You are a coding agent with tools to read, edit, and run code.")
        traj.add_user("Fix the failing division tests in calculator.py.")

        # Step 1: Read file
        read_call = make_tool_call(
            id="tc_1",
            name="open_source",
            arguments={"target": "calculator.py", "line_range": {"begin": 1, "end": 20}},
            canonical_name="read_file",
        )
        traj.add_assistant("Let me look at the file.", tool_calls=[read_call])
        traj.add_tool_observation(
            call=read_call,
            result=ToolResult(ok=True, content="def divide(a, b):\n    return a * b  # bug!"),
        )

        # Step 2: Apply patch
        patch_call = make_tool_call(
            id="tc_2",
            name="apply_patch",
            arguments={"patch": "--- a/calculator.py\n+++ b/calculator.py\n-    return a * b\n+    return a / b"},
            canonical_name="apply_patch",
        )
        traj.add_assistant("Found the bug. Applying fix.", tool_calls=[patch_call])
        traj.add_tool_observation(
            call=patch_call,
            result=ToolResult(ok=True, content="Patch applied successfully."),
        )

        # Step 3: Finish
        traj.add_assistant("The division operator was wrong. Fix applied.")

        traj.final_diff = "--- a/calculator.py\n+++ b/calculator.py\n-    return a * b\n+    return a / b"
        traj.tool_versions = {"open_source": {"version": "v2"}, "apply_patch": {"version": "v1"}}

        # Build sample
        sample = build_training_sample(traj)

        # Verify all metadata
        assert sample.task_id == "bugfix_001"
        assert sample.tool_profile_id == "mutation_v2"
        assert sample.reward == 1.0
        assert sample.status == "completed"
        assert sample.verifier_passed is True
        assert sample.verifier_score == 1.0

        # Verify segments
        assert len(sample.segments) == 9  # sys, user, asst, tc, tool, asst, tc, tool, asst
        kinds = [s["kind"] for s in sample.segments]
        assert kinds == [
            "system",
            "user",
            "assistant",
            "assistant_tool_call",
            "tool",
            "assistant",
            "assistant_tool_call",
            "tool",
            "assistant",
        ]

        # Verify mask alignment
        assert len(sample.character_mask) == len(sample.text)
        for seg, span in zip(sample.segments, sample.spans):
            expected = 1 if seg["trainable"] else 0
            for i in range(span["start"], span["end"]):
                assert sample.character_mask[i] == expected

        # Verify trainable content is only assistant
        for seg in sample.segments:
            if seg["kind"] in ("assistant", "assistant_tool_call"):
                assert seg["trainable"] is True
            else:
                assert seg["trainable"] is False

        # Verify metadata
        assert sample.metadata["repo"] == "examples/buggy_calculator"
        assert "final_diff" in sample.metadata
        assert "tool_versions" in sample.metadata

    def test_deterministic_sample_building(self):
        """Same trajectory should produce identical sample."""
        traj = make_full_trajectory()
        sample1 = build_training_sample(traj)
        sample2 = build_training_sample(traj)

        assert sample1.text == sample2.text
        assert sample1.character_mask == sample2.character_mask
        assert sample1.trainable_char_count == sample2.trainable_char_count
