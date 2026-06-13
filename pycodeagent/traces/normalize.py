"""Trace normalizer protocol surface."""

from __future__ import annotations

from typing import Protocol

from pycodeagent.traces.canonical_trace import NormalizationResult
from pycodeagent.traces.raw_trace import RawAgentTrace
from pycodeagent.traces.tool_catalog import AgentToolCatalog


class TraceNormalizer(Protocol):
    """Convert raw traces into canonical traces plus a report."""

    def agent_id(self) -> str: ...

    def normalize(
        self,
        raw_trace: RawAgentTrace,
        *,
        tool_catalog: AgentToolCatalog | None = None,
    ) -> NormalizationResult:
        ...
