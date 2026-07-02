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
from pycodeagent.runtime_trace import RuntimeTraceWriter
from pycodeagent.tools.bootstrap import ToolStackKind
from pycodeagent.trajectory.recorder import RunRecorder
from pycodeagent.trajectory.schema import RunStatus, Trajectory, VerifyResult

if TYPE_CHECKING:
    from pycodeagent.agent.llm_client import BaseLLMClient
    from pycodeagent.agent.provider_runtime import RuntimeProviderConfig
    from pycodeagent.agent.retained_history import RetainedHistoryWriter
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
_VALID_TOOL_STACK_KINDS = {"native_claude", "native_codex"}


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


def _resolve_profile_and_runtime(
    *,
    profile: "ToolProfile | None",
    runtime: "ToolRuntime | None",
    profile_mode: str | None,
    profile_seed: int,
    tool_stack_kind: ToolStackKind,
) -> tuple["ToolProfile", "ToolRuntime"]:
    """Resolve the effective tool profile/runtime for a local run.

    The formal runtime entry supports two mutually exclusive profile-selection
    paths:
    - pass a concrete ``profile``
    - request a deterministic sampled profile via ``profile_mode/profile_seed``

    If neither is supplied, the requested native family base profile/runtime is
    used.
    """
    from pycodeagent.mutations.profile_sampler import build_sampled_tool_profile
    from pycodeagent.tools.bootstrap import (
        _build_tool_stack,
        _infer_tool_stack_kind_from_profile,
    )
    from pycodeagent.tools.profile_factory import (
        build_native_claude_profile,
        build_native_codex_profile,
    )

    if profile is not None and profile_mode is not None:
        raise ValueError(
            "run_coding_task accepts either profile or profile_mode, not both"
        )
    if tool_stack_kind not in _VALID_TOOL_STACK_KINDS:
        raise ValueError(f"Unknown tool_stack_kind: {tool_stack_kind!r}")

    profile_stack_kind = (
        _infer_tool_stack_kind_from_profile(profile)
        if profile is not None
        else None
    )
    if (
        profile_stack_kind is not None
        and tool_stack_kind != profile_stack_kind
    ):
        raise ValueError(
            "run_coding_task received a native profile whose family conflicts "
            f"with tool_stack_kind={tool_stack_kind!r}"
        )
    if profile is not None and profile_stack_kind is None:
        raise ValueError(
            "run_coding_task received a profile without native family metadata; "
            "pass a profile built from native_claude/native_codex."
        )

    if profile is None and profile_mode is not None:
        profile = build_sampled_tool_profile(
            mode=profile_mode,
            seed=profile_seed,
            family="claude" if tool_stack_kind == "native_claude" else "codex",
        )
        profile_stack_kind = tool_stack_kind

    if runtime is None:
        selected_stack_kind = tool_stack_kind
        if profile is not None:
            selected_stack_kind = (
                profile_stack_kind or _infer_tool_stack_kind_from_profile(profile)
            )
        if selected_stack_kind is None:
            raise ValueError(
                "run_coding_task could not infer a native tool stack from the profile."
            )

        _, default_profile, runtime = _build_tool_stack(
            selected_stack_kind,
            profile_id=(profile.profile_id if profile is not None else None),
        )
        if profile is None:
            profile = default_profile

    if profile is None:
        if tool_stack_kind == "native_claude":
            profile = build_native_claude_profile()
        else:
            profile = build_native_codex_profile()

    return profile, runtime


def _client_runtime_provenance(client: "BaseLLMClient") -> dict[str, Any]:
    """Best-effort extraction of non-secret provider provenance."""
    try:
        provenance = client.runtime_provenance()
    except Exception:
        return {}
    if not isinstance(provenance, dict):
        return {}
    return dict(provenance)


def _client_protocol_provenance(client: "BaseLLMClient") -> dict[str, Any]:
    """Best-effort extraction of protocol/runtime capability facts."""
    try:
        capabilities = client.runtime_capabilities()
    except Exception:
        return {}
    if capabilities is None:
        return {}
    try:
        payload = capabilities.model_dump(mode="json")
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return dict(payload)


def _merged_client_provenance(client: "BaseLLMClient") -> dict[str, Any]:
    merged = _client_runtime_provenance(client)
    merged.update(_client_protocol_provenance(client))
    return merged


def run_coding_task(
    task: CodingTask,
    client: "BaseLLMClient",
    output_dir: Path,
    *,
    profile: "ToolProfile | None" = None,
    runtime: "ToolRuntime | None" = None,
    profile_mode: str | None = None,
    profile_seed: int = 0,
    tool_stack_kind: ToolStackKind,
    context_policy_mode: str = "full_history",
    context_max_messages: int | None = None,
    context_max_tokens: int | None = None,
    tool_token_reserve: int = 0,
    response_token_reserve: int = 0,
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
        profile: Tool profile for the selected native family.
        runtime: Tool runtime for the selected native family.
        profile_mode: Optional sampled profile mode to resolve at runtime entry.
            When provided, this samples from the selected native family base.
        profile_seed: Deterministic seed used with ``profile_mode``.
        tool_stack_kind: Explicit runtime stack family selection for the
            formal local runtime entry.
        context_policy_mode: Request-time context selection policy for the
            local runtime.
        context_max_messages: Optional message-count limit used with
            non-default context policies.
        context_max_tokens: Optional token budget for request-visible context,
            using the runtime's deterministic token estimator.
        tool_token_reserve: Reserved token budget for exposed tool specs.
        response_token_reserve: Reserved token budget for model response space.

    Returns:
        The completed trajectory with verifier result and reward.
    """
    # Local imports to avoid circular dependency at module load time
    from pycodeagent.agent.runner import run_agent_task
    from pycodeagent.agent.history_evolution import write_history_evolution_report
    from pycodeagent.agent.history_lineage import write_history_lineage_report
    from pycodeagent.agent.history_reconciliation import (
        write_compaction_chain_report,
        write_history_reconciliation_report,
    )
    from pycodeagent.agent.request_context import RequestContextWriter
    from pycodeagent.agent.request_context import request_context_metadata
    from pycodeagent.agent.retained_history import (
        RetainedHistoryWriter,
        retained_history_metadata,
    )
    from pycodeagent.tools.context import ToolContext

    output_dir = output_dir.resolve()
    provider_info = _merged_client_provenance(client)

    profile, runtime = _resolve_profile_and_runtime(
        profile=profile,
        runtime=runtime,
        profile_mode=profile_mode,
        profile_seed=profile_seed,
        tool_stack_kind=tool_stack_kind,
    )

    # Prepare workspace - uses unique directory to avoid conflicts
    workspace_base = output_dir / "w"
    try:
        workspace_root = prepare_workspace(task.repo_path, workspace_base)
    except (ValueError, OSError) as e:
        request_context_writer = RequestContextWriter.create(
            output_dir,
            run_id=output_dir.name or "local_runtime_run",
            task_id=task.task_id,
            workspace_root=str(workspace_base),
        )
        retained_history_writer = RetainedHistoryWriter.create(
            output_dir,
            run_id=output_dir.name or "local_runtime_run",
            task_id=task.task_id,
            workspace_root=str(workspace_base),
        )
        trace_writer = RuntimeTraceWriter.create(
            output_dir,
            run_id=output_dir.name or "local_runtime_run",
            task_id=task.task_id,
            tool_profile_id=profile.profile_id,
            workspace_root=str(workspace_base),
        )
        trace_writer.append(
            "run_started",
            data={
                "task_prompt": task.prompt,
                "max_turns": task.max_turns,
                "repo_path": str(task.repo_path),
                "workspace_root": str(workspace_base),
                **({"provider": provider_info} if provider_info else {}),
            },
        )
        trace_writer.append(
            "run_completed",
            data={
                "total_turns": 0,
                "final_status": RunStatus.ERROR.value,
                "stop_reason": "setup_error",
                "stop_detail": str(e),
            },
        )
        trace_writer.finalize()
        request_context_writer.finalize()
        retained_history_writer.finalize()
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
        if provider_info:
            trajectory.metadata["provider"] = provider_info

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
    ctx = ToolContext(
        workspace_root=workspace_root,
        task=workspace_task,
        artifact_root=output_dir,
    )
    trace_writer = RuntimeTraceWriter.create(
        output_dir,
        run_id=output_dir.name or "local_runtime_run",
        task_id=workspace_task.task_id,
        tool_profile_id=profile.profile_id,
        workspace_root=str(workspace_root),
    )
    retained_history_writer = RetainedHistoryWriter.create(
        output_dir,
        run_id=output_dir.name or "local_runtime_run",
        task_id=workspace_task.task_id,
        workspace_root=str(workspace_root),
    )
    request_context_writer = RequestContextWriter.create(
        output_dir,
        run_id=output_dir.name or "local_runtime_run",
        task_id=workspace_task.task_id,
        workspace_root=str(workspace_root),
    )
    trajectory = run_agent_task(
        workspace_task,
        client,
        runtime,
        profile,
        ctx,
        trace_writer=trace_writer,
        retained_history_writer=retained_history_writer,
        request_context_writer=request_context_writer,
        context_policy_mode=context_policy_mode,
        context_max_messages=context_max_messages,
        context_max_tokens=context_max_tokens,
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
    )
    trace_writer.finalize()
    request_context_writer.finalize()
    retained_history_writer.finalize()
    try:
        retained_history_meta = retained_history_metadata(output_dir)
    except Exception as exc:
        retained_history_meta = None
        trajectory.metadata["retained_history_metadata_error"] = str(exc)
    try:
        request_context_meta = request_context_metadata(output_dir)
    except Exception as exc:
        request_context_meta = None
        trajectory.metadata["request_context_metadata_error"] = str(exc)
    try:
        history_evolution_report = write_history_evolution_report(output_dir)
        history_evolution_report_path = str(output_dir / "history_evolution_report.json")
    except Exception as exc:
        history_evolution_report = None
        history_evolution_report_path = ""
        trajectory.metadata["history_evolution_report_error"] = str(exc)
    try:
        history_lineage_report = write_history_lineage_report(output_dir)
        history_lineage_report_path = str(output_dir / "history_lineage_report.json")
    except Exception as exc:
        history_lineage_report = None
        history_lineage_report_path = ""
        trajectory.metadata["history_lineage_report_error"] = str(exc)
    try:
        history_reconciliation_report = write_history_reconciliation_report(output_dir)
        history_reconciliation_report_path = str(
            output_dir / "history_reconciliation_report.json"
        )
    except Exception as exc:
        history_reconciliation_report = None
        history_reconciliation_report_path = ""
        trajectory.metadata["history_reconciliation_report_error"] = str(exc)
    try:
        compaction_chain_report = write_compaction_chain_report(output_dir)
        compaction_chain_report_path = str(output_dir / "compaction_chain_report.json")
    except Exception as exc:
        compaction_chain_report = None
        compaction_chain_report_path = ""
        trajectory.metadata["compaction_chain_report_error"] = str(exc)

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
    if provider_info:
        trajectory.metadata["provider"] = provider_info
    if retained_history_meta is not None:
        trajectory.metadata["retained_history_log_id"] = retained_history_meta.log_id
        trajectory.metadata["retained_history_entry_count"] = (
            retained_history_meta.entry_count
        )
    if request_context_meta is not None:
        trajectory.metadata["request_context_log_id"] = request_context_meta.log_id
        trajectory.metadata["request_context_entry_count"] = (
            request_context_meta.entry_count
        )
    if history_evolution_report_path:
        trajectory.metadata["history_evolution_report_path"] = (
            history_evolution_report_path
        )
    if history_evolution_report is not None:
        trajectory.metadata["history_evolution_report_ok"] = (
            history_evolution_report.ok
        )
    if history_lineage_report_path:
        trajectory.metadata["history_lineage_report_path"] = (
            history_lineage_report_path
        )
    if history_lineage_report is not None:
        trajectory.metadata["history_lineage_report_ok"] = history_lineage_report.ok
    if history_reconciliation_report_path:
        trajectory.metadata["history_reconciliation_report_path"] = (
            history_reconciliation_report_path
        )
    if history_reconciliation_report is not None:
        trajectory.metadata["history_reconciliation_report_ok"] = (
            history_reconciliation_report.ok
        )
    if compaction_chain_report_path:
        trajectory.metadata["compaction_chain_report_path"] = (
            compaction_chain_report_path
        )
    if compaction_chain_report is not None:
        trajectory.metadata["compaction_chain_report_ok"] = compaction_chain_report.ok

    # Persist artifacts
    recorder = RunRecorder(output_dir)
    recorder.write_all(trajectory, profile, verify_result, patch_text)

    return trajectory


def run_coding_task_with_provider(
    task: CodingTask,
    provider_config: "RuntimeProviderConfig | Path | str",
    output_dir: Path,
    **kwargs: Any,
) -> Trajectory:
    """Run a single coding task using a formal real-provider config."""
    from pycodeagent.agent.provider_runtime import (
        RuntimeProviderConfig,
        build_llm_client,
        resolve_runtime_provider_config,
    )

    if isinstance(provider_config, RuntimeProviderConfig):
        resolved_provider_config = provider_config
    else:
        resolved_provider_config = resolve_runtime_provider_config(provider_config)

    client = build_llm_client(resolved_provider_config)
    return run_coding_task(task, client, output_dir, **kwargs)
