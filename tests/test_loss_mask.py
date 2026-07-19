"""Tests for loss mask generation."""

from __future__ import annotations

import pytest

from pycodeagent.rl.loss_mask import LossMask, TrainableSpan, build_loss_mask, get_trainable_segments
from pycodeagent.rl.serializer import SerializedSegment, SerializedTrajectory, serialize_trajectory
from pycodeagent.trajectory.schema import (
    Message,
    Role,
    RunStatus,
    ToolCall,
    ToolResult,
    Trajectory,
    VerifyResult,
)


def make_serialized(
    *,
    segments: list[tuple[str, str, bool]] | None = None,
    task_id: str = "task_001",
    tool_profile_id: str = "base",
) -> SerializedTrajectory:
    """Helper to create a SerializedTrajectory from segment tuples.

    Each tuple is (kind, text, trainable).
    """
    if segments is None:
        segments = [
            ("system", "You are an agent.", False),
            ("user", "Fix the bug.", False),
            ("assistant", "I will fix it.", True),
        ]

    seg_objects = [
        SerializedSegment(kind=kind, text=text, trainable=trainable)
        for kind, text, trainable in segments
    ]
    full_text = "".join(s.text for s in seg_objects)

    return SerializedTrajectory(
        task_id=task_id,
        tool_profile_id=tool_profile_id,
        segments=seg_objects,
        text=full_text,
        reward=1.0,
        status="completed",
        verifier_passed=True,
        verifier_score=1.0,
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

    call = ToolCall(
        id="call_001",
        name="read_file",
        arguments={"path": "src/main.py"},
        canonical_name="read_file",
    )
    traj.add_assistant("Let me read the file.", tool_calls=[call])

    traj.add_tool_observation(
        call=call,
        result=ToolResult(ok=True, content="def divide(a, b):\n    return a * b"),
    )

    traj.add_assistant("Fixed!")

    return traj


class TestLossMaskBasic:
    """Tests for basic loss mask generation."""

    def test_returns_loss_mask(self):
        """Should return LossMask object."""
        serialized = make_serialized()
        mask = build_loss_mask(serialized)
        assert isinstance(mask, LossMask)

    def test_mask_length_matches_text(self):
        """Character mask length should match total text length."""
        serialized = make_serialized()
        mask = build_loss_mask(serialized)
        assert len(mask.character_mask) == len(serialized.text)
        assert mask.total_length == len(serialized.text)

    def test_system_masked_out(self):
        """System content should be masked out (0)."""
        serialized = make_serialized(
            segments=[("system", "hello", False)],
        )
        mask = build_loss_mask(serialized)
        assert mask.character_mask == [0, 0, 0, 0, 0]

    def test_user_masked_out(self):
        """User content should be masked out (0)."""
        serialized = make_serialized(
            segments=[("user", "fix", False)],
        )
        mask = build_loss_mask(serialized)
        assert mask.character_mask == [0, 0, 0]

    def test_assistant_trainable(self):
        """Assistant content should be trainable (1)."""
        serialized = make_serialized(
            segments=[("assistant", "fix", True)],
        )
        mask = build_loss_mask(serialized)
        assert mask.character_mask == [1, 1, 1]

    def test_tool_masked_out(self):
        """Tool observation content should be masked out (0)."""
        serialized = make_serialized(
            segments=[("tool", "result", False)],
        )
        mask = build_loss_mask(serialized)
        assert mask.character_mask == [0, 0, 0, 0, 0, 0]

    def test_assistant_tool_call_trainable(self):
        """Assistant tool call content should be trainable (1)."""
        serialized = make_serialized(
            segments=[("assistant_tool_call", '{"id":"1"}', True)],
        )
        mask = build_loss_mask(serialized)
        assert all(m == 1 for m in mask.character_mask)


class TestLossMaskMixed:
    """Tests for mixed content loss masks."""

    def test_mixed_segments(self):
        """Should correctly mask mixed segment types."""
        serialized = make_serialized(
            segments=[
                ("system", "sys", False),           # 3 chars, mask=0
                ("user", "usr", False),              # 3 chars, mask=0
                ("assistant", "fix", True),          # 3 chars, mask=1
                ("tool", "res", False),              # 3 chars, mask=0
            ],
        )
        mask = build_loss_mask(serialized)
        expected = [0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0]
        assert mask.character_mask == expected

    def test_trainable_char_count(self):
        """Should correctly count trainable characters."""
        serialized = make_serialized(
            segments=[
                ("system", "abc", False),
                ("assistant", "de", True),
                ("tool", "fghi", False),
            ],
        )
        mask = build_loss_mask(serialized)
        assert mask.trainable_char_count == 2
        assert mask.non_trainable_char_count == 7

    def test_all_trainable(self):
        """All trainable should have all 1s."""
        serialized = make_serialized(
            segments=[
                ("assistant", "abc", True),
                ("assistant", "def", True),
            ],
        )
        mask = build_loss_mask(serialized)
        assert mask.character_mask == [1] * 6
        assert mask.trainable_char_count == 6
        assert mask.non_trainable_char_count == 0

    def test_none_trainable(self):
        """No trainable content should have all 0s."""
        serialized = make_serialized(
            segments=[
                ("system", "abc", False),
                ("tool", "def", False),
            ],
        )
        mask = build_loss_mask(serialized)
        assert mask.character_mask == [0] * 6
        assert mask.trainable_char_count == 0
        assert mask.non_trainable_char_count == 6


class TestLossMaskSpans:
    """Tests for span-level mask."""

    def test_span_count_matches_segments(self):
        """Should have one span per segment."""
        serialized = make_serialized(
            segments=[
                ("system", "ab", False),
                ("assistant", "cd", True),
            ],
        )
        mask = build_loss_mask(serialized)
        assert len(mask.spans) == 2

    def test_span_offsets(self):
        """Spans should have correct start/end offsets."""
        serialized = make_serialized(
            segments=[
                ("system", "ab", False),
                ("assistant", "cde", True),
                ("tool", "f", False),
            ],
        )
        mask = build_loss_mask(serialized)
        assert mask.spans[0].start == 0
        assert mask.spans[0].end == 2
        assert mask.spans[1].start == 2
        assert mask.spans[1].end == 5
        assert mask.spans[2].start == 5
        assert mask.spans[2].end == 6

    def test_span_trainability(self):
        """Spans should reflect segment trainability."""
        serialized = make_serialized(
            segments=[
                ("system", "ab", False),
                ("assistant", "cd", True),
                ("tool", "ef", False),
            ],
        )
        mask = build_loss_mask(serialized)
        assert mask.spans[0].trainable is False
        assert mask.spans[1].trainable is True
        assert mask.spans[2].trainable is False

    def test_spans_are_contiguous(self):
        """Spans should cover the entire text without gaps."""
        serialized = make_serialized(
            segments=[
                ("system", "abc", False),
                ("assistant", "de", True),
                ("tool", "fghij", False),
            ],
        )
        mask = build_loss_mask(serialized)
        # First span starts at 0
        assert mask.spans[0].start == 0
        # Last span ends at total length
        assert mask.spans[-1].end == mask.total_length
        # Each span starts where previous ended
        for i in range(1, len(mask.spans)):
            assert mask.spans[i].start == mask.spans[i - 1].end


class TestLossMaskDeterminism:
    """Tests for deterministic loss mask generation."""

    def test_same_input_same_output(self):
        """Same serialized trajectory should produce same mask."""
        serialized = make_serialized()
        mask1 = build_loss_mask(serialized)
        mask2 = build_loss_mask(serialized)
        assert mask1.character_mask == mask2.character_mask
        assert len(mask1.spans) == len(mask2.spans)
        for s1, s2 in zip(mask1.spans, mask2.spans):
            assert s1.start == s2.start
            assert s1.end == s2.end
            assert s1.trainable == s2.trainable


class TestLossMaskFromTrajectory:
    """Integration tests: serialize then mask a real trajectory."""

    def test_full_trajectory_mask(self):
        """Full trajectory should have correct mask pattern."""
        traj = make_full_trajectory()
        serialized = serialize_trajectory(traj)
        mask = build_loss_mask(serialized)

        # Verify mask length matches text
        assert len(mask.character_mask) == len(serialized.text)

        # Verify trainable regions correspond to assistant segments
        for seg, span in zip(serialized.segments, mask.spans):
            expected = 1 if seg.trainable else 0
            for i in range(span.start, span.end):
                assert mask.character_mask[i] == expected

    def test_trainable_only_assistant_tool_calls(self):
        """Only assistant tool-call segments should be trainable."""
        traj = make_full_trajectory()
        serialized = serialize_trajectory(traj)
        mask = build_loss_mask(serialized)

        for seg, span in zip(serialized.segments, mask.spans):
            assert span.trainable is (seg.kind == "assistant_tool_call")


class TestGetTrainableSegments:
    """Tests for get_trainable_segments helper."""

    def test_returns_only_trainable(self):
        """Should return only trainable segments."""
        serialized = make_serialized(
            segments=[
                ("system", "ab", False),
                ("assistant", "cd", True),
                ("tool", "ef", False),
                ("assistant_tool_call", "gh", True),
            ],
        )
        trainable = get_trainable_segments(serialized)
        assert len(trainable) == 2
        assert trainable[0]["kind"] == "assistant"
        assert trainable[0]["text"] == "cd"
        assert trainable[1]["kind"] == "assistant_tool_call"
        assert trainable[1]["text"] == "gh"

    def test_offsets_correct(self):
        """Trainable segment offsets should account for preceding segments."""
        serialized = make_serialized(
            segments=[
                ("system", "ab", False),
                ("assistant", "cd", True),
                ("tool", "ef", False),
                ("assistant", "gh", True),
            ],
        )
        trainable = get_trainable_segments(serialized)
        assert trainable[0]["start"] == 2  # after "ab"
        assert trainable[0]["end"] == 4    # after "cd"
        assert trainable[1]["start"] == 6  # after "ab" + "cd" + "ef"
        assert trainable[1]["end"] == 8    # after "gh"

    def test_no_trainable_segments(self):
        """Should return empty list when nothing is trainable."""
        serialized = make_serialized(
            segments=[
                ("system", "ab", False),
                ("tool", "cd", False),
            ],
        )
        trainable = get_trainable_segments(serialized)
        assert trainable == []


class TestEmptySerializedTrajectory:
    """Tests for empty serialized trajectory."""

    def test_empty_segments(self):
        """Empty serialized trajectory should produce empty mask."""
        serialized = make_serialized(segments=[])
        mask = build_loss_mask(serialized)
        assert mask.character_mask == []
        assert mask.spans == []
        assert mask.total_length == 0
        assert mask.trainable_char_count == 0
