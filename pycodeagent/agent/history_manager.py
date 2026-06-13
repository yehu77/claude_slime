"""Runtime-owned request history management for local agent runs.

This module separates the full append-only trajectory history from the
request-visible history used to build each model call. It is intentionally
lighter than codex-rs' persisted message-history subsystem, but it makes the
same architectural distinction: trajectory remains the audit source of truth,
while the runtime owns a request-time history view that can evolve through
compaction and replacement-history artifacts.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, PrivateAttr

from pycodeagent.agent.compaction import ContextSelectionPlan, plan_request_context
from pycodeagent.agent.retained_history import RetainedHistoryWriter
from pycodeagent.agent.turn_state import (
    CarriedForwardState,
    CompactionArtifact,
    ContextPolicyMode,
    ContextSelection,
    estimate_messages_tokens,
)
from pycodeagent.trajectory.schema import Message


class RuntimeHistoryItem(BaseModel):
    """One item in the runtime-owned request history."""

    item_id: str
    item_kind: str
    message: Message
    source_trajectory_index: int | None = None
    replacement_record_id: str | None = None
    retained_entry_id: str | None = None


class ReferenceContextState(BaseModel):
    """Stable reference context that should remain visible across turns."""

    pinned_item_ids: list[str] = Field(default_factory=list)
    pinned_source_indices: list[int] = Field(default_factory=list)


class ReplacementHistoryRecord(BaseModel):
    """Audit record for replacing source history with a compacted carryover."""

    record_id: str
    turn_index: int
    reason: str
    source_item_ids: list[str] = Field(default_factory=list)
    source_retained_entry_ids: list[str] = Field(default_factory=list)
    source_trajectory_indices: list[int] = Field(default_factory=list)
    replacement_item_id: str
    replacement_retained_entry_id: str | None = None
    compaction_artifact_entry_id: str | None = None
    carried_forward_state_entry_id: str | None = None
    summary_slot_id: str | None = None
    carried_forward_state: CarriedForwardState | None = None
    rendered_message: Message


class RuntimeHistorySnapshot(BaseModel):
    """One request-time snapshot materialized from runtime history."""

    selected_messages: list[Message]
    context_selection: ContextSelection
    context_selection_plan: ContextSelectionPlan
    compaction_artifact: CompactionArtifact | None = None
    synthetic_summary_message: Message | None = None
    replacement_history_record: ReplacementHistoryRecord | None = None
    request_history_item_ids: list[str] = Field(default_factory=list)
    request_history_item_kinds: list[str] = Field(default_factory=list)
    request_history_source_indices: list[int] = Field(default_factory=list)
    context_selection_retained_entry_id: str | None = None
    selected_retained_entry_ids: list[str] = Field(default_factory=list)
    omitted_retained_entry_ids: list[str] = Field(default_factory=list)
    summary_retained_entry_id: str | None = None
    carried_forward_state_entry_id: str | None = None
    retained_history_last_entry_id: str | None = None
    retained_entry_count_before_snapshot: int = 0
    retained_entry_count_after_snapshot: int = 0
    request_history_item_count_before_snapshot: int = 0
    request_history_item_count_after_snapshot: int = 0
    replacement_history_active: bool = False
    replacement_history_record_id: str | None = None


class RuntimeHistoryManager(BaseModel):
    """Owns request-visible history separately from full trajectory history."""

    source_items: list[RuntimeHistoryItem] = Field(default_factory=list)
    request_items: list[RuntimeHistoryItem] = Field(default_factory=list)
    replacement_history: list[ReplacementHistoryRecord] = Field(default_factory=list)
    reference_context: ReferenceContextState = Field(default_factory=ReferenceContextState)
    _retained_history_writer: RetainedHistoryWriter | None = PrivateAttr(default=None)
    _retained_entry_ids: list[str] = PrivateAttr(default_factory=list)

    @classmethod
    def from_trajectory_messages(
        cls,
        messages: list[Message],
        *,
        retained_history_writer: RetainedHistoryWriter | None = None,
    ) -> RuntimeHistoryManager:
        manager = cls()
        manager._retained_history_writer = retained_history_writer
        manager.sync_source_messages(messages, turn_index=0)
        manager.reference_context = ReferenceContextState(
            pinned_item_ids=[
                item.item_id
                for item in manager.request_items
                if item.message.role.value in {"system", "user"}
            ],
            pinned_source_indices=[
                item.source_trajectory_index
                for item in manager.request_items
                if item.source_trajectory_index is not None
                and item.message.role.value in {"system", "user"}
            ],
        )
        return manager

    def sync_source_messages(
        self,
        trajectory_messages: list[Message],
        *,
        turn_index: int | None = None,
    ) -> None:
        """Append any new trajectory messages into source and request history."""

        while len(self.source_items) < len(trajectory_messages):
            source_index = len(self.source_items)
            item = RuntimeHistoryItem(
                item_id=f"history_item_{source_index:06d}",
                item_kind="source",
                message=trajectory_messages[source_index],
                source_trajectory_index=source_index,
            )
            retained_entry = self._append_source_retained_entry(
                item=item,
                turn_index=turn_index or 0,
            )
            item.retained_entry_id = retained_entry
            self.source_items.append(item)
            self.request_items.append(item)

    def build_context_plan(
        self,
        *,
        policy_mode: ContextPolicyMode | str,
        max_messages: int | None,
        session_state,
        turn_index: int,
        context_max_tokens: int | None = None,
        tool_token_reserve: int = 0,
        response_token_reserve: int = 0,
    ) -> ContextSelectionPlan:
        """Plan request-time context selection without mutating request history."""

        request_messages = [item.message for item in self.request_items]
        return plan_request_context(
            request_messages,
            policy_mode=policy_mode,
            max_messages=max_messages,
            session_state=session_state,
            turn_index=turn_index,
            context_max_tokens=context_max_tokens,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
        )

    def snapshot_for_request(
        self,
        *,
        policy_mode: ContextPolicyMode | str,
        max_messages: int | None,
        session_state,
        turn_index: int,
        context_max_tokens: int | None = None,
        tool_token_reserve: int = 0,
        response_token_reserve: int = 0,
    ) -> RuntimeHistorySnapshot:
        """Build one request snapshot from the current runtime history view."""

        context_plan = self.build_context_plan(
            policy_mode=policy_mode,
            max_messages=max_messages,
            session_state=session_state,
            turn_index=turn_index,
            context_max_tokens=context_max_tokens,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
        )
        return self.snapshot_from_plan(
            context_plan,
            max_messages=max_messages,
            context_max_tokens=context_max_tokens,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
            turn_index=turn_index,
        )

    def snapshot_from_plan(
        self,
        context_plan: ContextSelectionPlan,
        *,
        max_messages: int | None,
        context_max_tokens: int | None,
        tool_token_reserve: int,
        response_token_reserve: int,
        turn_index: int,
    ) -> RuntimeHistorySnapshot:
        """Materialize one request snapshot from a precomputed context plan."""

        request_items_before_snapshot = list(self.request_items)
        retained_entry_count_before_snapshot = self.retained_history_entry_count()
        request_item_indices = list(context_plan.selected_request_item_indices)
        selected_items = [
            request_items_before_snapshot[index]
            for index in request_item_indices
            if 0 <= index < len(request_items_before_snapshot)
        ]
        replacement_record: ReplacementHistoryRecord | None = None
        context_selection_retained_entry_id: str | None = None

        if (
            context_plan.compaction_artifact is not None
            and context_plan.synthetic_summary_message is not None
        ):
            selected_items, replacement_record = self._apply_compaction_replacement(
                context_plan=context_plan,
                turn_index=turn_index,
            )

        if self._retained_history_writer is not None:
            selection_entry = self._retained_history_writer.append_history_control(
                turn_index=turn_index,
                control_kind="context_selection_plan",
                value=context_plan.model_dump(mode="json"),
            )
            context_selection_retained_entry_id = selection_entry.entry_id
            self._retained_entry_ids.append(selection_entry.entry_id)

        context_selection = self._build_snapshot_context_selection(
            context_plan=context_plan,
            selected_items=selected_items,
            max_messages=max_messages,
            context_max_tokens=context_max_tokens,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
        )
        selected_messages = [item.message for item in selected_items]
        selected_source_index_set = {
            item.source_trajectory_index
            for item in selected_items
            if item.source_trajectory_index is not None
        }
        return RuntimeHistorySnapshot(
            selected_messages=selected_messages,
            context_selection=context_selection,
            context_selection_plan=context_plan,
            compaction_artifact=context_plan.compaction_artifact,
            synthetic_summary_message=context_plan.synthetic_summary_message,
            replacement_history_record=replacement_record,
            request_history_item_ids=[item.item_id for item in selected_items],
            request_history_item_kinds=[item.item_kind for item in selected_items],
            request_history_source_indices=[
                item.source_trajectory_index
                for item in selected_items
                if item.source_trajectory_index is not None
            ],
            context_selection_retained_entry_id=context_selection_retained_entry_id,
            selected_retained_entry_ids=[
                item.retained_entry_id
                for item in selected_items
                if item.retained_entry_id is not None
            ],
            omitted_retained_entry_ids=[
                source_item.retained_entry_id
                for source_item in self.source_items
                if (
                    source_item.source_trajectory_index not in selected_source_index_set
                    and source_item.retained_entry_id is not None
                )
            ],
            summary_retained_entry_id=(
                replacement_record.replacement_retained_entry_id
                if replacement_record is not None
                else None
            ),
            carried_forward_state_entry_id=(
                replacement_record.carried_forward_state_entry_id
                if replacement_record is not None
                else None
            ),
            retained_history_last_entry_id=self.retained_history_last_entry_id(),
            retained_entry_count_before_snapshot=retained_entry_count_before_snapshot,
            retained_entry_count_after_snapshot=self.retained_history_entry_count(),
            request_history_item_count_before_snapshot=len(request_items_before_snapshot),
            request_history_item_count_after_snapshot=len(selected_items),
            replacement_history_active=any(
                item.item_kind == "replacement" for item in selected_items
            ),
            replacement_history_record_id=(
                replacement_record.record_id if replacement_record is not None else None
            ),
        )

    def _apply_compaction_replacement(
        self,
        *,
        context_plan: ContextSelectionPlan,
        turn_index: int,
    ) -> tuple[list[RuntimeHistoryItem], ReplacementHistoryRecord]:
        compaction_artifact = context_plan.compaction_artifact
        synthetic_summary_message = context_plan.synthetic_summary_message
        assert compaction_artifact is not None
        assert synthetic_summary_message is not None

        compacted_indices = list(compaction_artifact.compacted_message_indices)
        compacted_items = [
            self.request_items[index]
            for index in compacted_indices
            if 0 <= index < len(self.request_items)
        ]
        record_id = f"replacement_history_{len(self.replacement_history) + 1:06d}"
        replacement_item = RuntimeHistoryItem(
            item_id=f"replacement_item_{len(self.replacement_history) + 1:06d}",
            item_kind="replacement",
            message=synthetic_summary_message,
            source_trajectory_index=None,
            replacement_record_id=record_id,
        )
        replacement_retained_entry_id: str | None = None
        if self._retained_history_writer is not None:
            replacement_entry = self._retained_history_writer.append_replacement_summary(
                turn_index=turn_index,
                request_item_id=replacement_item.item_id,
                message=synthetic_summary_message,
                replacement_record_id=record_id,
                source_item_ids=[item.item_id for item in compacted_items],
                source_retained_entry_ids=[
                    item.retained_entry_id
                    for item in compacted_items
                    if item.retained_entry_id is not None
                ],
                source_trajectory_indices=[
                    item.source_trajectory_index
                    for item in compacted_items
                    if item.source_trajectory_index is not None
                ],
                summary_slot_id=(
                    compaction_artifact.summary_slot.slot_id
                    if compaction_artifact.summary_slot is not None
                    else None
                ),
            )
            replacement_retained_entry_id = replacement_entry.entry_id
            replacement_item.retained_entry_id = replacement_entry.entry_id
            self._retained_entry_ids.append(replacement_entry.entry_id)
        carried_forward_state_entry_id: str | None = None
        if (
            self._retained_history_writer is not None
            and compaction_artifact.carried_forward_state is not None
        ):
            carried_forward_entry = self._retained_history_writer.append_carried_forward_state(
                turn_index=turn_index,
                replacement_record_id=record_id,
                value=compaction_artifact.carried_forward_state.model_dump(mode="json"),
            )
            carried_forward_state_entry_id = carried_forward_entry.entry_id
            self._retained_entry_ids.append(carried_forward_entry.entry_id)
        compaction_artifact_entry_id: str | None = None
        if self._retained_history_writer is not None:
            compaction_entry = self._retained_history_writer.append_history_control(
                turn_index=turn_index,
                control_kind="compaction_artifact",
                value=compaction_artifact.model_dump(mode="json"),
            )
            compaction_artifact_entry_id = compaction_entry.entry_id
            self._retained_entry_ids.append(compaction_entry.entry_id)
        replacement_record = ReplacementHistoryRecord(
            record_id=record_id,
            turn_index=turn_index,
            reason=compaction_artifact.reason,
            source_item_ids=[item.item_id for item in compacted_items],
            source_retained_entry_ids=[
                item.retained_entry_id
                for item in compacted_items
                if item.retained_entry_id is not None
            ],
            source_trajectory_indices=[
                item.source_trajectory_index
                for item in compacted_items
                if item.source_trajectory_index is not None
            ],
            replacement_item_id=replacement_item.item_id,
            replacement_retained_entry_id=replacement_retained_entry_id,
            compaction_artifact_entry_id=compaction_artifact_entry_id,
            carried_forward_state_entry_id=carried_forward_state_entry_id,
            summary_slot_id=(
                compaction_artifact.summary_slot.slot_id
                if compaction_artifact.summary_slot is not None
                else None
            ),
            carried_forward_state=compaction_artifact.carried_forward_state,
            rendered_message=synthetic_summary_message,
        )

        compacted_index_set = set(compacted_indices)
        new_request_items: list[RuntimeHistoryItem] = []
        inserted = False
        for index, item in enumerate(self.request_items):
            if index in compacted_index_set:
                if not inserted:
                    new_request_items.append(replacement_item)
                    inserted = True
                continue
            new_request_items.append(item)
        self.request_items = new_request_items
        self.replacement_history.append(replacement_record)
        return list(new_request_items), replacement_record

    def retained_history_entry_count(self) -> int:
        return len(self._retained_entry_ids)

    def retained_history_last_entry_id(self) -> str | None:
        if not self._retained_entry_ids:
            return None
        return self._retained_entry_ids[-1]

    def retained_history_summary(self) -> dict[str, object]:
        manifest = (
            self._retained_history_writer.manifest
            if self._retained_history_writer is not None
            else None
        )
        return {
            "retained_entry_count": self.retained_history_entry_count(),
            "last_entry_id": self.retained_history_last_entry_id(),
            "entry_counts_by_kind": (
                dict(manifest.entry_counts_by_kind)
                if manifest is not None
                else {}
            ),
            "replacement_history_count": len(self.replacement_history),
        }

    def _append_source_retained_entry(
        self,
        *,
        item: RuntimeHistoryItem,
        turn_index: int,
    ) -> str | None:
        if self._retained_history_writer is None or item.source_trajectory_index is None:
            return None
        entry = self._retained_history_writer.append_source_message(
            turn_index=turn_index,
            request_item_id=item.item_id,
            source_trajectory_index=item.source_trajectory_index,
            message=item.message,
        )
        self._retained_entry_ids.append(entry.entry_id)
        return entry.entry_id

    def _build_snapshot_context_selection(
        self,
        *,
        context_plan: ContextSelectionPlan,
        selected_items: list[RuntimeHistoryItem],
        max_messages: int | None,
        context_max_tokens: int | None,
        tool_token_reserve: int,
        response_token_reserve: int,
    ) -> ContextSelection:
        source_indices = [
            item.source_trajectory_index
            for item in selected_items
            if item.source_trajectory_index is not None
        ]
        source_items_by_index = {
            item.source_trajectory_index: item
            for item in self.source_items
            if item.source_trajectory_index is not None
        }
        included_role_counts: dict[str, int] = {}
        for source_index in source_indices:
            source_item = source_items_by_index.get(source_index)
            if source_item is None:
                continue
            role = source_item.message.role.value
            included_role_counts[role] = included_role_counts.get(role, 0) + 1

        selected_messages = [item.message for item in selected_items]
        omitted_source_messages = [
            source_item.message
            for source_item in self.source_items
            if source_item.source_trajectory_index not in set(source_indices)
        ]
        low_level_selection = context_plan.context_selection
        return ContextSelection(
            policy_mode=low_level_selection.policy_mode,
            max_messages=max_messages,
            context_max_tokens=context_max_tokens,
            included_message_indices=source_indices,
            omitted_message_count=max(len(self.source_items) - len(source_indices), 0),
            compacted_message_count=low_level_selection.compacted_message_count,
            first_included_index=(source_indices[0] if source_indices else None),
            last_included_index=(source_indices[-1] if source_indices else None),
            included_role_counts=included_role_counts,
            compaction_applied=low_level_selection.compaction_applied,
            compaction_reason=low_level_selection.compaction_reason,
            estimated_selected_tokens=estimate_messages_tokens(selected_messages),
            estimated_omitted_tokens=estimate_messages_tokens(omitted_source_messages),
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
            token_budget_satisfied=low_level_selection.token_budget_satisfied,
            token_overflow=low_level_selection.token_overflow,
        )
