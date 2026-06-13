from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.agent.history_evolution import (
    build_history_evolution_report_from_paths,
)
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


def test_history_evolution_report_tracks_append_only_turn_growth() -> None:
    tmp_path = make_unique_test_dir("history_evolution")
    try:
        repo = _make_repo(tmp_path)
        output_dir = tmp_path / "output"
        task = CodingTask(
            task_id="history_evolution_task",
            repo_path=repo,
            prompt="Inspect main.py and finish.",
            max_turns=5,
        )
        client = FakeLLMClient(
            responses=[
                _native_response(
                    assistant_text="Inspecting.",
                    call_id="c1",
                    name="read_file",
                    arguments={"path": "main.py"},
                    response_id="resp_1",
                ),
                _native_response(
                    assistant_text="Done.",
                    call_id="c2",
                    name="finish",
                    arguments={"answer": "Done"},
                    response_id="resp_2",
                ),
            ]
        )

        trajectory = run_coding_task(task, client, output_dir)
        assert trajectory.metadata["history_evolution_report_ok"] is True
        assert trajectory.metadata["retained_history_log_id"].startswith("output:")
        assert trajectory.metadata["retained_history_entry_count"] == 8
        assert trajectory.metadata["request_context_log_id"].startswith("output:")
        assert trajectory.metadata["request_context_entry_count"] == 2
        report_path = Path(trajectory.metadata["history_evolution_report_path"])
        assert report_path.exists()

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["ok"] is True
        assert report["turn_count"] == 2
        assert [transition["transition_kind"] for transition in report["transitions"]] == [
            "initial_snapshot",
            "append_only",
        ]
        assert report["transitions"][1]["prefix_carryover_ok"] is True
        assert report["transitions"][1]["appended_suffix_ok"] is True
        assert report["transitions"][1]["appended_source_message_count"] == 2
        assert report["transitions"][1]["appended_source_indices"] == [2, 3]
    finally:
        cleanup_test_path(tmp_path)


def test_history_evolution_report_accepts_model_backed_compaction_fixture() -> None:
    fixture_dir = Path(
        "tests/fixtures/local_runtime_trace_bundle_model_backed_compaction"
    )
    report = build_history_evolution_report_from_paths(
        request_context_path=fixture_dir / "request_context.jsonl",
        retained_history_path=fixture_dir / "retained_history.jsonl",
    )

    assert report.ok is True
    assert report.turn_count == 4
    assert report.transition_count == 4
    assert report.total_compaction_transition_count == 1
    assert report.transitions[-1].transition_kind == "replacement_compaction"
    assert report.transitions[-1].prefix_carryover_ok is True
    assert report.transitions[-1].appended_suffix_ok is True
    assert report.transitions[-1].snapshot_appended_kinds == [
        "replacement_summary",
        "carry_forward_state",
        "history_control",
        "history_control",
    ]
