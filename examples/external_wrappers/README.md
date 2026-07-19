# External Wrapper Examples

This directory contains repo-owned wrapper examples that speak the external
agent sidecar protocol.

These wrappers are not vendor binaries. They are smoke-test harnesses for
`run_external_agent_smoke.py` and the raw-artifact contracts.

Current examples:

- `claude_code_sidecar_wrapper.py`
  - writes `raw_trace.jsonl` and `raw_trace_summary.json`
  - leaves harness-derived outcome fields out of the sidecar summary
  - does not write `tool_catalog.json`
  - relies on `ClaudeCodeCatalogProvider` fallback
- `kilo_code_sidecar_wrapper.py`
  - writes `raw_trace.jsonl` and `raw_trace_summary.json`
  - leaves harness-derived outcome fields out of the sidecar summary
  - does not write `tool_catalog.json`
  - uses no catalog provider fallback by default

After the wrapper exits, the adapter rebuilds summary `status`, `final_diff`,
`verifier_result`, and reward metadata from the subprocess, workspace diff,
and verifier artifacts. A wrapper that explicitly asserts a conflicting value
causes a hard truth-conflict failure.

## Fixture And Golden Test

The Claude smoke wrapper is pinned by a checked-in regression bundle:

- fixture:
  `tests/fixtures/external_cli_claude_wrapper_bundle/`
- golden test:
  `tests/test_external_cli_wrapper_golden.py`

The golden test reruns `run_external_agent_smoke.py` against
`claude_code_sidecar_wrapper.py`, then compares these artifact classes against
the fixture:

- `raw_trace_summary.json`
- `raw_trace.jsonl`
- `tool_catalog.json`
- `final.diff`
- `verifier.json`
- `adapter_metadata.json`

The comparison normalizes machine-local noise such as absolute paths, elapsed
test duration text, and incidental pytest cache warnings. It does not perform
semantic trace normalization. It additionally asserts that summary diff and
verifier fields exactly match their standalone artifacts and that execution
status remains distinct from final task status.

The Kilo wrapper is pinned by a second regression bundle:

- fixture:
  `tests/fixtures/external_cli_kilo_wrapper_bundle/`
- golden test:
  `tests/test_external_cli_kilo_wrapper_golden.py`

Unlike the Claude wrapper bundle, the Kilo wrapper smoke path does not expect
`tool_catalog.json`, because `kilo_code` currently has no static
`ToolCatalogProvider`.
