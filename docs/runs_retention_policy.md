# Runs Retention Policy

RC-053 defines the lifecycle contract for local run artifacts. It is a
governance and validation layer only: it does not move, scrub, archive, or
delete anything under `runs/`.

The machine-readable contract consists of:

- [retention policy](../references/runs-retention-policy.json);
- [retained-run index schema](../references/retained-run-index.schema.json);
- [synthetic index example](../examples/runs_retention/retained-run-index.example.jsonl);
- [current aggregate coverage](../references/runs-retention-coverage.json).

The policy ID is `rc053-conservative-local-manual-v1`. It consumes the
`pycodeagent-runs-inventory/v1` contract from RC-052 and defines
`pycodeagent-retained-run-index-record/v1` for RC-054.

## Purpose Classes And Retention

Purpose and sensitivity are separate dimensions. A research-evidence run may
also be restricted; sensitivity can only add controls, never shorten
retention.

| Purpose class | Minimum active retention | Quarantine | Expiry action | Deletion eligible |
| --- | ---: | ---: | --- | --- |
| `contract_golden` | permanent | — | retain | no |
| `unique_research_evidence` | permanent | — | retain | no |
| `provider_raw` | 365 days | 30 days before deletion | manual review | yes, after all gates |
| `debug` | 90 days | 30 days | quarantine | yes, after all gates |
| `failed` | 90 days | 30 days | quarantine | yes, after all gates |
| `superseded` | 0 days | 30 days | quarantine | yes, after all gates |
| `duplicate` | 0 days | 30 days | quarantine | yes, after all gates |
| `unclassified_hold` | indefinite | — | manual-review hold | no |

Expiry never means delete. It only makes an eligible item available for the
next review or quarantine step. Unknown purpose values fail closed to
`unclassified_hold`.

RC-053 applies only two evidence-free classification rules to the current
inventory:

1. terminal `failed` or `error` status becomes `failed`;
2. otherwise a provider-payload group becomes `provider_raw`;
3. everything else becomes `unclassified_hold`.

The first matching priority wins and duplicate priorities are invalid.
Campaign-level declarations of golden, unique evidence, superseded, or
duplicate status require owner evidence and belong to RC-054.

## Sensitivity And Storage

An artifact group with no RC-052 risk label is `internal`. The presence of any
risk label, including a future unknown label, makes it `restricted`.
`potential_authorization_material` additionally requires an explicit
credential review.

Raw provider payloads, traces, event logs, workspaces, and logs may only remain
on the same machine. Any archive must be placed outside the Git working tree.
Network shares, self-managed object storage, managed cloud storage, and the Git
working tree itself are forbidden raw-data destinations under policy v1.

Tracked files may contain only redacted metadata, aggregate counts, checksums,
and local reference labels. They may not contain payload text, secret matches,
tool arguments/results, workspace contents, or an external storage URL.

## Retained-Run Index

A JSONL index begins with one header that locks:

- the policy ID;
- the RC-052 inventory schema;
- the exact inventory state fingerprint; and
- whether the index is synthetic.

Each entry targets one exact `runs/...` artifact group or artifact path.
Artifact entries override their parent group; duplicate targets are invalid.
When validating a live index, every inventory artifact must resolve through
exactly one artifact override or its parent group.

Entries record purpose class, sensitivity and risk labels, owner, retention
window, disposition, local storage class, source/archive checksums,
scrub/restore status, credential-review status, and an optional deletion
authorization ID. Wildcards, parent traversal, external URLs, and absolute
targets are forbidden.

The checked-in example is explicitly synthetic and cannot contain a deletion
authorization. RC-054 owns creation of the real index for all 741 current
artifact groups.

## Scrub, Archive, Restore, And Delete

Scrubbing always creates a derivative and must preserve the source. A tracked
scrub report records only status and redacted metadata; a match value must
never enter Git. Scrub failure retains the source and reports the failure.

An archive requires either SHA-256 or `sha256-tree-manifest-v1` for source and
archive. It must be restored into a temporary directory and verified before it
can satisfy a deletion precondition. Archive or restore failure retains the
source.

`delete_authorized` is valid only when all of the following are true:

1. the class is deletion-eligible;
2. active retention and quarantine have elapsed;
3. source and archive checksums exist;
4. temporary restore is verified;
5. scrub or sensitivity review is complete;
6. credential review is complete when its risk trigger is present; and
7. a repository-owner authorization names the exact targets and current
   inventory fingerprint.

Authorizations are one-batch-only. They cannot use wildcards, silently cover
extra entries, survive inventory drift, or be attached to retained entries.
Any missing condition fails closed to retain-and-report.

## Commands

All RC-053 commands are read-only:

```bash
python -B -m pycodeagent.dev.runs_retention validate-policy
python -B -m pycodeagent.dev.runs_retention validate-index
python -B -m pycodeagent.dev.runs_retention verify-coverage
```

The current coverage evaluates all 741 groups and 33 observed combinations.
It produces 40 `failed`, 125 `provider_raw`, and 576
`unclassified_hold` decisions. Eight groups are `internal`, 733 are
`restricted`, and zero are deletion-authorized.

RC-054 used this contract to classify and archive the historical inventory.
[RC-055 new-run enforcement](./run_writer_retention.md) applies the same
purpose classes and deletion gates at runtime/campaign artifact creation.
