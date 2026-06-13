from __future__ import annotations

from pathlib import Path

from pycodeagent.agent.llm_client import FakeLLMClient, GenerateResponse, ToolCallCandidate
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.eval.runtime_behavior_audit import build_runtime_behavior_audit
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


def _make_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
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
                arguments_raw=__import__("json").dumps(arguments or {}, ensure_ascii=False),
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


def test_runtime_behavior_audit_records_lite_failure_buckets() -> None:
    tmp_path = make_unique_test_dir("runtime_behavior_buckets")
    try:
        batch_dir = tmp_path / "batch"
        batch_dir.mkdir(parents=True, exist_ok=True)

        no_progress_repo = _make_repo(tmp_path, "repo_no_progress")
        no_progress_task = CodingTask(
            task_id="no_progress_task",
            repo_path=no_progress_repo,
            prompt="Inspect the file before finishing.",
            max_turns=3,
        )
        run_coding_task(
            no_progress_task,
            FakeLLMClient(
                responses=[
                    _native_response(
                        call_id="c1",
                        name="read_file",
                        arguments={"path": "main.py"},
                        response_id="resp_1",
                    ),
                    _native_response(
                        call_id="c2",
                        name="read_file",
                        arguments={"path": "main.py"},
                        response_id="resp_2",
                    ),
                    _native_response(
                        call_id="c3",
                        name="finish",
                        arguments={"answer": "Done"},
                        response_id="resp_3",
                    ),
                ]
            ),
            batch_dir / "no_progress_task__base",
        )

        malformed_repo = _make_repo(tmp_path, "repo_malformed")
        malformed_task = CodingTask(
            task_id="malformed_task",
            repo_path=malformed_repo,
            prompt="Read the file.",
            max_turns=2,
        )
        run_coding_task(
            malformed_task,
            FakeLLMClient(
                responses=[
                    GenerateResponse.from_native_tool_calling(
                        assistant_text="I will read the file.",
                        tool_calls=[
                            ToolCallCandidate(
                                call_id="c1",
                                name="read_file",
                                arguments_raw='{"path":',
                                arguments_parse_error="Expecting value",
                                source="native",
                            )
                        ],
                        finish_reason="tool_calls",
                        response_id="resp_bad",
                    )
                ]
            ),
            batch_dir / "malformed_task__base",
        )

        audit = build_runtime_behavior_audit(
            batch_dir,
            batch_dir / "runtime_behavior_audit.json",
            source_type="batch",
        )

        no_progress_run = next(run for run in audit.per_run if run.task_id == "no_progress_task")
        assert no_progress_run.saw_finish_without_progress is True
        assert no_progress_run.finish_without_progress_count == 1
        assert "finish_without_progress" in no_progress_run.observed_failure_buckets
        assert "no_meaningful_progress" in no_progress_run.observed_failure_buckets

        malformed_run = next(run for run in audit.per_run if run.task_id == "malformed_task")
        assert malformed_run.saw_schema_malformed is True
        assert "protocol_malformed_turn" in malformed_run.observed_failure_buckets

        assert audit.runs_with_finish_without_progress == 2
        assert audit.runs_with_schema_malformed == 1
    finally:
        cleanup_test_path(tmp_path)
