# External Agent Sidecar Protocol

This document defines the optional sidecar protocol for external coding-agent
CLIs that want to provide higher-fidelity artifacts to the scaffold.

The scaffold always supports a black-box fallback path:

- subprocess run
- stdout / stderr capture
- final diff
- verifier output
- observed raw-trace fallback

If an external CLI or wrapper can provide better trace fidelity, it should
write sidecar artifacts to the paths announced through environment variables.

## Environment Variables

The harness injects these variables before launching the external agent:

- `PYCODEAGENT_RUN_ID`
- `PYCODEAGENT_TASK_ID`
- `PYCODEAGENT_AGENT_ID`
- `PYCODEAGENT_RUN_DIR`
- `PYCODEAGENT_WORKSPACE_DIR`
- `PYCODEAGENT_STDOUT_PATH`
- `PYCODEAGENT_STDERR_PATH`
- `PYCODEAGENT_RAW_TRACE_PATH`
- `PYCODEAGENT_RAW_TRACE_SUMMARY_PATH`
- `PYCODEAGENT_TOOL_CATALOG_PATH`

An external wrapper does not need to use all of them.

## Required Sidecar Files

If a wrapper wants the scaffold to preserve its raw trace directly, it should
write:

```text
raw_trace.jsonl
raw_trace_summary.json
```

Optional:

```text
tool_catalog.json
```

The harness uses the presence of both `raw_trace.jsonl` and
`raw_trace_summary.json` to detect sidecar mode.

## File Semantics

### `raw_trace.jsonl`

- one JSON object per line
- each line must validate as `RawEvent`

### `raw_trace_summary.json`

- trace-level header only
- must validate as `RawTraceSummary`
- should not inline the whole event list

### `tool_catalog.json`

- optional runtime-effective catalog
- must validate as `AgentToolCatalog`

## Precedence Rules

1. If sidecar raw trace files exist, the adapter preserves `raw_trace.jsonl`
   and does not synthesize fallback events.
2. The sidecar summary owns trace identity and capture metadata, but it does
   not own harness-derived outcome fields. Sidecars should omit `status`,
   `final_diff`, `verifier_result`, and the outcome fields described below.
3. The adapter rebuilds those derived summary fields after execution. An
   explicitly supplied value is an assertion: if it disagrees with its
   authoritative artifact, the run fails with `ArtifactTruthConflictError`.
   It is never silently preferred or overwritten.
4. If sidecar raw trace files do not exist, the adapter emits an
   `observed_fallback` raw trace from the same authoritative artifacts.
5. If `tool_catalog.json` exists, it becomes
   `RawAgentRunResult.tool_catalog_path`.
6. If no sidecar catalog exists, normal harness catalog fallback rules apply:
   adapter artifact path first, then `ToolCatalogProvider`, then `None`.

### Field-level truth matrix

| Field | Authoritative source | Derived/preserved behavior |
| --- | --- | --- |
| events and tool calls | `raw_trace.jsonl` | sidecar events are preserved |
| `final_diff` | harness-generated `final.diff` | copied into the summary |
| `verifier_result` | harness-generated `verifier.json` | copied into the summary |
| `execution_status` | adapter subprocess result | preserved separately in metadata and `RawAgentRunResult.status` |
| `final_status` / summary `status` | execution status, then verifier result | non-completed execution wins; otherwise failed verifier means `failed` |
| `reward` | `verifier_result.score` | stored in summary metadata |

`execution_status=completed` and `final_status=failed` are intentionally
compatible: the CLI can exit successfully while its workspace still fails the
task verifier. The summary metadata records the matrix under
`truth_precedence` so downstream consumers can audit the derivation.

## Scope Boundary

This protocol is intentionally about artifact handoff, not semantic parsing.

It does not require the external wrapper to:

- normalize tools into canonical capabilities
- infer `READ_FILE` / `EDIT_FILE` / `RUN_COMMAND`
- emit schema-following samples

It only standardizes how raw artifacts enter the scaffold.

## Smoke Wrapper Flow

The repo includes a checked-in smoke wrapper example:

- `examples/external_wrappers/claude_code_sidecar_wrapper.py`

It can be launched through the root smoke CLI:

```powershell
python run_external_agent_smoke.py `
  claude_code `
  examples/buggy_counter `
  runs/external_smoke `
  --prompt "Inspect the repo and run tests." `
  --test-command "python -m pytest -q" `
  --command-prefix python examples/external_wrappers/claude_code_sidecar_wrapper.py `
  --run-id claude_wrapper_smoke_004
```

This path is intentionally narrow:

- it does not parse vendor-native tool calls
- it does not normalize raw trace events into canonical capabilities
- it only verifies subprocess execution plus sidecar artifact handoff

## Artifact Handoff Sequence

When `run_external_agent_smoke.py` launches an external wrapper:

1. `AgentHarness` creates the run bundle directory and workspace copy.
2. `ExternalCliArtifactAdapter` injects the sidecar environment variables.
3. The wrapper runs inside `PYCODEAGENT_WORKSPACE_DIR`.
4. If the wrapper writes `raw_trace.jsonl` and `raw_trace_summary.json`, the
   adapter preserves them as the authoritative raw trace.
5. If the wrapper does not write `tool_catalog.json`, the harness may still
   backfill one through a static `ToolCatalogProvider`.
6. The adapter always captures `stdout.log`, `stderr.log`, `final.diff`, and
   `verifier.json`.
7. The harness writes the run bundle, then the golden test compares the
   resulting artifacts against the checked-in fixture.

For the Claude wrapper smoke path, the checked-in regression sample is:

- fixture bundle:
  `tests/fixtures/external_cli_claude_wrapper_bundle/`
- golden test:
  `tests/test_external_cli_wrapper_golden.py`
