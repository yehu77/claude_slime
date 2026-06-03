"""Tests for slime rollout adapter."""

from __future__ import annotations

import pytest

from pycodeagent.rl.sample_builder import TrainingSample, build_training_sample
from pycodeagent.rl.slime_rollout import (
    SlimeRolloutRecord,
    SlimeRolloutSpan,
    build_slime_rollout,
    get_trainable_text_segments,
    split_context_and_target,
    trajectory_to_slime_rollout,
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


def make_sample(**kwargs) -> TrainingSample:
    """Helper to create a TrainingSample from trajectory kwargs."""
    traj = make_minimal_trajectory(**kwargs)
    return build_training_sample(traj)


class TestBuildSlimeRollout:
    """Tests for build_slime_rollout."""

    def test_returns_rollout_record(self):
        """Should return SlimeRolloutRecord."""
        sample = make_sample()
        rollout = build_slime_rollout(sample)
        assert isinstance(rollout, SlimeRolloutRecord)

    def test_preserves_task_id(self):
        """Should preserve task_id."""
        sample = make_sample(task_id="my_task")
        rollout = build_slime_rollout(sample)
        assert rollout.task_id == "my_task"

    def test_preserves_tool_profile_id(self):
        """Should preserve tool_profile_id."""
        sample = make_sample(tool_profile_id="mutation_v1")
        rollout = build_slime_rollout(sample)
        assert rollout.tool_profile_id == "mutation_v1"

    def test_preserves_reward(self):
        """Should preserve reward."""
        sample = make_sample(reward=0.5)
        rollout = build_slime_rollout(sample)
        assert rollout.reward == 0.5

    def test_preserves_status(self):
        """Should preserve status."""
        sample = make_sample(status=RunStatus.ERROR)
        rollout = build_slime_rollout(sample)
        assert rollout.status == "error"

    def test_preserves_verifier_passed(self):
        """Should preserve verifier passed."""
        sample = make_sample(verifier=VerifyResult(passed=False, score=0.2))
        rollout = build_slime_rollout(sample)
        assert rollout.verifier_passed is False

    def test_preserves_verifier_score(self):
        """Should preserve verifier score."""
        sample = make_sample(verifier=VerifyResult(passed=True, score=0.7))
        rollout = build_slime_rollout(sample)
        assert rollout.verifier_score == 0.7

    def test_preserves_text(self):
        """Should preserve serialized text."""
        sample = make_sample()
        rollout = build_slime_rollout(sample)
        assert rollout.text == sample.text

    def test_preserves_character_mask(self):
        """Should preserve character mask."""
        sample = make_sample()
        rollout = build_slime_rollout(sample)
        assert rollout.character_mask == sample.character_mask

    def test_preserves_spans(self):
        """Should preserve spans."""
        sample = make_sample()
        rollout = build_slime_rollout(sample)
        assert rollout.spans == sample.spans

    def test_preserves_segments(self):
        """Should preserve segments."""
        sample = make_sample()
        rollout = build_slime_rollout(sample)
        assert rollout.segments == sample.segments

    def test_total_char_count(self):
        """Should compute total char count from text."""
        sample = make_sample()
        rollout = build_slime_rollout(sample)
        assert rollout.total_char_count == len(sample.text)

    def test_trainable_char_count(self):
        """Should preserve trainable char count."""
        sample = make_sample()
        rollout = build_slime_rollout(sample)
        assert rollout.trainable_char_count == sample.trainable_char_count

    def test_extra_metadata(self):
        """Should include extra metadata."""
        sample = make_sample()
        rollout = build_slime_rollout(sample, extra_metadata={"batch_id": "batch_001"})
        assert rollout.metadata["batch_id"] == "batch_001"


class TestTrajectoryToSlimeRollout:
    """Tests for trajectory_to_slime_rollout."""

    def test_returns_rollout_record(self):
        """Should return SlimeRolloutRecord."""
        traj = make_minimal_trajectory()
        rollout = trajectory_to_slime_rollout(traj)
        assert isinstance(rollout, SlimeRolloutRecord)

    def test_full_trajectory(self):
        """Should convert full trajectory correctly."""
        traj = make_full_trajectory()
        rollout = trajectory_to_slime_rollout(traj)

        assert rollout.task_id == "task_full"
        assert rollout.tool_profile_id == "schema_v1"
        assert rollout.reward == 0.8
        assert rollout.status == "completed"
        assert rollout.verifier_passed is True
        assert rollout.verifier_score == 0.8

    def test_extra_metadata(self):
        """Should pass through extra metadata."""
        traj = make_minimal_trajectory()
        rollout = trajectory_to_slime_rollout(traj, extra_metadata={"source": "replay"})
        assert rollout.metadata["source"] == "replay"

    def test_equivalent_to_sample_pipeline(self):
        """Should produce same result as sample -> rollout."""
        traj = make_full_trajectory()
        sample = build_training_sample(traj)
        rollout_from_sample = build_slime_rollout(sample)
        rollout_from_traj = trajectory_to_slime_rollout(traj)

        assert rollout_from_sample.text == rollout_from_traj.text
        assert rollout_from_sample.character_mask == rollout_from_traj.character_mask
        assert rollout_from_sample.reward == rollout_from_traj.reward


class TestSlimeRolloutRecord:
    """Tests for SlimeRolloutRecord model."""

    def test_json_serializable(self):
        """Should be JSON serializable."""
        sample = make_sample()
        rollout = build_slime_rollout(sample)
        json_str = rollout.model_dump_json()
        assert isinstance(json_str, str)
        assert len(json_str) > 0

    def test_dict_export(self):
        """Should export to dict."""
        sample = make_sample()
        rollout = build_slime_rollout(sample)
        data = rollout.model_dump()
        assert isinstance(data, dict)
        assert "task_id" in data
        assert "text" in data
        assert "character_mask" in data


class TestGetTrainableTextSegments:
    """Tests for get_trainable_text_segments."""

    @staticmethod
    def _expected_trainable_segments(rollout: SlimeRolloutRecord) -> list[dict[str, int | str]]:
        """Compute expected trainable offsets directly from rollout segments."""
        expected: list[dict[str, int | str]] = []
        offset = 0
        for seg in rollout.segments:
            seg_len = len(seg["text"])
            if seg.get("trainable"):
                expected.append(
                    {
                        "kind": seg["kind"],
                        "text": seg["text"],
                        "start": offset,
                        "end": offset + seg_len,
                    }
                )
            offset += seg_len
        return expected

    def test_returns_only_trainable(self):
        """Should return only trainable segments."""
        traj = make_full_trajectory()
        rollout = trajectory_to_slime_rollout(traj)
        trainable = get_trainable_text_segments(rollout)

        for seg in trainable:
            assert seg["kind"] in ("assistant", "assistant_tool_call")

    def test_full_trajectory_trainable_count(self):
        """Full trajectory should have 3 trainable segments."""
        traj = make_full_trajectory()
        rollout = trajectory_to_slime_rollout(traj)
        trainable = get_trainable_text_segments(rollout)
        # 2 assistant + 1 assistant_tool_call
        assert len(trainable) == 3

    def test_minimal_trajectory_no_trainable(self):
        """Minimal trajectory has no assistant messages."""
        traj = make_minimal_trajectory()
        rollout = trajectory_to_slime_rollout(traj)
        trainable = get_trainable_text_segments(rollout)
        # Only system + user, no trainable
        assert len(trainable) == 0

    def test_offsets_present(self):
        """Every trainable segment should have start and end."""
        traj = make_full_trajectory()
        rollout = trajectory_to_slime_rollout(traj)
        trainable = get_trainable_text_segments(rollout)

        for seg in trainable:
            assert "start" in seg
            assert "end" in seg
            assert isinstance(seg["start"], int)
            assert isinstance(seg["end"], int)

    def test_offsets_correct(self):
        """Offsets should point to the correct text within rollout.text."""
        traj = make_full_trajectory()
        rollout = trajectory_to_slime_rollout(traj)
        trainable = get_trainable_text_segments(rollout)

        for seg in trainable:
            extracted = rollout.text[seg["start"]:seg["end"]]
            assert extracted == seg["text"]

    def test_multiple_assistant_segments_offsets(self):
        """Multiple trainable segments of the same kind should get distinct offsets."""
        traj = Trajectory(
            task_id="multi_asst",
            repo="r",
            tool_profile_id="p",
            reward=1.0,
            status=RunStatus.COMPLETED,
            verifier=VerifyResult(passed=True, score=1.0),
        )
        traj.add_system("sys")       # 3 chars, not trainable
        traj.add_user("usr")         # 3 chars, not trainable
        traj.add_assistant("abc")    # 3 chars, trainable -> start=6, end=9
        traj.add_assistant("def")    # 3 chars, trainable -> start=9, end=12
        traj.add_assistant("ghi")    # 3 chars, trainable -> start=12, end=15

        rollout = trajectory_to_slime_rollout(traj)
        trainable = get_trainable_text_segments(rollout)
        expected = self._expected_trainable_segments(rollout)

        assert len(trainable) == 3
        # All should be kind "assistant"
        for seg in trainable:
            assert seg["kind"] == "assistant"
            assert seg["text"].startswith("<assistant>\n")
            assert seg["text"].endswith("\n</assistant>\n")

        assert trainable == expected

    def test_mixed_assistant_and_tool_call_offsets(self):
        """Assistant + assistant_tool_call segments should get correct offsets."""
        traj = Trajectory(
            task_id="mixed",
            repo="r",
            tool_profile_id="p",
            reward=1.0,
            status=RunStatus.COMPLETED,
            verifier=VerifyResult(passed=True, score=1.0),
        )
        traj.add_system("S")         # 1 char, not trainable
        traj.add_user("U")           # 1 char, not trainable
        call = ToolCall(id="c1", name="read_file", arguments={"path": "x"})
        traj.add_assistant("A", tool_calls=[call])  # "A" trainable, tool_call trainable
        traj.add_tool_observation(call, result=ToolResult(ok=True, content="R"))  # not trainable
        traj.add_assistant("B")      # trainable

        rollout = trajectory_to_slime_rollout(traj)
        trainable = get_trainable_text_segments(rollout)
        expected = self._expected_trainable_segments(rollout)

        # 3 trainable: assistant block for "A", tool call block, assistant block for "B"
        assert len(trainable) == 3
        assert trainable[0]["kind"] == "assistant"
        assert "A" in trainable[0]["text"]
        assert trainable[0]["text"].startswith("<assistant>\n")

        assert trainable[1]["kind"] == "assistant_tool_call"
        assert trainable[1]["text"].startswith("<|tool|>\n")
        assert trainable[1]["text"].endswith("\n<|end|>\n")

        assert trainable[2]["kind"] == "assistant"
        assert "B" in trainable[2]["text"]

        assert trainable == expected

        # Verify all extracted text matches
        for seg in trainable:
            assert rollout.text[seg["start"]:seg["end"]] == seg["text"]

    def test_offsets_deterministic(self):
        """Same rollout should produce same offsets."""
        traj = make_full_trajectory()
        rollout = trajectory_to_slime_rollout(traj)

        trainable1 = get_trainable_text_segments(rollout)
        trainable2 = get_trainable_text_segments(rollout)

        for s1, s2 in zip(trainable1, trainable2):
            assert s1["start"] == s2["start"]
            assert s1["end"] == s2["end"]

    def test_offsets_ordered(self):
        """Returned trainable segments should be in text order."""
        traj = make_full_trajectory()
        rollout = trajectory_to_slime_rollout(traj)
        trainable = get_trainable_text_segments(rollout)

        for i in range(1, len(trainable)):
            assert trainable[i]["start"] >= trainable[i - 1]["end"]


class TestSplitContextAndTarget:
    """Tests for split_context_and_target."""

    def test_returns_tuple(self):
        """Should return tuple of three items."""
        traj = make_full_trajectory()
        rollout = trajectory_to_slime_rollout(traj)
        result = split_context_and_target(rollout)
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_context_is_non_trainable(self):
        """Context should only contain non-trainable segments."""
        traj = make_full_trajectory()
        rollout = trajectory_to_slime_rollout(traj)
        context, target, spans = split_context_and_target(rollout)

        # Context should not include assistant content
        for seg in rollout.segments:
            if seg["trainable"]:
                assert seg["text"] not in context or seg["text"] in target

    def test_target_is_trainable(self):
        """Target should only contain trainable segments."""
        traj = make_full_trajectory()
        rollout = trajectory_to_slime_rollout(traj)
        context, target, spans = split_context_and_target(rollout)

        # Target should be concatenation of trainable segments
        trainable_texts = [seg["text"] for seg in rollout.segments if seg["trainable"]]
        assert target == "".join(trainable_texts)

    def test_spans_within_target(self):
        """Target spans should be within target text."""
        traj = make_full_trajectory()
        rollout = trajectory_to_slime_rollout(traj)
        context, target, spans = split_context_and_target(rollout)

        for span in spans:
            assert span["start"] >= 0
            assert span["end"] <= len(target)
            assert span["end"] > span["start"]

    def test_minimal_trajectory_empty_target(self):
        """Minimal trajectory should have empty target."""
        traj = make_minimal_trajectory()
        rollout = trajectory_to_slime_rollout(traj)
        context, target, spans = split_context_and_target(rollout)

        assert target == ""
        assert spans == []
        assert len(context) > 0  # system + user content


class TestDeterminism:
    """Tests for deterministic rollout conversion."""

    def test_same_sample_same_rollout(self):
        """Same sample should produce same rollout."""
        sample = make_sample()
        rollout1 = build_slime_rollout(sample)
        rollout2 = build_slime_rollout(sample)

        assert rollout1.text == rollout2.text
        assert rollout1.character_mask == rollout2.character_mask
        assert rollout1.model_dump_json() == rollout2.model_dump_json()

    def test_same_trajectory_same_rollout(self):
        """Same trajectory should produce same rollout."""
        traj = make_full_trajectory()
        rollout1 = trajectory_to_slime_rollout(traj)
        rollout2 = trajectory_to_slime_rollout(traj)

        assert rollout1.model_dump_json() == rollout2.model_dump_json()


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_trajectory(self):
        """Empty trajectory should produce valid rollout."""
        traj = Trajectory(
            task_id="empty",
            repo="r",
            tool_profile_id="p",
        )
        rollout = trajectory_to_slime_rollout(traj)

        assert rollout.task_id == "empty"
        assert rollout.text == ""
        assert rollout.total_char_count == 0
        assert rollout.trainable_char_count == 0

    def test_error_trajectory(self):
        """Error trajectory should serialize correctly."""
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
        traj.add_assistant("Error occurred.")

        rollout = trajectory_to_slime_rollout(traj)

        assert rollout.status == "error"
        assert rollout.reward == -0.2
        assert rollout.verifier_passed is False

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

        rollout = trajectory_to_slime_rollout(traj)
        assert rollout.status == "timeout"


class TestIntegration:
    """End-to-end integration tests."""

    def test_full_pipeline(self):
        """Full pipeline: trajectory -> sample -> rollout."""
        traj = make_full_trajectory()
        sample = build_training_sample(traj)
        rollout = build_slime_rollout(sample)

        # Verify all fields preserved
        assert rollout.task_id == traj.task_id
        assert rollout.tool_profile_id == traj.tool_profile_id
        assert rollout.reward == traj.reward
        assert rollout.status == traj.status.value

        # Verify mask integrity
        assert len(rollout.character_mask) == len(rollout.text)
        trainable_count = sum(rollout.character_mask)
        assert rollout.trainable_char_count == trainable_count

    def test_full_pipeline_with_tool_calls(self):
        """Pipeline with multiple tool calls."""
        traj = Trajectory(
            task_id="multi_tool",
            repo="r",
            tool_profile_id="p",
            reward=1.0,
            status=RunStatus.COMPLETED,
            verifier=VerifyResult(passed=True, score=1.0),
        )

        traj.add_system("You are an agent.")
        traj.add_user("Fix the bug.")

        # Multiple tool calls
        for i in range(3):
            call = make_tool_call(id=f"call_{i}", name=f"tool_{i}")
            traj.add_assistant(f"Step {i}.", tool_calls=[call])
            traj.add_tool_observation(
                call=call,
                result=ToolResult(ok=True, content=f"Result {i}"),
            )

        traj.add_assistant("Done.")

        rollout = trajectory_to_slime_rollout(traj)

        # Should have: sys, user, (asst, tc, tool)*3, asst = 2 + 3*3 + 1 = 12
        assert len(rollout.segments) == 12

        # Count trainable
        trainable_kinds = [s["kind"] for s in rollout.segments if s["trainable"]]
        assert len(trainable_kinds) == 7  # 3 assistant + 3 tool_call + 1 final
