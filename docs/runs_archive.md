# Local Runs Archive

RC-054 applies the [RC-053 retention policy](./runs_retention_policy.md) to the
RC-052 inventory. It classifies every current artifact group, creates a
scrubbed local archive outside the Git worktree, verifies a full temporary
restore, and writes a retained-run index. It does not delete source data.

The tracked evidence is:

- [owner classification](../references/runs-archive-classification.json);
- [retained-run index](../references/retained-runs.index.jsonl);
- [archive manifest](../references/runs-archive-manifest.json);
- [scrub report](../references/runs-archive-scrub-report.json).

The physical archive is identified in tracked records only by
`local-archive:rc054-20260718`. Its absolute local path is deliberately not
stored in Git. The archive contains its own `.rc054-archive-manifest.json` with
the complete file checksum list.

## Owner Classification

The repository owner confirmed the following campaign-level decisions:

- `native_family_acceptance_final_v4`,
  `p3b_real_provider_compaction_acceptance`,
  `real_provider_behavior_baseline`, `real_provider_credibility_bundle`, and
  `toolview_mutation_data_generation` are unique research evidence;
- provider-payload groups within those evidence campaigns use the
  365-day `provider_raw` policy;
- `real_provider_smoke` is 90-day debug material;
- all earlier native-family acceptance, CLI-check, and final-v1–v3 campaigns
  are superseded and enter a new 30-day quarantine.

This produces 342 `unique_research_evidence`, 57 `provider_raw`, 21 `debug`,
and 321 `superseded` group entries. Sensitivity remains independent: eight
groups are `internal` and 733 are `restricted`.

No entry has `delete_authorized`. Quarantine is a lifecycle classification,
not permission to remove the source.

## Scrub And Archive Behavior

`pycodeagent.dev.runs_archive` is intentionally non-destructive:

1. it requires the destination to be absent and outside the Git worktree;
2. it verifies the RC-052 source fingerprint before reading;
3. it writes only into an owned staging directory;
4. it creates scrubbed derivatives without changing source bytes or mtimes;
5. it atomically installs the archive only after scrub and restore checks pass;
6. it has no delete command.

JSON and JSONL retain input key order so model-visible contract metadata is not
reinterpreted by the inventory scanner. Sensitive scalar values, bearer
tokens, email addresses, private-key blocks, and absolute user-home prefixes
are redacted. Plain text uses equivalent conservative patterns.

Compiled `.pyc`/`.pyo` caches cannot be safely text-scrubbed and are
regenerable, so the derivative contains a deterministic redacted placeholder
at the same path. Other non-UTF-8 files fail closed.

The current run scanned all 8,855 files. It produced 8,194 changed derivatives;
that number includes deterministic JSON/JSONL normalization and does not mean
every file contained sensitive data. The explicit replacement counts are
2,760 absolute user-home prefixes and 261 compiled-cache placeholders. No
matched value is stored in the tracked report.

## Checksum And Restore Evidence

Every retained index entry contains a source group digest and scrubbed archive
group digest. The full scrubbed payload contains 8,855 artifacts and
56,952,245 bytes, with SHA-256:

```text
cf939cdd5444be9d80f789e7d890c8ddcaf63479dccaa15da50bbae3d704bfd5
```

Before installation, the tool copies the complete scrubbed payload to a
temporary restore tree and rescans it. All 8,855 artifact paths, all 741
file-bearing groups, artifact classes, and all allowlisted contract metadata
matched the source inventory. The real retained index is also validated
against every source artifact through its parent group.

After installation, read-only verification recomputes every archived file
checksum, the complete payload digest, retained-index checksum, scrub
idempotency, source inventory fingerprint, and deletion count.

## Commands

Creating an archive is explicit and refuses an existing destination:

```bash
python -B -m pycodeagent.dev.runs_archive archive \
  --destination <local-path-outside-git>
```

Independent verification is read-only:

```bash
python -B -m pycodeagent.dev.runs_archive verify \
  --destination <local-path-outside-git>
```

Any later deletion requires a separate, exact authorization batch under
RC-053. The current archive and index do not provide that authorization.
