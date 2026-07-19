# Training Bundle Contract v1

RC-042 defines one bundle-level orchestration after the
[`PreparedSample` v1 boundary](./prepared_sample_contract.md):

```text
source-specific raw artifacts
  -> source adapter and validation-only source checks
  -> ordered PreparedSample v1 records
  -> TrainingBundleBuilder
       -> tokenize
       -> align labels/masks
       -> pack
       -> contract verify
       -> checksum manifest
  -> slime-compatible training bundle
```

`pycodeagent.rl.training_bundle.TrainingBundleBuilder` is the only active
implementation of these bundle steps. Rollout, schema-following,
runtime-observed, and auxiliary native-transformed entrypoints differ only in
how they collect and validate source evidence and in the recommendation model
returned to their existing callers.

## Deterministic Core Artifacts

Every builder invocation owns and rewrites:

| Artifact | Contract |
| --- | --- |
| `samples.jsonl` | validated PreparedSample v1 records in stable order |
| `tokenized.jsonl` | slime-facing token IDs, labels, attention and train masks |
| `packed.jsonl` | deterministic greedy packed sequences with source spans |
| `tokenizer_config.yaml` | resolved tokenizer and truncation policy |
| `train_config.json` | downstream dataset/config handoff |
| `contract_report.json` | source issues plus prepared/tokenized/packed verification |
| `bundle_manifest.json` | bundle v1 identity, counts, source references and SHA-256 |

Samples are ordered by:

```text
split, task_id, tool_profile_id, sample_id, source_type, sample_type
```

The manifest has no timestamp or random identifier. Rebuilding the same
source, configuration and destination produces identical builder-owned bytes.
`verify_training_bundle_manifest` rejects unknown manifest versions, unsafe
artifact paths, missing files, size changes, and checksum mismatches.

## Contract Verification

The shared verifier rejects:

- empty bundles unless a compatibility adapter explicitly permits them, and
  duplicate `sample_id` values;
- prepared/tokenized count differences;
- task, profile, sample, or source identity loss during tensorization;
- token/attention/label/train-mask misalignment;
- labels inconsistent with the token train mask;
- a non-empty character target that becomes empty after truncation;
- packed counts or unpacked source-span counts that do not round-trip;
- source-adapter issues such as rollout/sample pairing or schema manifest
  mismatch.

The builder writes the contract report before raising, so failed preparation
is inspectable but never receives a success manifest.

## Source Evidence Boundary

The builder does not copy, rewrite, or flatten raw traces, native tool
catalogs, runtime manifests, request logs, or source datasets.
`source_path` identifies their owning location and `source_artifacts` records
the artifacts the adapter used. Runtime-observed output therefore retains its
separate `raw_dataset/` and `prepared/` directories. Auxiliary
native-transformed samples retain raw source type and transformation evidence
inside PreparedSample metadata.

Rollout-specific `dataset_manifest.json` and `rollouts.jsonl` remain
source-adapter artifacts next to the shared bundle. `training_prep.json`
remains an entrypoint-specific compatibility recommendation and is not part of
the checksummed builder core.

## Versioned Migration from RC-040/041

The RC-040 characterization is now v3:

- all four routes emit the same seven core artifacts;
- `packed.jsonl` and `bundle_manifest.json` are new;
- native-transformed now emits the shared contract report and packing output;
- runtime-observed keeps its nested raw/prepared evidence layout;
- source-specific recommendation field names remain compatible.

RC-041 continues to own serialized text and mask semantics. RC-042 does not
change `assistant_tool_call_only`.
