"""Tests for CodingTask path normalization.

Locks the contract for:
- Normal relative path normalization
- Windows/POSIX separator normalization
- Absolute path rejection
- Directory traversal (..) rejection
- Empty path handling
- is_file_allowed integration
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pycodeagent.env.task import CodingTask
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


class TestNormalizeRepoRelativePath:
    """Tests for normalize_repo_relative_path."""

    def test_simple_relative_path(self):
        """Simple relative path should normalize to POSIX."""
        task = CodingTask(task_id="t", repo_path=Path("/tmp/test"), prompt="test")
        result = task.normalize_repo_relative_path("src/main.py")
        assert result == "src/main.py"

    def test_path_with_backslash_normalized(self):
        """Windows backslash should normalize to forward slash."""
        task = CodingTask(task_id="t", repo_path=Path("/tmp/test"), prompt="test")
        result = task.normalize_repo_relative_path("src\\main.py")
        assert result == "src/main.py"

    def test_nested_path_normalized(self):
        """Deeply nested path should normalize correctly."""
        task = CodingTask(task_id="t", repo_path=Path("/tmp/test"), prompt="test")
        result = task.normalize_repo_relative_path("a/b/c/d/file.py")
        assert result == "a/b/c/d/file.py"

    def test_single_component_path(self):
        """Single component path."""
        task = CodingTask(task_id="t", repo_path=Path("/tmp/test"), prompt="test")
        result = task.normalize_repo_relative_path("main.py")
        assert result == "main.py"

    def test_current_directory_returns_dot(self):
        """Current directory marker should normalize to dot."""
        task = CodingTask(task_id="t", repo_path=Path("/tmp/test"), prompt="test")
        result = task.normalize_repo_relative_path(".")
        assert result == "."

    def test_empty_path_returns_dot(self):
        """Empty path should normalize to dot."""
        task = CodingTask(task_id="t", repo_path=Path("/tmp/test"), prompt="test")
        result = task.normalize_repo_relative_path("")
        assert result == "."


class TestNormalizeRejectsAbsolute:
    """Tests for absolute path rejection."""

    def test_absolute_path_rejected(self):
        """Absolute path should raise."""
        task = CodingTask(task_id="t", repo_path=Path("/tmp/test"), prompt="test")
        # Use Path to create a proper absolute path for the current OS
        abs_path = str(Path("/etc/passwd").resolve())
        with pytest.raises(ValueError, match="Absolute paths are not allowed"):
            task.normalize_repo_relative_path(abs_path)

    def test_windows_style_absolute_rejected(self):
        """Windows-style absolute path should raise."""
        task = CodingTask(task_id="t", repo_path=Path("C:/test"), prompt="test")
        with pytest.raises(ValueError, match="Absolute paths are not allowed"):
            task.normalize_repo_relative_path("C:/Windows/System32")


class TestNormalizeRejectsTraversal:
    """Tests for directory traversal rejection."""

    def test_parent_traversal_rejected(self):
        """Parent traversal with .. should raise."""
        task = CodingTask(task_id="t", repo_path=Path("/tmp/test"), prompt="test")
        with pytest.raises(ValueError, match="escapes workspace"):
            task.normalize_repo_relative_path("../etc/passwd")

    def test_nested_parent_traversal_rejected(self):
        """Nested parent traversal should raise."""
        task = CodingTask(task_id="t", repo_path=Path("/tmp/test"), prompt="test")
        with pytest.raises(ValueError, match="escapes workspace"):
            task.normalize_repo_relative_path("src/../..")

    def test_mid_path_traversal_rejected(self):
        """Mid-path traversal should raise."""
        task = CodingTask(task_id="t", repo_path=Path("/tmp/test"), prompt="test")
        with pytest.raises(ValueError, match="escapes workspace"):
            task.normalize_repo_relative_path("a/b/../../c")


class TestIsFileAllowed:
    """Tests for is_file_allowed with allowed_files and forbidden_files."""

    def test_empty_allowed_allows_all(self):
        """Empty allowed_files should allow all files."""
        task = CodingTask(
            task_id="t",
            repo_path=Path("/tmp/test"),
            prompt="test",
            allowed_files=[],
            forbidden_files=[],
        )
        assert task.is_file_allowed("main.py")
        assert task.is_file_allowed("src/test.py")

    def test_allowed_pattern_matches(self):
        """allowed_files pattern should match."""
        task = CodingTask(
            task_id="t",
            repo_path=Path("/tmp/test"),
            prompt="test",
            allowed_files=["*.py"],
            forbidden_files=[],
        )
        assert task.is_file_allowed("main.py")
        assert task.is_file_allowed("src/test.py")
        assert not task.is_file_allowed("data.txt")

    def test_allowed_exact_match(self):
        """Exact filename in allowed_files should match."""
        task = CodingTask(
            task_id="t",
            repo_path=Path("/tmp/test"),
            prompt="test",
            allowed_files=["calculator.py"],
            forbidden_files=[],
        )
        assert task.is_file_allowed("calculator.py")
        assert not task.is_file_allowed("other.py")

    def test_forbidden_overrides_allowed(self):
        """forbidden_files should override allowed_files."""
        task = CodingTask(
            task_id="t",
            repo_path=Path("/tmp/test"),
            prompt="test",
            allowed_files=["*.py"],
            forbidden_files=["secret.py"],
        )
        assert task.is_file_allowed("main.py")
        assert not task.is_file_allowed("secret.py")

    def test_forbidden_pattern_blocks(self):
        """Forbidden pattern should block matching files."""
        task = CodingTask(
            task_id="t",
            repo_path=Path("/tmp/test"),
            prompt="test",
            allowed_files=[],
            forbidden_files=["*.txt"],
        )
        assert task.is_file_allowed("main.py")
        assert not task.is_file_allowed("data.txt")

    def test_absolute_path_not_allowed(self):
        """Absolute paths should not be allowed."""
        task = CodingTask(
            task_id="t",
            repo_path=Path("/tmp/test"),
            prompt="test",
        )
        # Use Path to create a proper absolute path for the current OS
        abs_path = str(Path("/etc/passwd").resolve())
        assert not task.is_file_allowed(abs_path)

    def test_traversal_not_allowed(self):
        """Traversal paths should not be allowed."""
        task = CodingTask(
            task_id="t",
            repo_path=Path("/tmp/test"),
            prompt="test",
        )
        assert not task.is_file_allowed("../secret")


class TestCodingTaskFromJsonl:
    """Tests for loading tasks from JSONL."""

    def _make_test_dir(self) -> Path:
        """Create a unique pytest-managed test directory."""
        return make_unique_test_dir("task_paths", prefix="jsonl")

    def _cleanup(self, test_dir: Path) -> None:
        """Remove the test directory."""
        cleanup_test_path(test_dir)

    def test_load_single_task(self):
        """Should load a single task from JSONL."""
        import json
        test_dir = self._make_test_dir()
        try:
            task_file = test_dir / "tasks.jsonl"
            task_file.write_text(json.dumps({
                "task_id": "test_001",
                "repo_path": "/tmp/repo",
                "prompt": "Fix the bug",
                "test_command": "pytest",
                "max_turns": 10,
            }))

            tasks = CodingTask.from_jsonl(task_file)
            assert len(tasks) == 1
            assert tasks[0].task_id == "test_001"
            assert tasks[0].prompt == "Fix the bug"
        finally:
            self._cleanup(test_dir)

    def test_load_multiple_tasks(self):
        """Should load multiple tasks from JSONL."""
        import json
        test_dir = self._make_test_dir()
        try:
            task_file = test_dir / "tasks.jsonl"
            task_file.write_text(
                json.dumps({"task_id": "t1", "repo_path": "/tmp/r1", "prompt": "p1"}) + "\n" +
                json.dumps({"task_id": "t2", "repo_path": "/tmp/r2", "prompt": "p2"})
            )

            tasks = CodingTask.from_jsonl(task_file)
            assert len(tasks) == 2
            assert tasks[0].task_id == "t1"
            assert tasks[1].task_id == "t2"
        finally:
            self._cleanup(test_dir)

    def test_skip_empty_lines(self):
        """Should skip empty lines in JSONL."""
        import json
        test_dir = self._make_test_dir()
        try:
            task_file = test_dir / "tasks.jsonl"
            task_file.write_text(
                json.dumps({"task_id": "t1", "repo_path": "/tmp/r1", "prompt": "p1"}) + "\n\n" +
                json.dumps({"task_id": "t2", "repo_path": "/tmp/r2", "prompt": "p2"})
            )

            tasks = CodingTask.from_jsonl(task_file)
            assert len(tasks) == 2
        finally:
            self._cleanup(test_dir)
