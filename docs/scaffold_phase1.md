# Scaffold Phase 1

This document freezes the phase-one scaffold contracts that exist before any
real external coding agent integration.

Phase one is intentionally narrow:

- use `MockAdapter` and synthetic raw traces
- keep `RawAgentTrace` as a first-class artifact from day one
- normalize into canonical capabilities
- render canonical actions into schema-following samples
- prove the downstream contract / training-prep path without depending on
  external agent observability

## Frozen Contracts

The following interfaces and artifact semantics are now pinned:

- `AgentAdapter.run_task(task, context: AgentRunContext) -> RawAgentRunResult`
- `TraceNormalizer.normalize(...) -> NormalizationResult`
- `RawEvent` as the one-event-per-line envelope for `raw_trace.jsonl`
- `raw_trace_summary.json` as the trace-level header artifact
- `CanonicalTrace` plus `NormalizationReport` as the normalization output pair
- renderer no-future-leakage behavior for schema-following samples

## Required Artifact Rules

Phase-one raw trace artifacts are always written as:

```text
raw_trace.jsonl
raw_trace_summary.json
canonical_trace.json
normalization_report.json
```

Important rules:

1. `raw_trace.jsonl` contains one `RawEvent` per line.
2. `raw_trace_summary.json` contains trace-level header data only.
3. `NormalizationResult` must always include both `canonical_trace` and
   `report`.
4. `command_exec` events must carry `command_role`.
5. Only `command_role = agent_command` may normalize into canonical
   `RUN_COMMAND`.
6. If `RawAgentRunResult.tool_catalog_path` exists, it takes precedence over
   `ToolCatalogProvider`.
7. All new scaffold artifacts must include `schema_version`.

## No Future Leakage

When generating the sample for canonical action `k`, renderer context may only
see raw events strictly before that action's tool call boundary.

It must not include:

- the current action's `tool_result`
- any later action
- `final.diff`
- verifier outcome
- run-end metadata that leaks task outcome

## Golden Snapshot

The phase-one contract is pinned by:

- fixture bundle:
  `tests/fixtures/multi_agent_mock_bundle/`
- human-readable example bundle:
  `examples/multi_agent_mock_run/`

The checked-in snapshot intentionally uses a sanitized placeholder:

```text
<workspace_dir>
```

This keeps the contract deterministic across machines while preserving the
artifact shape.

## External Sidecar Protocol

For real external CLI adapters, the sidecar handoff is defined separately in:

- `docs/external_agent_sidecar_protocol.md`

That protocol standardizes how a wrapper can hand raw artifacts to the
scaffold without forcing immediate semantic normalization.
