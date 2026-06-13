"""Tests for the checked-in toy task dataset."""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

import pytest

from pycodeagent.env.task import CodingTask
from pycodeagent.testing import cleanup_test_path, make_request_test_dir


_PROJECT_ROOT = Path(__file__).parent.parent
_DATASET_PATH = _PROJECT_ROOT / "datasets" / "tasks" / "toy_tasks.jsonl"
_EXPECTED_TASK_COUNT = 12
_EXPECTED_CATEGORIES = {"bugfix", "lint_format", "type_fix", "small_feature"}


def _load_tasks() -> list[CodingTask]:
    return CodingTask.from_jsonl(_DATASET_PATH)


def _get_test_root(request: pytest.FixtureRequest) -> Path:
    return make_request_test_dir("toy_dataset", request)


@pytest.fixture
def test_root(request: pytest.FixtureRequest):
    root = _get_test_root(request)
    yield root
    cleanup_test_path(root)


class TestDatasetLoading:
    """Loading and shape checks for the dataset."""

    def test_dataset_file_exists(self):
        assert _DATASET_PATH.exists(), f"Dataset not found: {_DATASET_PATH}"

    def test_all_tasks_load(self):
        tasks = _load_tasks()
        assert len(tasks) == _EXPECTED_TASK_COUNT

    def test_task_ids_are_unique(self):
        tasks = _load_tasks()
        task_ids = [task.task_id for task in tasks]
        assert len(task_ids) == len(set(task_ids)), "Task IDs should be unique"

    def test_all_tasks_have_required_fields(self):
        tasks = _load_tasks()
        for task in tasks:
            assert task.task_id
            assert task.repo_path
            assert task.prompt
            assert task.test_command
            assert task.max_turns > 0
            assert isinstance(task.allowed_files, list)
            assert isinstance(task.forbidden_files, list)
            assert isinstance(task.metadata, dict)

    def test_all_tasks_have_metadata_contract(self):
        tasks = _load_tasks()
        for task in tasks:
            assert task.metadata.get("category") in _EXPECTED_CATEGORIES
            assert task.metadata.get("difficulty") in {"easy", "medium"}
            assert isinstance(task.metadata.get("description"), str)
            primary_tools = task.metadata.get("primary_tools")
            assert isinstance(primary_tools, list), f"{task.task_id} primary_tools should be a list"
            assert len(primary_tools) >= 3, f"{task.task_id} should declare at least 3 primary tools"


class TestRepoPaths:
    """Repo structure and allowed-file checks."""

    def test_all_repo_paths_exist(self):
        tasks = _load_tasks()
        for task in tasks:
            repo_path = _PROJECT_ROOT / task.repo_path
            assert repo_path.exists(), f"Repo not found for {task.task_id}: {repo_path}"
            assert repo_path.is_dir(), f"Repo path should be a directory: {repo_path}"

    def test_all_repos_have_source_and_test_files(self):
        tasks = _load_tasks()
        for task in tasks:
            repo_path = _PROJECT_ROOT / task.repo_path
            py_files = list(repo_path.glob("*.py"))
            source_files = [f for f in py_files if not f.name.startswith("test_")]
            test_files = list(repo_path.glob("test_*.py"))
            assert source_files, f"No source files in {repo_path}"
            assert test_files, f"No test files in {repo_path}"

    def test_allowed_files_exist_in_repo(self):
        tasks = _load_tasks()
        for task in tasks:
            repo_path = _PROJECT_ROOT / task.repo_path
            for rel_path in task.allowed_files:
                assert (repo_path / rel_path).exists(), f"{task.task_id} allowed file missing: {rel_path}"


class TestVerificationCommand:
    """Sanity checks for verification commands."""

    def test_all_tasks_use_pytest(self):
        tasks = _load_tasks()
        for task in tasks:
            assert "pytest" in task.test_command, f"Expected pytest in test_command for {task.task_id}"

    @pytest.mark.parametrize("task_index", range(_EXPECTED_TASK_COUNT))
    @pytest.mark.slow
    @pytest.mark.integration
    def test_repo_tests_fail_before_fix(self, test_root, task_index):
        tasks = _load_tasks()
        task = tasks[task_index]

        repo_path = _PROJECT_ROOT / task.repo_path
        isolated_repo = test_root / f"repo_{task_index}"
        shutil.copytree(repo_path, isolated_repo)

        result = subprocess.run(
            ["pytest", "-q", "-p", "no:cacheprovider"],
            cwd=isolated_repo,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode != 0, f"Tests should fail for {task.task_id}"


class TestDatasetStability:
    """Dataset quality and stability checks."""

    def test_no_external_dependencies(self):
        tasks = _load_tasks()
        for task in tasks:
            repo_path = _PROJECT_ROOT / task.repo_path
            assert not (repo_path / "requirements.txt").exists()

    def test_allowed_files_are_narrow(self):
        tasks = _load_tasks()
        for task in tasks:
            assert task.allowed_files, f"{task.task_id} should have allowed_files"
            for pattern in task.allowed_files:
                assert pattern not in {"*", "**/*", "."}, f"{task.task_id} has overly broad allowed_files"

    def test_prompts_are_actionable(self):
        tasks = _load_tasks()
        verbs = ("fix", "add", "implement", "remove", "clean up")
        for task in tasks:
            assert len(task.prompt) >= 20, f"Prompt too short for {task.task_id}"
            prompt_lower = task.prompt.lower()
            assert any(verb in prompt_lower for verb in verbs), (
                f"Prompt should describe an action for {task.task_id}"
            )

    def test_primary_tools_are_reasonable(self):
        tasks = _load_tasks()
        allowed_tools = {"read_file", "apply_patch", "run_command", "finish", "list_files", "search_code"}
        for task in tasks:
            primary_tools = task.metadata["primary_tools"]
            assert "read_file" in primary_tools
            assert "apply_patch" in primary_tools
            assert "finish" in primary_tools
            assert set(primary_tools).issubset(allowed_tools)


class TestTaskCategories:
    """Category coverage checks for phase-3 experiments."""

    def test_dataset_covers_expected_categories(self):
        tasks = _load_tasks()
        categories = {task.metadata["category"] for task in tasks}
        assert categories == _EXPECTED_CATEGORIES

    def test_non_bugfix_categories_have_multiple_tasks(self):
        tasks = _load_tasks()
        counts = Counter(task.metadata["category"] for task in tasks)
        assert counts["bugfix"] >= 6
        assert counts["lint_format"] >= 2
        assert counts["type_fix"] >= 2
        assert counts["small_feature"] >= 2

    def test_tasks_cover_mixed_difficulties(self):
        tasks = _load_tasks()
        difficulties = {task.metadata["difficulty"] for task in tasks}
        assert difficulties == {"easy", "medium"}


class TestExampleRepos:
    """Example repo checks derived from the dataset itself."""

    def test_dataset_repo_names_are_unique(self):
        tasks = _load_tasks()
        repo_names = [Path(task.repo_path).name for task in tasks]
        assert len(repo_names) == len(set(repo_names))

    def test_dataset_repo_layout_matches_files(self):
        tasks = _load_tasks()
        for task in tasks:
            repo_path = _PROJECT_ROOT / task.repo_path
            source_files = [f.name for f in repo_path.glob("*.py") if not f.name.startswith("test_")]
            test_files = [f.name for f in repo_path.glob("test_*.py")]
            assert len(source_files) == 1, f"{task.task_id} should keep a single source file"
            assert len(test_files) == 1, f"{task.task_id} should keep a single test file"
