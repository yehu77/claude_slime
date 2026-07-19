"""Trace contracts for the multi-agent scaffold."""

from pycodeagent.traces.canonical_trace import (
    CanonicalAction,
    CanonicalTrace,
    NormalizationReport,
    NormalizationResult,
    read_canonical_trace,
    read_normalization_report,
    write_canonical_trace,
    write_normalization_report,
)
from pycodeagent.traces.normalize import TraceNormalizer
from pycodeagent.traces.native_profile_transform import (
    build_native_transformed_profile,
    build_native_transformed_profiles,
    generate_description_candidates,
    generate_name_candidates,
)
from pycodeagent.traces.noop_normalizer import NoOpTraceNormalizer
from pycodeagent.traces.raw_trace import (
    ArtifactRef,
    RawAgentRunResult,
    RawAgentTrace,
    RawEvent,
    RawTraceSummary,
    read_raw_events,
    read_raw_trace,
    read_raw_trace_summary,
    write_raw_events,
    write_raw_trace,
    write_raw_trace_summary,
)
from pycodeagent.traces.render import AugmentationRenderer, SchemaFollowingTraceRenderer
from pycodeagent.traces.tool_catalog import (
    AgentToolCatalog,
    CatalogToolEntry,
    read_tool_catalog,
    write_tool_catalog,
)
from pycodeagent.traces.tool_catalog_snapshot import catalog_to_base_tool_profile

__all__ = [
    "AgentToolCatalog",
    "ArtifactRef",
    "AugmentationRenderer",
    "CanonicalAction",
    "CanonicalTrace",
    "CatalogToolEntry",
    "NormalizationReport",
    "NormalizationResult",
    "NoOpTraceNormalizer",
    "RawAgentRunResult",
    "RawAgentTrace",
    "RawEvent",
    "RawTraceSummary",
    "SchemaFollowingTraceRenderer",
    "TraceNormalizer",
    "read_canonical_trace",
    "read_normalization_report",
    "read_raw_events",
    "read_raw_trace",
    "read_raw_trace_summary",
    "read_tool_catalog",
    "write_canonical_trace",
    "write_normalization_report",
    "write_raw_events",
    "write_raw_trace",
    "write_raw_trace_summary",
    "write_tool_catalog",
    "build_native_transformed_profile",
    "build_native_transformed_profiles",
    "catalog_to_base_tool_profile",
    "generate_description_candidates",
    "generate_name_candidates",
]
