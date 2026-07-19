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

## Artifact Layers

The phase-one golden contains three explicit layers. A normal adapter run may
persist only the raw and normalized artifacts; the checked-in golden adds one
representative derived sample and its integrity manifest.

| Layer | Artifact | Contract identifier |
| --- | --- | --- |
| Raw | `raw_trace.jsonl` | `RawEvent` rows; the companion summary owns trace schema version 1 |
| Raw | `raw_trace_summary.json` | `RawTraceSummary`, `schema_version: 1` |
| Raw | `tool_catalog.json` | `AgentToolCatalog`, `schema_version: 1` |
| Normalized | `canonical_trace.json` | `CanonicalTrace`, `schema_version: 1` |
| Normalized | `normalization_report.json` | `NormalizationReport`, `schema_version: 1` |
| Derived | `schema_following_sample.json` | `SchemaFollowingSample` with `sample_type: schema_following`; no top-level `schema_version` in the current sample model |
| Golden management | `golden_manifest.json` | phase-one golden manifest, `schema_version: 1` |
| Golden management | `README.md` | human-readable ownership and update instructions; covered by manifest checksum |

`raw_trace.jsonl` and `schema_following_sample.json` do not independently carry
a top-level `schema_version`. Raw rows are interpreted with their versioned
summary, while the sample is validated against the current
`SchemaFollowingSample` model. Adding a sample version is a future contract
change, not an assumption phase one silently makes.

## Required Artifact Rules

Important rules:

1. `raw_trace.jsonl` contains one `RawEvent` per line.
2. `raw_trace_summary.json` contains trace-level header data only.
3. `NormalizationResult` must always include both `canonical_trace` and
   `report`.
4. `command_exec` events must carry `command_role`.
5. Only `command_role = agent_command` may become execution evidence for its
   parent canonical action; harness verifier commands are never agent actions.
6. If `RawAgentRunResult.tool_catalog_path` exists, it takes precedence over
   `ToolCatalogProvider`.
7. The versioned phase-one contracts above must remain at `schema_version: 1`
   until an explicit migration is introduced; do not infer a missing version
   for the two unversioned payload shapes.

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

The phase-one contract is pinned by one checked-in, human-readable bundle:

- [`examples/multi_agent_mock_run/`](../examples/multi_agent_mock_run/README.md)

It is regenerated from a fixed `MockAdapter` scenario using the strict native
Claude `mock_base` ToolView. Tests consume that exact directory; there is no
second fixture copy under `tests/fixtures/`.

Update or verify the checked-in bundle from the repository root with:

```bash
python -B -m pycodeagent.testing.multi_agent_mock_golden --write
python -B -m pycodeagent.testing.multi_agent_mock_golden --check
```

To prove generation does not depend on existing golden contents, build and
verify a bundle in a new temporary directory:

```bash
tmp_dir="$(mktemp -d)"
python -B -m pycodeagent.testing.multi_agent_mock_golden \
  --write --output-dir "$tmp_dir/bundle"
python -B -m pycodeagent.testing.multi_agent_mock_golden \
  --check --output-dir "$tmp_dir/bundle"
```

`--write` constructs all eight files. `--check` validates the exact file set,
manifest byte sizes and SHA-256 digests, cross-artifact identities, native
Claude profile, canonical capabilities, and byte-for-byte deterministic
regeneration.

The checked-in snapshot intentionally uses a sanitized placeholder:

```text
<workspace_dir>
```

This keeps the contract deterministic across machines while preserving the
artifact shape.

## External Sidecar Protocol

For real external CLI adapters, the sidecar handoff is defined separately in
the [external-agent sidecar protocol](./external_agent_sidecar_protocol.md).

That protocol standardizes how a wrapper can hand raw artifacts to the
scaffold without forcing immediate semantic normalization.

Real external-agent ingestion is not a phase-one acceptance dependency. The
synthetic `MockAdapter` run exists to freeze raw-trace, native-catalog,
normalization, rendering, and downstream contract behavior before that later
integration step.
