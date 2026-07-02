"""Trajectory schema for recording multi-turn tool-use runs.

Every run produces a complete trajectory that can be:
- Inspected for debugging
- Serialized to slime samples for RL training
- Aggregated for batch metrics
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from pycodeagent.tools.contracts import ToolPayloadKind


# --- Internal tool call format ---


class ToolCall(BaseModel):
    """A single tool invocation, using the internal format independent of any
    specific LLM API."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    input_text: str | None = None
    canonical_name: str | None = None

    @property
    def payload_kind(self) -> ToolPayloadKind:
        if self.input_text is not None:
            return ToolPayloadKind.INPUT_TEXT
        return ToolPayloadKind.ARGUMENTS_OBJECT

    @model_validator(mode="after")
    def _validate_payload_shape(self) -> "ToolCall":
        if self.input_text is not None and self.arguments:
            raise ValueError(
                "ToolCall cannot contain both input_text and object arguments"
            )
        return self

    def model_dump(self, *args, **kwargs) -> dict[str, Any]:  # type: ignore[override]
        data = super().model_dump(*args, **kwargs)
        if data.get("input_text") is None:
            data.pop("input_text", None)
        if self.input_text is not None and data.get("arguments") == {}:
            data.pop("arguments", None)
            data["payload_kind"] = self.payload_kind.value
        return data


class ToolResult(BaseModel):
    """Structured result returned by a tool handler."""

    ok: bool
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False


class ToolObservation(BaseModel):
    """A paired tool call and its result, forming one complete tool-use step."""

    call: ToolCall
    result: ToolResult
    tool_name: str
    canonical_name: str | None = None
    tool_version: str | None = None


# --- Messages ---


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """A single message in the conversation history."""

    role: Role
    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    canonical_name: str | None = None
    tool_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# --- Verification ---


class VerifyResult(BaseModel):
    """Outcome of running the verifier on a workspace."""

    passed: bool
    score: float
    stdout: str = ""
    stderr: str = ""


# --- Trajectory ---


class RunStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"


class Trajectory(BaseModel):
    """Complete record of a single agent run on a coding task.

    Contains the full message history, structured tool call records,
    the final patch, and verification results.
    """

    task_id: str
    repo: str
    tool_profile_id: str
    tool_versions: dict[str, dict[str, str]] = Field(default_factory=dict)
    messages: list[Message] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    observations: list[ToolObservation] = Field(default_factory=list)
    final_diff: str = ""
    verifier: VerifyResult | None = None
    reward: float = 0.0
    status: RunStatus = RunStatus.COMPLETED
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_system(self, content: str) -> None:
        self.messages.append(Message(role=Role.SYSTEM, content=content))

    def add_user(
        self,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.messages.append(
            Message(
                role=Role.USER,
                content=content,
                metadata=metadata or {},
            )
        )

    def add_assistant(
        self, content: str, tool_calls: list[ToolCall] | None = None
    ) -> None:
        self.messages.append(
            Message(
                role=Role.ASSISTANT,
                content=content,
                tool_calls=tool_calls or [],
            )
        )
        if tool_calls:
            self.tool_calls.extend(tool_calls)

    def register_tool_versions(self, tool_versions: dict[str, dict[str, str]]) -> None:
        self.tool_versions.update(tool_versions)

    def add_tool_observation(
        self,
        call: ToolCall,
        result: ToolResult,
        *,
        tool_version: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        obs = ToolObservation(
            call=call,
            result=result,
            tool_name=call.name,
            canonical_name=call.canonical_name,
            tool_version=tool_version,
        )
        self.observations.append(obs)
        self.messages.append(
            Message(
                role=Role.TOOL,
                content=result.content,
                tool_call_id=call.id,
                tool_name=call.name,
                canonical_name=call.canonical_name,
                tool_version=tool_version,
                metadata=metadata or {},
            )
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the trajectory JSON format specified in CLAUDE.md."""
        return {
            "task_id": self.task_id,
            "repo": self.repo,
            "tool_profile_id": self.tool_profile_id,
            "tool_versions": self.tool_versions,
            "messages": [m.model_dump() for m in self.messages],
            "tool_calls": [tc.model_dump() for tc in self.tool_calls],
            "observations": [o.model_dump() for o in self.observations],
            "final_diff": self.final_diff,
            "verifier": self.verifier.model_dump() if self.verifier else None,
            "reward": self.reward,
            "status": self.status.value,
            "metadata": self.metadata,
        }
