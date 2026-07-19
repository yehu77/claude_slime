# Training-Prep Behavior Contract v3

RC-040 froze the observable behavior of the four training-prep paths before
unification. RC-041 normalized their prepared-sample model and mask policy.
RC-042 now routes all four through one checksummed bundle builder.

The executable golden is
[`repository_cleanup/training_prep_characterization.json`](./repository_cleanup/training_prep_characterization.json).
Its corpus represents the same semantic tool-use case—read `main.py` through
an exposed `inspect_file` ToolView—using each path's required source envelope.
The rollout corpus also includes a failed run so reward, status, and verifier
filtering remain observable.

## Path Matrix

| Path | Source adapter | Prepared mask | Outcome metadata | Contract and packing | Disposition |
| --- | --- | --- | --- | --- | --- |
| rollout | trajectory/run bundle | assistant tool call only | reward, status, verifier, task, profile | shared builder; rollout/source manifest retained | rollout source adapter |
| schema-following | schema-following split, including transformed ToolViews and hard negatives | assistant tool call only | task, profile, split, source and mutation identity; run outcome is not in its source schema | shared builder | schema source adapter |
| runtime-observed | observed runtime run → raw schema-following dataset → prepared bundle | assistant tool call only | schema fields plus observed family/profile/provenance metadata | shared builder under `prepared/`; `raw_dataset/` retained | nested source adapter |
| native-transformed | validated auxiliary Claude API transformed split | assistant tool call only | task/profile/source/transformation identity; no run outcome fields | shared builder plus auxiliary raw validation | auxiliary source adapter |

## Shared Invariants

All four paths must preserve these properties:

1. Concatenating segments reconstructs serialized text exactly.
2. Character-mask length equals text length and its sum equals the declared
   trainable-character count.
3. Token IDs, attention mask, labels, and token train mask stay aligned.
4. Non-trainable labels use `IGNORE_INDEX`; trainable labels equal token IDs.
5. Task and ToolView profile identity survive tensorization.
6. Tokenizer and train configuration artifacts round-trip through their
   loaders.

The shared builder packs and unpacks every route, records
`packed_sequence_count`, and materializes `packed.jsonl`.

## Frozen Failure Behavior

- Every direct prep path requires an explicit tokenizer selection.
- Rollout prep excludes non-completed runs by default and includes them only
  when requested.
- Schema-following prep rejects manifest, split-count, and loss-mask-policy
  mismatches through its contract report.
- Runtime-observed prep accepts only the `train` split and delegates prepared
  validation to schema-following prep.
- Native-transformed prep accepts only the `train` split and refuses a source
  that fails its auxiliary dataset validator.

## RC-041/042 Resolution

Contractual differences:

- Source adapters and source-specific provenance fields.
- PreparedSample v1 `assistant_tool_call_only` masking for every path.
- Runtime-observed raw-dataset evidence and profile/source manifests.

Adapter-specific compatibility:

- Four recommendation models and three naming vocabularies
  (`canonical_*`, `primary_*`, and nested runtime paths).
- Runtime-observed's double recommendation file and nested output layout.
- Rollout's source-owned rollout/dataset manifest artifacts.

The RC-040 v1 broad-mask observations remain historical evidence in the goal
record. The executable characterization is now v3 and verifies the RC-041
mask migration plus the RC-042 shared bundle. See
[`prepared_sample_contract.md`](./prepared_sample_contract.md) for the active
sample boundary and
[`training_bundle_contract.md`](./training_bundle_contract.md) for bundle
artifacts, checksums and source-evidence ownership.
