from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from pycodeagent.agent.llm_client import FakeLLMClient, GenerateResponse, ToolCallCandidate
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_NATIVE_FIXTURE_DIR = Path("tests/fixtures/local_runtime_trace_bundle_native")
_COMPACTION_FIXTURE_DIR = Path("tests/fixtures/local_runtime_trace_bundle_compaction")
_MODEL_BACKED_COMPACTION_FIXTURE_DIR = Path(
    "tests/fixtures/local_runtime_trace_bundle_model_backed_compaction"
)
_TEST_NAMESPACE = "runtime_trace_golden"
_FIXED_WORKSPACE_ID = "abc123def456"


class _FixedUuid:
    hex = "abc123def4567890abc123def4567890"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _normalize_string(value: str, *, workspace_dir: Path) -> str:
    normalized = value.replace("\r\n", "\n")
    replacements = [
        (str(workspace_dir.resolve()), "<workspace_dir>"),
        (str(workspace_dir.resolve()).replace("\\", "/"), "<workspace_dir>"),
    ]
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    return normalized


def _normalize_value(value, *, workspace_dir: Path):
    if isinstance(value, str):
        return _normalize_string(value, workspace_dir=workspace_dir)
    if isinstance(value, list):
        return [_normalize_value(item, workspace_dir=workspace_dir) for item in value]
    if isinstance(value, dict):
        return {
            key: _normalize_value(item, workspace_dir=workspace_dir)
            for key, item in value.items()
        }
    return value


def _load_normalized_fixture_json(
    fixture_dir: Path,
    relative_path: str,
):
    fixture_manifest = _load_json(fixture_dir / "runtime_trace_manifest.json")
    fixture_workspace_dir = Path(fixture_manifest["workspace_root"])
    return _normalize_value(
        _load_json(fixture_dir / relative_path),
        workspace_dir=fixture_workspace_dir,
    )


def _load_normalized_fixture_jsonl(
    fixture_dir: Path,
    relative_path: str,
) -> list[dict]:
    fixture_manifest = _load_json(fixture_dir / "runtime_trace_manifest.json")
    fixture_workspace_dir = Path(fixture_manifest["workspace_root"])
    return _normalize_value(
        _load_jsonl(fixture_dir / relative_path),
        workspace_dir=fixture_workspace_dir,
    )


def _run_trace_bundle(
    *,
    tmp: Path,
    task_id: str = "trace_task",
    task_prompt: str,
    responses: list[GenerateResponse],
    max_turns: int = 5,
    context_policy_mode: str = "full_history",
    context_max_messages: int | None = None,
) -> tuple[Path, Path]:
    repo = tmp / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    output_dir = tmp / "output"
    task = CodingTask(
        task_id=task_id,
        repo_path=repo,
        prompt=task_prompt,
        max_turns=max_turns,
    )
    client = FakeLLMClient(responses=responses)

    time_values = iter(range(1700000000000, 1700000000500))
    with patch(
        "pycodeagent.runtime_trace.writer._unix_time_ms",
        side_effect=lambda: next(time_values),
    ), patch(
        "pycodeagent.agent.retained_history._unix_time_ms",
        side_effect=lambda: next(time_values),
    ), patch(
        "pycodeagent.agent.request_context._unix_time_ms",
        side_effect=lambda: next(time_values),
    ), patch(
        "pycodeagent.env.coding_env.uuid.uuid4",
        return_value=_FixedUuid(),
    ):
        run_coding_task(
            task,
            client,
            output_dir,
            context_policy_mode=context_policy_mode,
            context_max_messages=context_max_messages,
        )

    workspace_dir = output_dir / "w" / _FIXED_WORKSPACE_ID
    return output_dir, workspace_dir


def test_native_local_runtime_trace_bundle_matches_fixture() -> None:
    tmp = make_unique_test_dir(_TEST_NAMESPACE)
    try:
        output_dir, workspace_dir = _run_trace_bundle(
            tmp=tmp,
            task_prompt="Inspect main.py and finish through native tool calling.",
            responses=[
                GenerateResponse.from_native_tool_calling(
                    assistant_text="I will inspect the file.",
                    tool_calls=[
                        ToolCallCandidate(
                            call_id="c1",
                            name="read_file",
                            arguments_raw='{"path":"main.py"}',
                            arguments_obj={"path": "main.py"},
                            source="native",
                        )
                    ],
                    finish_reason="tool_calls",
                    response_id="resp_native_1",
                ),
                GenerateResponse.from_native_tool_calling(
                    assistant_text="Done.",
                    tool_calls=[
                        ToolCallCandidate(
                            call_id="c2",
                            name="finish",
                            arguments_raw='{"answer":"Done"}',
                            arguments_obj={"answer": "Done"},
                            source="native",
                        )
                    ],
                    finish_reason="tool_calls",
                    response_id="resp_native_2",
                ),
            ],
        )

        assert _normalize_value(
            _load_json(output_dir / "runtime_trace_manifest.json"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_json(
            _NATIVE_FIXTURE_DIR,
            "runtime_trace_manifest.json",
        )

        assert _normalize_value(
            _load_jsonl(output_dir / "runtime_trace.jsonl"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_jsonl(
            _NATIVE_FIXTURE_DIR,
            "runtime_trace.jsonl",
        )

        assert _normalize_value(
            _load_json(output_dir / "retained_history_manifest.json"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_json(
            _NATIVE_FIXTURE_DIR,
            "retained_history_manifest.json",
        )

        assert _normalize_value(
            _load_jsonl(output_dir / "retained_history.jsonl"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_jsonl(
            _NATIVE_FIXTURE_DIR,
            "retained_history.jsonl",
        )

        assert _normalize_value(
            _load_json(output_dir / "request_context_manifest.json"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_json(
            _NATIVE_FIXTURE_DIR,
            "request_context_manifest.json",
        )

        assert _normalize_value(
            _load_jsonl(output_dir / "request_context.jsonl"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_jsonl(
            _NATIVE_FIXTURE_DIR,
            "request_context.jsonl",
        )

        actual_payloads = sorted(path.name for path in (output_dir / "payloads").glob("*.json"))
        fixture_payloads = sorted(path.name for path in (_NATIVE_FIXTURE_DIR / "payloads").glob("*.json"))
        assert actual_payloads == fixture_payloads

        for payload_name in fixture_payloads:
            assert _normalize_value(
                _load_json(output_dir / "payloads" / payload_name),
                workspace_dir=workspace_dir,
            ) == _load_normalized_fixture_json(
                _NATIVE_FIXTURE_DIR,
                f"payloads/{payload_name}",
            )
    finally:
        cleanup_test_path(tmp)


def test_compaction_local_runtime_trace_bundle_matches_fixture() -> None:
    tmp = make_unique_test_dir(_TEST_NAMESPACE)
    try:
        output_dir, workspace_dir = _run_trace_bundle(
            tmp=tmp,
            task_id="trace_compaction_task",
            task_prompt="Inspect, inspect again, inspect once more, and finish.",
            responses=[
                GenerateResponse.from_native_tool_calling(
                    assistant_text="Inspecting once.",
                    tool_calls=[
                        ToolCallCandidate(
                            call_id="c1",
                            name="read_file",
                            arguments_raw='{"path":"main.py"}',
                            arguments_obj={"path": "main.py"},
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
                            name="list_files",
                            arguments_raw='{"path":"."}',
                            arguments_obj={"path": "."},
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
                            name="read_file",
                            arguments_raw='{"path":"main.py"}',
                            arguments_obj={"path": "main.py"},
                            source="native",
                        )
                    ],
                    finish_reason="tool_calls",
                    response_id="resp_3",
                ),
                GenerateResponse.from_native_tool_calling(
                    assistant_text="Done.",
                    tool_calls=[
                        ToolCallCandidate(
                            call_id="c4",
                            name="finish",
                            arguments_raw='{"answer":"Done"}',
                            arguments_obj={"answer": "Done"},
                            source="native",
                        )
                    ],
                    finish_reason="tool_calls",
                    response_id="resp_4",
                ),
            ],
            max_turns=6,
            context_policy_mode="deterministic_compaction",
            context_max_messages=6,
        )

        assert _normalize_value(
            _load_json(output_dir / "runtime_trace_manifest.json"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_json(
            _COMPACTION_FIXTURE_DIR,
            "runtime_trace_manifest.json",
        )

        assert _normalize_value(
            _load_jsonl(output_dir / "runtime_trace.jsonl"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_jsonl(
            _COMPACTION_FIXTURE_DIR,
            "runtime_trace.jsonl",
        )

        assert _normalize_value(
            _load_json(output_dir / "retained_history_manifest.json"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_json(
            _COMPACTION_FIXTURE_DIR,
            "retained_history_manifest.json",
        )

        assert _normalize_value(
            _load_jsonl(output_dir / "retained_history.jsonl"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_jsonl(
            _COMPACTION_FIXTURE_DIR,
            "retained_history.jsonl",
        )

        assert _normalize_value(
            _load_json(output_dir / "request_context_manifest.json"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_json(
            _COMPACTION_FIXTURE_DIR,
            "request_context_manifest.json",
        )

        assert _normalize_value(
            _load_jsonl(output_dir / "request_context.jsonl"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_jsonl(
            _COMPACTION_FIXTURE_DIR,
            "request_context.jsonl",
        )

        actual_payloads = sorted(path.name for path in (output_dir / "payloads").glob("*.json"))
        fixture_payloads = sorted(path.name for path in (_COMPACTION_FIXTURE_DIR / "payloads").glob("*.json"))
        assert actual_payloads == fixture_payloads

        for payload_name in fixture_payloads:
            assert _normalize_value(
                _load_json(output_dir / "payloads" / payload_name),
                workspace_dir=workspace_dir,
            ) == _load_normalized_fixture_json(
                _COMPACTION_FIXTURE_DIR,
                f"payloads/{payload_name}",
            )
    finally:
        cleanup_test_path(tmp)


def test_model_backed_compaction_local_runtime_trace_bundle_matches_fixture() -> None:
    tmp = make_unique_test_dir(_TEST_NAMESPACE)
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
        output_dir, workspace_dir = _run_trace_bundle(
            tmp=tmp,
            task_id="trace_model_backed_compaction_task",
            task_prompt="Inspect, inspect again, inspect once more, and finish.",
            responses=[
                GenerateResponse.from_native_tool_calling(
                    assistant_text="Inspecting once.",
                    tool_calls=[
                        ToolCallCandidate(
                            call_id="c1",
                            name="read_file",
                            arguments_raw='{"path":"main.py"}',
                            arguments_obj={"path": "main.py"},
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
                            name="list_files",
                            arguments_raw='{"path":"."}',
                            arguments_obj={"path": "."},
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
                            name="read_file",
                            arguments_raw='{"path":"main.py"}',
                            arguments_obj={"path": "main.py"},
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
                    tool_calls=[
                        ToolCallCandidate(
                            call_id="c4",
                            name="finish",
                            arguments_raw='{"answer":"Done"}',
                            arguments_obj={"answer": "Done"},
                            source="native",
                        )
                    ],
                    finish_reason="tool_calls",
                    response_id="resp_4",
                ),
            ],
            max_turns=6,
            context_policy_mode="model_backed_compaction",
            context_max_messages=6,
        )

        assert _normalize_value(
            _load_json(output_dir / "runtime_trace_manifest.json"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_json(
            _MODEL_BACKED_COMPACTION_FIXTURE_DIR,
            "runtime_trace_manifest.json",
        )

        assert _normalize_value(
            _load_jsonl(output_dir / "runtime_trace.jsonl"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_jsonl(
            _MODEL_BACKED_COMPACTION_FIXTURE_DIR,
            "runtime_trace.jsonl",
        )

        assert _normalize_value(
            _load_json(output_dir / "retained_history_manifest.json"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_json(
            _MODEL_BACKED_COMPACTION_FIXTURE_DIR,
            "retained_history_manifest.json",
        )

        assert _normalize_value(
            _load_jsonl(output_dir / "retained_history.jsonl"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_jsonl(
            _MODEL_BACKED_COMPACTION_FIXTURE_DIR,
            "retained_history.jsonl",
        )

        assert _normalize_value(
            _load_json(output_dir / "request_context_manifest.json"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_json(
            _MODEL_BACKED_COMPACTION_FIXTURE_DIR,
            "request_context_manifest.json",
        )

        assert _normalize_value(
            _load_jsonl(output_dir / "request_context.jsonl"),
            workspace_dir=workspace_dir,
        ) == _load_normalized_fixture_jsonl(
            _MODEL_BACKED_COMPACTION_FIXTURE_DIR,
            "request_context.jsonl",
        )

        actual_payloads = sorted(path.name for path in (output_dir / "payloads").glob("*.json"))
        fixture_payloads = sorted(
            path.name
            for path in (_MODEL_BACKED_COMPACTION_FIXTURE_DIR / "payloads").glob("*.json")
        )
        assert actual_payloads == fixture_payloads

        for payload_name in fixture_payloads:
            assert _normalize_value(
                _load_json(output_dir / "payloads" / payload_name),
                workspace_dir=workspace_dir,
            ) == _load_normalized_fixture_json(
                _MODEL_BACKED_COMPACTION_FIXTURE_DIR,
                f"payloads/{payload_name}",
            )
    finally:
        cleanup_test_path(tmp)
