"""Frozen RC-033 behavior matrix for request-history compaction."""

from __future__ import annotations

import pytest

from pycodeagent.agent import compaction, turn_state
from pycodeagent.agent.compaction import (
    CANONICAL_COMPACTION_OWNER,
    COMPACTION_CONTRACT_VERSION,
    MODEL_BACKED_COMPACTION_BACKEND,
    MODEL_BACKED_COMPACTION_FAILURE_KINDS,
    MODEL_BACKED_COMPACTION_FALLBACK_POLICY,
    ModelBackedCompactionOutput,
    ModelCompactedSpan,
    apply_model_backed_compaction_output,
    apply_model_backed_fallback,
    plan_request_context,
    structured_output_schema_for_compaction,
)
from pycodeagent.agent.turn_state import (
    CarriedForwardState,
    ContextPolicyMode,
    RuntimeSessionState,
)
from pycodeagent.trajectory.schema import Message, Role


pytestmark = pytest.mark.mainline


def _messages() -> list[Message]:
    return [
        Message(role=Role.SYSTEM, content="system"),
        Message(role=Role.USER, content="task"),
        Message(role=Role.ASSISTANT, content="assistant-1 " * 8),
        Message(role=Role.TOOL, content="tool-1 " * 8),
        Message(role=Role.ASSISTANT, content="assistant-2 " * 8),
        Message(role=Role.TOOL, content="tool-2 " * 8),
        Message(role=Role.ASSISTANT, content="assistant-3"),
        Message(role=Role.TOOL, content="tool-3"),
    ]


def test_obsolete_model_backed_result_envelope_is_removed() -> None:
    assert not hasattr(compaction, "ModelBackedCompactionResult")


@pytest.mark.parametrize(
    "private_name",
    [
        "_select_full_history",
        "_select_tail_window",
        "_select_deterministic_compaction",
        "_build_context_selection",
        "_build_turn_ranges",
        "_build_carried_forward_state",
        "_render_deterministic_summary",
        "_token_budget_allows",
    ],
)
def test_turn_state_contains_no_duplicate_compaction_implementation(
    private_name: str,
) -> None:
    assert not hasattr(turn_state, private_name)
    assert hasattr(compaction, private_name)


def test_turn_state_public_entrypoint_delegates_to_canonical_owner(monkeypatch) -> None:
    sentinel = object()

    def fake_selector(*args, **kwargs):
        del args, kwargs
        return sentinel

    monkeypatch.setattr(compaction, "select_request_messages", fake_selector)
    assert (
        turn_state.select_request_messages(
            _messages(),
            policy_mode=ContextPolicyMode.FULL_HISTORY,
            max_messages=None,
        )
        is sentinel
    )
    assert CANONICAL_COMPACTION_OWNER == "pycodeagent.agent.compaction"


def test_model_backed_contract_schema_and_successful_replacement_are_frozen() -> None:
    session_state = RuntimeSessionState(recovery_state=object())
    plan = plan_request_context(
        _messages(),
        policy_mode=ContextPolicyMode.MODEL_BACKED_COMPACTION,
        max_messages=6,
        session_state=session_state,
        turn_index=4,
    )
    assert plan.compaction_artifact is not None
    assert plan.compacted_turn_indices == [1, 2]

    output = ModelBackedCompactionOutput(
        summary_text="model summary",
        carried_forward_state=CarriedForwardState(
            pending_issue_kind="validation_failure",
            pending_issue_detail="rerun tests",
        ),
        compacted_span=ModelCompactedSpan(
            source_message_indices=[2, 3, 4, 5],
            source_turn_indices=[1, 2],
            pinned_message_indices=[0, 1],
        ),
    )
    applied = apply_model_backed_compaction_output(plan, output=output)

    assert COMPACTION_CONTRACT_VERSION == 1
    assert structured_output_schema_for_compaction()["required"] == [
        "summary_text",
        "carried_forward_state",
        "compacted_span",
    ]
    assert applied.model_backed_requested is True
    assert applied.model_backed_used is True
    assert applied.fallback_applied is False
    assert applied.compaction_artifact is not None
    assert applied.compaction_artifact.compacted_message_indices == [2, 3, 4, 5]
    assert applied.compaction_artifact.summary_slot is not None
    assert applied.compaction_artifact.summary_slot.summary_kind == "model_backed_compaction"
    assert applied.compaction_artifact.summary_slot.rendered_text == "model summary"
    assert applied.compaction_artifact.carried_forward_state == output.carried_forward_state


@pytest.mark.parametrize("failure_kind", MODEL_BACKED_COMPACTION_FAILURE_KINDS)
def test_model_backed_failure_always_downgrades_to_deterministic_plan(
    failure_kind: str,
) -> None:
    plan = plan_request_context(
        _messages(),
        policy_mode=ContextPolicyMode.MODEL_BACKED_COMPACTION,
        max_messages=6,
        session_state=RuntimeSessionState(recovery_state=object()),
        turn_index=4,
    )
    deterministic_summary = plan.synthetic_summary_message

    fallback = apply_model_backed_fallback(
        plan,
        backend_mode=MODEL_BACKED_COMPACTION_BACKEND,
        fallback_policy=MODEL_BACKED_COMPACTION_FALLBACK_POLICY,
        fallback_reason=failure_kind,
        failure_kind=failure_kind,
    )

    assert fallback.model_backed_requested is True
    assert fallback.model_backed_used is False
    assert fallback.fallback_applied is True
    assert fallback.fallback_policy == "deterministic_compaction"
    assert fallback.compaction_backend_failure_kind == failure_kind
    assert fallback.synthetic_summary_message == deterministic_summary
    assert fallback.context_selection.compaction_applied is True


def test_model_backed_failure_taxonomy_rejects_unversioned_extensions() -> None:
    plan = plan_request_context(
        _messages(),
        policy_mode=ContextPolicyMode.MODEL_BACKED_COMPACTION,
        max_messages=6,
        session_state=RuntimeSessionState(recovery_state=object()),
        turn_index=4,
    )
    with pytest.raises(ValueError, match="Unsupported compaction failure kind"):
        apply_model_backed_fallback(
            plan,
            backend_mode=MODEL_BACKED_COMPACTION_BACKEND,
            fallback_policy=MODEL_BACKED_COMPACTION_FALLBACK_POLICY,
            fallback_reason="new_failure",
            failure_kind="new_failure",
        )
