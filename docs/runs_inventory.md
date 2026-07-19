# Local Runs Inventory

RC-052 establishes a read-only, content-redacted inventory for the ignored
`runs/` tree. Its purpose is to make later retention decisions evidence-based;
it does not authorize archive, upload, scrubbing, or deletion.

The tracked artifacts are:

- [summary](../references/runs-inventory.summary.json): aggregate counts and
  the deterministic state fingerprint;
- [inventory](../references/runs-inventory.jsonl): one header, 741 artifact
  groups, and 8,855 artifact metadata records;
- [record schema](../references/runs-inventory.schema.json): the versioned
  JSONL record contract.

## Snapshot

The 2026-07-18 scan covers 8,855 files in 741 file-bearing directories, with a
logical size of 59,472,914 bytes. Every discovered artifact and group has an
explicit classification. The state fingerprint is:

```text
fea8f4f533fc2a1e6bf5289a067e90703d60f8d4ccbeed5e57ca22b7f7568089
```

The largest classes are 6,035 raw-provider payloads, 754 workspace snapshots,
542 reports, 510 traces, and 437 manifests. Of the manifests, 431 parse and
resolve according to the known manifest contract, while six have missing
references. No current structured file failed JSON parsing; non-JSON files are
recorded as `not_structured`, not silently omitted.

Content hashing found 494 duplicate groups containing 3,641 files. Keeping one
copy per group would account for 6,619,151 redundant bytes, but this is only an
inventory fact: duplicates may have distinct evidentiary or provenance value,
so RC-052 makes no deletion decision.

## Redaction Boundary

The scanner reads files only to:

1. compute a content digest used internally for duplicate grouping and the
   whole-tree fingerprint;
2. parse allowlisted run metadata;
3. check known manifest references; and
4. detect potential sensitive-data patterns.

It never serializes payload text, workspace contents, secret matches, tool
arguments/results, raw content hashes, or symlink targets. Safe scalar values
for `run_id`, `task_id`, `profile_id`, `family`, `status`, and
`schema_version` may be retained; other values become a one-way redaction
record.

Risk labels are conservative indicators, not confirmation that a file contains
a usable secret. The current report labels 205 files for potential
authorization material, 936 for absolute user paths, 6,035 as raw-provider
content, 517 as raw-trace content, 754 as workspace snapshots, and 28 as logs.
The matched text is never written to the report.

Paths and allowlisted identifiers are still metadata and may themselves be
sensitive in some environments. Review the inventory before sharing it outside
the repository.

## Commands

Generate the tracked snapshot only after intentionally reviewing the local
tree:

```bash
python -B -m pycodeagent.dev.runs_inventory scan
```

Validate the tracked report without requiring a local `runs/` tree:

```bash
python -B -m pycodeagent.dev.runs_inventory validate
```

Rescan the local tree without writing and require exact equality with the
tracked report:

```bash
python -B -m pycodeagent.dev.runs_inventory verify
```

The fingerprint includes relative path, size, mtime, and file content digest,
so any of those changes cause verification to fail. The serialized report has
no generation timestamp and stable record ordering, making repeated scans
byte-deterministic when the source tree is unchanged.

## Governance Boundary

RC-053 may use this inventory to define retention classes and a retained-run
index, but it first requires owner decisions for retention periods, external
storage, and irreversible deletion. RC-054 is the separate, higher-risk goal
that may eventually scrub or archive selected runs. Neither goal may interpret
this report as implicit permission to change `runs/`.
