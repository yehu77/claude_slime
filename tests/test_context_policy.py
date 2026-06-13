from __future__ import annotations

from pycodeagent.agent.turn_state import (
    ContextPolicyMode,
    PendingIssueRecord,
    RuntimeSessionState,
    RuntimeTurnState,
    estimate_messages_tokens,
    select_request_messages,
)
from pycodeagent.trajectory.schema import Message, Role


def _msg(role: Role, content: str) -> Message:
    return Message(role=role, content=content)


def test_full_history_keeps_all_messages() -> None:
    messages = [
        _msg(Role.SYSTEM, "system"),
        _msg(Role.USER, "task"),
        _msg(Role.ASSISTANT, "assistant"),
        _msg(Role.TOOL, "tool"),
    ]

    result = select_request_messages(
        messages,
        policy_mode=ContextPolicyMode.FULL_HISTORY,
        max_messages=None,
    )

    assert result.selected_messages == messages
    assert result.context_selection.included_message_indices == [0, 1, 2, 3]
    assert result.context_selection.omitted_message_count == 0
    assert result.context_selection.compaction_applied is False
    assert result.context_selection.compaction_reason is None
    assert result.planning_metadata.compaction_considered is False
    assert result.planning_metadata.consideration_reason == "full_history_policy"


def test_tail_window_keeps_pinned_messages_and_newest_tail() -> None:
    messages = [
        _msg(Role.SYSTEM, "system"),
        _msg(Role.USER, "task"),
        _msg(Role.ASSISTANT, "assistant-1"),
        _msg(Role.TOOL, "tool-1"),
        _msg(Role.ASSISTANT, "assistant-2"),
        _msg(Role.TOOL, "tool-2"),
    ]

    result = select_request_messages(
        messages,
        policy_mode=ContextPolicyMode.TAIL_WINDOW,
        max_messages=4,
    )

    assert result.context_selection.included_message_indices == [0, 1, 4, 5]
    assert [message.content for message in result.selected_messages] == [
        "system",
        "task",
        "assistant-2",
        "tool-2",
    ]
    assert result.context_selection.omitted_message_count == 2
    assert result.context_selection.compaction_applied is True
    assert result.context_selection.compaction_reason == "tail_window_truncation"
    assert result.planning_metadata.compaction_considered is True
    assert result.planning_metadata.consideration_reason == "tail_window_limit_exceeded"
    assert result.planning_metadata.pinned_message_indices == [0, 1]


def test_tail_window_preserves_additional_user_and_system_messages() -> None:
    messages = [
        _msg(Role.SYSTEM, "system"),
        _msg(Role.USER, "task"),
        _msg(Role.ASSISTANT, "assistant-1"),
        _msg(Role.TOOL, "tool-1"),
        _msg(Role.USER, "follow-up"),
        _msg(Role.ASSISTANT, "assistant-2"),
        _msg(Role.TOOL, "tool-2"),
    ]

    result = select_request_messages(
        messages,
        policy_mode=ContextPolicyMode.TAIL_WINDOW,
        max_messages=4,
    )

    assert result.context_selection.included_message_indices == [0, 1, 4, 6]
    assert [message.role for message in result.selected_messages] == [
        Role.SYSTEM,
        Role.USER,
        Role.USER,
        Role.TOOL,
    ]


def test_tail_window_keeps_all_pinned_messages_even_if_limit_is_smaller() -> None:
    messages = [
        _msg(Role.SYSTEM, "system"),
        _msg(Role.USER, "task"),
        _msg(Role.ASSISTANT, "assistant-1"),
        _msg(Role.USER, "follow-up"),
        _msg(Role.TOOL, "tool-1"),
    ]

    result = select_request_messages(
        messages,
        policy_mode=ContextPolicyMode.TAIL_WINDOW,
        max_messages=1,
    )

    assert result.context_selection.included_message_indices == [0, 1, 3]
    assert [message.content for message in result.selected_messages] == [
        "system",
        "task",
        "follow-up",
    ]
    assert result.context_selection.omitted_message_count == 2
    assert result.context_selection.compaction_applied is True


def test_tail_window_context_selection_counts_are_stable() -> None:
    messages = [
        _msg(Role.SYSTEM, "system"),
        _msg(Role.USER, "task"),
        _msg(Role.ASSISTANT, "assistant-1"),
        _msg(Role.TOOL, "tool-1"),
        _msg(Role.ASSISTANT, "assistant-2"),
        _msg(Role.TOOL, "tool-2"),
    ]

    result = select_request_messages(
        messages,
        policy_mode=ContextPolicyMode.TAIL_WINDOW,
        max_messages=4,
    )

    assert result.context_selection.first_included_index == 0
    assert result.context_selection.last_included_index == 5
    assert result.context_selection.included_role_counts == {
        "system": 1,
        "user": 1,
        "assistant": 1,
        "tool": 1,
    }


def test_deterministic_compaction_compacts_complete_old_turns() -> None:
    messages = [
        _msg(Role.SYSTEM, "system"),
        _msg(Role.USER, "task"),
        Message(
            role=Role.ASSISTANT,
            content="assistant-1",
            tool_calls=[],
        ),
        _msg(Role.TOOL, "tool-1"),
        Message(
            role=Role.ASSISTANT,
            content="assistant-2",
            tool_calls=[],
        ),
        _msg(Role.TOOL, "tool-2"),
        Message(
            role=Role.ASSISTANT,
            content="assistant-3",
            tool_calls=[],
        ),
        _msg(Role.TOOL, "tool-3"),
    ]
    session_state = RuntimeSessionState(recovery_state=object(), context_max_messages=6)

    result = select_request_messages(
        messages,
        policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION,
        max_messages=6,
        session_state=session_state,
        turn_index=4,
    )

    assert result.context_selection.compaction_applied is True
    assert result.context_selection.compaction_reason == "deterministic_turn_compaction"
    assert result.context_selection.compacted_message_count == 4
    assert result.context_selection.included_message_indices == [0, 1, 6, 7]
    assert result.compaction_artifact is not None
    assert result.compaction_artifact.compacted_message_indices == [2, 3, 4, 5]
    assert result.compaction_artifact.candidate_turn_ranges[0].turn_index == 1
    assert result.compaction_artifact.candidate_turn_ranges[1].turn_index == 2
    assert result.planning_metadata.compaction_considered is True
    assert result.planning_metadata.consideration_reason == "message_limit_exceeded"
    assert result.planning_metadata.candidate_turn_indices == [1, 2, 3]
    assert result.planning_metadata.compacted_turn_indices == [1, 2]
    assert result.synthetic_summary_message is not None
    assert result.synthetic_summary_message.role == Role.SYSTEM
    assert "[compacted runtime context]" in result.synthetic_summary_message.content
    assert len(result.selected_messages) == 5


def test_model_backed_compaction_mode_reuses_deterministic_selection_boundary() -> None:
    messages = [
        _msg(Role.SYSTEM, "system"),
        _msg(Role.USER, "task"),
        _msg(Role.ASSISTANT, "assistant-1"),
        _msg(Role.TOOL, "tool-1"),
        _msg(Role.ASSISTANT, "assistant-2"),
        _msg(Role.TOOL, "tool-2"),
        _msg(Role.ASSISTANT, "assistant-3"),
        _msg(Role.TOOL, "tool-3"),
    ]
    session_state = RuntimeSessionState(
        recovery_state=object(),
        context_policy_mode=ContextPolicyMode.MODEL_BACKED_COMPACTION.value,
        context_max_messages=6,
    )

    result = select_request_messages(
        messages,
        policy_mode=ContextPolicyMode.MODEL_BACKED_COMPACTION,
        max_messages=6,
        session_state=session_state,
        turn_index=4,
    )

    assert result.context_selection.policy_mode == "model_backed_compaction"
    assert result.context_selection.compaction_applied is True
    assert result.compaction_artifact is not None
    assert result.compaction_artifact.compacted_message_indices == [2, 3, 4, 5]


def test_deterministic_compaction_preserves_pending_issue_window() -> None:
    messages = [
        _msg(Role.SYSTEM, "system"),
        _msg(Role.USER, "task"),
        _msg(Role.ASSISTANT, "assistant-1"),
        _msg(Role.TOOL, "tool-1"),
        _msg(Role.ASSISTANT, "assistant-2"),
        _msg(Role.TOOL, "tool-2"),
        _msg(Role.ASSISTANT, "assistant-3"),
        _msg(Role.TOOL, "tool-3"),
    ]
    session_state = RuntimeSessionState(
        recovery_state=object(),
        active_pending_issue=PendingIssueRecord(
            kind="validation_failure",
            detail="still pending",
            opened_at_turn=3,
            last_observed_turn=3,
        ),
        context_max_messages=6,
    )
    session_state.turn_states = [
        RuntimeTurnState(
            turn_index=1,
            message_count_before_turn=2,
            context_selection=_dummy_selection(),
        ),
        RuntimeTurnState(
            turn_index=2,
            message_count_before_turn=4,
            context_selection=_dummy_selection(),
        ),
        RuntimeTurnState(
            turn_index=3,
            message_count_before_turn=6,
            context_selection=_dummy_selection(),
        ),
    ]

    result = select_request_messages(
        messages,
        policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION,
        max_messages=6,
        session_state=session_state,
        turn_index=4,
    )

    assert result.compaction_artifact is not None
    assert result.compaction_artifact.compacted_message_indices == [2, 3, 4, 5]
    assert result.compaction_artifact.retained_message_indices == [0, 1, 6, 7]
    assert result.compaction_artifact.carried_forward_state.pending_issue_kind == "validation_failure"
    assert result.planning_metadata.preserved_from_turn == 3


def test_full_history_reports_token_overflow_without_truncation() -> None:
    messages = [
        _msg(Role.SYSTEM, "system"),
        _msg(Role.USER, "task"),
        _msg(Role.ASSISTANT, "a" * 120),
        _msg(Role.TOOL, "b" * 120),
    ]

    result = select_request_messages(
        messages,
        policy_mode=ContextPolicyMode.FULL_HISTORY,
        max_messages=None,
        context_max_tokens=20,
    )

    assert result.selected_messages == messages
    assert result.context_selection.token_budget_satisfied is False
    assert result.context_selection.token_overflow > 0
    assert result.context_selection.included_message_indices == [0, 1, 2, 3]


def test_tail_window_respects_token_budget() -> None:
    messages = [
        _msg(Role.SYSTEM, "system"),
        _msg(Role.USER, "task"),
        _msg(Role.ASSISTANT, "a" * 80),
        _msg(Role.TOOL, "b" * 80),
        _msg(Role.ASSISTANT, "c" * 20),
        _msg(Role.TOOL, "d" * 20),
    ]
    desired_messages = [messages[index] for index in [0, 1, 4, 5]]
    token_budget = estimate_messages_tokens(desired_messages)

    result = select_request_messages(
        messages,
        policy_mode=ContextPolicyMode.TAIL_WINDOW,
        max_messages=None,
        context_max_tokens=token_budget,
    )

    assert result.context_selection.included_message_indices == [0, 1, 4, 5]
    assert result.context_selection.token_budget_satisfied is True
    assert result.context_selection.estimated_selected_tokens == token_budget
    assert result.context_selection.estimated_omitted_tokens > 0


def test_deterministic_compaction_can_satisfy_token_budget() -> None:
    messages = [
        _msg(Role.SYSTEM, "system"),
        _msg(Role.USER, "task"),
        _msg(Role.ASSISTANT, "assistant-1 " * 10),
        _msg(Role.TOOL, "tool-1 " * 10),
        _msg(Role.ASSISTANT, "assistant-2 " * 10),
        _msg(Role.TOOL, "tool-2 " * 10),
        _msg(Role.ASSISTANT, "assistant-3"),
        _msg(Role.TOOL, "tool-3"),
    ]
    session_state = RuntimeSessionState(recovery_state=object(), context_max_messages=6)

    unconstrained = select_request_messages(
        messages,
        policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION,
        max_messages=6,
        session_state=session_state,
        turn_index=4,
    )
    assert unconstrained.compaction_artifact is not None
    token_budget = estimate_messages_tokens(unconstrained.selected_messages)

    result = select_request_messages(
        messages,
        policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION,
        max_messages=6,
        session_state=session_state,
        turn_index=4,
        context_max_tokens=token_budget,
    )

    assert result.compaction_artifact is not None
    assert result.context_selection.token_budget_satisfied is True
    assert result.compaction_artifact.token_budget_target is not None
    assert result.compaction_artifact.token_budget_satisfied is True


def _dummy_selection():
    return select_request_messages(
        [_msg(Role.SYSTEM, "system"), _msg(Role.USER, "task")],
        policy_mode=ContextPolicyMode.FULL_HISTORY,
        max_messages=None,
    ).context_selection
