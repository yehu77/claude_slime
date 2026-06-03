"""No-op normalizer for raw-artifact smoke paths."""

from __future__ import annotations

from pycodeagent.traces.canonical_trace import (
    CanonicalTrace,
    NormalizationReport,
    NormalizationResult,
)
from pycodeagent.traces.normalize import TraceNormalizer


class NoOpTraceNormalizer(TraceNormalizer):
    """Return an empty canonical trace while preserving run-level metadata."""

    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id

    def agent_id(self) -> str:
        return self._agent_id

    def normalize(self, raw_trace, *, tool_catalog=None) -> NormalizationResult:
        trace = CanonicalTrace(
            trace_id=raw_trace.trace_id,
            task_id=raw_trace.task_id,
            agent_name=raw_trace.agent_name,
            agent_version=raw_trace.agent_version,
            actions=[],
            final_diff=raw_trace.final_diff,
            verifier_result=raw_trace.verifier_result,
            status=raw_trace.status,
            metadata={"source": "noop"},
        )
        report = NormalizationReport(
            trace_id=raw_trace.trace_id,
            catalog_id=tool_catalog.catalog_id if tool_catalog is not None else None,
            warnings=["normalization not implemented"],
        )
        return NormalizationResult(canonical_trace=trace, report=report)
