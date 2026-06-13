from __future__ import annotations

from pycodeagent.agent.recovery import RuntimeRecoveryState
from pycodeagent.agent.turn_context import (
    build_runtime_session_context,
    build_runtime_turn_context,
)
from pycodeagent.agent.turn_state import CarriedForwardState, RuntimeSessionState, SummarySlot
from pycodeagent.env.task import CodingTask
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.tools.bootstrap import build_base_tool_runtime
from pycodeagent.tools.context import ToolContext
from pycodeagent.trajectory.schema import Message, Role


def test_build_runtime_session_context_captures_stable_run_facts() -> None:
    tmp = make_unique_test_dir("turn_context")
    try:
        workspace = tmp / "repo"
        workspace.mkdir(parents=True, exist_ok=True)
        task = CodingTask(
            task_id="ctx_task",
            repo_path=workspace,
            prompt="Inspect and validate.",
            metadata={"require_runtime_validation_evidence": True},
        )
        _, profile, _ = build_base_tool_runtime()
        session_state = RuntimeSessionState(
            recovery_state=RuntimeRecoveryState(requires_validation_evidence=True),
            context_policy_mode="tail_window",
            context_max_messages=6,
            context_max_tokens=512,
            tool_token_reserve=64,
            response_token_reserve=128,
        )

        session_context = build_runtime_session_context(
            task,
            ToolContext(workspace_root=workspace, task=task),
            profile,
            session_state,
            tool_specs=profile.get_exposed_specs(),
            provider_provenance={"client_mode": "mimo_native_tools", "model": "demo-model"},
            runtime_capabilities={"protocol_mode": "native_tool_calling"},
            context_policy_mode="tail_window",
            context_max_messages=6,
            context_max_tokens=512,
            tool_token_reserve=64,
            response_token_reserve=128,
            system_prompt_text="You are a coding agent.",
            user_prompt_text="Inspect and validate.",
        )

        assert session_context.task_id == "ctx_task"
        assert session_context.workspace_root == str(workspace)
        assert session_context.tool_profile_id == profile.profile_id
        assert session_context.tool_order[0] == "list_files"
        assert session_context.canonical_tool_order[-1] == "finish"
        assert session_context.provider_provenance["client_mode"] == "mimo_native_tools"
        assert session_context.runtime_capabilities["protocol_mode"] == "native_tool_calling"
        assert session_context.context_policy_mode == "tail_window"
        assert session_context.context_max_messages == 6
        assert session_context.context_max_tokens == 512
        assert session_context.tool_token_reserve == 64
        assert session_context.response_token_reserve == 128
        assert session_context.requires_validation_evidence is True
        assert session_context.system_prompt_text == "You are a coding agent."
        assert len(session_context.system_prompt_fingerprint) == 16
        assert session_context.session_state is session_state
    finally:
        cleanup_test_path(tmp)


def test_build_runtime_turn_context_reflects_session_carryover() -> None:
    tmp = make_unique_test_dir("turn_context")
    try:
        workspace = tmp / "repo"
        workspace.mkdir(parents=True, exist_ok=True)
        task = CodingTask(
            task_id="turn_ctx_task",
            repo_path=workspace,
            prompt="Inspect and continue.",
        )
        _, profile, _ = build_base_tool_runtime()
        session_state = RuntimeSessionState(
            recovery_state=RuntimeRecoveryState(requires_validation_evidence=False),
            context_policy_mode="deterministic_compaction",
            context_max_messages=4,
        )
        session_state.summary_slot = SummarySlot(
            slot_id="summary_slot_0001",
            status="active",
            source_message_indices=[2, 3, 4],
            rendered_text="Earlier edits and test output.",
            opened_at_turn=1,
            last_refreshed_turn=1,
            summary_kind="deterministic_compaction",
        )
        session_state.carried_forward_state = CarriedForwardState(
            pending_issue_kind="validation_failed",
            pending_issue_detail="tests failing",
            carried_notes=["main.py edited"],
        )
        session_context = build_runtime_session_context(
            task,
            ToolContext(workspace_root=workspace, task=task),
            profile,
            session_state,
            tool_specs=profile.get_exposed_specs(),
            provider_provenance={},
            runtime_capabilities={"protocol_mode": "native_tool_calling"},
            context_policy_mode="deterministic_compaction",
            context_max_messages=4,
            context_max_tokens=None,
            tool_token_reserve=0,
            response_token_reserve=0,
            system_prompt_text="system",
            user_prompt_text="user",
        )
        messages = [
            Message(role=Role.SYSTEM, content="system"),
            Message(role=Role.USER, content="user"),
            Message(role=Role.ASSISTANT, content="Inspecting"),
            Message(role=Role.TOOL, content="Tool result"),
        ]

        turn_context = build_runtime_turn_context(
            session_context,
            messages,
            turn_index=2,
            pending_issue_kind_before_turn="validation_failed",
            active_validation_issue_kind_before_turn="tests_failed",
            active_validation_issue_id_before_turn="validation_issue_001",
            completion_evidence_status_before_turn="pending",
            validation_phase_before_turn="repair",
            expected_next_step_before_turn="revalidate",
            completion_gate_status_before_turn="blocked_pending_issue",
        )

        assert turn_context.turn_index == 2
        assert turn_context.message_count_before_turn == 4
        assert turn_context.session is session_context
        assert turn_context.turn_state.message_count_before_turn == 4
        assert (
            turn_context.turn_state.context_selection.policy_mode
            == "deterministic_compaction"
        )
        assert turn_context.turn_state.lifecycle_phase == "turn_started"
        assert turn_context.turn_state.pending_issue_id_before_turn is None
        assert turn_context.turn_state.pending_issue_kind_before_turn == "validation_failed"
        assert (
            turn_context.turn_state.active_validation_issue_kind_before_turn
            == "tests_failed"
        )
        assert (
            turn_context.turn_state.active_validation_issue_id_before_turn
            == "validation_issue_001"
        )
        assert turn_context.turn_state.completion_evidence_status_before_turn == "pending"
        assert turn_context.turn_state.validation_phase_before_turn == "repair"
        assert turn_context.turn_state.expected_next_step_before_turn == "revalidate"
        assert (
            turn_context.turn_state.completion_gate_status_before_turn
            == "blocked_pending_issue"
        )
        assert turn_context.turn_state.summary_slot_status_before_turn == "active"
        assert turn_context.turn_state.carried_forward_state_present_before_turn is True
    finally:
        cleanup_test_path(tmp)
