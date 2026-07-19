# PreparedSample Contract v1

RC-041 defines one source-neutral, versioned boundary between source-specific
trace transformation and tokenization/packing:

```text
raw source evidence
  -> source adapter / canonicalization / ToolView transformation
  -> deterministic serialization and character mask
  -> PreparedSample v1
  -> tokenization / packing / downstream training consumer
```

`pycodeagent.rl.prepared_sample.PreparedSample` is the only model at this
boundary. `TrainingSample`, `SchemaFollowingPreparedSample`, and
`ClaudeApiSFTPreparedSample` remain compatibility aliases to that same class;
they are not independent contracts.

## Required Core

Every sample carries:

- `schema_version=1`;
- `sample_id`, `sample_type`, `source_type`, and `split`;
- `task_id` and model-visible `tool_profile_id`;
- the declared `loss_mask_policy`;
- serialized `text`, ordered `segments`, character `spans`,
  `character_mask`, and `trainable_char_count`;
- a `metadata` mapping for lossless source evidence.

`mutation_category` is optional because a trajectory need not be transformed.
`reward`, `status`, `verifier_passed`, and `verifier_score` form one optional
run-outcome group: sources that own all four must preserve them, while sources
that do not carry run outcomes must leave all four absent. Adapters must not
fabricate missing outcomes.

## Mask Policy

PreparedSample v1 has exactly one policy:
`assistant_tool_call_only`. A trainable segment must have kind
`assistant_tool_call`; system, user, natural-language assistant, and tool
observation segments are context.

This is an explicit versioned migration from the broad masks captured by the
RC-040 v1 baseline for rollout and auxiliary Claude targets. Raw auxiliary
records may retain their historical source policy, but the adapter records it
as `metadata.source_loss_mask_policy` and emits the v1 prepared policy.

## Evidence Boundary

The core fields normalize only what tokenization and packing need. Evidence
that explains how the target was derived remains in metadata, including where
applicable:

- raw trace/request identifiers and source provenance;
- canonical tool intent;
- transformed/model-visible target tool call;
- mutation and transformation details;
- runtime-observed family/profile evidence;
- repository, diff, and tool-version evidence.

The prepared contract does not replace raw or canonical artifacts. It records
their training-facing projection without collapsing canonical tool identity
into the exposed ToolView name.

## Loud Validation

Construction and JSONL loading reject:

- missing or empty identities;
- unknown schema or loss-mask versions;
- text/mask length mismatch or non-binary masks;
- segment/span count, offset, text, or trainability mismatch;
- a trainable segment other than `assistant_tool_call`;
- a declared trainable count that differs from the mask;
- partially populated run outcomes;
- undeclared top-level fields.

`read_prepared_samples` reports the JSONL path and line number. All
source-specific read/write helpers delegate to the same validated loader and
deterministic writer.

## Compatibility and Next Boundary

RC-041 owns the sample model and tensorization input. RC-042 now owns the
shared contract-report, tokenization, packing and manifest orchestration
documented in [`training_bundle_contract.md`](./training_bundle_contract.md).
Recommendation models and source-owned raw layouts intentionally remain
adapter-specific.
