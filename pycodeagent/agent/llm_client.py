"""LLM client interface for text-mode agent execution.

This module defines the abstract interface for LLM clients and provides
a fake client for deterministic testing. Real SDK adapters (OpenAI,
Anthropic) are not implemented here; they belong in concrete adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class GenerateRequest(BaseModel):
    """Input to the LLM generate call."""

    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]


class GenerateResponse(BaseModel):
    """Output from the LLM generate call (raw text)."""

    text: str


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients.

    Text-mode clients return raw text that must be parsed by the agent's
    parser. Native tool-calling clients are out of scope for NS-03.
    """

    @abstractmethod
    def generate(self, request: GenerateRequest) -> GenerateResponse:
        """Generate a text response given messages and tool specs."""
        ...


class FakeLLMClient(BaseLLMClient):
    """A fake LLM client that returns predetermined responses.

    Used for deterministic testing. Each call to generate() returns the
    next response from the queue, or repeats the last response if the
    queue is exhausted.
    """

    def __init__(self, responses: list[str]) -> None:
        """Initialize with a list of predetermined text responses.

        Args:
            responses: List of raw text outputs the client will return.
        """
        self._responses = list(responses)
        self._call_count = 0

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        """Return the next predetermined response."""
        if not self._responses:
            raise RuntimeError("FakeLLMClient has no responses configured")

        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        return GenerateResponse(text=self._responses[idx])

    @property
    def call_count(self) -> int:
        """Number of times generate() has been called."""
        return self._call_count
