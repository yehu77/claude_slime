"""Mock adapter path for scaffold phase one."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pycodeagent.adapters.base import AgentRunContext, ToolCatalogProvider
from pycodeagent.adapters.workspace_digest import (
    WORKSPACE_DIGEST_ALGORITHM,
    WORKSPACE_DIGEST_VERSION,
    compute_workspace_digest,
)
from pycodeagent.env.task import CodingTask
from pycodeagent.tools.families import build_claude_canonical_registry
from pycodeagent.tools.profile_factory import build_native_claude_profile
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.traces.canonical_trace import (
    CanonicalAction,
    CanonicalTrace,
    NormalizationReport,
    NormalizationResult,
)
from pycodeagent.traces.raw_trace import (
    RawAgentRunResult,
    RawAgentTrace,
    RawEvent,
    RawTraceSummary,
    write_raw_trace,
)
from pycodeagent.traces.tool_catalog import AgentToolCatalog, CatalogToolEntry, write_tool_catalog
from pycodeagent.trajectory.schema import RunStatus, VerifyResult


class MockAdapter:
    """Deterministic adapter that emits synthetic raw traces."""

    _AGENT_ID = "mock_agent"
    _AGENT_VERSION = "v1"

    def __init__(self, *, emit_tool_catalog: bool = True) -> None:
        self._emit_tool_catalog = emit_tool_catalog

    def agent_id(self) -> str:
        return self._AGENT_ID

    def agent_version(self) -> str:
        return self._AGENT_VERSION

    def run_task(self, task: CodingTask, context: AgentRunContext) -> RawAgentRunResult:
        profile = build_native_claude_profile(profile_id="mock_base")
        tool_catalog_path: str | None = None
        catalog = build_mock_tool_catalog(
            task_id=task.task_id,
            agent_name=self.agent_id(),
            agent_version=self.agent_version(),
            profile=profile,
        )
        if self._emit_tool_catalog:
            tool_catalog_path = str(
                write_tool_catalog(catalog, context.run_dir / "tool_catalog.json")
            )

        before_hash = compute_workspace_digest(context.workspace_dir)
        trace = generate_synthetic_raw_trace(
            task=task,
            agent_name=self.agent_id(),
            agent_version=self.agent_version(),
            workspace_dir=context.workspace_dir,
            tool_catalog_id=catalog.catalog_id if tool_catalog_path else None,
            profile=profile,
        )
        raw_trace_path = context.run_dir / "raw_trace.jsonl"
        raw_trace_summary_path = context.run_dir / "raw_trace_summary.json"
        write_raw_trace(trace, raw_trace_path, raw_trace_summary_path)

        verifier = trace.verifier_result or VerifyResult(passed=True, score=1.0)
        verifier_path = context.run_dir / "verifier.json"
        verifier_path.write_text(
            json.dumps(verifier.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        final_diff_path = context.run_dir / "final.diff"
        final_diff_path.write_text(trace.final_diff, encoding="utf-8")
        context.stdout_path.write_text("mock adapter completed\n", encoding="utf-8")
        context.stderr_path.write_text("", encoding="utf-8")
        (context.run_dir / "adapter_metadata.json").write_text(
            json.dumps(
                {
                    "agent_id": self.agent_id(),
                    "agent_version": self.agent_version(),
                    "tool_catalog_emitted": self._emit_tool_catalog,
                    "workspace_digest_algorithm": WORKSPACE_DIGEST_ALGORITHM,
                    "workspace_digest_version": WORKSPACE_DIGEST_VERSION,
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
            status=trace.status,
            tool_catalog_path=tool_catalog_path,
            raw_trace_path=str(raw_trace_path),
            raw_trace_summary_path=str(raw_trace_summary_path),
            stdout_path=str(context.stdout_path),
            stderr_path=str(context.stderr_path),
            final_diff_path=str(final_diff_path),
            verifier_result_path=str(verifier_path),
            workspace_before_hash=before_hash,
            workspace_after_hash=after_hash,
            metadata={
                "trace_id": trace.trace_id,
                "workspace_digest_algorithm": WORKSPACE_DIGEST_ALGORITHM,
                "workspace_digest_version": WORKSPACE_DIGEST_VERSION,
            },
        )


class MockToolCatalogProvider:
    """Fallback provider for the mock adapter."""

    def __init__(self) -> None:
        self._profile = build_native_claude_profile(profile_id="mock_base")

    def agent_id(self) -> str:
        return "mock_agent"

    def get_tool_catalog(
        self,
        *,
        task: CodingTask | None = None,
        workspace_dir: Path | None = None,
        run_artifacts: RawAgentRunResult | None = None,
    ) -> AgentToolCatalog | None:
        task_id = task.task_id if task is not None else "unknown_task"
        return build_mock_tool_catalog(
            task_id=task_id,
            agent_name=self.agent_id(),
            agent_version="v1",
            profile=self._profile,
        )


class MockTraceNormalizer:
    """Deterministic mock normalizer for phase-one scaffold tests."""

    def __init__(self) -> None:
        self._profile = build_native_claude_profile(profile_id="mock_base")
        self._registry = build_claude_canonical_registry()

    def agent_id(self) -> str:
        return "mock_agent"

    def normalize(
        self,
        raw_trace: RawAgentTrace,
        *,
        tool_catalog: AgentToolCatalog | None = None,
    ) -> NormalizationResult:
        events_by_id = {event.event_id: event for event in raw_trace.events}
        agent_command_children: dict[str, list[RawEvent]] = {}
        for event in raw_trace.events:
            if (
                event.event_kind == "command_exec"
                and event.parsed_payload.get("command_role") == "agent_command"
                and event.parent_event_id is not None
            ):
                agent_command_children.setdefault(event.parent_event_id, []).append(event)

        actions: list[CanonicalAction] = []
        mapped_events: list[str] = []
        unmapped_events: list[str] = []
        warnings: list[str] = []
        represented_command_event_ids: set[str] = set()

        for event in raw_trace.events:
            if event.event_kind == "tool_call":
                parsed = event.parsed_payload
                canonical_name = parsed.get("canonical_name")
                try:
                    tool_name = str(parsed["tool_name"])
                    arguments = dict(parsed.get("arguments", {}))
                    view, canonical_args = self._profile.map_call_arguments(
                        tool_name,
                        arguments,
                        canonical_tool=self._registry.get(str(canonical_name or tool_name)),
                    )
                except Exception as exc:
                    unmapped_events.append(event.event_id)
                    warnings.append(f"Failed to normalize {event.event_id}: {exc}")
                    continue
                raw_event_refs = [event.event_id]
                for command_event in agent_command_children.get(event.event_id, []):
                    raw_event_refs.append(command_event.event_id)
                    represented_command_event_ids.add(command_event.event_id)
                actions.append(
                    CanonicalAction(
                        action_id=f"action_{len(actions) + 1}",
                        capability=view.canonical_name.upper(),
                        canonical_args=canonical_args,
                        raw_event_refs=raw_event_refs,
                        raw_tool_name=tool_name,
                        metadata={"tool_call_event_id": event.event_id},
                    )
                )
                mapped_events.extend(raw_event_refs)
                continue

            if event.event_kind == "command_exec":
                role = event.parsed_payload.get("command_role")
                if role != "agent_command":
                    unmapped_events.append(event.event_id)
                    continue
                if event.event_id in represented_command_event_ids:
                    continue
                parent_id = event.parent_event_id
                parent = events_by_id.get(parent_id or "")
                if parent is None or parent.event_kind != "tool_call":
                    unmapped_events.append(event.event_id)
                    warnings.append(
                        f"Agent command event {event.event_id} is missing a tool_call parent"
                    )
                    continue
                parsed = parent.parsed_payload
                tool_name = str(parsed["tool_name"])
                arguments = dict(parsed.get("arguments", {}))
                try:
                    view, canonical_args = self._profile.map_call_arguments(
                        tool_name,
                        arguments,
                        canonical_tool=self._registry.get("Bash"),
                    )
                except Exception as exc:
                    unmapped_events.append(event.event_id)
                    warnings.append(f"Failed to normalize {event.event_id}: {exc}")
                    continue
                actions.append(
                    CanonicalAction(
                        action_id=f"action_{len(actions) + 1}",
                        capability=view.canonical_name.upper(),
                        canonical_args=canonical_args,
                        raw_event_refs=[parent.event_id, event.event_id],
                        raw_tool_name=tool_name,
                        metadata={"tool_call_event_id": parent.event_id},
                    )
                )
                mapped_events.extend([parent.event_id, event.event_id])

        trace = CanonicalTrace(
            trace_id=raw_trace.trace_id,
            task_id=raw_trace.task_id,
            agent_name=raw_trace.agent_name,
            agent_version=raw_trace.agent_version,
            actions=actions,
            final_diff=raw_trace.final_diff,
            verifier_result=raw_trace.verifier_result,
            status=raw_trace.status,
            metadata={"source": "mock_normalizer", **raw_trace.metadata},
        )
        report = NormalizationReport(
            trace_id=raw_trace.trace_id,
            catalog_id=tool_catalog.catalog_id if tool_catalog is not None else None,
            mapped_events=mapped_events,
            unmapped_events=_dedupe_preserve_order(unmapped_events),
            warnings=warnings,
        )
        return NormalizationResult(canonical_trace=trace, report=report)


def build_mock_tool_catalog(
    *,
    task_id: str,
    agent_name: str,
    agent_version: str,
    profile: ToolProfile,
) -> AgentToolCatalog:
    """Build a deterministic mock tool catalog from a ToolProfile."""
    tools = []
    for tool_view in profile.tools:
        tools.append(
            CatalogToolEntry(
                raw_tool_name=tool_view.exposed_name,
                description=tool_view.description,
                input_schema=tool_view.input_schema,
                output_format_hint="text",
                availability_conditions={},
                tool_family=tool_view.canonical_name,
                canonical_name=tool_view.canonical_name,
                version=tool_view.version,
                metadata={
                    "canonical_name": tool_view.canonical_name,
                    "exposed_name": tool_view.exposed_name,
                },
            )
        )
    return AgentToolCatalog(
        catalog_id=f"{agent_name}__{task_id}__catalog",
        agent_name=agent_name,
        agent_version=agent_version,
        capture_mode="synthetic",
        source_kind="mock_provider",
        tools=tools,
        metadata={"tool_profile": profile.model_dump(mode="json")},
    )


def generate_synthetic_raw_trace(
    *,
    task: CodingTask,
    agent_name: str,
    agent_version: str,
    workspace_dir: Path,
    tool_catalog_id: str | None,
    profile: ToolProfile,
) -> RawAgentTrace:
    """Generate a deterministic synthetic raw trace for one task."""
    plan = list(task.metadata.get("mock_plan", _default_mock_plan(task)))
    events: list[RawEvent] = []
    seq = 1
    events.append(
        RawEvent(
            event_id="event_001",
            seq=seq,
            event_kind="message",
            source="harness",
            visibility="model",
            evidence_level="synthetic",
            parsed_payload={"role": "system", "content": "You are a coding agent."},
        )
    )
    seq += 1
    events.append(
        RawEvent(
            event_id="event_002",
            seq=seq,
            event_kind="message",
            source="harness",
            visibility="model",
            evidence_level="synthetic",
            parsed_payload={"role": "user", "content": task.prompt},
        )
    )
    seq += 1

    registry = build_claude_canonical_registry()
    for step_index, step in enumerate(plan, start=1):
        tool_name = str(step["tool"])
        canonical_tool = registry.get(tool_name)
        projected = profile.project_canonical_call(
            tool_name,
            dict(step.get("arguments", {})),
            call_id=f"call_{step_index}",
            canonical_tool=canonical_tool,
        )
        assistant_event_id = f"event_{seq:03d}"
        events.append(
            RawEvent(
                event_id=assistant_event_id,
                seq=seq,
                event_kind="assistant_text",
                source="agent",
                visibility="model",
                evidence_level="synthetic",
                parsed_payload={
                    "text": str(step.get("assistant_text", f"Use {projected.name}.")),
                },
            )
        )
        seq += 1
        tool_call_event_id = f"event_{seq:03d}"
        events.append(
            RawEvent(
                event_id=tool_call_event_id,
                seq=seq,
                event_kind="tool_call",
                source="agent",
                visibility="model",
                evidence_level="synthetic",
                raw_payload=projected.to_payload(),
                parsed_payload={
                    "call_id": projected.call_id,
                    "tool_name": projected.name,
                    "arguments": projected.arguments,
                    "canonical_name": tool_name,
                },
                metadata={"step_index": step_index},
            )
        )
        seq += 1

        if tool_name == "Bash":
            command = str(step["arguments"]["command"])
            events.append(
                RawEvent(
                    event_id=f"event_{seq:03d}",
                    seq=seq,
                    event_kind="command_exec",
                    source="agent",
                    visibility="harness",
                    evidence_level="synthetic",
                    parsed_payload={
                        "command": command,
                        "argv": [command],
                        "cwd": step["arguments"].get("cwd", "."),
                        "command_role": "agent_command",
                    },
                    parent_event_id=tool_call_event_id,
                )
            )
            seq += 1

        result_payload = step.get("result", {})
        events.append(
            RawEvent(
                event_id=f"event_{seq:03d}",
                seq=seq,
                event_kind="tool_result",
                source="harness",
                visibility="model",
                evidence_level="synthetic",
                parsed_payload={
                    "tool_call_id": projected.call_id,
                    "tool_name": projected.name,
                    "canonical_name": tool_name,
                    "ok": bool(result_payload.get("ok", True)),
                    "content": str(result_payload.get("content", f"{tool_name} completed")),
                },
                parent_event_id=tool_call_event_id,
            )
        )
        seq += 1

    events.append(
        RawEvent(
            event_id=f"event_{seq:03d}",
            seq=seq,
            event_kind="command_exec",
            source="harness",
            visibility="internal",
            evidence_level="synthetic",
            parsed_payload={
                "command": str(task.test_command),
                "argv": [str(task.test_command)],
                "cwd": ".",
                "command_role": "harness_verifier",
            },
        )
    )
    seq += 1
    events.append(
        RawEvent(
            event_id=f"event_{seq:03d}",
            seq=seq,
            event_kind="run_end",
            source="harness",
            visibility="internal",
            evidence_level="synthetic",
            parsed_payload={"status": RunStatus.COMPLETED.value},
        )
    )

    return RawAgentTrace(
        summary=RawTraceSummary(
            trace_id=f"{task.task_id}__trace",
            agent_name=agent_name,
            agent_version=agent_version,
            task_id=task.task_id,
            workspace_dir=str(workspace_dir),
            tool_catalog_id=tool_catalog_id,
            status=RunStatus.COMPLETED,
            final_diff="diff --git a/README.md b/README.md\n",
            verifier_result=VerifyResult(passed=True, score=1.0, stdout="ok", stderr=""),
            metadata={"source_type": "synthetic", "task_prompt": task.prompt},
        ),
        events=events,
    )


def _default_mock_plan(task: CodingTask) -> list[dict[str, Any]]:
    prompt_text = task.prompt.lower()
    return [
        {
            "tool": "Read",
            "arguments": {"file_path": "README.md"},
            "assistant_text": "I will inspect the repository README first.",
            "result": {"ok": True, "content": "README contents"},
        },
        {
            "tool": "Bash",
            "arguments": {"command": "pytest -q"},
            "assistant_text": (
                "I will run tests to validate the current state."
                if "test" in prompt_text
                else "I will run the project test suite."
            ),
            "result": {"ok": True, "content": "pytest passed"},
        },
    ]


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
