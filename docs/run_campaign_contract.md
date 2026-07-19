# RunCampaign / RunMatrix Contract

Status: active, version 1, defined by RC-043 on 2026-07-18.

Owner: runtime and evaluation maintainers.

## Purpose and boundary

`RunCampaign` is the repository-owned contract for expressing and resuming a
runtime run matrix. It binds these dimensions:

```text
task × native tool family × ToolView mode × ToolView seed × provider × repeat
```

The implementation lives in `pycodeagent.eval.run_campaign`. Version 1
provides deterministic expansion, logical run identity, append-only attempts,
resume, artifact indexing, and failure summaries. It delegates one run to
`run_coding_task`, so the existing trajectory and runtime-trace contracts
remain the source of truth.

RC-044 migrated the active behavior-baseline, credibility, and
ToolView-mutation entrypoints onto this contract. Their research-specific
audits, gates, exporters, and summaries remain observer/analysis layers.
The archived legacy study route is a negative boundary and is not a
compatibility target.

Version 1 is single-process orchestration. Two writers must not execute the
same campaign output root concurrently.

## Versioned specification

`RunCampaign(schema_version=1)` contains:

- a filesystem-safe `campaign_id`;
- a `RunMatrix`;
- the retention class and owner passed to every run writer.

`RunMatrix` contains non-empty task IDs, native tool-stack families, ToolView
profile modes, non-negative profile seeds, provider descriptors, and a repeat
count. Every dimension is duplicate-free and normalized into sorted order.
Equivalent sets therefore serialize, fingerprint, and expand identically
regardless of their input order.

A provider descriptor has a stable `provider_id` and optional finite,
JSON-compatible, non-secret metadata. Credentials are runtime inputs to the
caller-owned client factory. They must not appear in the campaign spec.
Known credential keys such as `api_key`, `authorization`, `password`,
`secret`, and `token` are rejected recursively.

The full normalized specification receives a canonical SHA-256
`spec_fingerprint`. Its expanded case list receives a separate
`plan_fingerprint`. The output root is permanently bound to both fingerprints
by `campaign_spec.json`; reusing it with a different spec or plan is a hard
error.

## Deterministic expansion and run identity

Expansion uses the normalized Cartesian product in this order:

1. task ID;
2. native tool-stack family;
3. ToolView profile mode;
4. ToolView profile seed;
5. provider ID;
6. zero-based repeat index.

Each `CampaignRunCase(schema_version=1)` records all six dimensions plus its
ordinal. Its `run_id` is `run_` followed by the first 20 hexadecimal
characters of the SHA-256 digest of the complete logical identity. A detected
collision is a hard error.

The provider is a transport dimension; the family is the model-visible native
tool surface. Keeping them independent prevents provider selection from
silently changing exposed ToolView or canonical backend semantics.

## Artifact layout

The campaign root contains only deterministic, relative-path indexes:

```text
campaign_spec.json
campaign_manifest.json
campaign_artifact_index.json
campaign_failure_summary.json
runs/
  <run_id>/
    campaign_run_record.json
    attempts/
      <run_id>__attempt_0001/
        campaign_attempt.json
        trajectory.json
        tool_profile.json
        runtime_trace.jsonl
        runtime_trace_manifest.json
        ... optional verifier, patch, and retention artifacts
```

`campaign_artifact_index.json` has one entry for every planned case, including
pending cases. A terminal record keeps the full case identity, attempt path,
artifact paths, trajectory status, tool-profile ID, reward, verifier result,
and normalized failure classification. Paths are relative to the bound output
root; path escapes and missing artifacts are rejected during resume.

`campaign_manifest.json` reports planned, terminal, and pending counts,
dimension values, outcome counts, trajectory-status counts, and
`contract_ok`. Provider/executor errors make `contract_ok=false`. A complete
trajectory with a failed verifier is still valid evidence and is retained,
indexed, and listed in the failure summary.

Campaign artifacts intentionally omit wall-clock timestamps and absolute
paths. A no-op resume therefore reproduces byte-identical campaign indexes and
summaries.

## Resume and failure semantics

Resume follows these rules:

1. A valid terminal `campaign_run_record.json` is revalidated and skipped.
2. If interruption happened after complete run artifacts were written but
   before the terminal record, the completed attempt is recovered without a
   provider call.
3. An incomplete or corrupt attempt remains in place. Resume allocates the
   next numbered attempt directory and never overwrites the prior trace.
4. A normal provider/client/executor exception becomes a terminal
   `executor_error` record. The matrix continues and the error is included in
   `campaign_failure_summary.json`.
5. `KeyboardInterrupt` and `SystemExit` preserve the current attempt and stop
   the invocation. A later invocation resumes from the installed state.
6. Spec drift, corrupt terminal identity, artifact escape, missing required
   run artifacts, or trajectory/profile/trace-manifest identity drift is a hard
   contract error. It is never converted into a successful run.

These rules make runtime trace bundles append-only at the attempt level.
The campaign runner has no delete, cleanup, archive, or overwrite operation.
Retention and lifecycle enforcement remains owned by the run-writer and runs
governance contracts.

## Preserved single-run contract

The default executor calls `run_coding_task` with the selected task, family,
ToolView mode and seed, plus campaign retention metadata. A complete attempt
must retain:

- the full `Trajectory`, including task and ToolView identity;
- final status, reward, and verifier fields;
- the exact exposed `tool_profile.json`;
- append-only `runtime_trace.jsonl` and its closed manifest;
- the exposed-to-canonical boundary already recorded by trajectory and trace
  events.

The campaign layer indexes these artifacts; it does not reinterpret, flatten,
or regenerate them.

## Active campaign migration

RC-044 uses `execute_profile_run_campaigns` when an active entrypoint supplies
a paired mode-to-seed mapping. It installs one standard `RunCampaign` per
ToolView mode beneath a deterministic group root. This prevents a mapping such
as `base -> 0, tool_reorder -> 7` from accidentally becoming the four-case
mode×seed cross-product of one `RunMatrix`.

The group writes `profile_campaign_group_spec.json` before execution and
`profile_campaign_group_manifest.json` after its child campaigns. Both are
deterministic and bind the exact tasks, family, paired ToolViews, provider
provenance, repeat count, and retention fields. A changed group spec requires
a new output root. A group also refuses to share its root with legacy
direct-run directories; it never deletes or silently combines them.

The old-to-new field mapping is:

| Active entrypoint | Old orchestration fields | RunCampaign mapping | Retained analysis |
| --- | --- | --- | --- |
| behavior baseline | tasks, one profile mode, repeat, family, provider client factory | task IDs, one paired mode/seed (`seed=0`), repeat, family, non-secret provider descriptor | behavior audit, promotion gates, failure buckets |
| credibility bundle | tasks, `profile_seed_by_mode`, repeat, family, provider client factory | one child campaign per paired mode/seed; task and repeat dimensions remain in each matrix | behavior summary, observed bundle, reconciliation, credibility gates |
| ToolView mutation generation | tasks, mutation-config profiles, `profile_seed_by_mode`, repeat, family | one child campaign per paired mode/seed; research-owned executor supplies the exact sampled profile | observed export, acceptance gates, training prep |

The legacy direct artifact path
`<task>__<mode>__rep_<n>__<profile>/trajectory.json` maps to the terminal
record's relative `artifact_paths.trajectory` under:

```text
runs/profile_<mode-seed-digest>/
  runs/<run_id>/attempts/<run_id>__attempt_<n>/trajectory.json
```

Run count, status, reward, verifier data, and referenced artifact existence are
preserved. Execution order is now the contract order: sorted ToolView mode,
sorted task ID, then repeat index. Downstream batch discovery follows only
terminal `campaign_run_record.json` artifacts. It deliberately excludes
partial attempts and continues to accept older direct-run directories for
read-only historical analysis.

## Verification

The offline contract gate is:

```bash
python -B -m pytest -q --strict-markers tests/test_run_campaign.py
```

It covers normalized expansion and run IDs, secret rejection, a real
fake-client matrix across both native families, byte-stable no-op resume,
post-write interruption recovery, partial-attempt preservation, per-run error
continuation, spec/task drift rejection, paired mode/seed expansion, terminal-
artifact discovery, status/reward preservation, and group-level idempotent
resume. Static regression assertions prevent the three migrated modules from
reintroducing private task/repeat loops or destructive `rmtree` orchestration.
