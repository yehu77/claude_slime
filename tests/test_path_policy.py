"""Tests for path_policy module and workspace enforcement in builtin tools.

Covers:
- Absolute path rejection
- .. escape rejection
- Workspace boundary enforcement (Path.resolve() check)
- Task-level allowed/forbidden file constraints for ALL tools
- Workspace-relative output paths
- run_command conservative allowlist (python/python3/node NOT allowed)
- list_files directory visibility for allowed descendants
- Runtime ctx passing via inspect (not TypeError fallback)
- Missing context rejection
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from pycodeagent.env.path_policy import (
    PathPolicyError,
    resolve_and_validate_path,
    validate_cwd,
)
from pycodeagent.env.task import CodingTask
from pycodeagent.testing import (
    cleanup_test_path,
    get_managed_test_root,
    make_unique_test_dir,
    reset_test_root,
)
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.builtin.file_ops import (
    _list_files_handler,
    _read_file_handler,
)
from pycodeagent.tools.builtin.search import _search_code_handler
from pycodeagent.tools.builtin.patch import _apply_patch_handler
from pycodeagent.tools.builtin.bash import _run_command_handler
from pycodeagent.tools.registry import ToolRegistry
from pycodeagent.tools.runtime import ToolRuntime, _handler_accepts_ctx
from pycodeagent.tools.spec import ToolProfile, ToolView
from pycodeagent.trajectory.schema import ToolCall


# ---------------------------------------------------------------------------
# Pytest-managed test workspace
# ---------------------------------------------------------------------------

_TEST_WORKSPACE_NAMESPACE = "path_policy"


@pytest.fixture(autouse=True)
def _clean_test_workspace():
    """Ensure a clean test workspace dir before/after each test."""
    reset_test_root(_TEST_WORKSPACE_NAMESPACE)
    yield
    cleanup_test_path(get_managed_test_root(_TEST_WORKSPACE_NAMESPACE))


def _make_workspace(suffix: str = "", files: dict[str, str] | None = None) -> Path:
    """Create a workspace directory with optional files under the temp root."""
    workspace = get_managed_test_root(_TEST_WORKSPACE_NAMESPACE) / f"ws_{suffix}"
    workspace.mkdir(parents=True, exist_ok=True)
    if files:
        for rel, content in files.items():
            p = workspace / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
    return workspace


def _make_ctx(
    workspace: Path,
    allowed_files: list[str] | None = None,
    forbidden_files: list[str] | None = None,
) -> ToolContext:
    """Create a ToolContext with optional task constraints."""
    task = None
    if allowed_files is not None or forbidden_files is not None:
        task = CodingTask(
            task_id="test",
            repo_path=workspace,
            prompt="test",
            allowed_files=allowed_files or [],
            forbidden_files=forbidden_files or [],
        )
    return ToolContext(workspace_root=workspace, task=task)


def _build_runtime_and_profile():
    """Build a ToolRuntime and ToolProfile from builtin tools."""
    from pycodeagent.tools.builtin import ALL_BUILTIN_TOOLS
    registry = ToolRegistry()
    for tool in ALL_BUILTIN_TOOLS:
        registry.register(tool)
    runtime = ToolRuntime(registry)
    profile = ToolProfile(
        profile_id="test",
        tools=[
            ToolView(
                canonical_name=t.canonical_name,
                exposed_name=t.canonical_name,
                description=t.canonical_name,
                input_schema=t.canonical_schema,
            )
            for t in ALL_BUILTIN_TOOLS
        ],
    )
    return runtime, profile


# ---------------------------------------------------------------------------
# TestResolveAndValidatePath
# ---------------------------------------------------------------------------

class TestResolveAndValidatePath:

    def test_absolute_path_rejected(self):
        workspace = _make_workspace("abs_path")
        abs_path = "C:\\Windows\\System32" if os.name == "nt" else "/etc/passwd"
        with pytest.raises(PathPolicyError) as exc_info:
            resolve_and_validate_path(abs_path, workspace)
        assert exc_info.value.error_type == "absolute_path"

    def test_dotdot_escape_rejected(self):
        workspace = _make_workspace("dotdot")
        with pytest.raises(PathPolicyError) as exc_info:
            resolve_and_validate_path("../outside.txt", workspace)
        assert exc_info.value.error_type == "workspace_escape"
        assert "Path traversal is not allowed" in str(exc_info.value)

    def test_internal_dotdot_normalization_allowed(self):
        workspace = _make_workspace("internal_dotdot", {"dir/file.txt": "content"})
        result = resolve_and_validate_path(
            "dir/../dir/file.txt",
            workspace,
            must_exist=True,
            must_be_file=True,
        )
        assert result == (workspace / "dir" / "file.txt").resolve()

    def test_nested_upward_escape_rejected(self):
        workspace = _make_workspace("nested_escape")
        with pytest.raises(PathPolicyError) as exc_info:
            resolve_and_validate_path("a/../../outside.txt", workspace)
        assert exc_info.value.error_type == "workspace_escape"
        assert "Path traversal is not allowed" in str(exc_info.value)

    def test_valid_relative_path_allowed(self):
        workspace = _make_workspace("valid_rel", {"subdir/file.txt": "content"})
        result = resolve_and_validate_path(
            "subdir/file.txt", workspace, must_exist=True, must_be_file=True,
        )
        assert result.is_file()
        assert str(result).startswith(str(workspace.resolve()))

    def test_forbidden_file_rejected(self):
        workspace = _make_workspace("forbidden", {".env": "secret"})
        task = CodingTask(
            task_id="test", repo_path=workspace, prompt="test",
            forbidden_files=[".env"],
        )
        with pytest.raises(PathPolicyError) as exc_info:
            resolve_and_validate_path(
                ".env", workspace, must_exist=True,
                check_allowed_fn=task.is_file_allowed,
            )
        assert exc_info.value.error_type == "forbidden_file"

    def test_not_found_rejected(self):
        workspace = _make_workspace("notfound")
        with pytest.raises(PathPolicyError) as exc_info:
            resolve_and_validate_path(
                "nonexistent.txt", workspace, must_exist=True,
            )
        assert exc_info.value.error_type == "not_found"


# ---------------------------------------------------------------------------
# TestValidateCwd
# ---------------------------------------------------------------------------

class TestValidateCwd:

    def test_none_returns_workspace(self):
        workspace = _make_workspace("cwd_none")
        result = validate_cwd(None, workspace)
        assert result == workspace.resolve()

    def test_escape_rejected(self):
        workspace = _make_workspace("cwd_escape")
        with pytest.raises(PathPolicyError) as exc_info:
            validate_cwd("..", workspace)
        assert exc_info.value.error_type == "workspace_escape"

    def test_valid_subdir_allowed(self):
        workspace = _make_workspace("cwd_subdir", {"subdir/.keep": ""})
        result = validate_cwd("subdir", workspace)
        assert result == (workspace / "subdir").resolve()


# ---------------------------------------------------------------------------
# TestListFilesHandler
# ---------------------------------------------------------------------------

class TestListFilesHandler:

    def test_absolute_path_rejected(self):
        workspace = _make_workspace("ls_abs")
        ctx = _make_ctx(workspace)
        abs_path = "C:\\Windows" if os.name == "nt" else "/etc"
        result = _list_files_handler(path=abs_path, ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "absolute_path"

    def test_escape_rejected(self):
        workspace = _make_workspace("ls_escape")
        ctx = _make_ctx(workspace)
        result = _list_files_handler(path="../outside", ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "workspace_escape"

    def test_valid_path_success(self):
        workspace = _make_workspace("ls_valid", {"file.txt": "content"})
        ctx = _make_ctx(workspace)
        result = _list_files_handler(path=".", ctx=ctx)
        assert result.ok
        assert "file.txt" in result.content

    def test_forbidden_file_hidden_from_listing(self):
        """list_files must not expose files forbidden by task."""
        workspace = _make_workspace("ls_forbidden", {
            "src/main.py": "code",
            ".env": "secret",
        })
        ctx = _make_ctx(workspace, forbidden_files=[".env"])
        result = _list_files_handler(path=".", ctx=ctx)
        assert result.ok
        assert "src/main.py" in result.content
        assert ".env" not in result.content

    def test_allowed_files_filter(self):
        """list_files must only show files matching allowed_files."""
        workspace = _make_workspace("ls_allowed", {
            "src/main.py": "code",
            "src/utils.py": "util",
            "tests/test_main.py": "test",
        })
        ctx = _make_ctx(workspace, allowed_files=["src/*.py"])
        result = _list_files_handler(path=".", ctx=ctx)
        assert result.ok
        assert "src/main.py" in result.content
        assert "src/utils.py" in result.content
        assert "tests/test_main.py" not in result.content

    def test_output_is_workspace_relative(self):
        """list_files output paths must be workspace-relative, not relative
        to the requested subdirectory."""
        workspace = _make_workspace("ls_relpath", {
            "sub/file.txt": "content",
        })
        ctx = _make_ctx(workspace)
        result = _list_files_handler(path="sub", ctx=ctx)
        assert result.ok
        # Must be sub/file.txt, not just file.txt
        assert "sub/file.txt" in result.content

    def test_nonrecursive_shows_parent_dir_of_allowed_files(self):
        """Non-recursive list_files must show directories that contain
        allowed descendant files, even if the directory path itself
        doesn't match allowed_files patterns."""
        workspace = _make_workspace("ls_dir_vis", {
            "src/main.py": "code",
            "src/utils.py": "util",
        })
        ctx = _make_ctx(workspace, allowed_files=["src/*.py"])
        result = _list_files_handler(path=".", recursive=False, ctx=ctx)
        assert result.ok
        # 'src' directory must be visible because it contains allowed files
        assert "src" in result.content.split("\n") or "src/" in result.content

    def test_nonrecursive_hides_dir_with_no_allowed_files(self):
        """Non-recursive list_files must hide directories that contain
        no allowed descendant files."""
        workspace = _make_workspace("ls_dir_hide", {
            "src/main.py": "code",
            "build/output.bin": "binary",
        })
        ctx = _make_ctx(workspace, allowed_files=["src/*.py"])
        result = _list_files_handler(path=".", recursive=False, ctx=ctx)
        assert result.ok
        assert "build" not in result.content.split("\n")
        assert "build/" not in result.content


# ---------------------------------------------------------------------------
# TestReadFileHandler
# ---------------------------------------------------------------------------

class TestReadFileHandler:

    def test_absolute_path_rejected(self):
        workspace = _make_workspace("rf_abs")
        ctx = _make_ctx(workspace)
        abs_path = "C:\\Windows\\System32\\drivers\\etc\\hosts" if os.name == "nt" else "/etc/passwd"
        result = _read_file_handler(path=abs_path, ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "absolute_path"

    def test_escape_rejected(self):
        workspace = _make_workspace("rf_escape")
        ctx = _make_ctx(workspace)
        result = _read_file_handler(path="../outside.txt", ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "workspace_escape"

    def test_valid_file_success(self):
        workspace = _make_workspace("rf_valid", {"file.txt": "hello world"})
        ctx = _make_ctx(workspace)
        result = _read_file_handler(path="file.txt", ctx=ctx)
        assert result.ok
        assert "hello world" in result.content

    def test_forbidden_file_rejected(self):
        """read_file must reject files forbidden by task."""
        workspace = _make_workspace("rf_forbidden", {".env": "secret=value"})
        ctx = _make_ctx(workspace, forbidden_files=[".env"])
        result = _read_file_handler(path=".env", ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "forbidden_file"

    def test_not_in_allowed_files_rejected(self):
        """read_file must reject files not in allowed_files when specified."""
        workspace = _make_workspace("rf_not_allowed", {
            "src/main.py": "code",
            "README.md": "readme",
        })
        ctx = _make_ctx(workspace, allowed_files=["src/*.py"])
        result = _read_file_handler(path="README.md", ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "forbidden_file"

    def test_allowed_file_passes(self):
        """read_file must allow files matching allowed_files."""
        workspace = _make_workspace("rf_allowed", {"src/main.py": "code"})
        ctx = _make_ctx(workspace, allowed_files=["src/*.py"])
        result = _read_file_handler(path="src/main.py", ctx=ctx)
        assert result.ok
        assert "code" in result.content

    def test_start_line_must_be_positive(self):
        workspace = _make_workspace("rf_start_line_invalid", {"file.txt": "a\nb\n"})
        ctx = _make_ctx(workspace)
        result = _read_file_handler(path="file.txt", start_line=0, ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "invalid_line_range"
        assert "start_line must be >= 1" in result.content

    def test_end_line_must_be_positive(self):
        workspace = _make_workspace("rf_end_line_invalid", {"file.txt": "a\nb\n"})
        ctx = _make_ctx(workspace)
        result = _read_file_handler(path="file.txt", end_line=0, ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "invalid_line_range"
        assert "end_line must be >= 1" in result.content

    def test_end_line_before_start_line_rejected(self):
        workspace = _make_workspace("rf_reversed_range", {"file.txt": "a\nb\nc\n"})
        ctx = _make_ctx(workspace)
        result = _read_file_handler(path="file.txt", start_line=3, end_line=2, ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "invalid_line_range"
        assert "before start_line" in result.content

    def test_start_line_beyond_file_length_rejected(self):
        workspace = _make_workspace("rf_range_oob", {"file.txt": "a\nb\n"})
        ctx = _make_ctx(workspace)
        result = _read_file_handler(path="file.txt", start_line=5, ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "invalid_line_range"
        assert "exceeds file length" in result.content


# ---------------------------------------------------------------------------
# TestSearchCodeHandler
# ---------------------------------------------------------------------------

class TestSearchCodeHandler:

    def test_forbidden_file_not_searched(self):
        """search_code must skip files forbidden by task."""
        workspace = _make_workspace("sc_forbidden", {
            "src/main.py": "TODO: fix this",
            ".env": "TODO: secret",
        })
        ctx = _make_ctx(workspace, forbidden_files=[".env"])
        result = _search_code_handler(query="TODO", ctx=ctx)
        assert result.ok
        assert "src/main.py" in result.content
        assert ".env" not in result.content

    def test_allowed_files_filter(self):
        """search_code must only search files matching allowed_files."""
        workspace = _make_workspace("sc_allowed", {
            "src/main.py": "TODO: fix",
            "tests/test.py": "TODO: test",
        })
        ctx = _make_ctx(workspace, allowed_files=["src/*.py"])
        result = _search_code_handler(query="TODO", ctx=ctx)
        assert result.ok
        assert "src/main.py" in result.content
        assert "tests/test.py" not in result.content

    def test_output_paths_are_workspace_relative(self):
        """search_code output paths must be workspace-relative."""
        workspace = _make_workspace("sc_relpath", {
            "sub/deep.py": "findme",
        })
        ctx = _make_ctx(workspace)
        result = _search_code_handler(query="findme", path="sub", ctx=ctx)
        assert result.ok
        # Must show sub/deep.py, not just deep.py
        assert "sub/deep.py" in result.content

    def test_escape_rejected(self):
        workspace = _make_workspace("sc_escape")
        ctx = _make_ctx(workspace)
        result = _search_code_handler(query="test", path="../outside", ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "workspace_escape"

    def test_rg_backend_is_used_when_available(self, monkeypatch: pytest.MonkeyPatch):
        workspace = _make_workspace("sc_rg_backend", {
            "src/main.py": "TODO: fix\n",
            "notes.txt": "TODO: ignore\n",
        })
        ctx = _make_ctx(workspace)

        def fake_run(argv, capture_output, text, cwd):
            assert argv[0] == "rg"
            assert argv[1:7] == [
                "--line-number",
                "--with-filename",
                "--color",
                "never",
                "--fixed-strings",
                "--ignore-case",
            ]
            assert cwd == workspace
            assert argv[-1] == "src/main.py"
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="src/main.py:1:TODO: fix\n",
                stderr="",
            )

        monkeypatch.setattr("pycodeagent.tools.builtin.search.shutil.which", lambda name: "rg")
        monkeypatch.setattr("pycodeagent.tools.builtin.search.subprocess.run", fake_run)

        result = _search_code_handler(
            query="TODO",
            glob_pattern="src/*.py",
            ctx=ctx,
        )
        assert result.ok
        assert result.metadata.get("backend") == "rg"
        assert "src/main.py:1: TODO: fix" in result.content
        assert "notes.txt" not in result.content

    def test_rg_failure_falls_back_to_python(self, monkeypatch: pytest.MonkeyPatch):
        workspace = _make_workspace("sc_rg_fallback", {"file.txt": "TODO: fallback\n"})
        ctx = _make_ctx(workspace)

        def fake_run(*args, **kwargs):
            raise OSError("rg failed")

        monkeypatch.setattr("pycodeagent.tools.builtin.search.shutil.which", lambda name: "rg")
        monkeypatch.setattr("pycodeagent.tools.builtin.search.subprocess.run", fake_run)

        result = _search_code_handler(query="TODO", ctx=ctx)
        assert result.ok
        assert result.metadata.get("backend") == "python"
        assert "file.txt:1: TODO: fallback" in result.content


# ---------------------------------------------------------------------------
# TestApplyPatchHandler
# ---------------------------------------------------------------------------

class TestApplyPatchHandler:

    def test_escape_rejected(self):
        workspace = _make_workspace("ap_escape")
        ctx = _make_ctx(workspace)
        diff = "--- a/../outside.txt\n+++ b/../outside.txt\n@@ -1 +1 @@\n-old\n+new\n"
        result = _apply_patch_handler(diff, ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "workspace_escape"

    def test_forbidden_file_rejected(self):
        workspace = _make_workspace("ap_forbidden", {".env": "secret=value\n"})
        ctx = _make_ctx(workspace, forbidden_files=[".env"])
        diff = "--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-secret=value\n+secret=newvalue\n"
        result = _apply_patch_handler(diff, ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "forbidden_file"

    def test_valid_patch_success(self):
        workspace = _make_workspace("ap_valid", {"file.txt": "old content\n"})
        ctx = _make_ctx(workspace)
        diff = "--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-old content\n+new content\n"
        result = _apply_patch_handler(diff, ctx=ctx)
        assert result.ok
        assert "new content" in (workspace / "file.txt").read_text()

    def test_create_new_file_success(self):
        workspace = _make_workspace("ap_create")
        ctx = _make_ctx(workspace)
        diff = (
            "--- /dev/null\n"
            "+++ b/newdir/new.txt\n"
            "@@ -0,0 +1,2 @@\n"
            "+hello\n"
            "+world\n"
        )
        result = _apply_patch_handler(diff, ctx=ctx)
        assert result.ok
        assert (workspace / "newdir" / "new.txt").read_text(encoding="utf-8") == "hello\nworld\n"

    def test_delete_file_success(self):
        workspace = make_unique_test_dir("path_policy_delete", prefix="patch_delete")
        try:
            (workspace / "old.txt").write_text("alpha\nbeta\n", encoding="utf-8")
            ctx = _make_ctx(workspace)
            diff = (
                "--- a/old.txt\n"
                "+++ /dev/null\n"
                "@@ -1,2 +0,0 @@\n"
                "-alpha\n"
                "-beta\n"
            )
            result = _apply_patch_handler(diff, ctx=ctx)
            assert result.ok
            assert not (workspace / "old.txt").exists()
        finally:
            cleanup_test_path(workspace)

    def test_multi_hunk_patch_success(self):
        workspace = _make_workspace(
            "ap_multi",
            {"file.txt": "one\ntwo\nthree\nfour\nfive\n"},
        )
        ctx = _make_ctx(workspace)
        diff = (
            "--- a/file.txt\n"
            "+++ b/file.txt\n"
            "@@ -1,2 +1,2 @@\n"
            "-one\n"
            "+ONE\n"
            " two\n"
            "@@ -4,2 +4,2 @@\n"
            "-four\n"
            "+FOUR\n"
            " five\n"
        )
        result = _apply_patch_handler(diff, ctx=ctx)
        assert result.ok
        assert (workspace / "file.txt").read_text(encoding="utf-8") == "ONE\ntwo\nthree\nFOUR\nfive\n"

    def test_rename_patch_rejected(self):
        workspace = _make_workspace("ap_rename", {"old.txt": "value\n"})
        ctx = _make_ctx(workspace)
        diff = (
            "--- a/old.txt\n"
            "+++ b/new.txt\n"
            "@@ -1 +1 @@\n"
            "-value\n"
            "+value\n"
        )
        result = _apply_patch_handler(diff, ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "patch_apply"
        assert "rename patches are not supported" in result.content


# ---------------------------------------------------------------------------
# TestRunCommandHandler
# ---------------------------------------------------------------------------

class TestRunCommandHandler:

    def test_cwd_escape_rejected(self):
        workspace = _make_workspace("rc_cwd_escape")
        ctx = _make_ctx(workspace)
        result = _run_command_handler(command="git status", cwd="..", ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "workspace_escape"

    def test_default_cwd_is_workspace(self):
        """git with default cwd should not be rejected by policy."""
        workspace = _make_workspace("rc_default_cwd", {"marker.txt": "test"})
        ctx = _make_ctx(workspace)
        result = _run_command_handler(command="git --version", ctx=ctx)
        assert result.metadata.get("error_type") != "command_policy"

    def test_valid_subdir_cwd(self):
        """git with valid subdir cwd should not be rejected by policy."""
        workspace = _make_workspace("rc_subdir_cwd", {"subdir/.keep": ""})
        ctx = _make_ctx(workspace)
        result = _run_command_handler(command="git --version", cwd="subdir", ctx=ctx)
        assert result.metadata.get("error_type") != "command_policy"

    def test_python_rejected(self):
        """python must be rejected — can execute arbitrary host code."""
        workspace = _make_workspace("rc_python")
        ctx = _make_ctx(workspace)
        result = _run_command_handler(command="python script.py", ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "command_policy"
        assert "not in allowlist" in result.content

    def test_python3_rejected(self):
        """python3 must be rejected — can execute arbitrary host code."""
        workspace = _make_workspace("rc_python3")
        ctx = _make_ctx(workspace)
        result = _run_command_handler(command="python3 script.py", ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "command_policy"

    def test_node_rejected(self):
        """node must be rejected — can execute arbitrary host code."""
        workspace = _make_workspace("rc_node")
        ctx = _make_ctx(workspace)
        result = _run_command_handler(command="node app.js", ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "command_policy"

    def test_npm_rejected(self):
        """npm must be rejected — can execute arbitrary scripts."""
        workspace = _make_workspace("rc_npm")
        ctx = _make_ctx(workspace)
        result = _run_command_handler(command="npm test", ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "command_policy"

    def test_pnpm_rejected(self):
        """pnpm must be rejected — can execute arbitrary scripts."""
        workspace = _make_workspace("rc_pnpm")
        ctx = _make_ctx(workspace)
        result = _run_command_handler(command="pnpm test", ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "command_policy"

    def test_pytest_allowed(self):
        """pytest should pass command policy."""
        workspace = _make_workspace("rc_pytest")
        ctx = _make_ctx(workspace)
        result = _run_command_handler(command="pytest --version", ctx=ctx)
        assert result.metadata.get("error_type") != "command_policy"

    def test_ruff_allowed(self):
        """ruff should pass command policy (may not be installed)."""
        workspace = _make_workspace("rc_ruff")
        ctx = _make_ctx(workspace)
        result = _run_command_handler(command="ruff --version", ctx=ctx)
        assert result.metadata.get("error_type") != "command_policy"

    def test_mypy_allowed(self):
        """mypy should pass command policy (may not be installed)."""
        workspace = _make_workspace("rc_mypy")
        ctx = _make_ctx(workspace)
        result = _run_command_handler(command="mypy --version", ctx=ctx)
        assert result.metadata.get("error_type") != "command_policy"

    def test_git_allowed(self):
        """git should pass command policy."""
        workspace = _make_workspace("rc_git")
        ctx = _make_ctx(workspace)
        result = _run_command_handler(command="git --version", ctx=ctx)
        assert result.metadata.get("error_type") != "command_policy"

    def test_git_write_subcommand_rejected(self):
        """git write-capable subcommands must be rejected."""
        workspace = _make_workspace("rc_git_push")
        ctx = _make_ctx(workspace)
        result = _run_command_handler(command="git push", ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "command_policy"
        assert "git subcommand not allowed" in result.content

    def test_shell_control_syntax_rejected(self):
        """Shell chaining must be rejected before execution."""
        workspace = _make_workspace("rc_shell_syntax")
        ctx = _make_ctx(workspace)
        result = _run_command_handler(command="git --version && git status", ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "command_policy"
        assert "unsupported shell syntax" in result.content

    def test_posix_commands_rejected(self):
        """POSIX-only commands must be rejected — not reliably available on Windows."""
        workspace = _make_workspace("rc_posix")
        ctx = _make_ctx(workspace)
        for cmd in ["ls", "cat file.txt", "head file.txt", "tail file.txt",
                     "grep pattern file.txt", "find . -name x", "wc -l file.txt",
                     "echo hello", "pwd"]:
            result = _run_command_handler(command=cmd, ctx=ctx)
            assert result.is_error, f"{cmd!r} should be rejected by policy"
            assert result.metadata.get("error_type") == "command_policy", \
                f"{cmd!r} should be command_policy, got {result.metadata.get('error_type')}"

    def test_dangerous_commands_rejected(self):
        """rm, sudo, curl, etc. must be rejected."""
        workspace = _make_workspace("rc_danger")
        ctx = _make_ctx(workspace)
        for cmd in ["rm -rf /", "sudo ls", "curl http://example.com", "wget http://example.com"]:
            result = _run_command_handler(command=cmd, ctx=ctx)
            assert result.is_error, f"{cmd!r} should be rejected"
            assert result.metadata.get("error_type") == "command_policy"


# ---------------------------------------------------------------------------
# TestMissingContext
# ---------------------------------------------------------------------------

class TestMissingContext:

    def test_list_files_requires_context(self):
        result = _list_files_handler(path=".")
        assert result.is_error
        assert result.metadata.get("error_type") == "missing_context"

    def test_read_file_requires_context(self):
        result = _read_file_handler(path="file.txt")
        assert result.is_error
        assert result.metadata.get("error_type") == "missing_context"

    def test_search_code_requires_context(self):
        result = _search_code_handler(query="test")
        assert result.is_error
        assert result.metadata.get("error_type") == "missing_context"

    def test_apply_patch_requires_context(self):
        result = _apply_patch_handler(diff="--- a/a\n+++ b/a\n")
        assert result.is_error
        assert result.metadata.get("error_type") == "missing_context"

    def test_run_command_requires_context(self):
        result = _run_command_handler(command="ls")
        assert result.is_error
        assert result.metadata.get("error_type") == "missing_context"


# ---------------------------------------------------------------------------
# TestRuntimeContextIntegration
# ---------------------------------------------------------------------------

class TestRuntimeContextIntegration:

    def test_runtime_passes_ctx_to_handler(self):
        """Verify runtime.execute() passes ctx to builtin handlers."""
        workspace = _make_workspace("rt_ctx", {"test.txt": "hello"})
        runtime, profile = _build_runtime_and_profile()
        ctx = ToolContext(workspace_root=workspace)
        call = ToolCall(id="c1", name="read_file", arguments={"path": "test.txt"})
        result = runtime.execute(call, profile, ctx=ctx)
        assert result.ok
        assert "hello" in result.content

    def test_runtime_rejects_escape_via_ctx(self):
        """Verify runtime.execute() rejects workspace escape via ctx."""
        workspace = _make_workspace("rt_escape")
        runtime, profile = _build_runtime_and_profile()
        ctx = ToolContext(workspace_root=workspace)
        call = ToolCall(id="c2", name="read_file", arguments={"path": "../etc/passwd"})
        result = runtime.execute(call, profile, ctx=ctx)
        assert result.is_error
        assert result.metadata.get("error_type") == "workspace_escape"

    def test_runtime_without_ctx_still_works_for_finish(self):
        """Finish tool should work without ctx since it doesn't need workspace."""
        runtime, profile = _build_runtime_and_profile()
        call = ToolCall(id="c3", name="finish", arguments={"answer": "done"})
        result = runtime.execute(call, profile)
        assert result.ok

    def test_handler_accepts_ctx_inspection(self):
        """_handler_accepts_ctx must correctly detect ctx support."""
        def with_ctx(x: int, *, ctx: ToolContext | None = None) -> None:
            pass

        def without_ctx(x: int) -> None:
            pass

        assert _handler_accepts_ctx(with_ctx) is True
        assert _handler_accepts_ctx(without_ctx) is False

    def test_runtime_does_not_swallow_type_errors(self):
        """A handler that raises TypeError internally must NOT be silently
        retried without ctx — the error must propagate."""
        from pycodeagent.tools.builtin import ALL_BUILTIN_TOOLS
        from pycodeagent.tools.spec import CanonicalTool

        def buggy_handler(x: str, *, ctx: ToolContext | None = None):
            # Simulate a real bug inside the handler
            raise TypeError("real bug inside handler")

        buggy_tool = CanonicalTool(
            canonical_name="buggy",
            canonical_schema={
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            },
            handler=buggy_handler,
        )

        registry = ToolRegistry()
        for t in ALL_BUILTIN_TOOLS:
            registry.register(t)
        registry.register(buggy_tool)

        runtime = ToolRuntime(registry)
        profile = ToolProfile(
            profile_id="test",
            tools=[
                ToolView(
                    canonical_name="buggy",
                    exposed_name="buggy",
                    description="buggy",
                    input_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
                ),
            ],
        )
        workspace = _make_workspace("rt_typeerr")
        ctx = ToolContext(workspace_root=workspace)
        call = ToolCall(id="c4", name="buggy", arguments={"x": "test"})
        result = runtime.execute(call, profile, ctx=ctx)
        # The TypeError must be reported, not silently swallowed
        assert result.is_error
        assert "real bug inside handler" in result.content
        assert "Traceback" not in result.content
        assert result.metadata.get("error_type") == "handler_exception"
        assert result.metadata.get("exception_type") == "TypeError"
