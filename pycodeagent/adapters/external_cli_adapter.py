"""Shared raw-artifact capture adapter for external CLI agents."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pycodeagent.adapters.base import AgentRunContext
from pycodeagent.adapters.workspace_digest import (
    WORKSPACE_DIGEST_ALGORITHM,
    WORKSPACE_DIGEST_VERSION,
    compute_workspace_digest,
)
from pycodeagent.env.coding_env import compute_diff
from pycodeagent.env.task import CodingTask
from pycodeagent.env.verifier import run_verifier
from pycodeagent.traces.raw_trace import (
    ArtifactRef,
    RawAgentRunResult,
    RawAgentTrace,
    RawEvent,
    RawTraceSummary,
    write_raw_trace,
    write_raw_trace_summary,
)
from pycodeagent.trajectory.schema import RunStatus, VerifyResult


class ArtifactTruthConflictError(ValueError):
    """A sidecar asserted a derived field that conflicts with harness evidence."""


class ExternalCliArtifactAdapter:
    """Common subprocess + sidecar raw-artifact capture for external agents."""

    def __init__(
        self,
        *,
        agent_id: str,
        display_name: str,
        command_prefix: list[str],
        exec_subcommand: str | None,
        extra_args: list[str] | None = None,
        timeout_seconds: int = 900,
        environment: dict[str, str] | None = None,
        sidecar_raw_trace_name: str = "raw_trace.jsonl",
        sidecar_summary_name: str = "raw_trace_summary.json",
        sidecar_catalog_name: str = "tool_catalog.json",
        adapter_version: str = "raw_trace_v1",
    ) -> None:
        self._agent_id = agent_id
        self._display_name = display_name
        self._command_prefix = list(command_prefix)
        self._exec_subcommand = exec_subcommand
        self._extra_args = list(extra_args or [])
        self._timeout_seconds = timeout_seconds
        self._environment = dict(environment or {})
        self._sidecar_raw_trace_name = sidecar_raw_trace_name
        self._sidecar_summary_name = sidecar_summary_name
        self._sidecar_catalog_name = sidecar_catalog_name
        self._adapter_version = adapter_version

    def agent_id(self) -> str:
        return self._agent_id

    def agent_version(self) -> str:
        return self._adapter_version

    def build_argv(self, task: CodingTask) -> list[str]:
        argv = list(self._command_prefix)
        if self._exec_subcommand is not None:
            argv.append(self._exec_subcommand)
        argv.extend(self._extra_args)
        argv.append(task.prompt)
        return argv

    def build_runtime_environment(
        self,
        *,
        task: CodingTask,
        context: AgentRunContext,
    ) -> dict[str, str]:
        """Return adapter-specific environment overrides for one run."""
        del task, context
        return {}

    def run_task(self, task: CodingTask, context: AgentRunContext) -> RawAgentRunResult:
        before_hash = compute_workspace_digest(context.workspace_dir)
        raw_trace_path = context.run_dir / "raw_trace.jsonl"
        raw_trace_summary_path = context.run_dir / "raw_trace_summary.json"
        tool_catalog_path = context.run_dir / "tool_catalog.json"
        final_diff_path = context.run_dir / "final.diff"
        verifier_path = context.run_dir / "verifier.json"
        adapter_metadata_path = context.run_dir / "adapter_metadata.json"

        sidecar_raw_trace_path = context.run_dir / self._sidecar_raw_trace_name
        sidecar_summary_path = context.run_dir / self._sidecar_summary_name
        sidecar_catalog_path = context.run_dir / self._sidecar_catalog_name
        argv = self.build_argv(task)
        resolved_argv = resolve_command_argv(argv)
        env = build_sidecar_env(
            context=context,
            raw_trace_path=sidecar_raw_trace_path,
            raw_trace_summary_path=sidecar_summary_path,
            tool_catalog_path=sidecar_catalog_path,
            extra_env={
                **self._environment,
                **self.build_runtime_environment(task=task, context=context),
            },
        )

        stdout = ""
        stderr = ""
        status = RunStatus.COMPLETED
        returncode: int | None = None
        error: str | None = None

        try:
            proc = subprocess.run(
                resolved_argv,
                capture_output=True,
                text=False,
                timeout=self._timeout_seconds,
                cwd=context.workspace_dir,
                env=env,
            )
            stdout = decode_subprocess_output(proc.stdout)
            stderr = decode_subprocess_output(proc.stderr)
            returncode = proc.returncode
            status = RunStatus.COMPLETED if proc.returncode == 0 else RunStatus.FAILED
        except subprocess.TimeoutExpired as exc:
            stdout = decode_subprocess_output(exc.stdout)
            stderr = decode_subprocess_output(exc.stderr)
            status = RunStatus.TIMEOUT
            error = f"{self._display_name} timed out after {self._timeout_seconds}s"
        except FileNotFoundError as exc:
            status = RunStatus.ERROR
            error = f"{self._display_name} executable not found: {exc}"
        except Exception as exc:
            status = RunStatus.ERROR
            error = f"{self._display_name} execution error: {exc}"

        context.stdout_path.write_text(stdout or "", encoding="utf-8")
        context.stderr_path.write_text(stderr or "", encoding="utf-8")

        final_diff = compute_diff(task.repo_path, context.workspace_dir)
        final_diff_path.write_text(final_diff, encoding="utf-8")
        verifier = run_verifier(task, context.workspace_dir)
        verifier_path.write_text(
            json.dumps(verifier.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        sidecar_used = sidecar_raw_trace_path.exists() and sidecar_summary_path.exists()
        if sidecar_used:
            _copy_if_needed(sidecar_raw_trace_path, raw_trace_path)
            summary = reconcile_sidecar_summary(
                sidecar_summary_path=sidecar_summary_path,
                execution_status=status,
                final_diff=final_diff,
                verifier=verifier,
            )
            write_raw_trace_summary(summary, raw_trace_summary_path)
        else:
            observed_trace = build_observed_fallback_trace(
                agent_name=self.agent_id(),
                agent_version=self.agent_version(),
                task=task,
                context=context,
                argv=argv,
                stdout=stdout,
                stderr=stderr,
                status=status,
                error=error,
                returncode=returncode,
                final_diff=final_diff,
                verifier=verifier,
            )
            write_raw_trace(observed_trace, raw_trace_path, raw_trace_summary_path)

        tool_catalog_result_path: str | None = None
        if sidecar_catalog_path.exists():
            _copy_if_needed(sidecar_catalog_path, tool_catalog_path)
            tool_catalog_result_path = str(tool_catalog_path)

        adapter_metadata_path.write_text(
            json.dumps(
                {
                    "agent_id": self.agent_id(),
                    "agent_version": self.agent_version(),
                    "argv": argv,
                    "timeout_seconds": self._timeout_seconds,
                    "sidecar_raw_trace_detected": sidecar_used,
                    "sidecar_catalog_detected": sidecar_catalog_path.exists(),
                    "returncode": returncode,
                    "status": status.value,
                    "execution_status": status.value,
                    "error": error,
                    "workspace_digest_algorithm": WORKSPACE_DIGEST_ALGORITHM,
                    "workspace_digest_version": WORKSPACE_DIGEST_VERSION,
                    "sidecar_protocol_env": {
                        "PYCODEAGENT_AGENT_ID": self.agent_id(),
                        "PYCODEAGENT_RUN_DIR": str(context.run_dir),
                        "PYCODEAGENT_WORKSPACE_DIR": str(context.workspace_dir),
                        "PYCODEAGENT_RAW_TRACE_PATH": str(sidecar_raw_trace_path),
                        "PYCODEAGENT_RAW_TRACE_SUMMARY_PATH": str(sidecar_summary_path),
                        "PYCODEAGENT_TOOL_CATALOG_PATH": str(sidecar_catalog_path),
                    },
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        after_hash = compute_workspace_digest(context.workspace_dir)
        return RawAgentRunResult(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id(),
            agent_version=self.agent_version(),
            status=status,
            tool_catalog_path=tool_catalog_result_path,
            raw_trace_path=str(raw_trace_path),
            raw_trace_summary_path=str(raw_trace_summary_path),
            stdout_path=str(context.stdout_path),
            stderr_path=str(context.stderr_path),
            final_diff_path=str(final_diff_path),
            verifier_result_path=str(verifier_path),
            workspace_before_hash=before_hash,
            workspace_after_hash=after_hash,
            error=error,
            metadata={
                "sidecar_raw_trace_detected": sidecar_used,
                "sidecar_catalog_detected": sidecar_catalog_path.exists(),
                "command_prefix": self._command_prefix,
                "execution_status": status.value,
                "workspace_digest_algorithm": WORKSPACE_DIGEST_ALGORITHM,
                "workspace_digest_version": WORKSPACE_DIGEST_VERSION,
            },
        )


def build_sidecar_env(
    *,
    context: AgentRunContext,
    raw_trace_path: Path,
    raw_trace_summary_path: Path,
    tool_catalog_path: Path,
    extra_env: dict[str, str],
) -> dict[str, str]:
    run_dir = context.run_dir.resolve()
    workspace_dir = context.workspace_dir.resolve()
    stdout_path = context.stdout_path.resolve()
    stderr_path = context.stderr_path.resolve()
    raw_trace_path = raw_trace_path.resolve()
    raw_trace_summary_path = raw_trace_summary_path.resolve()
    tool_catalog_path = tool_catalog_path.resolve()
    env = dict(extra_env)
    env.update(
        {
            "PYCODEAGENT_RUN_ID": context.run_id,
            "PYCODEAGENT_TASK_ID": context.task_id,
            "PYCODEAGENT_AGENT_ID": context.agent_id,
            "PYCODEAGENT_RUN_DIR": str(run_dir),
            "PYCODEAGENT_WORKSPACE_DIR": str(workspace_dir),
            "PYCODEAGENT_STDOUT_PATH": str(stdout_path),
            "PYCODEAGENT_STDERR_PATH": str(stderr_path),
            "PYCODEAGENT_RAW_TRACE_PATH": str(raw_trace_path),
            "PYCODEAGENT_RAW_TRACE_SUMMARY_PATH": str(raw_trace_summary_path),
            "PYCODEAGENT_TOOL_CATALOG_PATH": str(tool_catalog_path),
        }
    )
    merged = dict(os.environ)
    merged.update(env)
    return merged


def resolve_command_argv(argv: list[str]) -> list[str]:
    """Resolve the executable portion of an argv list for subprocess use.

    This is especially important on Windows, where interactive shells may find
    ``.cmd`` / ``.ps1`` shims that ``subprocess`` will not reliably discover
    from a bare command name.
    """
    if not argv:
        raise ValueError("External CLI argv may not be empty")
    executable = argv[0]
    resolved = shutil.which(executable) or executable
    return [resolved, *argv[1:]]


def decode_subprocess_output(data: bytes | str | None) -> str:
    """Decode subprocess output without crashing on mixed encodings."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="replace")


def derive_final_status(
    *,
    execution_status: RunStatus,
    verifier: VerifyResult,
) -> RunStatus:
    """Derive task outcome without conflating it with process execution."""
    if execution_status != RunStatus.COMPLETED:
        return execution_status
    if not verifier.passed:
        return RunStatus.FAILED
    return RunStatus.COMPLETED


def reconcile_sidecar_summary(
    *,
    sidecar_summary_path: Path,
    execution_status: RunStatus,
    final_diff: str,
    verifier: VerifyResult,
) -> RawTraceSummary:
    """Rebuild derived summary fields from their authoritative artifacts.

    A sidecar may omit ``status``, ``final_diff``, and ``verifier_result``.
    If it supplies any of them, the value is treated as an explicit assertion
    and must exactly match the harness-derived value.
    """
    try:
        payload = json.loads(sidecar_summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid sidecar raw trace summary: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Sidecar raw trace summary must be a JSON object")

    final_status = derive_final_status(
        execution_status=execution_status,
        verifier=verifier,
    )
    authoritative = {
        "status": final_status.value,
        "final_diff": final_diff,
        "verifier_result": verifier.model_dump(mode="json"),
    }
    conflicts: list[str] = []
    for field, expected in authoritative.items():
        if field not in payload:
            continue
        asserted = payload[field]
        if field == "status":
            asserted = RunStatus(asserted).value
        elif field == "verifier_result":
            asserted = VerifyResult.model_validate(asserted).model_dump(mode="json")
        if asserted != expected:
            conflicts.append(field)

    sidecar_metadata = payload.get("metadata", {})
    if not isinstance(sidecar_metadata, dict):
        raise ValueError("Sidecar raw trace summary metadata must be a JSON object")
    metadata_claims = {
        "execution_status": execution_status.value,
        "final_status": final_status.value,
        "reward": verifier.score,
    }
    for field, expected in metadata_claims.items():
        if field in sidecar_metadata and sidecar_metadata[field] != expected:
            conflicts.append(f"metadata.{field}")

    if conflicts:
        joined = ", ".join(sorted(conflicts))
        raise ArtifactTruthConflictError(
            "Sidecar summary conflicts with authoritative artifacts: "
            f"{joined}. Omit harness-derived fields from sidecar summaries."
        )

    payload.update(authoritative)
    payload["metadata"] = {
        **sidecar_metadata,
        **metadata_claims,
        "truth_precedence": {
            "events": "raw_trace.jsonl",
            "final_diff": "final.diff",
            "verifier_result": "verifier.json",
            "execution_status": "adapter subprocess result",
            "final_status": "derived from execution_status and verifier_result",
            "reward": "verifier_result.score",
        },
    }
    return RawTraceSummary.model_validate(payload)


def build_observed_fallback_trace(
    *,
    agent_name: str,
    agent_version: str,
    task: CodingTask,
    context: AgentRunContext,
    argv: list[str],
    stdout: str,
    stderr: str,
    status: RunStatus,
    error: str | None,
    returncode: int | None,
    final_diff: str,
    verifier: VerifyResult,
) -> RawAgentTrace:
    final_status = derive_final_status(
        execution_status=status,
        verifier=verifier,
    )
    events: list[RawEvent] = [
        RawEvent(
            event_id="event_001",
            seq=1,
            event_kind="message",
            source="harness",
            visibility="model",
            evidence_level="observed",
            parsed_payload={"role": "user", "content": task.prompt},
        ),
        RawEvent(
            event_id="event_002",
            seq=2,
            event_kind="process_exec",
            source="adapter",
            visibility="internal",
            evidence_level="observed",
            parsed_payload={
                "argv": argv,
                "cwd": str(context.workspace_dir),
                "command_role": "setup",
            },
        ),
    ]
    next_seq = 3
    if stdout:
        events.append(
            RawEvent(
                event_id=f"event_{next_seq:03d}",
                seq=next_seq,
                event_kind="stdout_capture",
                source="agent",
                visibility="harness",
                evidence_level="observed",
                raw_payload={"text": stdout},
                parsed_payload={"char_count": len(stdout)},
                artifact_refs=[ArtifactRef(artifact_kind="stdout_log", path=str(context.stdout_path))],
            )
        )
        next_seq += 1
    if stderr:
        events.append(
            RawEvent(
                event_id=f"event_{next_seq:03d}",
                seq=next_seq,
                event_kind="stderr_capture",
                source="agent",
                visibility="harness",
                evidence_level="observed",
                raw_payload={"text": stderr},
                parsed_payload={"char_count": len(stderr)},
                artifact_refs=[ArtifactRef(artifact_kind="stderr_log", path=str(context.stderr_path))],
            )
        )
        next_seq += 1
    events.append(
        RawEvent(
            event_id=f"event_{next_seq:03d}",
            seq=next_seq,
            event_kind="run_end",
            source="adapter",
            visibility="internal",
            evidence_level="observed",
            parsed_payload={
                "execution_status": status.value,
                "final_status": final_status.value,
                "returncode": returncode,
            },
            error=error,
            artifact_refs=[
                ArtifactRef(artifact_kind="final_diff", path=str(context.run_dir / "final.diff")),
                ArtifactRef(artifact_kind="verifier_result", path=str(context.run_dir / "verifier.json")),
            ],
        )
    )
    return RawAgentTrace(
        summary=RawTraceSummary(
            trace_id=f"{context.run_id}__raw_trace",
            agent_name=agent_name,
            agent_version=agent_version,
            task_id=task.task_id,
            workspace_dir=str(context.workspace_dir),
            tool_catalog_id=None,
            status=final_status,
            final_diff=final_diff,
            verifier_result=verifier,
            metadata={
                "capture_mode": "observed_fallback",
                "error": error,
                "returncode": returncode,
                "execution_status": status.value,
                "final_status": final_status.value,
                "reward": verifier.score,
                "truth_precedence": {
                    "events": "raw_trace.jsonl",
                    "final_diff": "final.diff",
                    "verifier_result": "verifier.json",
                    "execution_status": "adapter subprocess result",
                    "final_status": "derived from execution_status and verifier_result",
                    "reward": "verifier_result.score",
                },
            },
        ),
        events=events,
    )


def _copy_if_needed(source: Path, target: Path) -> None:
    if source.resolve() == target.resolve():
        return
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
