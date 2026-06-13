from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.agent.history_lineage import write_history_lineage_report
from pycodeagent.agent.llm_client import (
    FakeLLMClient,
    GenerateResponse,
    ToolCallCandidate,
)
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


def _make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (repo / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return repo


def _native_response(
    *,
    assistant_text: str = "",
    call_id: str | None = None,
    name: str | None = None,
    arguments: dict | None = None,
    finish_reason: str | None = None,
    response_id: str | None = None,
) -> GenerateResponse:
    tool_calls: list[ToolCallCandidate] = []
    if name is not None:
        tool_calls.append(
            ToolCallCandidate(
                call_id=call_id,
                name=name,
                arguments_raw=json.dumps(arguments or {}, ensure_ascii=False),
                arguments_obj=arguments or {},
                source="native",
            )
        )
    return GenerateResponse.from_native_tool_calling(
        assistant_text=assistant_text,
        tool_calls=tool_calls,
        finish_reason=finish_reason or ("tool_calls" if tool_calls else "stop"),
        response_id=response_id,
    )


def test_history_lineage_report_accepts_model_backed_compaction_fixture() -> None:
    fixture_dir = Path(
        "tests/fixtures/local_runtime_trace_bundle_model_backed_compaction"
    )
    report = write_history_lineage_report(fixture_dir)

    assert report.ok is True
    assert report.replacement_record_count == 1
    assert report.records[0].record_id == "replacement_history_000001"
    assert report.records[0].summary_retained_entry_id == "retained_entry_000012"
    assert report.records[0].carried_forward_state_entry_id == "retained_entry_000013"
    assert report.records[0].compaction_artifact_entry_id == "retained_entry_000014"
    assert report.records[0].source_retained_entry_ids == [
        "retained_entry_000004",
        "retained_entry_000005",
        "retained_entry_000007",
        "retained_entry_000008",
    ]


def test_run_coding_task_persists_history_lineage_report() -> None:
    tmp_path = make_unique_test_dir("history_lineage")
    try:
        repo = _make_repo(tmp_path)
        output_dir = tmp_path / "output"
        task = CodingTask(
            task_id="history_lineage_task",
            repo_path=repo,
            prompt="Inspect, inspect again, inspect once more, and finish.",
            max_turns=6,
        )
        compaction_output = {
            "summary_text": "[model compacted context]\ncovered_turns=1-2\nnext_focus=latest inspection context",
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
                "carried_notes": ["Model-backed compaction preserved the earlier inspections."],
            },
            "compacted_span": {
                "source_message_indices": [2, 3, 4, 5],
                "source_turn_indices": [1, 2],
                "pinned_message_indices": [0, 1],
                "replacement_summary_kind": "model_backed_compaction",
            },
        }
        client = FakeLLMClient(
            responses=[
                _native_response(call_id="c1", name="read_file", arguments={"path": "main.py"}, response_id="resp_1"),
                _native_response(call_id="c2", name="list_files", arguments={"path": "."}, response_id="resp_2"),
                _native_response(call_id="c3", name="read_file", arguments={"path": "main.py"}, response_id="resp_3"),
                GenerateResponse.from_native_tool_calling(
                    assistant_text=json.dumps(compaction_output, ensure_ascii=False),
                    tool_calls=[],
                    finish_reason="stop",
                    response_id="resp_compact",
                    request_kind="context_compaction",
                    structured_output=compaction_output,
                ),
                _native_response(call_id="c4", name="finish", arguments={"answer": "Done"}, response_id="resp_4"),
            ]
        )

        trajectory = run_coding_task(
            task,
            client,
            output_dir,
            context_policy_mode="model_backed_compaction",
            context_max_messages=6,
        )
        assert trajectory.metadata["history_lineage_report_ok"] is True
        lineage_path = Path(trajectory.metadata["history_lineage_report_path"])
        assert lineage_path.exists()
        lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
        assert lineage["replacement_record_count"] == 1
        assert lineage["records"][0]["record_id"] == "replacement_history_000001"
        assert lineage["records"][0]["compaction_artifact_entry_id"] == "retained_entry_000014"
    finally:
        cleanup_test_path(tmp_path)
