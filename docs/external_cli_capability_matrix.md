# External CLI Capability Matrix

This matrix tracks what the current raw-artifact-capable external adapters can
do without claiming full semantic normalization.

## Current Matrix

| Capability | `CodexCliAdapter` | `ClaudeCodeAdapter` |
| --- | --- | --- |
| Subprocess execution | Yes | Yes |
| `AgentRunContext` support | Yes | Yes |
| Sidecar env injection | Yes | Yes |
| Preserve `raw_trace.jsonl` sidecar | Yes | Yes |
| Preserve `raw_trace_summary.json` sidecar | Yes | Yes |
| Preserve `tool_catalog.json` sidecar | Yes | Yes |
| Observed fallback raw trace | Yes | Yes |
| `stdout.log` / `stderr.log` capture | Yes | Yes |
| `final.diff` capture | Yes | Yes |
| `verifier.json` capture | Yes | Yes |
| Static catalog provider available | Yes | Yes |
| Runtime-effective sidecar catalog accepted | Yes | Yes |
| Canonical trace normalization | No-op only | No-op only |
| Tool-call semantic parsing from stdout | No | No |
| Schema-following data from real traces | Not yet | Not yet |

## Claude Wrapper Smoke Fixture Fidelity

The checked-in Claude wrapper smoke fixture lives at:

- `tests/fixtures/external_cli_claude_wrapper_bundle/`

Its fidelity level should be understood precisely:

- sidecar smoke: Yes
- subprocess raw artifact capture: Yes
- runtime-observed model-visible tool trace: No
- normalization-ready native tool events: No, unless a future wrapper emits
  structured tool events rather than only assistant-text plus run-end events

This means the fixture is useful for:

- validating sidecar handoff
- validating adapter/harness/catalog fallback integration
- freezing raw artifact contract shape

It is not yet sufficient for:

- agent-specific canonical capability extraction
- semantic tool-call supervision from real vendor traces
- evaluating normalization quality

## What This Means

Current adapters prove:

- the subprocess adapter abstraction is reusable across more than one agent
- the sidecar handoff contract is agent-agnostic
- the harness can treat multiple external agents uniformly
- catalog fallback remains independent from runtime artifact capture

Current adapters do **not** yet prove:

- faithful semantic parsing of native agent logs
- canonical capability extraction from real raw traces
- robust reconstruction of tool calls from vendor-specific stdout

## Recommended Next Step

The next adapter-level milestone should be:

1. bring up a real wrapper for one agent against the documented sidecar
   protocol
2. collect one real raw bundle end to end
3. only then start a first real `TraceNormalizer`
