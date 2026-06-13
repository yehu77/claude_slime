"""Tests for the deterministic local-runtime task pack."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.testing import cleanup_test_path, make_request_test_dir
from pycodeagent.trajectory.schema import RunStatus


_PROJECT_ROOT = Path(__file__).parent.parent
_DATASET_PATH = _PROJECT_ROOT / "datasets" / "tasks" / "deterministic_runtime_tasks.jsonl"
_FIXTURE_PATH = _PROJECT_ROOT / "tests" / "fixtures" / "deterministic_runtime_task_pack" / "smoke_cases.json"
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
    return make_request_test_dir("deterministic_runtime_task_pack", request)


@pytest.fixture
def test_root(request: pytest.FixtureRequest):
    root = _get_test_root(request)
    yield root
    cleanup_test_path(root)


class TestDeterministicRuntimeTaskPackContract:
    """Static checks for the checked-in dataset and smoke fixture."""

    def test_dataset_and_fixture_exist(self):
        assert _DATASET_PATH.exists(), f"Dataset not found: {_DATASET_PATH}"
        assert _FIXTURE_PATH.exists(), f"Fixture not found: {_FIXTURE_PATH}"

    def test_all_tasks_load(self):
        tasks = _load_tasks()
        assert len(tasks) == _EXPECTED_TASK_COUNT

    def test_fixture_covers_every_task(self):
        tasks = _task_map()
        cases = _case_map()
        assert set(tasks) == set(cases)

    def test_repo_paths_exist(self):
        tasks = _load_tasks()
        for task in tasks:
            repo_path = _PROJECT_ROOT / task.repo_path
            assert repo_path.exists(), f"Repo not found for {task.task_id}: {repo_path}"
            assert repo_path.is_dir(), f"Repo path should be a directory: {repo_path}"

    def test_metadata_highlights_structured_runtime_tools(self):
        tasks = _load_tasks()
        for task in tasks:
            assert task.metadata.get("category") == "deterministic_runtime"
            assert task.metadata.get("difficulty") == "easy"
            assert isinstance(task.metadata.get("description"), str)
            assert isinstance(task.metadata.get("expected_pattern"), str)
            primary_tools = task.metadata.get("primary_tools")
            assert isinstance(primary_tools, list)
            assert "python_run" in primary_tools
            assert "finish" in primary_tools
            assert any(tool in primary_tools for tool in {"create_file", "write_file"})

    def test_prompts_and_allowed_files_are_narrow(self):
        tasks = _load_tasks()
        for task in tasks:
            prompt_lower = task.prompt.lower()
            assert any(verb in prompt_lower for verb in ("create", "rewrite", "read", "verify"))
            assert task.allowed_files
            for allowed in task.allowed_files:
                assert allowed not in {"*", "**/*", "."}


class TestDeterministicRuntimeTaskPackSmoke:
    """Deterministic smoke over the full checked-in task pack."""

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

        workspaces_dir = output_dir / "w"
        workspace_dirs = list(workspaces_dir.iterdir())
        assert len(workspace_dirs) == 1
        workspace = workspace_dirs[0]

        for relative_path, expected_content in case["expected_files"].items():
            target = workspace / relative_path
            assert target.exists(), f"Expected file missing: {relative_path}"
            assert target.read_text(encoding="utf-8") == expected_content

        if task_id == "runtime_subdir_formatter_001":
            python_run_call = next(call for call in trajectory.tool_calls if call.name == "python_run")
            assert python_run_call.arguments["cwd"] == "app"
