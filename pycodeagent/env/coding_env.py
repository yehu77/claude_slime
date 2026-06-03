"""Coding environment orchestration.

Coordinates:
1. Workspace preparation (copy from source repo)
2. Agent execution
3. Verification
4. Reward computation
5. Artifact persistence

This module provides the minimal single-task flow. Batch execution,
dataset loading, and experiment management are out of scope for NS-04.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from pycodeagent.env.task import CodingTask
from pycodeagent.env.verifier import run_verifier
from pycodeagent.trajectory.recorder import RunRecorder
from pycodeagent.trajectory.schema import RunStatus, Trajectory, VerifyResult

if TYPE_CHECKING:
    from pycodeagent.agent.llm_client import BaseLLMClient
    from pycodeagent.tools.spec import ToolProfile
    from pycodeagent.tools.runtime import ToolRuntime


# Directories to ignore when copying source repo (test artifacts, caches, etc.)
_IGNORE_COPY_PATTERNS = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".tox",
    ".nox",
    "*.pyc",
    "*.pyo",
}

_IGNORED_DIFF_PARTS = {"__pycache__", ".git", ".pytest_cache"}


def _ignore_copy_patterns(directory: str, contents: list[str]) -> list[str]:
    """Filter out cache and test artifact directories during copytree."""
    ignored = []
    for name in contents:
        if name in _IGNORE_COPY_PATTERNS:
            ignored.append(name)
        elif name.endswith(".pyc") or name.endswith(".pyo"):
            ignored.append(name)
    return ignored


def prepare_workspace(
    source_repo: Path,
    workspace_base: Path,
) -> Path:
    """Copy source repo to a unique workspace directory.

    Uses a unique workspace name (uuid suffix) to avoid conflicts with
    existing directories that may be locked or have permission issues
    on Windows.

    Ignores cache directories (__pycache__, .pytest_cache, etc.) to avoid
    permission issues and keep workspace clean.

    Args:
        source_repo: Path to the original repository.
        workspace_base: Base directory where a unique workspace should be created.
                       The actual workspace will be workspace_base / uuid4().

    Returns:
        The resolved workspace path (unique directory).

    Raises:
        ValueError: If source_repo doesn't exist or copy fails.
    """
    source_repo = source_repo.resolve()
    workspace_base = workspace_base.resolve()

    if not source_repo.exists():
        raise ValueError(f"Source repo does not exist: {source_repo}")

    # Ensure base directory exists
    workspace_base.mkdir(parents=True, exist_ok=True)

    # Create unique workspace directory to avoid conflicts
    workspace_root = workspace_base / uuid.uuid4().hex[:12]

    # Copy the repo to the unique workspace, ignoring cache directories
    try:
        shutil.copytree(source_repo, workspace_root, ignore=_ignore_copy_patterns)
    except shutil.Error as e:
        raise ValueError(f"Failed to copy source repo: {e}") from e

    return workspace_root


def compute_diff(
    source_repo: Path,
    workspace_root: Path,
) -> str:
    """Compute unified diff between source repo and workspace.

    Uses git diff if the source is a git repo, otherwise falls back to
    a simple file-by-file comparison.

    Args:
        source_repo: Path to the original repository.
        workspace_root: Path to the modified workspace.

    Returns:
        Unified diff text, or empty string if no changes.
    """
    source_repo = source_repo.resolve()
    workspace_root = workspace_root.resolve()

    # Try git diff first (if source is a git repo)
    git_dir = source_repo / ".git"
    if git_dir.exists():
        try:
            # Use git diff with --no-index to compare the two directories
            # We need to compare from workspace, treating source as original
            result = subprocess.run(
                ["git", "diff", "--no-index", str(source_repo), str(workspace_root)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # git diff --no-index returns 0 if no diff, 1 if diff exists
            if result.returncode in (0, 1):
                diff_text = result.stdout
                # Clean up the diff by replacing absolute paths with a/b prefixes
                src_str = str(source_repo)
                ws_str = str(workspace_root)
                lines = diff_text.splitlines(keepends=True)
                cleaned = []
                for line in lines:
                    if line.startswith("diff --git "):
                        # Rewrite diff line: diff --git /abs/path/a /abs/path/b
                        # to: diff --git a/relpath b/relpath
                        parts = line[len("diff --git "):].split()
                        if len(parts) >= 2:
                            p1, p2 = parts[0], parts[1]
                            if p1.startswith(src_str):
                                rel1 = p1[len(src_str):].lstrip("/\\")
                            else:
                                rel1 = p1
                            if p2.startswith(ws_str):
                                rel2 = p2[len(ws_str):].lstrip("/\\")
                            else:
                                rel2 = p2
                            line = f"diff --git a/{rel1} b/{rel2}\n"
                    elif line.startswith("--- "):
                        p = line[len("--- "):].strip()
                        if p.startswith(src_str):
                            rel = p[len(src_str):].lstrip("/\\")
                            line = f"--- a/{rel}\n"
                    elif line.startswith("+++ "):
                        p = line[len("+++ "):].strip()
                        if p.startswith(ws_str):
                            rel = p[len(ws_str):].lstrip("/\\")
                            line = f"+++ b/{rel}\n"
                    cleaned.append(line)
                return "".join(cleaned)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # Fall through to simple diff

    # Fallback: simple diff using difflib for non-git repos
    return _compute_simple_diff(source_repo, workspace_root)


def _compute_simple_diff(source_repo: Path, workspace_root: Path) -> str:
    """Compute a simple unified diff without git."""
    import difflib

    diff_parts = []

    relative_paths: set[PurePosixPath] = set()
    for source_file in _iter_diff_candidate_files(source_repo):
        relative_paths.add(PurePosixPath(*source_file.relative_to(source_repo).parts))
    for workspace_file in _iter_diff_candidate_files(workspace_root):
        relative_paths.add(
            PurePosixPath(*workspace_file.relative_to(workspace_root).parts)
        )

    for rel_path in sorted(relative_paths):
        source_file = source_repo.joinpath(*rel_path.parts)
        workspace_file = workspace_root.joinpath(*rel_path.parts)

        source_content = _read_text_for_diff(source_file)
        workspace_content = _read_text_for_diff(workspace_file)
        if source_content is None or workspace_content is None:
            continue

        if workspace_content != source_content:
            diff = difflib.unified_diff(
                source_content,
                workspace_content,
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
            )
            diff_parts.extend(diff)

    return "".join(diff_parts)


def _iter_diff_candidate_files(root: Path):
    """Yield files that should participate in fallback diff computation."""
    if not root.exists():
        return

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _IGNORED_DIFF_PARTS for part in path.parts):
            continue
        yield path


def _read_text_for_diff(path: Path) -> list[str] | None:
    """Read a file as text for diffing.

    Returns ``[]`` for a missing file and ``None`` for files that should be
    skipped (for example unreadable or binary files).
    """
    if not path.exists():
        return []

    try:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (UnicodeDecodeError, OSError):
        return None


def compute_reward(
    verify_result: VerifyResult,
    patch_text: str,
    trajectory: Trajectory,
) -> float:
    """Return only the numeric reward component of the reward decision."""
    reward, _ = compute_reward_details(verify_result, patch_text, trajectory)
    return reward


def compute_reward_details(
    verify_result: VerifyResult,
    patch_text: str,
    trajectory: Trajectory,
) -> tuple[float, str]:
    """Compute reward and an explicit reason code.

    Reward policy:
    - ``1.0``: verifier passed and run completed cleanly
    - ``0.5``: verifier passed but run ended non-cleanly
    - ``0.1``: verifier failed, but the run produced a real patch
    - ``0.0``: verifier failed and no effective modification was made
    - ``-0.2``: parse/tool/runtime/setup/verifier execution errors
    - ``-0.5``: timeout or forbidden command policy violations
    """
    stop_reason = str(trajectory.metadata.get("stop_reason") or "")
    tool_error_type = _extract_tool_error_type(trajectory)
    has_patch = bool(patch_text.strip())

    if trajectory.status == RunStatus.COMPLETED and verify_result.passed:
        return 1.0, "verifier_passed"

    if trajectory.status == RunStatus.TIMEOUT or verify_result.stderr.startswith(
        "Test command timed out"
    ):
        return -0.5, "timeout"

    if trajectory.status != RunStatus.COMPLETED and tool_error_type in {
        "command_policy",
        "timeout",
    }:
        reason = (
            "forbidden_command"
            if tool_error_type == "command_policy"
            else "tool_timeout"
        )
        return -0.5, reason

    if stop_reason == "parse_error":
        return -0.2, "parse_error"

    if stop_reason == "llm_error":
        return -0.2, "llm_error"

    if trajectory.metadata.get("setup_error"):
        return -0.2, "setup_error"

    if trajectory.status == RunStatus.ERROR:
        if tool_error_type:
            return -0.2, f"tool_error:{tool_error_type}"
        if verify_result.stderr.startswith("Verifier execution error"):
            return -0.2, "verifier_execution_error"
        return -0.2, "run_error"

    if verify_result.passed:
        return 0.5, "verifier_passed_but_run_not_completed"

    if has_patch:
        return 0.1, "verifier_failed_with_patch"

    return 0.0, "no_effective_change"


def _extract_tool_error_type(trajectory: Trajectory) -> str:
    """Return the most recent structured tool error type, if any."""
    for observation in reversed(trajectory.observations):
        if observation.result.is_error or not observation.result.ok:
            error_type = observation.result.metadata.get("error_type")
            if isinstance(error_type, str) and error_type:
                return error_type
    return ""


def _status_from_verifier(verify_result: VerifyResult) -> RunStatus:
    """Map a verifier result to the run status used in artifacts."""
    if verify_result.passed:
        return RunStatus.COMPLETED
    if verify_result.stderr.startswith("Test command timed out"):
        return RunStatus.TIMEOUT
    return RunStatus.FAILED


def run_coding_task(
    task: CodingTask,
    client: "BaseLLMClient",
    output_dir: Path,
    *,
    profile: "ToolProfile | None" = None,
    runtime: "ToolRuntime | None" = None,
) -> Trajectory:
    """Run a single coding task end-to-end.

    This is the main entry point for NS-04. It orchestrates:
    1. Workspace preparation
    2. Agent execution
    3. Verification
    4. Reward computation
    5. Artifact persistence

    Args:
        task: The coding task to solve.
        client: LLM client for the agent.
        output_dir: Directory to store run artifacts.
        profile: Tool profile (default: base profile from bootstrap).
        runtime: Tool runtime (default: built from bootstrap).

    Returns:
        The completed trajectory with verifier result and reward.
    """
    # Local imports to avoid circular dependency at module load time
    from pycodeagent.agent.runner import run_agent_task
    from pycodeagent.tools.bootstrap import build_base_tool_runtime
    from pycodeagent.tools.context import ToolContext

    output_dir = output_dir.resolve()

    # Use bootstrap defaults if not provided
    if profile is None or runtime is None:
        _, default_profile, default_runtime = build_base_tool_runtime()
        if profile is None:
            profile = default_profile
        if runtime is None:
            runtime = default_runtime

    # Prepare workspace - uses unique directory to avoid conflicts
    workspace_base = output_dir / "w"
    try:
        workspace_root = prepare_workspace(task.repo_path, workspace_base)
    except (ValueError, OSError) as e:
        # Record setup failure and persist minimal artifacts
        # Catch both ValueError (our errors) and OSError (permission, disk, etc.)
        trajectory = Trajectory(
            task_id=task.task_id,
            repo=str(task.repo_path),  # Source repo since workspace doesn't exist
            tool_profile_id=profile.profile_id,
            status=RunStatus.ERROR,
            reward=-0.2,
        )
        trajectory.metadata = {
            "setup_error": str(e),
            "failure_reason": "setup_error",
            "reward_reason": "setup_error",
        }

        # Persist minimal artifacts even on setup failure
        recorder = RunRecorder(output_dir)
        recorder.write_trajectory(trajectory)
        recorder.write_tool_profile(profile)
        # Write empty/error verifier result
        error_verifier = VerifyResult(passed=False, score=0.0, stdout="", stderr=str(e))
        recorder.write_verifier_result(error_verifier)
        recorder.write_final_patch("")

        return trajectory

    # Create a workspace-relative task for the agent
    # This ensures trajectory.repo reflects the actual workspace where agent runs
    workspace_task = CodingTask(
        task_id=task.task_id,
        repo_path=workspace_root,  # Point to workspace, not source
        prompt=task.prompt,
        test_command=task.test_command,
        max_turns=task.max_turns,
        allowed_files=task.allowed_files,
        forbidden_files=task.forbidden_files,
        metadata=task.metadata,
    )

    # Run agent
    ctx = ToolContext(workspace_root=workspace_root, task=workspace_task)
    trajectory = run_agent_task(workspace_task, client, runtime, profile, ctx)

    # Run verifier (use original task for test_command but workspace for execution)
    verify_result = run_verifier(task, workspace_root)
    trajectory.verifier = verify_result
    if trajectory.status == RunStatus.COMPLETED:
        trajectory.status = _status_from_verifier(verify_result)

    # Compute diff
    patch_text = compute_diff(task.repo_path, workspace_root)
    trajectory.final_diff = patch_text

    # Compute reward
    reward, reward_reason = compute_reward_details(
        verify_result,
        patch_text,
        trajectory,
    )
    trajectory.reward = reward
    trajectory.metadata["reward_reason"] = reward_reason
    if trajectory.status != RunStatus.COMPLETED:
        trajectory.metadata.setdefault("failure_reason", reward_reason)

    # Persist artifacts
    recorder = RunRecorder(output_dir)
    recorder.write_all(trajectory, profile, verify_result, patch_text)

    return trajectory
