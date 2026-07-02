from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.agent.compaction_acceptance import (
    verify_p3b_compaction_acceptance,
)
from pycodeagent.agent.llm_client import (
    FakeLLMClient,
    GenerateResponse,
    ToolCallCandidate,
)
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


def _native_response(
    *,
    assistant_text: str,
    tool_call: tuple[str, str, dict] | None = None,
    request_kind: str = "generate",
    structured_output: dict | None = None,
) -> GenerateResponse:
    tool_calls: list[ToolCallCandidate] = []
    if tool_call is not None:
        call_id, name, arguments = tool_call
        tool_calls.append(
            ToolCallCandidate(
                call_id=call_id,
                name=name,
                arguments_raw=json.dumps(arguments, ensure_ascii=False),
                arguments_obj=arguments,
                source="native",
            )
        )
    return GenerateResponse.from_native_tool_calling(
        assistant_text=assistant_text,
        tool_calls=tool_calls,
        finish_reason="tool_calls" if tool_calls else "stop",
        request_kind=request_kind,
        structured_output=structured_output,
    )


def _run_trace_bundle(
    *,
    tmp: Path,
    task_id: str,
    task_prompt: str,
    responses: list[GenerateResponse],
    max_turns: int,
    context_policy_mode: str,
    context_max_messages: int | None,
) -> tuple[Path, object]:
    repo = tmp / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")

    task = CodingTask(
        task_id=task_id,
        repo_path=repo,
        prompt=task_prompt,
        test_command='python -c "print(\'ok\')"',
        max_turns=max_turns,
    )
    output_dir = tmp / "run"
    trajectory = run_coding_task(
        task,
        FakeLLMClient(responses=responses),
        output_dir,
        tool_stack_kind="native_claude",
        context_policy_mode=context_policy_mode,
        context_max_messages=context_max_messages,
    )
    return output_dir, trajectory


def test_verify_p3b_compaction_acceptance_passes_for_model_backed_bundle() -> None:
    tmp = make_unique_test_dir("p3b_compaction_acceptance")
    try:
        compaction_output = {
            "summary_text": (
                "[model compacted context]\n"
                "covered_turns=1-2\n"
                "next_focus=latest inspection context"
            ),
            "carried_forward_state": {
                "pending_issue_kind": None,
                "pending_issue_detail": "",
                "completion_evidence_status": "not_required",
                "validation_phase": "idle",
                "last_successful_validation_turn": None,
                "last_validation_attempt_turn": None,
                "last_validation_failure_turn": None,
                "last_mutation_turn": None,
                "recent_compacted_tool_outcomes": [],
                "carried_notes": [
                    "Model-backed compaction preserved the earlier inspections."
                ],
            },
            "compacted_span": {
                "source_message_indices": [2, 3, 4, 5],
                "source_turn_indices": [1, 2],
                "pinned_message_indices": [0, 1],
                "replacement_summary_kind": "model_backed_compaction",
            },
        }
        output_dir, _ = _run_trace_bundle(
            tmp=tmp,
            task_id="trace_model_backed_compaction_task",
            task_prompt="Inspect, inspect again, inspect once more, and finish.",
            responses=[
                GenerateResponse.from_native_tool_calling(
                    assistant_text="Inspecting once.",
                    tool_calls=[
                        ToolCallCandidate(
                            call_id="c1",
                            name="Read",
                            arguments_raw='{"file_path":"main.py"}',
                            arguments_obj={"file_path": "main.py"},
                            source="native",
                        )
                    ],
                    finish_reason="tool_calls",
                    response_id="resp_1",
                ),
                GenerateResponse.from_native_tool_calling(
                    assistant_text="Inspecting again.",
                    tool_calls=[
                        ToolCallCandidate(
                            call_id="c2",
                            name="Glob",
                            arguments_raw='{"pattern":"*","path":"."}',
                            arguments_obj={"pattern": "*", "path": "."},
                            source="native",
                        )
                    ],
                    finish_reason="tool_calls",
                    response_id="resp_2",
                ),
                GenerateResponse.from_native_tool_calling(
                    assistant_text="Inspecting once more.",
                    tool_calls=[
                        ToolCallCandidate(
                            call_id="c3",
                            name="Read",
                            arguments_raw='{"file_path":"main.py"}',
                            arguments_obj={"file_path": "main.py"},
                            source="native",
                        )
                    ],
                    finish_reason="tool_calls",
                    response_id="resp_3",
                ),
                GenerateResponse.from_native_tool_calling(
                    assistant_text=json.dumps(compaction_output, ensure_ascii=False),
                    tool_calls=[],
                    finish_reason="stop",
                    response_id="resp_compact",
                    request_kind="context_compaction",
                    structured_output=compaction_output,
                ),
                GenerateResponse.from_native_tool_calling(
                    assistant_text="Done.",
                    tool_calls=[],
                    finish_reason="stop",
                    response_id="resp_4",
                ),
            ],
            max_turns=6,
            context_policy_mode="model_backed_compaction",
            context_max_messages=6,
        )

        report = verify_p3b_compaction_acceptance(
            output_dir,
            require_real_provider=False,
        )
        assert report.ok is True
        assert report.requested_count >= 1
        assert report.completed_count >= 1
        assert report.applied_count >= 1
        assert report.successful_model_backed_apply_count >= 1
        assert report.replacement_history_active is True
        assert report.history_lineage_ok is True
    finally:
        cleanup_test_path(tmp)


def test_verify_p3b_compaction_acceptance_rejects_non_model_backed_bundle() -> None:
    tmp = make_unique_test_dir("p3b_compaction_acceptance")
    try:
        output_dir, _ = _run_trace_bundle(
            tmp=tmp,
            task_id="trace_compaction_task",
            task_prompt="Inspect, inspect again, inspect once more, and finish.",
            responses=[
                GenerateResponse.from_native_tool_calling(
                    assistant_text="Inspecting once.",
                    tool_calls=[
                        ToolCallCandidate(
                            call_id="c1",
                            name="Read",
                            arguments_raw='{"file_path":"main.py"}',
                            arguments_obj={"file_path": "main.py"},
                            source="native",
                        )
                    ],
                    finish_reason="tool_calls",
                    response_id="resp_1",
                ),
                GenerateResponse.from_native_tool_calling(
                    assistant_text="Inspecting again.",
                    tool_calls=[
                        ToolCallCandidate(
                            call_id="c2",
                            name="Glob",
                            arguments_raw='{"pattern":"*","path":"."}',
                            arguments_obj={"pattern": "*", "path": "."},
                            source="native",
                        )
                    ],
                    finish_reason="tool_calls",
                    response_id="resp_2",
                ),
                GenerateResponse.from_native_tool_calling(
                    assistant_text="Inspecting once more.",
                    tool_calls=[
                        ToolCallCandidate(
                            call_id="c3",
                            name="Read",
                            arguments_raw='{"file_path":"main.py"}',
                            arguments_obj={"file_path": "main.py"},
                            source="native",
                        )
                    ],
                    finish_reason="tool_calls",
                    response_id="resp_3",
                ),
                GenerateResponse.from_native_tool_calling(
                    assistant_text="Done.",
                    tool_calls=[],
                    finish_reason="stop",
                    response_id="resp_4",
                ),
            ],
            max_turns=6,
            context_policy_mode="deterministic_compaction",
            context_max_messages=6,
        )

        report = verify_p3b_compaction_acceptance(
            output_dir,
            require_real_provider=False,
        )
        assert report.ok is False
        assert any(
            "context_compaction_requested" in error
            or "context_compaction_completed" in error
            or "context_compaction_applied" in error
            for error in report.errors
        )
    finally:
        cleanup_test_path(tmp)
