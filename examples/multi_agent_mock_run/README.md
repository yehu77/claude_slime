# Multi-Agent Mock Run Example

This directory is a sanitized phase-one mock scaffold bundle.

It mirrors the golden fixture in:

`tests/fixtures/multi_agent_mock_bundle/`

The snapshot is produced from:

- task prompt: `Inspect the repo and run tests.`
- mock agent id: `mock_agent`
- canonical target profile: `base`

The checked-in files use `<workspace_dir>` as a stable placeholder instead of a
machine-local absolute path.

Included artifacts:

- `raw_trace_summary.json`
- `raw_trace.jsonl`
- `canonical_trace.json`
- `normalization_report.json`
- `schema_following_sample.json`
