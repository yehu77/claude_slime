"""Single-task agent runner for the local coding runtime.

Implements the minimal agent loop:
1. Build initial prompt with task and tool specs
2. Call LLM client
3. Parse response
4. Execute tool calls
5. Record observations
6. Check stopping conditions
7. Repeat until done

Native tool-calling is the formal runtime transport.

This runner does NOT handle:
- Verifier execution
- Reward computation
- Artifact persistence
- Workspace copying
- Batch execution
"""

from __future__ import annotations

import json
from typing import Any

from pycodeagent.agent.llm_client import (
    BaseLLMClient,
    GenerateRequest,
    GenerateResponse,
    RuntimeClientCapabilities,
    StructuredOutputSchema,
)
from pycodeagent.agent.compaction import (
    MODEL_BACKED_COMPACTION_BACKEND,
    MODEL_BACKED_COMPACTION_FALLBACK_POLICY,
    ModelBackedCompactionOutput,
    apply_model_backed_compaction_output,
    apply_model_backed_fallback,
    compacted_messages_for_plan,
    normalize_model_backed_compaction_output_payload,
    structured_output_schema_for_compaction,
)
from pycodeagent.agent.history_manager import RuntimeHistoryManager
from pycodeagent.agent.parser import ParseResult, interpret_model_response
from pycodeagent.agent.prompt import (
    build_compaction_messages,
    build_initial_messages,
    build_parse_repair_message_for_transport,
)
from pycodeagent.agent.request_context import RequestContextWriter
from pycodeagent.agent.retained_history import RetainedHistoryWriter
from pycodeagent.agent.recovery import (
    CompletionBlockFamily,
    RuntimeRecoveryState,
    assess_completion_block,
    classify_turn_action,
    classify_turn_outcome,
    canonical_tool_name,
    derive_stop_policy_input_snapshot,
    record_parse_result,
    record_tool_result,
    stop_hook_reason_code_for_block_reason,
)
from pycodeagent.agent.stopping import StopReason, should_stop
from pycodeagent.agent.turn_context import (
    RuntimeSessionContext,
    RuntimeTurnContext,
    build_runtime_session_context,
    build_runtime_turn_context,
)
from pycodeagent.agent.turn_state import (
    CompactionArtifact,
    ContextPolicyMode,
    ContextSelection,
    RuntimeSessionState,
    RuntimeTurnState,
    TurnLifecyclePhase,
    begin_turn,
    build_session_metadata,
    derive_continuation_decision_kind,
    derive_termination_kind,
    finalize_session,
    finalize_turn,
    initialize_session_budgets,
    mark_turn_phase,
    note_parse_diagnostics,
    note_protocol_or_parse_failure,
    note_stop_decision,
    note_tool_execution,
    sync_pending_issue_record,
)
from pycodeagent.env.task import CodingTask
from pycodeagent.runtime_trace import RuntimePayloadRef, RuntimeTraceWriter
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.runtime import ToolExecutionInspection, ToolRuntime
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.trajectory.schema import Message, RunStatus, ToolCall, ToolResult, Trajectory


def run_agent_task(
    task: CodingTask,
    client: BaseLLMClient,
    runtime: ToolRuntime,
    profile: ToolProfile,
    ctx: ToolContext,
    trace_writer: RuntimeTraceWriter | None = None,
    retained_history_writer: RetainedHistoryWriter | None = None,
    request_context_writer: RequestContextWriter | None = None,
    context_policy_mode: ContextPolicyMode | str = ContextPolicyMode.FULL_HISTORY.value,
    context_max_messages: int | None = None,
    context_max_tokens: int | None = None,
    tool_token_reserve: int = 0,
    response_token_reserve: int = 0,
) -> Trajectory:
    """Run the agent on a single coding task."""
    runtime_capabilities = _runtime_capabilities(client)
    provider_info = _merge_provider_protocol_metadata(
        _runtime_provenance(client),
        runtime_capabilities,
    )
    trajectory = Trajectory(
        task_id=task.task_id,
        repo=str(task.repo_path),
        tool_profile_id=profile.profile_id,
        status=RunStatus.COMPLETED,
    )
    trajectory.register_tool_versions(profile.get_tool_versions())

    tool_specs = profile.get_exposed_specs()
    prompt_transport = _prompt_transport_mode(runtime_capabilities)
    messages = build_initial_messages(task.prompt, tool_specs)
    trajectory.add_system(messages[0]["content"])
    trajectory.add_user(messages[1]["content"])

    history_manager = RuntimeHistoryManager.from_trajectory_messages(
        trajectory.messages,
        retained_history_writer=retained_history_writer,
    )

    _emit_tool_profile_exposed(
        trace_writer,
        profile,
        tool_specs,
    )

    current_turn = 0
    loop_state = RuntimeRecoveryState(
        requires_validation_evidence=task.requires_runtime_validation_evidence()
    )
    normalized_context_policy = ContextPolicyMode(str(context_policy_mode))
    session_state = RuntimeSessionState(
        recovery_state=loop_state,
        context_policy_mode=normalized_context_policy.value,
        context_max_messages=context_max_messages,
        context_max_tokens=context_max_tokens,
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
    )
    initialize_session_budgets(session_state)
    session_context = build_runtime_session_context(
        task,
        ctx,
        profile,
        session_state,
        tool_specs=tool_specs,
        provider_provenance=provider_info,
        runtime_capabilities=runtime_capabilities.model_dump(mode="json"),
        context_policy_mode=normalized_context_policy.value,
        context_max_messages=context_max_messages,
        context_max_tokens=context_max_tokens,
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
        system_prompt_text=messages[0]["content"],
        user_prompt_text=messages[1]["content"],
    )
    _emit_run_started(
        trace_writer,
        session_context,
        task,
        ctx,
        provider_info=provider_info,
        runtime_capabilities=runtime_capabilities,
    )
    loop_state.refresh_completion_evidence_status()
    loop_state.refresh_validation_phase()

    while current_turn < task.max_turns:
        current_turn += 1
        history_manager.sync_source_messages(
            trajectory.messages,
            turn_index=max(current_turn - 1, 0),
        )
        validation_phase_before_turn = loop_state.refresh_validation_phase().value
        turn_context = build_runtime_turn_context(
            session_context,
            trajectory.messages,
            turn_index=current_turn,
            pending_issue_kind_before_turn=_pending_issue_kind_value(
                loop_state.pending_issue_kind
            ),
            active_validation_issue_kind_before_turn=loop_state.active_validation_issue_kind(),
            active_validation_issue_id_before_turn=loop_state.active_issue_id(),
            completion_evidence_status_before_turn=(
                loop_state.refresh_completion_evidence_status().value
            ),
            validation_phase_before_turn=validation_phase_before_turn,
            expected_next_step_before_turn=loop_state.expected_next_step().value,
            completion_gate_status_before_turn=(
                loop_state.completion_gate_status().value
            ),
        )
        turn_state = turn_context.turn_state
        begin_turn(session_state, turn_state)
        turn_state.request_history_item_count_before_turn = len(
            history_manager.request_items
        )
        turn_state.replacement_history_active_before_turn = bool(
            history_manager.replacement_history
        )
        _emit_turn_started(
            trace_writer,
            turn_context,
        )

        context_plan = history_manager.build_context_plan(
            policy_mode=session_context.context_policy_mode,
            max_messages=session_context.context_max_messages,
            session_state=session_context.session_state,
            turn_index=current_turn,
            context_max_tokens=session_context.context_max_tokens,
            tool_token_reserve=session_context.tool_token_reserve,
            response_token_reserve=session_context.response_token_reserve,
        )
        context_plan = _maybe_run_model_backed_compaction(
            client,
            trace_writer,
            turn_context,
            history_manager=history_manager,
            context_plan=context_plan,
        )
        context_result = history_manager.snapshot_from_plan(
            context_plan,
            max_messages=session_context.context_max_messages,
            context_max_tokens=session_context.context_max_tokens,
            tool_token_reserve=session_context.tool_token_reserve,
            response_token_reserve=session_context.response_token_reserve,
            turn_index=current_turn,
        )
        if request_context_writer is not None:
            request_context_writer.append_snapshot(
                task_id=task.task_id,
                turn_index=current_turn,
                snapshot=context_result,
                context_max_messages=session_context.context_max_messages,
            )
        _emit_context_selection_events(
            trace_writer,
            turn_context,
            context_result,
        )
        turn_context.selected_messages = list(context_result.selected_messages)
        turn_state.context_selection = context_result.context_selection
        turn_context.context_selection = context_result.context_selection
        turn_state.request_history_item_ids = list(
            context_result.request_history_item_ids
        )
        turn_state.request_history_item_kinds = list(
            context_result.request_history_item_kinds
        )
        turn_state.request_history_source_indices = list(
            context_result.request_history_source_indices
        )
        turn_state.request_history_item_count_after_snapshot = (
            context_result.request_history_item_count_after_snapshot
        )
        turn_state.replacement_history_active_after_turn = (
            context_result.replacement_history_active
        )
        turn_state.replacement_history_record_id = (
            context_result.replacement_history_record_id
        )
        turn_state.context_token_budget = session_context.context_max_tokens
        turn_state.selected_context_tokens = (
            context_result.context_selection.estimated_selected_tokens
        )
        turn_state.token_budget_satisfied = (
            context_result.context_selection.token_budget_satisfied
        )
        if not context_result.context_selection.token_budget_satisfied:
            turn_state.token_overflow_reason = (
                context_result.context_selection.compaction_reason
            )
        _apply_context_selection_result(session_context, context_result)
        turn_context.request_messages = [
            _message_to_dict(message, transport_mode=prompt_transport)
            for message in context_result.selected_messages
        ]
        request = GenerateRequest(
            messages=turn_context.request_messages,
            tools=session_context.tool_specs,
        )
        mark_turn_phase(turn_state, TurnLifecyclePhase.REQUEST_BUILT)
        request_payload_refs = _emit_model_request_built(
            trace_writer,
            turn_context,
            context_result,
            history_manager=history_manager,
            runtime_capabilities=runtime_capabilities,
        )
        if request_payload_refs.get("compaction") is not None:
            turn_state.compaction_artifact_ref = request_payload_refs[
                "compaction"
            ].payload_id

        try:
            response = client.generate(request)
        except Exception as e:
            trajectory.status = RunStatus.ERROR
            finalize_session(
                session_state,
                total_turns=current_turn,
                final_status=trajectory.status.value,
                stop_reason="llm_error",
                stop_detail=f"LLM error: {type(e).__name__}: {e}",
                stop_decision_code="llm_error",
            )
            validation_issue = loop_state.current_or_last_validation_issue()
            turn_state.pending_issue_kind_after_turn = _pending_issue_kind_value(
                loop_state.pending_issue_kind
            )
            turn_state.pending_issue_id_after_turn = (
                session_state.active_pending_issue.issue_id
                if session_state.active_pending_issue is not None
                else None
            )
            turn_state.active_validation_issue_kind_after_turn = (
                loop_state.active_validation_issue_kind()
            )
            turn_state.completion_evidence_status_after_turn = (
                loop_state.refresh_completion_evidence_status().value
            )
            turn_state.validation_phase_after_turn = (
                loop_state.refresh_validation_phase().value
            )
            turn_state.expected_next_step_after_turn = loop_state.expected_next_step().value
            turn_state.completion_gate_status_after_turn = (
                loop_state.completion_gate_status().value
            )
            turn_state.active_validation_issue_id_after_turn = loop_state.active_issue_id()
            turn_state.validation_attempt_count_after_turn = (
                validation_issue.validation_attempt_count
                if validation_issue is not None
                else 0
            )
            turn_state.revision_attempt_count_after_turn = (
                validation_issue.revision_attempt_count
                if validation_issue is not None
                else 0
            )
            turn_state.finish_deferral_count_after_turn = (
                session_state.finish_deferral_budget_total
                - session_state.finish_deferral_budget_remaining
                if (
                    session_state.finish_deferral_budget_total is not None
                    and session_state.finish_deferral_budget_remaining is not None
                )
                else 0
            )
            turn_state.stop_decision_code = "llm_error"
            turn_state.continuation_decision_kind = "stop_llm_error"
            turn_state.termination_kind = session_state.session_termination_kind
            turn_state.summary_slot_status_after_turn = (
                session_context.session_state.summary_slot.status
                if session_context.session_state.summary_slot is not None
                else None
            )
            turn_state.carried_forward_state_present_after_turn = (
                session_context.session_state.carried_forward_state is not None
            )
            turn_state.replacement_history_active_after_turn = bool(
                history_manager.replacement_history
            )
            turn_state.turn_outcome = "none"
            mark_turn_phase(turn_state, TurnLifecyclePhase.STOP_DECIDED)
            finalize_turn(session_state, turn_state)
            trajectory.metadata = build_session_metadata(
                session_state,
                total_turns=current_turn,
            )
            trajectory.metadata["llm_error"] = str(e)
            trajectory.metadata["llm_error_type"] = type(e).__name__
            _emit_run_completed(
                trace_writer,
                session_state,
                trajectory.metadata,
                history_manager=history_manager,
            )
            return trajectory

        _emit_model_response_received(trace_writer, current_turn, response)
        mark_turn_phase(turn_state, TurnLifecyclePhase.PROVIDER_RESPONSE_RECEIVED)

        parsed = interpret_model_response(
            response,
            runtime_capabilities=runtime_capabilities,
        )
        mark_turn_phase(turn_state, TurnLifecyclePhase.RESPONSE_INTERPRETED)
        _emit_provider_response_interpreted(
            trace_writer,
            current_turn,
            parsed,
            runtime_capabilities=runtime_capabilities,
        )
        _emit_assistant_parse_completed(trace_writer, current_turn, parsed)
        mark_turn_phase(turn_state, TurnLifecyclePhase.ASSISTANT_PARSED)
        note_parse_diagnostics(
            session_state,
            recovery_warning_count=len(parsed.recovery_warnings),
            parse_status=parsed.parse_status,
            tool_call_count=len(parsed.tool_calls),
            assistant_content_present=bool(parsed.assistant_content.strip()),
        )
        if parsed.protocol_errors:
            note_protocol_or_parse_failure(
                session_state,
                failure_kind="protocol_error",
                turn_index=current_turn,
            )
        elif parsed.parse_errors and not parsed.tool_calls:
            note_protocol_or_parse_failure(
                session_state,
                failure_kind="parse_error",
                turn_index=current_turn,
            )
        record_parse_result(loop_state, parsed, turn_index=current_turn)
        turn_action = classify_turn_action(
            parsed.tool_calls,
            phase_before=validation_phase_before_turn,
        )

        trajectory.add_assistant(
            parsed.assistant_content,
            tool_calls=parsed.tool_calls if parsed.has_tool_calls else None,
        )

        executed_tool_results: list[tuple[ToolCall, ToolResult]] = []
        turn_state.requested_tool_call_count = len(parsed.tool_calls)
        mark_turn_phase(turn_state, TurnLifecyclePhase.TOOL_DISPATCH)
        for call in parsed.tool_calls:
            inspection = runtime.inspect_call(call, profile)
            exposed_payload_kind = (
                "exposed_input_text"
                if call.input_text is not None
                else "exposed_arguments"
            )
            exposed_payload_value = (
                call.input_text
                if call.input_text is not None
                else call.arguments
            )
            exposed_args_ref = _write_json_payload(
                trace_writer,
                exposed_payload_kind,
                exposed_payload_value,
            )
            _emit_tool_call_validation_completed(
                trace_writer,
                current_turn,
                call,
                inspection,
                exposed_args_ref,
            )
            _emit_tool_call_mapping_completed(
                trace_writer,
                current_turn,
                call,
                inspection,
                exposed_args_ref,
            )

            if inspection.mapping_valid:
                _emit_tool_execution_started(trace_writer, current_turn, call, inspection)
                if canonical_tool_name(call) == "finish":
                    stop_policy_input = derive_stop_policy_input_snapshot(
                        session_state,
                        loop_state,
                        current_turn=current_turn,
                    )
                    blocked_finish_result = _make_blocked_finish_result(
                        call,
                        loop_state,
                        policy_input=stop_policy_input,
                    )
                    if blocked_finish_result is not None:
                        result = blocked_finish_result
                    else:
                        result = runtime._invoke_handler(
                            inspection.canonical_tool,
                            inspection.canonical_args or {},
                            inspection.canonical_input_text,
                            ctx,
                        )
                else:
                    result = runtime._invoke_handler(
                        inspection.canonical_tool,
                        inspection.canonical_args or {},
                        inspection.canonical_input_text,
                        ctx,
                    )
                _emit_tool_execution_result(
                    trace_writer,
                    current_turn,
                    call,
                    inspection,
                    result,
                )
            else:
                result = inspection.error_result or ToolResult(
                    ok=False,
                    content="Tool execution inspection failed",
                    is_error=True,
                    metadata={"error_type": "inspection_failed"},
                )

            tool_version: str | None = None
            resolved = profile.get_tool(call.name)
            if resolved is not None:
                tool_version = resolved[0].version
            trajectory.add_tool_observation(
                call,
                result,
                tool_version=tool_version,
            )
            record_tool_result(
                loop_state,
                call,
                result,
                turn_index=current_turn,
            )
            canonical_name = canonical_tool_name(call)
            note_tool_execution(
                session_state,
                canonical_name=canonical_name,
                result_ok=result.ok,
                result_is_error=result.is_error,
                error_type=str(result.metadata.get("error_type") or "") or None,
                turn_index=current_turn,
            )
            if (
                canonical_name != "finish"
                and result.ok
                and not result.is_error
                and loop_state.active_failure_kind is not None
            ):
                loop_state.note_corrective_progress(turn_index=current_turn)
            executed_tool_results.append((call, result))
            _emit_tool_result_appended(trace_writer, current_turn, call)
        mark_turn_phase(turn_state, TurnLifecyclePhase.POST_TOOL_OBSERVATION)
        turn_state.executed_tool_call_count = len(executed_tool_results)
        turn_state.successful_tool_call_count = sum(
            1 for _, result in executed_tool_results if result.ok and not result.is_error
        )

        stop_policy_input = derive_stop_policy_input_snapshot(
            session_state,
            loop_state,
            current_turn=current_turn,
        )
        stop_decision = should_stop(
            tool_calls=parsed.tool_calls,
            parse_errors=parsed.parse_errors,
            current_turn=current_turn,
            max_turns=task.max_turns,
            assistant_content=parsed.assistant_content,
            recovery_state=loop_state,
            policy_input=stop_policy_input,
        )
        note_stop_decision(
            session_state,
            stop_decision=stop_decision,
            turn_index=current_turn,
        )
        sync_pending_issue_record(
            session_state,
            turn_index=current_turn,
            resolution_trigger=stop_decision.decision_code,
        )
        turn_state.parse_errors = list(parsed.parse_errors)
        turn_state.tool_call_ids = [call.id for call in parsed.tool_calls]
        turn_state.pending_issue_id_after_turn = (
            session_state.active_pending_issue.issue_id
            if session_state.active_pending_issue is not None
            else None
        )
        turn_state.pending_issue_kind_after_turn = stop_decision.pending_issue_kind
        turn_state.active_validation_issue_kind_after_turn = (
            stop_decision.active_validation_issue_kind
        )
        turn_state.completion_evidence_status_after_turn = (
            stop_decision.completion_evidence_status
        )
        turn_state.completion_block_family_after_turn = (
            stop_decision.completion_block_family
        )
        turn_state.validation_phase_after_turn = stop_decision.validation_phase
        turn_state.expected_next_step_after_turn = stop_decision.expected_next_step
        turn_state.completion_gate_status_after_turn = (
            stop_decision.completion_gate_status
        )
        turn_state.active_validation_issue_id_after_turn = (
            stop_decision.active_validation_issue_id
        )
        turn_state.validation_attempt_count_after_turn = (
            stop_decision.validation_attempt_count or 0
        )
        turn_state.revision_attempt_count_after_turn = (
            stop_decision.revision_attempt_count or 0
        )
        turn_state.finish_deferral_count_after_turn = (
            stop_decision.finish_deferral_count or 0
        )
        turn_state.turn_action = turn_action.value
        turn_state.stop_decision_code = stop_decision.decision_code
        turn_state.continuation_decision_kind = derive_continuation_decision_kind(
            stop_decision
        )
        turn_state.termination_kind = derive_termination_kind(stop_decision)
        turn_state.continue_reason = stop_decision.continue_reason
        turn_state.model_needs_follow_up = stop_decision.model_needs_follow_up
        turn_state.runtime_needs_follow_up = stop_decision.runtime_needs_follow_up
        turn_state.stop_hook_evaluated = stop_decision.stop_hook_evaluated
        turn_state.stop_hook_blocked = stop_decision.stop_hook_blocked
        turn_state.stop_hook_reason = stop_decision.stop_hook_reason
        turn_state.stop_hook_reason_code = stop_decision.stop_hook_reason_code
        turn_state.policy_mode = stop_decision.policy_mode
        turn_state.recent_failure_kind_after_turn = stop_policy_input.recent_failure_kind
        turn_state.summary_slot_status_after_turn = (
            session_context.session_state.summary_slot.status
            if session_context.session_state.summary_slot is not None
            else None
        )
        turn_state.carried_forward_state_present_after_turn = (
            session_context.session_state.carried_forward_state is not None
        )
        turn_state.replacement_history_active_after_turn = bool(
            history_manager.replacement_history
        )
        turn_state.turn_outcome = classify_turn_outcome(
            phase_before=validation_phase_before_turn,
            phase_after=stop_decision.validation_phase or validation_phase_before_turn,
            action=turn_action,
            tool_results=executed_tool_results,
            stop_decision_code=stop_decision.decision_code,
            stop_reason=(
                stop_decision.reason.value
                if stop_decision.reason is not None
                else None
            ),
        ).value
        mark_turn_phase(turn_state, TurnLifecyclePhase.STOP_DECIDED)

        if stop_decision.should_stop:
            stop_reason = (
                stop_decision.reason.value
                if stop_decision.reason is not None
                else ""
            )
            if stop_decision.reason == StopReason.PARSE_ERROR:
                trajectory.status = RunStatus.ERROR
            elif stop_decision.reason == StopReason.MAX_TURNS:
                trajectory.status = RunStatus.FAILED
            elif stop_decision.reason not in {
                None,
                StopReason.FINISH,
                StopReason.NO_TOOL_CALLS,
            }:
                trajectory.status = RunStatus.FAILED
            finalize_session(
                session_state,
                total_turns=current_turn,
                final_status=trajectory.status.value,
                stop_reason=stop_reason,
                stop_detail=stop_decision.detail,
                stop_decision_code=stop_decision.decision_code,
            )
            turn_state.termination_kind = session_state.session_termination_kind

        finalize_turn(session_state, turn_state)
        _emit_turn_stop_decision(
            trace_writer,
            current_turn,
            stop_decision,
            turn_state,
            session_state,
            history_manager=history_manager,
        )
        _append_runtime_repair_messages(
            trajectory,
            parsed,
            stop_decision,
        )

        if stop_decision.should_stop:
            break

    if session_state.session_outcome is None:
        if trajectory.status == RunStatus.COMPLETED and current_turn >= task.max_turns:
            trajectory.status = RunStatus.FAILED
            finalize_session(
                session_state,
                total_turns=current_turn,
                final_status=trajectory.status.value,
                stop_reason=StopReason.MAX_TURNS.value,
                stop_detail=f"Reached max_turns={task.max_turns}",
                stop_decision_code=StopReason.MAX_TURNS.value,
            )
        else:
            finalize_session(
                session_state,
                total_turns=current_turn,
                final_status=trajectory.status.value,
                stop_reason=session_state.stop_reason,
                stop_detail=session_state.stop_detail,
                stop_decision_code=session_state.stop_decision_code or "max_turns",
            )
    history_manager.sync_source_messages(
        trajectory.messages,
        turn_index=max(current_turn, 0),
    )
    trajectory.metadata = build_session_metadata(
        session_state,
        total_turns=current_turn,
    )
    _emit_run_completed(
        trace_writer,
        session_state,
        trajectory.metadata,
        history_manager=history_manager,
    )

    return trajectory


def _message_to_dict(
    msg: Message,
    *,
    transport_mode: str = "native_tool_calling",
) -> dict[str, Any]:
    """Convert a Message to a dict for the LLM request."""
    result: dict[str, Any] = {
        "role": msg.role.value,
        "content": msg.content,
    }
    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id:
        result["tool_call_id"] = msg.tool_call_id
    if msg.tool_name:
        result["name"] = msg.tool_name
    return result


def _append_runtime_repair_messages(
    trajectory: Trajectory,
    parsed: ParseResult,
    stop_decision: Any,
) -> None:
    if (
        parsed.parse_status == "fatal"
        and not parsed.tool_calls
        and not stop_decision.should_stop
        and stop_decision.decision_code == "recoverable_parse_error"
    ):
        trajectory.add_user(
            build_parse_repair_message_for_transport(parsed.parse_errors),
            metadata={
                "message_kind": "runtime_repair",
                "repair_kind": "parse_error",
                "decision_code": stop_decision.decision_code,
                "tool_call_transport": "native_tool_calling",
            },
        )


def _write_json_payload(
    trace_writer: RuntimeTraceWriter | None,
    kind: str,
    value: Any,
) -> RuntimePayloadRef | None:
    if trace_writer is None:
        return None
    return trace_writer.write_json_payload(kind, value)


def _emit_tool_profile_exposed(
    trace_writer: RuntimeTraceWriter | None,
    profile: ToolProfile,
    tool_specs: list[dict[str, Any]],
) -> None:
    if trace_writer is None:
        return
    tool_specs_ref = trace_writer.write_json_payload("tool_specs", tool_specs)
    trace_writer.append(
        "tool_profile_exposed",
        data={
            "tool_profile_id": profile.profile_id,
            "mutation_manifest_version": profile.metadata.get(
                "mutation_manifest_version", 1
            ),
            "profile_mode": str(profile.metadata.get("mode", "base")),
            "profile_seed": int(profile.metadata.get("seed", 0)),
            "mutation_axes": list(profile.metadata.get("mutation_axes", [])),
            "compat_mode": profile.metadata.get("compat_mode"),
            "reorder_anchor_policy": profile.metadata.get(
                "reorder_anchor_policy",
                "finish_last",
            ),
            "tool_order_seed": profile.metadata.get("tool_order_seed"),
            "schema_variant_categories": dict(
                profile.metadata.get("schema_variant_categories", {})
            ),
            "selected_variant_ids": dict(
                profile.metadata.get("selected_variant_ids", {})
            ),
            "tool_versions": profile.get_tool_versions(),
            "tool_view_versions": {
                tool.exposed_name: tool.version for tool in profile.tools
            },
            "tool_names": [spec.get("name", "") for spec in tool_specs],
            "tool_order": [tool.exposed_name for tool in profile.tools],
            "canonical_tool_order": [
                tool.canonical_name for tool in profile.tools
            ],
        },
        payload_refs=[tool_specs_ref],
    )


def _runtime_provenance(client: BaseLLMClient) -> dict[str, Any]:
    """Best-effort extraction of non-secret client provenance."""
    try:
        provenance = client.runtime_provenance()
    except Exception:
        return {}
    if not isinstance(provenance, dict):
        return {}
    return dict(provenance)


def _runtime_capabilities(client: BaseLLMClient) -> RuntimeClientCapabilities:
    """Best-effort extraction of runtime protocol capabilities."""
    try:
        capabilities = client.runtime_capabilities()
    except Exception:
        return RuntimeClientCapabilities()
    if isinstance(capabilities, RuntimeClientCapabilities):
        return capabilities
    try:
        return RuntimeClientCapabilities.model_validate(capabilities)
    except Exception:
        return RuntimeClientCapabilities()


def _merge_provider_protocol_metadata(
    provider_info: dict[str, Any],
    runtime_capabilities: RuntimeClientCapabilities,
) -> dict[str, Any]:
    merged = dict(provider_info)
    merged.update(
        {
            "protocol_mode": runtime_capabilities.protocol_mode,
            "supports_native_tools": runtime_capabilities.supports_native_tools,
            "text_fallback_allowed": runtime_capabilities.text_fallback_allowed,
            "structured_finish_mode": runtime_capabilities.structured_finish_mode,
            "provider_family": runtime_capabilities.provider_family,
            "provider_name": runtime_capabilities.provider_name,
        }
    )
    return merged


def _prompt_transport_mode(runtime_capabilities: RuntimeClientCapabilities) -> str:
    return runtime_capabilities.protocol_mode


def _emit_run_started(
    trace_writer: RuntimeTraceWriter | None,
    session_context: RuntimeSessionContext,
    task: CodingTask,
    ctx: ToolContext,
    *,
    provider_info: dict[str, Any],
    runtime_capabilities: RuntimeClientCapabilities,
) -> None:
    if trace_writer is None:
        return
    data = {
        "task_prompt": task.prompt,
        "max_turns": task.max_turns,
        "repo_path": str(task.repo_path),
        "workspace_root": str(ctx.workspace_root),
        "tool_profile_id": session_context.tool_profile_id,
        "context_policy_mode": session_context.context_policy_mode,
        "context_max_messages": session_context.context_max_messages,
        "context_max_tokens": session_context.context_max_tokens,
        "tool_token_reserve": session_context.tool_token_reserve,
        "response_token_reserve": session_context.response_token_reserve,
        "requires_validation_evidence": (
            session_context.requires_validation_evidence
        ),
        "system_prompt_fingerprint": session_context.system_prompt_fingerprint,
    }
    provider_payload = _merge_provider_protocol_metadata(
        provider_info,
        runtime_capabilities,
    )
    if provider_payload:
        data["provider"] = provider_payload
    trace_writer.append("run_started", data=data)


def _pending_issue_kind_value(pending_issue_kind: Any) -> str | None:
    if pending_issue_kind is None:
        return None
    return getattr(pending_issue_kind, "value", str(pending_issue_kind))


def _apply_context_selection_result(
    session_context: RuntimeSessionContext,
    context_result,
) -> None:
    session_state = session_context.session_state
    compaction_artifact: CompactionArtifact | None = context_result.compaction_artifact
    if compaction_artifact is None:
        return
    session_state.summary_slot = compaction_artifact.summary_slot
    session_state.carried_forward_state = compaction_artifact.carried_forward_state
    session_state.last_compaction_artifact = compaction_artifact
    session_state.compaction_count += 1


def _maybe_run_model_backed_compaction(
    client: BaseLLMClient,
    trace_writer: RuntimeTraceWriter | None,
    turn_context: RuntimeTurnContext,
    *,
    history_manager: RuntimeHistoryManager,
    context_plan,
):
    session_context = turn_context.session
    runtime_capabilities = RuntimeClientCapabilities.model_validate(
        session_context.runtime_capabilities
    )
    if (
        session_context.context_policy_mode
        != ContextPolicyMode.MODEL_BACKED_COMPACTION.value
    ):
        return context_plan
    if context_plan.compaction_artifact is None:
        return context_plan

    request_messages = [item.message for item in history_manager.request_items]
    compacted_messages = compacted_messages_for_plan(request_messages, context_plan)
    pinned_index_set = set(context_plan.compaction_artifact.pinned_message_indices)
    pinned_messages = [
        message
        for index, message in enumerate(request_messages)
        if index in pinned_index_set
    ]
    request = GenerateRequest(
        messages=build_compaction_messages(
            compacted_messages=compacted_messages,
            pinned_messages=pinned_messages,
            compaction_artifact=context_plan.compaction_artifact,
            carried_forward_state=context_plan.compaction_artifact.carried_forward_state,
        ),
        tools=[],
        request_kind="context_compaction",
        structured_output_schema=StructuredOutputSchema(
            name="runtime_compaction_output",
            schema=structured_output_schema_for_compaction(),
            strict=True,
        ),
    )
    _emit_context_compaction_requested(
        trace_writer,
        turn_context.turn_index,
        context_plan=context_plan,
        request=request,
        runtime_capabilities=runtime_capabilities,
    )

    if not (
        runtime_capabilities.supports_structured_output
        and runtime_capabilities.supports_model_backed_compaction
    ):
        fallback_plan = apply_model_backed_fallback(
            context_plan,
            backend_mode=MODEL_BACKED_COMPACTION_BACKEND,
            fallback_policy=MODEL_BACKED_COMPACTION_FALLBACK_POLICY,
            fallback_reason="capability_unavailable",
            failure_kind="capability_unavailable",
        )
        _emit_context_compaction_failed(
            trace_writer,
            turn_context.turn_index,
            context_plan=fallback_plan,
            backend_mode=MODEL_BACKED_COMPACTION_BACKEND,
            failure_kind="capability_unavailable",
            detail="Client capabilities do not allow model-backed compaction",
        )
        return fallback_plan

    try:
        response = client.generate(request)
    except Exception as exc:
        fallback_plan = apply_model_backed_fallback(
            context_plan,
            backend_mode=MODEL_BACKED_COMPACTION_BACKEND,
            fallback_policy=MODEL_BACKED_COMPACTION_FALLBACK_POLICY,
            fallback_reason="provider_error",
            failure_kind="provider_error",
        )
        _emit_context_compaction_failed(
            trace_writer,
            turn_context.turn_index,
            context_plan=fallback_plan,
            backend_mode=MODEL_BACKED_COMPACTION_BACKEND,
            failure_kind="provider_error",
            detail=f"{type(exc).__name__}: {exc}",
        )
        return fallback_plan

    if response.structured_output is None:
        detail = response.structured_output_parse_error or "missing_structured_output"
        fallback_plan = apply_model_backed_fallback(
            context_plan,
            backend_mode=MODEL_BACKED_COMPACTION_BACKEND,
            fallback_policy=MODEL_BACKED_COMPACTION_FALLBACK_POLICY,
            fallback_reason="structured_output_parse_error",
            failure_kind="structured_output_parse_error",
        )
        _emit_context_compaction_failed(
            trace_writer,
            turn_context.turn_index,
            context_plan=fallback_plan,
            backend_mode=MODEL_BACKED_COMPACTION_BACKEND,
            failure_kind="structured_output_parse_error",
            detail=detail,
            response=response,
        )
        return fallback_plan

    try:
        normalized_structured_output = normalize_model_backed_compaction_output_payload(
            response.structured_output
        )
        output = ModelBackedCompactionOutput.model_validate(normalized_structured_output)
    except Exception as exc:
        fallback_plan = apply_model_backed_fallback(
            context_plan,
            backend_mode=MODEL_BACKED_COMPACTION_BACKEND,
            fallback_policy=MODEL_BACKED_COMPACTION_FALLBACK_POLICY,
            fallback_reason="schema_validation_error",
            failure_kind="schema_validation_error",
        )
        _emit_context_compaction_failed(
            trace_writer,
            turn_context.turn_index,
            context_plan=fallback_plan,
            backend_mode=MODEL_BACKED_COMPACTION_BACKEND,
            failure_kind="schema_validation_error",
            detail=str(exc),
            response=response,
        )
        return fallback_plan

    span_validation_error = _validate_model_backed_compaction_span(
        output=output,
        context_plan=context_plan,
    )
    if span_validation_error is not None:
        fallback_plan = apply_model_backed_fallback(
            context_plan,
            backend_mode=MODEL_BACKED_COMPACTION_BACKEND,
            fallback_policy=MODEL_BACKED_COMPACTION_FALLBACK_POLICY,
            fallback_reason="compacted_span_mismatch",
            failure_kind="compacted_span_mismatch",
        )
        _emit_context_compaction_failed(
            trace_writer,
            turn_context.turn_index,
            context_plan=fallback_plan,
            backend_mode=MODEL_BACKED_COMPACTION_BACKEND,
            failure_kind="compacted_span_mismatch",
            detail=span_validation_error,
            response=response,
        )
        return fallback_plan

    updated_plan = apply_model_backed_compaction_output(
        context_plan,
        output=output,
        backend_mode=MODEL_BACKED_COMPACTION_BACKEND,
    )
    _emit_context_compaction_completed(
        trace_writer,
        turn_context.turn_index,
        context_plan=updated_plan,
        response=response,
        output=output,
    )
    return updated_plan


def _validate_model_backed_compaction_span(
    *,
    output: ModelBackedCompactionOutput,
    context_plan,
) -> str | None:
    artifact = context_plan.compaction_artifact
    if artifact is None:
        return "missing_compaction_artifact"
    expected_message_indices = list(artifact.compacted_message_indices)
    if list(output.compacted_span.source_message_indices) != expected_message_indices:
        return (
            "source_message_indices_mismatch: "
            f"expected={expected_message_indices} "
            f"actual={list(output.compacted_span.source_message_indices)}"
        )
    if list(output.compacted_span.pinned_message_indices) != list(
        artifact.pinned_message_indices
    ):
        return (
            "pinned_message_indices_mismatch: "
            f"expected={list(artifact.pinned_message_indices)} "
            f"actual={list(output.compacted_span.pinned_message_indices)}"
        )
    if output.compacted_span.replacement_summary_kind != "model_backed_compaction":
        return (
            "replacement_summary_kind_mismatch: "
            f"actual={output.compacted_span.replacement_summary_kind}"
        )
    actual_turn_indices = list(output.compacted_span.source_turn_indices)
    compacted_turn_indices = list(context_plan.compacted_turn_indices)
    if actual_turn_indices != compacted_turn_indices:
        return (
            "source_turn_indices_mismatch: "
            f"expected={compacted_turn_indices} actual={actual_turn_indices}"
        )
    return None


def _emit_turn_started(
    trace_writer: RuntimeTraceWriter | None,
    turn_context: RuntimeTurnContext,
) -> None:
    if trace_writer is None:
        return
    turn_state = turn_context.turn_state
    session_context = turn_context.session
    trace_writer.append(
        "turn_started",
        turn_index=turn_state.turn_index,
        data={
            "turn_index": turn_state.turn_index,
            "message_count_before_turn": turn_state.message_count_before_turn,
            "request_history_item_count_before_turn": (
                turn_state.request_history_item_count_before_turn
            ),
            "context_policy_mode": session_context.context_policy_mode,
            "context_max_messages": session_context.context_max_messages,
            "context_max_tokens": session_context.context_max_tokens,
            "tool_token_reserve": session_context.tool_token_reserve,
            "response_token_reserve": session_context.response_token_reserve,
            "session_stop_status_before_turn": (
                session_context.session_state.session_stop_status
            ),
            "validation_phase_before_turn": turn_state.validation_phase_before_turn,
            "expected_next_step_before_turn": turn_state.expected_next_step_before_turn,
            "completion_gate_status_before_turn": (
                turn_state.completion_gate_status_before_turn
            ),
            "pending_issue_id_before_turn": turn_state.pending_issue_id_before_turn,
            "active_validation_issue_id_before_turn": (
                turn_state.active_validation_issue_id_before_turn
            ),
            "active_validation_issue_kind_before_turn": (
                turn_state.active_validation_issue_kind_before_turn
            ),
            "validation_budget_remaining_before_turn": (
                session_context.session_state.validation_budget_remaining
            ),
            "revision_budget_remaining_before_turn": (
                session_context.session_state.revision_budget_remaining
            ),
            "finish_deferral_budget_remaining_before_turn": (
                session_context.session_state.finish_deferral_budget_remaining
            ),
            "summary_slot_status_before_turn": turn_state.summary_slot_status_before_turn,
            "carried_forward_state_present_before_turn": (
                turn_state.carried_forward_state_present_before_turn
            ),
            "replacement_history_active_before_turn": (
                turn_state.replacement_history_active_before_turn
            ),
        },
        )


def _emit_context_compaction_requested(
    trace_writer: RuntimeTraceWriter | None,
    turn_index: int,
    *,
    context_plan,
    request: GenerateRequest,
    runtime_capabilities: RuntimeClientCapabilities,
) -> None:
    if trace_writer is None:
        return
    request_ref = trace_writer.write_json_payload(
        "context_compaction_request",
        {
            "request_kind": request.request_kind,
            "messages": request.messages,
            "tools": request.tools,
            "structured_output_schema": (
                request.structured_output_schema.model_dump(mode="json")
                if request.structured_output_schema is not None
                else None
            ),
        },
    )
    payload_refs = [request_ref]
    if context_plan.compaction_artifact is not None:
        artifact_ref = trace_writer.write_json_payload(
            "context_compaction_request_artifact",
            context_plan.compaction_artifact.model_dump(mode="json"),
        )
        payload_refs.append(artifact_ref)
    trace_writer.append(
        "context_compaction_requested",
        turn_index=turn_index,
        data={
            "turn_index": turn_index,
            "backend_mode": MODEL_BACKED_COMPACTION_BACKEND,
            "request_kind": request.request_kind,
            "policy_mode": context_plan.policy_mode,
            "model_backed_requested": context_plan.model_backed_requested,
            "fallback_policy": context_plan.fallback_policy,
            "supports_structured_output": runtime_capabilities.supports_structured_output,
            "supports_model_backed_compaction": (
                runtime_capabilities.supports_model_backed_compaction
            ),
            "compacted_message_count": (
                len(context_plan.compaction_artifact.compacted_message_indices)
                if context_plan.compaction_artifact is not None
                else 0
            ),
        },
        payload_refs=payload_refs,
    )


def _emit_context_compaction_completed(
    trace_writer: RuntimeTraceWriter | None,
    turn_index: int,
    *,
    context_plan,
    response: GenerateResponse,
    output: ModelBackedCompactionOutput,
) -> None:
    if trace_writer is None:
        return
    payload_refs = [
        trace_writer.write_json_payload(
            "context_compaction_response",
            response.model_dump(mode="json"),
        ),
        trace_writer.write_json_payload(
            "context_compaction_output",
            output.model_dump(mode="json"),
        ),
    ]
    if context_plan.compaction_artifact is not None:
        payload_refs.append(
            trace_writer.write_json_payload(
                "context_compaction_final_artifact",
                context_plan.compaction_artifact.model_dump(mode="json"),
            )
        )
    trace_writer.append(
        "context_compaction_completed",
        turn_index=turn_index,
        data={
            "turn_index": turn_index,
            "backend_mode": (
                context_plan.compaction_backend_mode
                or MODEL_BACKED_COMPACTION_BACKEND
            ),
            "request_kind": response.request_kind,
            "model_backed_requested": context_plan.model_backed_requested,
            "model_backed_used": context_plan.model_backed_used,
            "fallback_applied": context_plan.fallback_applied,
            "fallback_reason": context_plan.fallback_reason,
            "summary_text_present": bool(output.summary_text.strip()),
            "summary_kind": (
                context_plan.compaction_artifact.summary_slot.summary_kind
                if (
                    context_plan.compaction_artifact is not None
                    and context_plan.compaction_artifact.summary_slot is not None
                )
                else None
            ),
            "carried_forward_state_present": True,
            "source_message_indices": list(output.compacted_span.source_message_indices),
            "source_turn_indices": list(output.compacted_span.source_turn_indices),
            "pinned_message_indices": list(output.compacted_span.pinned_message_indices),
        },
        payload_refs=payload_refs,
    )


def _emit_context_compaction_failed(
    trace_writer: RuntimeTraceWriter | None,
    turn_index: int,
    *,
    context_plan,
    backend_mode: str,
    failure_kind: str,
    detail: str,
    response: GenerateResponse | None = None,
) -> None:
    if trace_writer is None:
        return
    payload_refs = []
    if context_plan.compaction_artifact is not None:
        payload_refs.append(
            trace_writer.write_json_payload(
                "context_compaction_failed_artifact",
                context_plan.compaction_artifact.model_dump(mode="json"),
            )
        )
    if response is not None:
        payload_refs.append(
            trace_writer.write_json_payload(
                "context_compaction_failed_response",
                response.model_dump(mode="json"),
            )
        )
    trace_writer.append(
        "context_compaction_failed",
        turn_index=turn_index,
        data={
            "turn_index": turn_index,
            "backend_mode": backend_mode,
            "policy_mode": context_plan.policy_mode,
            "model_backed_requested": context_plan.model_backed_requested,
            "model_backed_used": context_plan.model_backed_used,
            "failure_kind": failure_kind,
            "detail": detail,
            "fallback_policy": context_plan.fallback_policy,
            "fallback_applied": context_plan.fallback_applied,
            "fallback_reason": context_plan.fallback_reason,
        },
        payload_refs=payload_refs,
    )


def _emit_context_selection_events(
    trace_writer: RuntimeTraceWriter | None,
    turn_context: RuntimeTurnContext,
    context_result,
) -> None:
    if trace_writer is None:
        return
    turn_index = turn_context.turn_index
    context_plan = context_result.context_selection_plan
    context_selection = context_result.context_selection
    plan_ref = trace_writer.write_json_payload(
        "context_selection_plan",
        context_plan.model_dump(mode="json"),
    )
    trace_writer.append(
        "context_selection_planned",
        turn_index=turn_index,
        data={
            "turn_index": turn_index,
            "policy_mode": context_plan.policy_mode,
            "compaction_considered": context_plan.compaction_considered,
            "compaction_considered_reason": context_plan.compaction_considered_reason,
            "compaction_skip_reason": context_plan.compaction_skip_reason,
            "trigger_message_overflow": context_plan.trigger_message_overflow,
            "trigger_token_overflow": context_plan.trigger_token_overflow,
            "model_backed_requested": context_plan.model_backed_requested,
            "model_backed_used": context_plan.model_backed_used,
            "compaction_backend_mode": context_plan.compaction_backend_mode,
            "fallback_policy": context_plan.fallback_policy,
            "fallback_applied": context_plan.fallback_applied,
            "fallback_reason": context_plan.fallback_reason,
            "compaction_backend_failure_kind": (
                context_plan.compaction_backend_failure_kind
            ),
            "request_history_item_count_before_snapshot": (
                context_plan.request_history_item_count_before_snapshot
            ),
            "selected_request_item_indices": list(
                context_plan.selected_request_item_indices
            ),
            "selected_message_count_after_selection": (
                context_plan.selected_message_count_after_selection
            ),
            "compaction_decision": context_plan.compaction_decision,
            "pinned_message_indices": list(context_plan.pinned_message_indices),
            "preserved_from_turn": context_plan.preserved_from_turn,
            "candidate_turn_indices": list(context_plan.candidate_turn_indices),
            "compacted_turn_indices": list(context_plan.compacted_turn_indices),
            "included_message_indices": list(
                context_selection.included_message_indices
            ),
            "omitted_message_count": context_selection.omitted_message_count,
            "compacted_message_count": context_selection.compacted_message_count,
            "compaction_applied": context_selection.compaction_applied,
            "compaction_reason": context_selection.compaction_reason,
            "token_budget_satisfied": context_selection.token_budget_satisfied,
            "token_overflow": context_selection.token_overflow,
        },
        payload_refs=[plan_ref],
    )
    event_kind = (
        "context_compaction_applied"
        if context_selection.compaction_applied
        else "context_compaction_skipped"
    )
    event_data = {
        "turn_index": turn_index,
        "policy_mode": context_plan.policy_mode,
        "compaction_decision": context_plan.compaction_decision,
        "compaction_applied": context_selection.compaction_applied,
        "compaction_reason": context_selection.compaction_reason,
        "compaction_considered": context_plan.compaction_considered,
        "compaction_considered_reason": context_plan.compaction_considered_reason,
        "compaction_skip_reason": context_plan.compaction_skip_reason,
        "trigger_message_overflow": context_plan.trigger_message_overflow,
        "trigger_token_overflow": context_plan.trigger_token_overflow,
        "model_backed_requested": context_plan.model_backed_requested,
        "model_backed_used": context_plan.model_backed_used,
        "compaction_backend_mode": context_plan.compaction_backend_mode,
        "fallback_policy": context_plan.fallback_policy,
        "fallback_applied": context_plan.fallback_applied,
        "fallback_reason": context_plan.fallback_reason,
        "selected_message_count_after_selection": (
            context_plan.selected_message_count_after_selection
        ),
        "summary_slot_planned": context_plan.replacement_summary_planned,
        "carried_forward_state_planned": context_plan.carried_forward_state_planned,
        "pinned_message_indices": list(context_plan.pinned_message_indices),
        "preserved_from_turn": context_plan.preserved_from_turn,
        "candidate_turn_indices": list(context_plan.candidate_turn_indices),
        "compacted_turn_indices": list(context_plan.compacted_turn_indices),
    }
    payload_refs = [plan_ref]
    if context_plan.compaction_artifact is not None:
        compaction_ref = trace_writer.write_json_payload(
            "context_compaction_plan_artifact",
            context_plan.compaction_artifact.model_dump(mode="json"),
        )
        payload_refs.append(compaction_ref)
        event_data["compacted_message_indices"] = list(
            context_plan.compaction_artifact.compacted_message_indices
        )
        event_data["retained_message_indices"] = list(
            context_plan.compaction_artifact.retained_message_indices
        )
        event_data["artifact_reason"] = context_plan.compaction_artifact.reason
        if context_plan.compaction_artifact.summary_slot is not None:
            event_data["summary_slot_id"] = (
                context_plan.compaction_artifact.summary_slot.slot_id
            )
    trace_writer.append(
        event_kind,
        turn_index=turn_index,
        data=event_data,
        payload_refs=payload_refs,
    )


def _emit_model_request_built(
    trace_writer: RuntimeTraceWriter | None,
    turn_context: RuntimeTurnContext,
    context_result,
    *,
    history_manager: RuntimeHistoryManager,
    runtime_capabilities: RuntimeClientCapabilities,
) -> dict[str, RuntimePayloadRef | None]:
    payload_refs: dict[str, RuntimePayloadRef | None] = {
        "request": None,
        "compaction": None,
        "summary": None,
        "replacement_history": None,
        "request_history_snapshot": None,
    }
    if trace_writer is None:
        return payload_refs
    context_selection: ContextSelection = context_result.context_selection
    turn_index = turn_context.turn_index
    request_messages = turn_context.request_messages
    tool_specs = turn_context.session.tool_specs
    request_ref = trace_writer.write_json_payload(
        "model_request",
        {
            "messages": request_messages,
            "tools": tool_specs,
        },
    )
    payload_refs["request"] = request_ref
    event_payload_refs = [request_ref]
    request_history_snapshot_ref = trace_writer.write_json_payload(
        "request_history_snapshot",
        {
            "turn_index": turn_index,
            "request_history_item_ids": list(
                getattr(context_result, "request_history_item_ids", [])
            ),
            "request_history_item_kinds": list(
                getattr(context_result, "request_history_item_kinds", [])
            ),
            "request_history_source_indices": list(
                getattr(context_result, "request_history_source_indices", [])
            ),
            "context_selection_retained_entry_id": getattr(
                context_result,
                "context_selection_retained_entry_id",
                None,
            ),
            "selected_retained_entry_ids": list(
                getattr(context_result, "selected_retained_entry_ids", [])
            ),
            "omitted_retained_entry_ids": list(
                getattr(context_result, "omitted_retained_entry_ids", [])
            ),
            "summary_retained_entry_id": getattr(
                context_result,
                "summary_retained_entry_id",
                None,
            ),
            "carried_forward_state_entry_id": getattr(
                context_result,
                "carried_forward_state_entry_id",
                None,
            ),
            "retained_history_last_entry_id": getattr(
                context_result,
                "retained_history_last_entry_id",
                None,
            ),
            "retained_entry_count_before_snapshot": getattr(
                context_result,
                "retained_entry_count_before_snapshot",
                history_manager.retained_history_entry_count(),
            ),
            "retained_entry_count_after_snapshot": getattr(
                context_result,
                "retained_entry_count_after_snapshot",
                history_manager.retained_history_entry_count(),
            ),
            "request_history_item_count_before_snapshot": getattr(
                context_result,
                "request_history_item_count_before_snapshot",
                len(request_messages),
            ),
            "request_history_item_count_after_snapshot": getattr(
                context_result,
                "request_history_item_count_after_snapshot",
                len(request_messages),
            ),
            "replacement_history_active": getattr(
                context_result,
                "replacement_history_active",
                False,
            ),
            "replacement_history_record_id": getattr(
                context_result,
                "replacement_history_record_id",
                None,
            ),
        },
    )
    payload_refs["request_history_snapshot"] = request_history_snapshot_ref
    event_payload_refs.append(request_history_snapshot_ref)
    if context_result.compaction_artifact is not None:
        compaction_ref = trace_writer.write_json_payload(
            "context_compaction_artifact",
            context_result.compaction_artifact.model_dump(mode="json"),
        )
        payload_refs["compaction"] = compaction_ref
        event_payload_refs.append(compaction_ref)
    if context_result.synthetic_summary_message is not None:
        summary_ref = trace_writer.write_json_payload(
            "synthetic_summary_message",
            context_result.synthetic_summary_message.model_dump(mode="json"),
        )
        payload_refs["summary"] = summary_ref
        event_payload_refs.append(summary_ref)
    replacement_history_record = getattr(
        context_result,
        "replacement_history_record",
        None,
    )
    if replacement_history_record is not None:
        replacement_ref = trace_writer.write_json_payload(
            "replacement_history",
            replacement_history_record.model_dump(mode="json"),
        )
        payload_refs["replacement_history"] = replacement_ref
        event_payload_refs.append(replacement_ref)
    trace_writer.append(
        "model_request_built",
        turn_index=turn_index,
        data={
            "turn_index": turn_index,
            "message_count": len(request_messages),
            "protocol_mode": runtime_capabilities.protocol_mode,
            "supports_native_tools": runtime_capabilities.supports_native_tools,
            "included_message_indices": list(
                context_selection.included_message_indices
            ),
            "omitted_message_count": context_selection.omitted_message_count,
            "compacted_message_count": context_selection.compacted_message_count,
            "compaction_applied": context_selection.compaction_applied,
            "compaction_reason": context_selection.compaction_reason,
            "compaction_considered": context_result.context_selection_plan.compaction_considered,
            "compaction_considered_reason": (
                context_result.context_selection_plan.compaction_considered_reason
            ),
            "compaction_skip_reason": (
                context_result.context_selection_plan.compaction_skip_reason
            ),
            "trigger_message_overflow": (
                context_result.context_selection_plan.trigger_message_overflow
            ),
            "trigger_token_overflow": (
                context_result.context_selection_plan.trigger_token_overflow
            ),
            "model_backed_requested": (
                context_result.context_selection_plan.model_backed_requested
            ),
            "model_backed_used": (
                context_result.context_selection_plan.model_backed_used
            ),
            "compaction_backend_mode": (
                context_result.context_selection_plan.compaction_backend_mode
            ),
            "fallback_policy": (
                context_result.context_selection_plan.fallback_policy
            ),
            "fallback_applied": (
                context_result.context_selection_plan.fallback_applied
            ),
            "fallback_reason": (
                context_result.context_selection_plan.fallback_reason
            ),
            "context_max_tokens": context_selection.context_max_tokens,
            "estimated_selected_tokens": (
                context_selection.estimated_selected_tokens
            ),
            "estimated_omitted_tokens": (
                context_selection.estimated_omitted_tokens
            ),
            "tool_token_reserve": context_selection.tool_token_reserve,
            "response_token_reserve": context_selection.response_token_reserve,
            "token_budget_satisfied": context_selection.token_budget_satisfied,
            "token_overflow": context_selection.token_overflow,
            "summary_slot_included": context_result.synthetic_summary_message is not None,
            "carried_forward_state_present": (
                context_result.compaction_artifact is not None
                and context_result.compaction_artifact.carried_forward_state is not None
            ),
            "pinned_message_indices": list(
                context_result.context_selection_plan.pinned_message_indices
            ),
            "preserved_from_turn": context_result.context_selection_plan.preserved_from_turn,
            "candidate_turn_indices": list(
                context_result.context_selection_plan.candidate_turn_indices
            ),
            "compacted_turn_indices": list(
                context_result.context_selection_plan.compacted_turn_indices
            ),
            "context_selection_retained_entry_id": getattr(
                context_result,
                "context_selection_retained_entry_id",
                None,
            ),
            "selected_retained_entry_ids": list(
                getattr(context_result, "selected_retained_entry_ids", [])
            ),
            "omitted_retained_entry_ids": list(
                getattr(context_result, "omitted_retained_entry_ids", [])
            ),
            "summary_retained_entry_id": getattr(
                context_result,
                "summary_retained_entry_id",
                None,
            ),
            "carried_forward_state_entry_id": getattr(
                context_result,
                "carried_forward_state_entry_id",
                None,
            ),
            "retained_history_last_entry_id": getattr(
                context_result,
                "retained_history_last_entry_id",
                history_manager.retained_history_last_entry_id(),
            ),
            "retained_entry_count_before_snapshot": getattr(
                context_result,
                "retained_entry_count_before_snapshot",
                history_manager.retained_history_entry_count(),
            ),
            "retained_entry_count_after_snapshot": getattr(
                context_result,
                "retained_entry_count_after_snapshot",
                history_manager.retained_history_entry_count(),
            ),
            "request_history_item_count_before_snapshot": getattr(
                context_result,
                "request_history_item_count_before_snapshot",
                len(request_messages),
            ),
            "request_history_item_count_after_snapshot": getattr(
                context_result,
                "request_history_item_count_after_snapshot",
                len(request_messages),
            ),
            "replacement_history_active": getattr(
                context_result,
                "replacement_history_active",
                False,
            ),
            "replacement_history_record_id": getattr(
                context_result,
                "replacement_history_record_id",
                None,
            ),
        },
        payload_refs=event_payload_refs,
    )
    return payload_refs


def _emit_model_response_received(
    trace_writer: RuntimeTraceWriter | None,
    turn_index: int,
    response: GenerateResponse,
) -> None:
    if trace_writer is None:
        return
    response_ref = trace_writer.write_json_payload(
        "provider_response_envelope",
        response.model_dump(mode="json"),
    )
    trace_writer.append(
        "model_response_received",
        turn_index=turn_index,
        data={
            "turn_index": turn_index,
            "transport_mode": response.transport_mode,
            "assistant_text_present": bool(response.assistant_text),
            "tool_call_candidate_count": len(response.tool_calls),
            "finish_reason": response.finish_reason,
            "response_id": response.response_id,
        },
        payload_refs=[response_ref],
    )


def _emit_provider_response_interpreted(
    trace_writer: RuntimeTraceWriter | None,
    turn_index: int,
    parsed: ParseResult,
    *,
    runtime_capabilities: RuntimeClientCapabilities,
) -> None:
    if trace_writer is None:
        return
    interpretation_ref = trace_writer.write_json_payload(
        "provider_response_interpretation",
        {
            "transport_mode": parsed.transport_mode,
            "assistant_content": parsed.assistant_content,
            "tool_calls": [tool_call.model_dump(mode="json") for tool_call in parsed.tool_calls],
            "parse_errors": list(parsed.parse_errors),
            "protocol_errors": list(parsed.protocol_errors),
            "parse_status": parsed.parse_status,
            "format_family": parsed.format_family,
            "fallback_parser_used": parsed.fallback_parser_used,
            "protocol_decision": parsed.protocol_decision,
            "protocol_error_kind": parsed.protocol_error_kind,
            "text_fallback_used": parsed.text_fallback_used,
            "fallback_reason": parsed.fallback_reason,
            "fallback_allowed": parsed.fallback_allowed,
            "tool_call_candidate_count": parsed.tool_call_candidate_count,
            "accepted_tool_call_count": parsed.accepted_tool_call_count,
            "rejected_tool_call_candidate_count": parsed.rejected_tool_call_candidate_count,
            "finish_reason": parsed.finish_reason,
            "provider_response_id": parsed.provider_response_id,
            "raw_provider_payload": parsed.raw_provider_payload,
        },
    )
    trace_writer.append(
        "provider_response_interpreted",
        turn_index=turn_index,
        data={
            "turn_index": turn_index,
            "transport_mode": parsed.transport_mode,
            "assistant_text_present": bool(parsed.assistant_content),
            "tool_call_candidate_count": parsed.tool_call_candidate_count,
            "tool_call_count": len(parsed.tool_calls),
            "parse_status": parsed.parse_status,
            "protocol_error_count": len(parsed.protocol_errors),
            "parse_error_count": len(parsed.parse_errors),
            "fallback_parser_used": parsed.fallback_parser_used,
            "protocol_decision": parsed.protocol_decision,
            "protocol_error_kind": parsed.protocol_error_kind,
            "text_fallback_used": parsed.text_fallback_used,
            "fallback_reason": parsed.fallback_reason,
            "fallback_allowed": parsed.fallback_allowed,
            "accepted_tool_call_count": parsed.accepted_tool_call_count,
            "rejected_tool_call_candidate_count": parsed.rejected_tool_call_candidate_count,
            "expected_protocol_mode": runtime_capabilities.protocol_mode,
            "finish_reason": parsed.finish_reason,
        },
        payload_refs=[interpretation_ref],
    )


def _emit_assistant_parse_completed(
    trace_writer: RuntimeTraceWriter | None,
    turn_index: int,
    parsed: ParseResult,
) -> None:
    if trace_writer is None:
        return
    parse_ref = trace_writer.write_json_payload(
        "assistant_parse_result",
        {
            "normalized_text": parsed.normalized_text,
            "assistant_content": parsed.assistant_content,
            "tool_calls": [tool_call.model_dump(mode="json") for tool_call in parsed.tool_calls],
            "fatal_errors": list(parsed.fatal_errors),
            "protocol_errors": list(parsed.protocol_errors),
            "recovery_warnings": list(parsed.recovery_warnings),
            "normalization_actions": list(parsed.normalization_actions),
            "format_family": parsed.format_family,
            "parse_status": parsed.parse_status,
            "transport_mode": parsed.transport_mode,
            "protocol_decision": parsed.protocol_decision,
            "protocol_error_kind": parsed.protocol_error_kind,
            "text_fallback_used": parsed.text_fallback_used,
            "fallback_reason": parsed.fallback_reason,
            "fallback_allowed": parsed.fallback_allowed,
            "fallback_parser_used": parsed.fallback_parser_used,
            "tool_call_candidate_count": parsed.tool_call_candidate_count,
            "accepted_tool_call_count": parsed.accepted_tool_call_count,
            "rejected_tool_call_candidate_count": parsed.rejected_tool_call_candidate_count,
            "finish_reason": parsed.finish_reason,
            "provider_response_id": parsed.provider_response_id,
        },
    )
    trace_writer.append(
        "assistant_parse_completed",
        turn_index=turn_index,
        data={
            "turn_index": turn_index,
            "assistant_content_present": bool(parsed.assistant_content),
            "tool_call_count": len(parsed.tool_calls),
            "parse_errors": list(parsed.parse_errors),
            "parse_status": parsed.parse_status,
            "format_family": parsed.format_family,
            "transport_mode": parsed.transport_mode,
            "protocol_decision": parsed.protocol_decision,
            "protocol_error_kind": parsed.protocol_error_kind,
            "text_fallback_used": parsed.text_fallback_used,
            "fallback_reason": parsed.fallback_reason,
            "fallback_allowed": parsed.fallback_allowed,
            "fallback_parser_used": parsed.fallback_parser_used,
            "tool_call_candidate_count": parsed.tool_call_candidate_count,
            "accepted_tool_call_count": parsed.accepted_tool_call_count,
            "rejected_tool_call_candidate_count": parsed.rejected_tool_call_candidate_count,
            "fatal_error_count": len(parsed.fatal_errors),
            "protocol_error_count": len(parsed.protocol_errors),
            "recovery_warning_count": len(parsed.recovery_warnings),
            "recovery_warnings": list(parsed.recovery_warnings),
            "normalization_actions": list(parsed.normalization_actions),
        },
        payload_refs=[parse_ref],
    )


def _emit_tool_call_validation_completed(
    trace_writer: RuntimeTraceWriter | None,
    turn_index: int,
    call: ToolCall,
    inspection: ToolExecutionInspection,
    exposed_args_ref: RuntimePayloadRef | None,
) -> None:
    if trace_writer is None:
        return
    payload_refs = [exposed_args_ref] if exposed_args_ref is not None else []
    trace_writer.append(
        "tool_call_validation_completed",
        turn_index=turn_index,
        tool_call_id=call.id,
        data={
            "turn_index": turn_index,
            "tool_call_id": call.id,
            "exposed_tool_name": call.name,
            "schema_valid": inspection.schema_valid,
            "validation_error": None if inspection.schema_valid else inspection.error_message,
        },
        payload_refs=payload_refs,
    )


def _emit_tool_call_mapping_completed(
    trace_writer: RuntimeTraceWriter | None,
    turn_index: int,
    call: ToolCall,
    inspection: ToolExecutionInspection,
    exposed_args_ref: RuntimePayloadRef | None,
) -> None:
    if trace_writer is None:
        return
    payload_refs: list[RuntimePayloadRef] = []
    if exposed_args_ref is not None:
        payload_refs.append(exposed_args_ref)
    if inspection.mapping_valid and inspection.canonical_args is not None:
        canonical_args_ref = trace_writer.write_json_payload(
            "canonical_arguments",
            inspection.canonical_args,
        )
        payload_refs.append(canonical_args_ref)
    trace_writer.append(
        "tool_call_mapping_completed",
        turn_index=turn_index,
        tool_call_id=call.id,
        data={
            "turn_index": turn_index,
            "tool_call_id": call.id,
            "exposed_tool_name": call.name,
            "canonical_tool_name": (
                inspection.canonical_tool.canonical_name
                if inspection.canonical_tool is not None
                else call.canonical_name
            ),
            "mapping_valid": inspection.mapping_valid,
            "mapping_error": None if inspection.mapping_valid else inspection.error_message,
        },
        payload_refs=payload_refs,
    )


def _emit_tool_execution_started(
    trace_writer: RuntimeTraceWriter | None,
    turn_index: int,
    call: ToolCall,
    inspection: ToolExecutionInspection,
) -> None:
    if trace_writer is None or inspection.canonical_tool is None:
        return
    trace_writer.append(
        "tool_execution_started",
        turn_index=turn_index,
        tool_call_id=call.id,
        data={
            "turn_index": turn_index,
            "tool_call_id": call.id,
            "canonical_tool_name": inspection.canonical_tool.canonical_name,
        },
    )


def _emit_tool_execution_result(
    trace_writer: RuntimeTraceWriter | None,
    turn_index: int,
    call: ToolCall,
    inspection: ToolExecutionInspection,
    result: ToolResult,
) -> None:
    if trace_writer is None:
        return
    result_ref = trace_writer.write_json_payload(
        "tool_result",
        result.model_dump(mode="json"),
    )
    canonical_tool_name = (
        inspection.canonical_tool.canonical_name
        if inspection.canonical_tool is not None
        else call.canonical_name
    )
    metadata = result.metadata or {}
    target_paths = metadata.get("resolved_target_paths")
    target_file_count = metadata.get("target_file_count")
    if target_file_count is None and isinstance(target_paths, list):
        target_file_count = len(target_paths)
    execution_summary = {
        "execution_kind": metadata.get("execution_kind"),
        "execution_stage": metadata.get("execution_stage") or metadata.get("stage"),
        "policy_decision": metadata.get("policy_decision"),
        "policy_reason": metadata.get("policy_reason"),
        "policy_reason_code": metadata.get("policy_reason_code"),
        "policy_domain": metadata.get("policy_domain"),
        "command_family": metadata.get("command_family"),
        "target_file_count": target_file_count,
    }
    if result.is_error or not result.ok:
        trace_writer.append(
            "tool_execution_failed",
            turn_index=turn_index,
            tool_call_id=call.id,
            data={
                "turn_index": turn_index,
                "tool_call_id": call.id,
                "canonical_tool_name": canonical_tool_name,
                "error_type": str(result.metadata.get("error_type") or "tool_execution_error"),
                "error_message": result.content,
                **execution_summary,
            },
            payload_refs=[result_ref],
        )
        return
    trace_writer.append(
        "tool_execution_completed",
        turn_index=turn_index,
        tool_call_id=call.id,
        data={
            "turn_index": turn_index,
            "tool_call_id": call.id,
            "canonical_tool_name": canonical_tool_name,
            "ok": result.ok,
            "is_error": result.is_error,
            **execution_summary,
        },
        payload_refs=[result_ref],
    )


def _make_blocked_finish_result(
    call: ToolCall,
    recovery_state: RuntimeRecoveryState,
    *,
    policy_input,
) -> ToolResult | None:
    assessment = assess_completion_block(
        recovery_state,
        meaningful_progress_observed=policy_input.meaningful_progress_observed,
        progress_gate_applicable=policy_input.progress_gate_applicable,
        recent_failure_kind=policy_input.recent_failure_kind,
    )
    detail = assessment.detail
    if not detail:
        return None
    finish_block_reason = assessment.block_reason
    expected_next_step = (
        "retry_parse_or_tool"
        if finish_block_reason == "no_meaningful_progress"
        else recovery_state.expected_next_step().value
    )
    completion_gate_status = recovery_state.completion_gate_status().value
    active_issue = recovery_state.current_or_last_validation_issue()
    answer = str(call.arguments.get("answer") or "")
    summary = str(call.arguments.get("summary") or "")
    content = (
        f"{detail}\n"
        f"Next step: {expected_next_step}."
    )
    return ToolResult(
        ok=False,
        content=content,
        is_error=True,
        metadata={
            "error_type": "completion_blocked",
            "stage": "runtime_stop_policy",
            "execution_stage": "runtime_stop_policy",
            "execution_kind": "finish_signal",
            "operation": "finish",
            "policy_domain": "runtime",
            "policy_decision": "deny",
            "policy_reason": detail,
            "policy_reason_code": "completion_blocked",
            "stop_hook_reason_code": stop_hook_reason_code_for_block_reason(
                finish_block_reason
            ),
            "is_finish": True,
            "answer_present": bool(answer),
            "summary_present": bool(summary),
            "finish_blocked_by_policy": True,
            "completion_block_family": assessment.completion_block_family.value,
            "finish_block_reason": finish_block_reason,
            "finish_gate_reason": finish_block_reason,
            "completion_gate_status": completion_gate_status,
            "expected_next_step": expected_next_step,
            "recent_failure_kind": policy_input.recent_failure_kind,
            "meaningful_progress_observed": (
                policy_input.meaningful_progress_observed
            ),
            "completion_allowed": assessment.completion_allowed,
            "validation_evidence_fresh": assessment.validation_evidence_fresh,
            "active_failure_kind": assessment.active_failure_kind,
            "corrective_progress_after_failure": (
                assessment.corrective_progress_after_failure
            ),
            "post_mutation_validation_pending": (
                assessment.post_mutation_validation_pending
            ),
            "active_validation_issue_kind": recovery_state.active_validation_issue_kind(),
            "active_validation_issue_id": (
                active_issue.issue_id if active_issue is not None else None
            ),
            "pending_issue_kind": _pending_issue_kind_value(
                recovery_state.pending_issue_kind
            ),
        },
    )


def _emit_tool_result_appended(
    trace_writer: RuntimeTraceWriter | None,
    turn_index: int,
    call: ToolCall,
) -> None:
    if trace_writer is None:
        return
    trace_writer.append(
        "tool_result_appended",
        turn_index=turn_index,
        tool_call_id=call.id,
        data={
            "turn_index": turn_index,
            "tool_call_id": call.id,
            "tool_name": call.name,
            "canonical_tool_name": call.canonical_name,
        },
    )


def _emit_turn_stop_decision(
    trace_writer: RuntimeTraceWriter | None,
    turn_index: int,
    stop_decision,
    turn_state: RuntimeTurnState,
    session_state: RuntimeSessionState,
    *,
    history_manager: RuntimeHistoryManager,
) -> None:
    if trace_writer is None:
        return
    data = {
        "turn_index": turn_index,
        "should_stop": stop_decision.should_stop,
        "reason": (
            stop_decision.reason.value
            if stop_decision.reason is not None
            else None
        ),
        "detail": stop_decision.detail,
        "decision_code": stop_decision.decision_code,
        "continuation_decision_kind": turn_state.continuation_decision_kind,
        "termination_kind": turn_state.termination_kind,
        "continue_reason": stop_decision.continue_reason,
        "completion_block_family": stop_decision.completion_block_family,
        "policy_mode": stop_decision.policy_mode,
        "model_needs_follow_up": stop_decision.model_needs_follow_up,
        "runtime_needs_follow_up": stop_decision.runtime_needs_follow_up,
        "stop_hook_evaluated": stop_decision.stop_hook_evaluated,
        "stop_hook_blocked": stop_decision.stop_hook_blocked,
        "stop_hook_reason": stop_decision.stop_hook_reason,
        "stop_hook_reason_code": stop_decision.stop_hook_reason_code,
        "pending_issue_id": turn_state.pending_issue_id_after_turn,
        "pending_issue_kind": stop_decision.pending_issue_kind,
        "active_validation_issue_kind": stop_decision.active_validation_issue_kind,
        "active_validation_issue_id": stop_decision.active_validation_issue_id,
        "validation_phase_after_turn": turn_state.validation_phase_after_turn,
        "expected_next_step": stop_decision.expected_next_step,
        "completion_gate_status": stop_decision.completion_gate_status,
        "finish_blocked_by_policy": stop_decision.finish_blocked_by_policy,
        "finish_block_reason": stop_decision.finish_block_reason,
        "finish_gate_reason": stop_decision.finish_gate_reason,
        "finish_attempted": stop_decision.finish_attempted,
        "completion_allowed": stop_decision.completion_allowed,
        "validation_evidence_fresh": stop_decision.validation_evidence_fresh,
        "meaningful_progress_observed": stop_decision.meaningful_progress_observed,
        "recent_failure_kind": stop_decision.recent_failure_kind,
        "active_failure_kind": stop_decision.active_failure_kind,
        "corrective_progress_after_failure": (
            stop_decision.corrective_progress_after_failure
        ),
        "post_mutation_validation_pending": (
            stop_decision.post_mutation_validation_pending
        ),
        "turn_action": turn_state.turn_action,
        "turn_outcome": turn_state.turn_outcome,
        "requested_tool_call_count": turn_state.requested_tool_call_count,
        "executed_tool_call_count": turn_state.executed_tool_call_count,
        "successful_tool_call_count": turn_state.successful_tool_call_count,
        "validation_attempt_count": stop_decision.validation_attempt_count,
        "revision_attempt_count": stop_decision.revision_attempt_count,
        "finish_deferral_count": stop_decision.finish_deferral_count,
        "context_token_budget": turn_state.context_token_budget,
        "selected_context_tokens": turn_state.selected_context_tokens,
        "token_budget_satisfied": turn_state.token_budget_satisfied,
        "token_overflow_reason": turn_state.token_overflow_reason,
        "summary_slot_status_after_turn": turn_state.summary_slot_status_after_turn,
        "carried_forward_state_present_after_turn": (
            turn_state.carried_forward_state_present_after_turn
        ),
        "replacement_history_active_after_turn": (
            turn_state.replacement_history_active_after_turn
        ),
        "replacement_history_record_id": turn_state.replacement_history_record_id,
        "retained_history_last_entry_id": history_manager.retained_history_last_entry_id(),
        "retained_entry_count": history_manager.retained_history_entry_count(),
        "session_continuation_turn_count": len(session_state.continuation_ledger),
        "validation_budget_remaining": session_state.validation_budget_remaining,
        "revision_budget_remaining": session_state.revision_budget_remaining,
        "finish_deferral_budget_remaining": (
            session_state.finish_deferral_budget_remaining
        ),
        "consecutive_no_progress_turns": session_state.consecutive_no_progress_turns,
    }
    if stop_decision.completion_evidence_status not in {None, "not_required"}:
        data["completion_evidence_status"] = stop_decision.completion_evidence_status
    if stop_decision.last_successful_validation_turn is not None:
        data["last_successful_validation_turn"] = (
            stop_decision.last_successful_validation_turn
        )
    if stop_decision.last_validation_attempt_turn is not None:
        data["last_validation_attempt_turn"] = (
            stop_decision.last_validation_attempt_turn
        )
    if stop_decision.last_validation_failure_turn is not None:
        data["last_validation_failure_turn"] = (
            stop_decision.last_validation_failure_turn
        )
    if stop_decision.last_mutation_turn is not None:
        data["last_mutation_turn"] = stop_decision.last_mutation_turn
    turn_state_ref = trace_writer.write_json_payload(
        "turn_state",
        turn_state.model_dump(mode="json"),
    )
    trace_writer.append(
        "turn_stop_decision",
        turn_index=turn_index,
        data=data,
        payload_refs=[turn_state_ref],
    )


def _emit_run_completed(
    trace_writer: RuntimeTraceWriter | None,
    session_state: RuntimeSessionState,
    metadata: dict[str, Any],
    *,
    history_manager: RuntimeHistoryManager,
) -> None:
    if trace_writer is None:
        return
    session_payload = trace_writer.write_json_payload(
        "session_state",
        session_state.model_dump(mode="json"),
    )
    trace_writer.append(
        "run_completed",
        data={
            "total_turns": metadata["total_turns"],
            "final_status": metadata.get("final_status") or session_state.final_status,
            "stop_reason": metadata["stop_reason"],
            "stop_detail": metadata["stop_detail"],
            "stop_decision_code": metadata["stop_decision_code"],
            "pending_issue_kind": metadata["pending_issue_kind"],
            "pending_issue_cleared": metadata["pending_issue_cleared"],
            "session_stop_status": session_state.session_stop_status,
            "session_termination_kind": session_state.session_termination_kind,
            "validation_budget_remaining": session_state.validation_budget_remaining,
            "revision_budget_remaining": session_state.revision_budget_remaining,
            "finish_deferral_budget_remaining": (
                session_state.finish_deferral_budget_remaining
            ),
            "budget_snapshot": metadata.get("budget_snapshot"),
            "session_outcome": metadata.get("session_outcome"),
            "last_turn_continuation": metadata.get("last_turn_continuation"),
            "retained_history": history_manager.retained_history_summary(),
        },
        payload_refs=[session_payload],
    )


class AgentRunner:
    """Alternative class-based interface for running agents."""

    def __init__(
        self,
        client: BaseLLMClient,
        runtime: ToolRuntime,
        profile: ToolProfile,
        *,
        context_policy_mode: ContextPolicyMode | str = (
            ContextPolicyMode.FULL_HISTORY.value
        ),
        context_max_messages: int | None = None,
        context_max_tokens: int | None = None,
        tool_token_reserve: int = 0,
        response_token_reserve: int = 0,
    ) -> None:
        self.client = client
        self.runtime = runtime
        self.profile = profile
        self.context_policy_mode = ContextPolicyMode(str(context_policy_mode)).value
        self.context_max_messages = context_max_messages
        self.context_max_tokens = context_max_tokens
        self.tool_token_reserve = tool_token_reserve
        self.response_token_reserve = response_token_reserve

    def run(self, task: CodingTask, ctx: ToolContext) -> Trajectory:
        return run_agent_task(
            task=task,
            client=self.client,
            runtime=self.runtime,
            profile=self.profile,
            ctx=ctx,
            context_policy_mode=self.context_policy_mode,
            context_max_messages=self.context_max_messages,
            context_max_tokens=self.context_max_tokens,
            tool_token_reserve=self.tool_token_reserve,
            response_token_reserve=self.response_token_reserve,
        )
