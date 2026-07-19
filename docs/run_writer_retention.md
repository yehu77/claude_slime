# New-Run Retention Enforcement

RC-055 applies the [RC-053 retention policy](./runs_retention_policy.md) while
new runtime and multi-agent run bundles are being written. It governs new
artifacts only; the RC-054 archive and its historical index remain unchanged.

## Creation Contract

`RuntimeTraceWriter`, `run_coding_task`, and `AgentHarness.run_task` accept an
RC-053 `retention_class` and owner. Their deterministic default is
`unclassified_hold`, which has no expiry and cannot be deleted. An unknown
class fails before runtime artifacts are created.

Each run directory contains:

- `run_retention_manifest.json`, the current lifecycle state;
- `retained-run.index.jsonl`, a policy-validated header and exact run entry;
- `run_retention_events.jsonl`, an append-only creation/resume/finalization
  journal; and
- for local runtime runs, a matching `retention` object in
  `runtime_trace_manifest.json`.

Raw runtime traces are labelled `raw_trace_content` and
`raw_provider_content`; multi-agent bundles additionally carry
`workspace_snapshot_content`. These labels make the run `restricted` from
creation. They do not shorten retention or authorize remote storage.

## Checksum And Recovery

The source checksum uses `sha256-tree-manifest-v1`: sorted relative paths and
file bytes are hashed together. The retention manifest, retained index,
lifecycle journal, and runtime trace manifest are excluded because they embed
or journal the checksum itself. The protected set includes raw events,
payloads, trajectories, verifier output, diffs, logs, and workspaces.

The retained index is written atomically before the mutable lifecycle
manifest. A resumed writer must match the original run ID, task ID, policy,
purpose class, owner, and risk labels. It preserves the original retention and
quarantine timestamps, records a resume event, recomputes the checksum, and
continues event and payload ordinals. A finalized run cannot be resumed.

`run_coding_task` seals retention only after the full trajectory, verifier,
profile, and final patch have been persisted. If a process exits earlier, the
run remains indexed in `active` state and fails closed to retention.

## Verification And Cleanup

Verification checks the policy, RC-053 index structure, manifest/index
agreement, and the final directory-tree checksum:

```bash
python -B -m pycodeagent.dev.runs_lifecycle verify <run-dir>
```

Cleanup planning is always dry-run:

```bash
python -B -m pycodeagent.dev.runs_lifecycle cleanup <run-dir> [...]
```

It reports missing retention, quarantine, archive checksum, restore, scrub,
credential-review, and exact-batch-authorization gates. It never moves,
scrubs, archives, or deletes files. `--execute` is rejected. A future
destructive tool must separately validate an exact repository-owner RC-053
authorization and all bound preconditions; no wildcard, implicit directory,
or reused authorization is accepted.
