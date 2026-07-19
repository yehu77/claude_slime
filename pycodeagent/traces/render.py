"""Canonical-trace rendering into schema-following samples."""

from __future__ import annotations

from typing import Any, Protocol

from pycodeagent.rl.schema_following import (
    CanonicalToolIntent,
    SchemaFollowingMessage,
    SchemaFollowingSample,
)
from pycodeagent.tools.families import (
    build_claude_canonical_registry,
    build_codex_canonical_registry,
)
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.traces.canonical_trace import CanonicalAction, CanonicalTrace
from pycodeagent.traces.raw_trace import RawAgentTrace, RawEvent


class AugmentationRenderer(Protocol):
    """Render canonical traces into alternate schema-following samples."""

    def render_from_trace(
        self,
        canonical_trace: CanonicalTrace,
        *,
        raw_trace: RawAgentTrace,
        target_profiles: list[ToolProfile],
    ) -> list[SchemaFollowingSample]:
        ...


class SchemaFollowingTraceRenderer:
    """Default renderer from canonical traces into schema-following samples."""

    def render_from_trace(
        self,
        canonical_trace: CanonicalTrace,
        *,
        raw_trace: RawAgentTrace,
        target_profiles: list[ToolProfile],
    ) -> list[SchemaFollowingSample]:
        registry = _canonical_registry_for_profiles(target_profiles)
        events_by_id = {event.event_id: event for event in raw_trace.events}
        samples: list[SchemaFollowingSample] = []

        for action_index, action in enumerate(canonical_trace.actions, start=1):
            context_messages = _context_before_action(raw_trace, action, events_by_id)
            if not context_messages:
                context_messages = [
                    SchemaFollowingMessage(
                        role="user",
                        content=f"Complete task {canonical_trace.task_id}.",
                    )
                ]
            canonical_tool = _canonical_tool_for_capability(registry, action.capability)
            intent = CanonicalToolIntent(
                tool=canonical_tool.canonical_name,
                arguments=action.canonical_args,
            )
            for profile in target_profiles:
                target_call = profile.project_canonical_call(
                    canonical_tool.canonical_name,
                    action.canonical_args,
                    call_id="call_1",
                    canonical_tool=canonical_tool,
                )
                mutation_category = str(profile.metadata.get("mode", profile.profile_id))
                samples.append(
                    SchemaFollowingSample(
                        sample_id=(
                            f"sf__{canonical_trace.task_id}__{action.action_id}"
                            f"__{profile.profile_id}"
                        ),
                        sample_type="schema_following",
                        source_type="synthetic",
                        split="train",
                        task_id=canonical_trace.task_id,
                        tool_profile_id=profile.profile_id,
                        mutation_category=mutation_category,
                        messages=context_messages,
                        canonical_intent=intent,
                        target_tool_call=target_call,
                        target_text=target_call.render_text(),
                        loss_mask_policy="assistant_tool_call_only",
                        metadata={
                            "trace_id": canonical_trace.trace_id,
                            "action_id": action.action_id,
                            "raw_event_refs": list(action.raw_event_refs),
                            "agent_name": canonical_trace.agent_name,
                            "profile_mode": profile.metadata.get("mode", "base"),
                        },
                    )
                )
        return samples


def _canonical_registry_for_profiles(target_profiles: list[ToolProfile]):
    families = {
        str(profile.metadata.get("family"))
        for profile in target_profiles
        if profile.metadata.get("family") is not None
    }
    if families == {"claude"}:
        return build_claude_canonical_registry()
    if families == {"codex"}:
        return build_codex_canonical_registry()
    raise ValueError(
        "SchemaFollowingTraceRenderer requires native-family target profiles "
        f"from exactly one family, got {sorted(families)!r}"
    )


def _canonical_tool_for_capability(registry, capability: str):
    """Resolve canonical trace capabilities without losing native name casing."""
    normalized = capability.casefold()
    matches = [
        tool
        for tool in registry.list()
        if tool.canonical_name.casefold() == normalized
    ]
    if len(matches) == 1:
        return matches[0]
    return registry.get(capability)


def _context_before_action(
    raw_trace: RawAgentTrace,
    action: CanonicalAction,
    events_by_id: dict[str, RawEvent],
) -> list[SchemaFollowingMessage]:
    target_event = _resolve_target_event(action, events_by_id)
    cutoff_seq = target_event.seq
    context: list[SchemaFollowingMessage] = []
    for event in raw_trace.events:
        if event.seq >= cutoff_seq:
            break
        message = _event_to_message(event)
        if message is not None:
            context.append(message)
    return context


def _resolve_target_event(
    action: CanonicalAction,
    events_by_id: dict[str, RawEvent],
) -> RawEvent:
    tool_call_event_id = action.metadata.get("tool_call_event_id")
    if isinstance(tool_call_event_id, str):
        return events_by_id[tool_call_event_id]
    refs = [events_by_id[event_id] for event_id in action.raw_event_refs if event_id in events_by_id]
    if not refs:
        raise ValueError(f"Action {action.action_id} has no valid raw_event_refs")
    tool_call_events = [event for event in refs if event.event_kind == "tool_call"]
    if tool_call_events:
        return min(tool_call_events, key=lambda event: event.seq)
    return min(refs, key=lambda event: event.seq)


def _event_to_message(event: RawEvent) -> SchemaFollowingMessage | None:
    if event.event_kind == "message":
        role = event.parsed_payload.get("role")
        content = event.parsed_payload.get("content", "")
        if role in {"system", "user", "assistant", "tool"} and isinstance(content, str):
            return SchemaFollowingMessage(
                role=role,
                content=content,
                metadata=dict(event.metadata),
            )
        return None

    if event.event_kind == "assistant_text":
        content = event.parsed_payload.get("text", "")
        if not isinstance(content, str) or not content:
            return None
        return SchemaFollowingMessage(
            role="assistant",
            content=content,
            metadata=dict(event.metadata),
        )

    if event.event_kind == "tool_result":
        content = event.parsed_payload.get("content", "")
        if not isinstance(content, str):
            return None
        metadata: dict[str, Any] = dict(event.metadata)
        for key in ("tool_name", "tool_call_id", "canonical_name"):
            value = event.parsed_payload.get(key)
            if isinstance(value, str):
                metadata[key] = value
        return SchemaFollowingMessage(
            role="tool",
            content=content,
            metadata=metadata,
        )

    return None
