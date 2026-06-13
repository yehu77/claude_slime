"""Tests for the realistic local-runtime workload pack and behavior audit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.eval.runtime_behavior_audit import build_runtime_behavior_audit
from pycodeagent.testing import cleanup_test_path, make_request_test_dir
from pycodeagent.trajectory.schema import RunStatus


_PROJECT_ROOT = Path(__file__).parent.parent
_DATASET_PATH = _PROJECT_ROOT / "datasets" / "tasks" / "realistic_runtime_tasks.jsonl"
_FIXTURE_PATH = _PROJECT_ROOT / "tests" / "fixtures" / "realistic_runtime_task_pack" / "smoke_cases.json"
_EXPECTED_TASK_COUNT = 3


def _load_tasks() -> list[CodingTask]:
    return CodingTask.from_jsonl(_DATASET_PATH)


def _load_cases() -> list[dict]:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]


def _case_map() -> dict[str, dict]:
    return {case["task_id"]: case for case in _load_cases()}


def _task_map() -> dict[str, CodingTask]:
    return {task.task_id: task for task in _load_tasks()}


def _get_test_root(request: pytest.FixtureRequest) -> Path:
    return make_request_test_dir("realistic_runtime_task_pack", request)


@pytest.fixture
def test_root(request: pytest.FixtureRequest):
    root = _get_test_root(request)
    yield root
    cleanup_test_path(root)


class TestRealisticRuntimeTaskPackContract:
    def test_dataset_and_fixture_exist(self):
        assert _DATASET_PATH.exists()
        assert _FIXTURE_PATH.exists()

    def test_all_tasks_load(self):
        assert len(_load_tasks()) == _EXPECTED_TASK_COUNT

    def test_fixture_covers_every_task(self):
        assert set(_task_map()) == set(_case_map())

    def test_metadata_requires_validation_driven_behavior(self):
        tasks = _load_tasks()
        for task in tasks:
            assert task.metadata.get("category") == "runtime_realistic"
            assert task.metadata.get("difficulty") == "medium"
            assert task.metadata.get("require_runtime_validation_evidence") is True
            primary_tools = task.metadata.get("primary_tools")
            assert isinstance(primary_tools, list)
            assert "python_run" in primary_tools
            assert "finish" in primary_tools
            assert any(tool in primary_tools for tool in {"create_file", "write_file"})
            prompt_lower = task.prompt.lower()
            assert "validate" in prompt_lower or "pytest" in prompt_lower or "check" in prompt_lower
            assert "finish" in task.prompt.lower()


class TestRealisticRuntimeTaskPackSmoke:
    @pytest.mark.parametrize(
        "task_id",
        [case["task_id"] for case in _load_cases()],
    )
    @pytest.mark.slow
    @pytest.mark.integration
    def test_task_case_runs_to_completion(self, test_root, task_id: str):
        task = _task_map()[task_id]
        case = _case_map()[task_id]
        output_dir = test_root / task_id
        absolute_task = task.model_copy(
            update={"repo_path": (_PROJECT_ROOT / task.repo_path).resolve()}
        )
        client = FakeLLMClient(case["responses"])

        trajectory = run_coding_task(absolute_task, client, output_dir)

        assert trajectory.status == RunStatus.COMPLETED, trajectory.metadata
        assert trajectory.verifier is not None
        assert trajectory.verifier.passed, trajectory.verifier.stderr
        assert trajectory.reward == 1.0
        assert [call.name for call in trajectory.tool_calls] == case["expected_tool_names"]
        assert trajectory.metadata["validation_phase"] == "validated"
        assert trajectory.metadata["last_validation_attempt_turn"] is not None

        workspace = next((output_dir / "w").iterdir())
        for relative_path, expected_content in case["expected_files"].items():
            target = workspace / relative_path
            assert target.exists(), f"Expected file missing: {relative_path}"
            assert target.read_text(encoding="utf-8") == expected_content

    @pytest.mark.slow
    @pytest.mark.integration
    def test_behavior_audit_captures_repeated_run_patterns(self, test_root):
        batch_root = test_root / "batch_runs"
        batch_root.mkdir(parents=True, exist_ok=True)

        for task_id, task in _task_map().items():
            case = _case_map()[task_id]
            output_dir = batch_root / f"{task_id}__base"
            absolute_task = task.model_copy(
                update={"repo_path": (_PROJECT_ROOT / task.repo_path).resolve()}
            )
            client = FakeLLMClient(case["responses"])
            trajectory = run_coding_task(absolute_task, client, output_dir)
            assert trajectory.status == RunStatus.COMPLETED, trajectory.metadata

        audit = build_runtime_behavior_audit(
            batch_root,
            test_root / "runtime_behavior_audit.json",
            source_type="batch",
        )

        assert audit.run_count == 3
        assert audit.completed_run_count == 3
        assert audit.passed_run_count == 3
        assert audit.validation_turn_count == 6
        assert audit.revalidation_turn_count == 3
        assert audit.revision_turn_count == 3
        assert audit.finish_deferred_count == 1
        assert audit.compaction_turn_count == 0
        assert audit.validation_issue_count == 4
        assert audit.validation_retry_count == 3
        assert audit.revision_after_validation_failure_count == 3
        assert audit.token_budget_compaction_turn_count == 0
        assert audit.runs_with_validation_failure == 3
        assert audit.runs_with_revision_after_failure == 3
        assert audit.runs_with_finish_deferred == 1
        assert audit.runs_with_compaction == 0
        assert audit.runs_with_validation_budget_exhausted == 0
        assert audit.runs_with_revision_budget_exhausted == 0
        assert audit.runs_with_finish_blocked_by_validation == 1
        assert audit.runs_with_token_overflow == 0
        assert audit.premature_finish_count == 1
        assert audit.no_progress_after_validation_failure_count == 0
        assert audit.tool_progress_stall_count == 1
        assert audit.schema_malformed_turn_count == 0
        assert audit.unrecovered_validation_failure_count == 0
        assert audit.runs_with_premature_finish == 1
        assert audit.runs_with_no_progress_after_validation_failure == 0
        assert audit.runs_with_tool_progress_stall == 1
        assert audit.runs_with_schema_malformed == 0
        assert audit.runs_with_unrecovered_validation_failure == 0
        assert audit.runs_with_parse_error == 0
        assert audit.runs_with_llm_error == 0
        assert audit.runs_with_no_tool_progress == 0
        assert audit.mean_validation_attempts_per_issue == 1.75
        assert audit.mean_revision_attempts_per_issue == 0.75
        assert all(run.context_policy_modes == ["full_history"] for run in audit.per_run)

    @pytest.mark.slow
    @pytest.mark.integration
    def test_behavior_audit_captures_token_budget_compaction_runs(self, test_root):
        repo = test_root / "compaction_repo"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "main.py").write_text(
            "print('hello world')\n" * 20,
            encoding="utf-8",
        )
        (repo / "test_ok.py").write_text(
            "def test_ok():\n    assert True\n",
            encoding="utf-8",
        )
        task = CodingTask(
            task_id="realistic_compaction_audit_001",
            repo_path=repo,
            prompt="Inspect main.py, inspect the workspace, inspect main.py again, and finish.",
            test_command="pytest -q -p no:cacheprovider",
            max_turns=6,
        )
        client = FakeLLMClient(
            [
                """<|tool|>
{"id":"c1","name":"read_file","arguments":{"path":"main.py"}}
<|end|>""",
                """<|tool|>
{"id":"c2","name":"list_files","arguments":{"path":"."}}
<|end|>""",
                """<|tool|>
{"id":"c3","name":"read_file","arguments":{"path":"main.py"}}
<|end|>""",
                """<|tool|>
{"id":"c4","name":"finish","arguments":{"answer":"Done"}}
<|end|>""",
            ]
        )
        batch_root = test_root / "compaction_batch"
        output_dir = batch_root / "compaction_case__base"

        trajectory = run_coding_task(
            task,
            client,
            output_dir,
            context_policy_mode="deterministic_compaction",
            context_max_messages=6,
            context_max_tokens=400,
        )

        assert trajectory.status == RunStatus.COMPLETED, trajectory.metadata

        audit = build_runtime_behavior_audit(
            batch_root,
            test_root / "runtime_behavior_audit_compaction.json",
            source_type="batch",
        )

        assert audit.run_count == 1
        assert audit.compaction_turn_count >= 1
        assert audit.token_budget_compaction_turn_count >= 1
        assert audit.runs_with_compaction == 1
        assert audit.runs_with_token_overflow == 0
        assert audit.per_run[0].context_policy_modes == ["deterministic_compaction"]
