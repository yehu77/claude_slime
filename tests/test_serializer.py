"""Tests for trajectory serialization."""

from __future__ import annotations

import json

import pytest

from pycodeagent.rl.serializer import (
    SerializedSegment,
    SerializedTrajectory,
    serialize_trajectory,
)
from pycodeagent.trajectory.schema import (
    Message,
    Role,
    RunStatus,
    ToolCall,
    ToolResult,
    Trajectory,
    VerifyResult,
)


def _extract_tool_call_json(segment_text: str) -> str:
    """Extract the JSON payload from a serialized tool-call block."""
    prefix = "<|tool|>\n"
    suffix = "\n<|end|>\n"
    assert segment_text.startswith(prefix)
    assert segment_text.endswith(suffix)
    return segment_text[len(prefix) : -len(suffix)]


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
    """Helper to create a minimal trajectory with system + user messages."""
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
    traj.add_user("Fix the division bug in calculator.py.")

    # Assistant responds with tool call
    call = make_tool_call(name="read_file", canonical_name="read_file")
    traj.add_assistant("I'll read the file first.", tool_calls=[call])

    # Tool result
    traj.add_tool_observation(
        call=call,
        result=ToolResult(ok=True, content="def divide(a, b):\n    return a * b"),
    )

    # Assistant provides fix
    patch_call = make_tool_call(
        id="call_002",
        name="apply_patch",
        arguments={"patch": "--- a/calc.py\n+++ b/calc.py\n-    return a * b\n+    return a / b"},
        canonical_name="apply_patch",
    )
    traj.add_assistant("The bug is multiplication instead of division.", tool_calls=[patch_call])

    # Tool result for patch
    traj.add_tool_observation(
        call=patch_call,
        result=ToolResult(ok=True, content="Patch applied successfully."),
    )

    # Final assistant message
    traj.add_assistant("The fix has been applied.")

    return traj


class TestSerializeMinimalTrajectory:
    """Tests for serializing a minimal trajectory."""

    def test_returns_serialized_trajectory(self):
        """Should return SerializedTrajectory object."""
        traj = make_minimal_trajectory()
        result = serialize_trajectory(traj)
        assert isinstance(result, SerializedTrajectory)

    def test_preserves_task_id(self):
        """Should preserve task_id."""
        traj = make_minimal_trajectory(task_id="my_task")
        result = serialize_trajectory(traj)
        assert result.task_id == "my_task"

    def test_preserves_tool_profile_id(self):
        """Should preserve tool_profile_id."""
        traj = make_minimal_trajectory(tool_profile_id="mutation_v1")
        result = serialize_trajectory(traj)
        assert result.tool_profile_id == "mutation_v1"

    def test_preserves_reward(self):
        """Should preserve reward."""
        traj = make_minimal_trajectory(reward=0.75)
        result = serialize_trajectory(traj)
        assert result.reward == 0.75

    def test_preserves_status(self):
        """Should preserve status as string."""
        traj = make_minimal_trajectory(status=RunStatus.ERROR)
        result = serialize_trajectory(traj)
        assert result.status == "error"

    def test_preserves_verifier_info(self):
        """Should preserve verifier passed/score."""
        traj = make_minimal_trajectory(
            verifier=VerifyResult(passed=False, score=0.3),
        )
        result = serialize_trajectory(traj)
        assert result.verifier_passed is False
        assert result.verifier_score == 0.3

    def test_no_verifier(self):
        """Should handle missing verifier."""
        traj = make_minimal_trajectory()
        traj.verifier = None
        result = serialize_trajectory(traj)
        assert result.verifier_passed is False
        assert result.verifier_score == 0.0

    def test_segments_count(self):
        """Minimal trajectory should have 2 segments (system + user)."""
        traj = make_minimal_trajectory()
        result = serialize_trajectory(traj)
        assert len(result.segments) == 2

    def test_segment_kinds(self):
        """Segments should have correct kinds."""
        traj = make_minimal_trajectory()
        result = serialize_trajectory(traj)
        assert result.segments[0].kind == "system"
        assert result.segments[1].kind == "user"


class TestSerializeFullTrajectory:
    """Tests for serializing a trajectory with all message types."""

    def test_segment_count(self):
        """Full trajectory should have segments for all message parts."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)
        # system, user, assistant, assistant_tool_call, tool,
        # assistant, assistant_tool_call, tool, assistant = 9
        assert len(result.segments) == 9

    def test_preserves_message_order(self):
        """Segments should follow message order."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)
        kinds = [seg.kind for seg in result.segments]
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

    def test_assistant_content_trainable(self):
        """Assistant content segments should be trainable."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)
        for seg in result.segments:
            if seg.kind == "assistant":
                assert seg.trainable is True

    def test_assistant_tool_call_trainable(self):
        """Assistant tool call segments should be trainable."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)
        for seg in result.segments:
            if seg.kind == "assistant_tool_call":
                assert seg.trainable is True

    def test_system_not_trainable(self):
        """System segments should not be trainable."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)
        for seg in result.segments:
            if seg.kind == "system":
                assert seg.trainable is False

    def test_user_not_trainable(self):
        """User segments should not be trainable."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)
        for seg in result.segments:
            if seg.kind == "user":
                assert seg.trainable is False

    def test_tool_not_trainable(self):
        """Tool observation segments should not be trainable."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)
        for seg in result.segments:
            if seg.kind == "tool":
                assert seg.trainable is False

    def test_tool_call_json_format(self):
        """Tool call segments should be valid JSON."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)
        for seg in result.segments:
            if seg.kind == "assistant_tool_call":
                data = json.loads(_extract_tool_call_json(seg.text))
                assert "id" in data
                assert "name" in data
                assert "arguments" in data

    def test_tool_call_deterministic_order(self):
        """Tool call JSON should have deterministic key ordering."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)
        for seg in result.segments:
            if seg.kind == "assistant_tool_call":
                # sort_keys=True should produce consistent ordering
                parsed = json.loads(_extract_tool_call_json(seg.text))
                re_encoded = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
                assert _extract_tool_call_json(seg.text) == re_encoded

    def test_segments_use_explicit_boundary_markers(self):
        """Serialized text should keep segment boundaries explicit."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)

        assert result.segments[0].text.startswith("<system>\n")
        assert result.segments[1].text.startswith("<user>\n")
        assert any(seg.text.startswith("<assistant>\n") for seg in result.segments if seg.kind == "assistant")
        assert any(seg.text.startswith("<tool_result name=") for seg in result.segments if seg.kind == "tool")


class TestSerializeTextConcatenation:
    """Tests for text concatenation."""

    def test_text_concatenates_all_segments(self):
        """Full text should be concatenation of all segment texts."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)
        expected = "".join(seg.text for seg in result.segments)
        assert result.text == expected

    def test_text_length_matches_segments(self):
        """Text length should match sum of segment text lengths."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)
        total_seg_len = sum(len(seg.text) for seg in result.segments)
        assert len(result.text) == total_seg_len


class TestSerializeDeterminism:
    """Tests for deterministic serialization."""

    def test_same_trajectory_same_output(self):
        """Same trajectory should produce identical serialized output."""
        traj = make_full_trajectory()
        result1 = serialize_trajectory(traj)
        result2 = serialize_trajectory(traj)

        assert result1.text == result2.text
        assert len(result1.segments) == len(result2.segments)
        for s1, s2 in zip(result1.segments, result2.segments):
            assert s1.kind == s2.kind
            assert s1.text == s2.text
            assert s1.trainable == s2.trainable

    def test_tool_call_ordering_stable(self):
        """Tool calls with same arguments should produce same JSON."""
        call = make_tool_call(
            arguments={"z": 1, "a": 2, "m": 3},
        )
        traj = Trajectory(
            task_id="t1",
            repo="r",
            tool_profile_id="p",
            messages=[
                Message(role=Role.SYSTEM, content="sys"),
                Message(role=Role.USER, content="usr"),
                Message(role=Role.ASSISTANT, content="text", tool_calls=[call]),
            ],
        )
        result1 = serialize_trajectory(traj)
        result2 = serialize_trajectory(traj)
        # Find tool call segment
        tc1 = next(s for s in result1.segments if s.kind == "assistant_tool_call")
        tc2 = next(s for s in result2.segments if s.kind == "assistant_tool_call")
        assert tc1.text == tc2.text


class TestSerializeMetadata:
    """Tests for metadata inclusion."""

    def test_includes_repo(self):
        """Should include repo in metadata."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)
        assert result.metadata["repo"] == "examples/buggy_calc"

    def test_includes_final_diff(self):
        """Should include final_diff in metadata."""
        traj = make_full_trajectory()
        traj.final_diff = "--- a/calc.py\n+++ b/calc.py\n"
        result = serialize_trajectory(traj)
        assert result.metadata["final_diff"] == traj.final_diff

    def test_includes_tool_versions(self):
        """Should include tool_versions in metadata."""
        traj = make_full_trajectory()
        traj.tool_versions = {"read_file": {"version": "1.0"}}
        result = serialize_trajectory(traj)
        assert result.metadata["tool_versions"] == {"read_file": {"version": "1.0"}}

    def test_tool_call_segment_metadata(self):
        """Tool call segments should have tool metadata."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)
        tc_segments = [s for s in result.segments if s.kind == "assistant_tool_call"]
        for seg in tc_segments:
            assert "tool_call_id" in seg.metadata
            assert "tool_name" in seg.metadata

    def test_tool_segment_metadata(self):
        """Tool observation segments should have tool metadata."""
        traj = make_full_trajectory()
        result = serialize_trajectory(traj)
        tool_segments = [s for s in result.segments if s.kind == "tool"]
        for seg in tool_segments:
            assert "tool_call_id" in seg.metadata
            assert "tool_name" in seg.metadata


class TestSerializeAssistantWithoutToolCalls:
    """Tests for assistant messages without tool calls."""

    def test_no_tool_call_segment(self):
        """Assistant with no tool calls should not produce assistant_tool_call segment."""
        traj = Trajectory(
            task_id="t1",
            repo="r",
            tool_profile_id="p",
            messages=[
                Message(role=Role.SYSTEM, content="sys"),
                Message(role=Role.USER, content="usr"),
                Message(role=Role.ASSISTANT, content="Done!"),
            ],
        )
        result = serialize_trajectory(traj)
        kinds = [s.kind for s in result.segments]
        assert "assistant_tool_call" not in kinds
        assert "assistant" in kinds

    def test_assistant_empty_content_with_tool_call(self):
        """Assistant with empty content but tool calls should still produce tool call segment."""
        call = make_tool_call()
        traj = Trajectory(
            task_id="t1",
            repo="r",
            tool_profile_id="p",
            messages=[
                Message(role=Role.SYSTEM, content="sys"),
                Message(role=Role.USER, content="usr"),
                Message(role=Role.ASSISTANT, content="", tool_calls=[call]),
            ],
        )
        result = serialize_trajectory(traj)
        kinds = [s.kind for s in result.segments]
        # Empty content should not produce an assistant segment
        # but tool call should still be there
        assert "assistant_tool_call" in kinds
        assistant_kinds = [s.kind for s in result.segments if s.kind == "assistant"]
        # No assistant content segment since content is empty
        assert len(assistant_kinds) == 0


class TestSerializeEmptyTrajectory:
    """Tests for empty trajectory."""

    def test_empty_messages(self):
        """Trajectory with no messages should produce empty segments."""
        traj = Trajectory(
            task_id="t_empty",
            repo="r",
            tool_profile_id="p",
        )
        result = serialize_trajectory(traj)
        assert len(result.segments) == 0
        assert result.text == ""
