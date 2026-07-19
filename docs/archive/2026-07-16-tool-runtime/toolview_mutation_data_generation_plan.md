# ToolView Mutation Data-Generation Plan

> Archived by RC-016 on 2026-07-16. Current native-family terminology and
> policy are defined by
> [ADR-0001](../../adr/0001-native-family-runtime-boundary.md). This file is a
> historical implementation record and cannot override that decision. See this
> archive's README for provenance and replacement mapping.

> Historical status note: references below to legacy compatibility modes or
> legacy-first defaults are archival context from before the native-only
> cleanup. The current mainline mutation/data-generation path is native-family
> based.

## Summary

This document defines the narrow implementation path for the repository's
ToolView-mutation data-generation mainline:

- mutate exposed tool schema
- run the real-provider local runtime
- preserve the actually emitted exposed tool call
- export training-ready observed data

This is intentionally narrower than a mutation research program. It does not
define a new benchmark, a new failure-analysis stack, or a new runtime-maturity
roadmap. It only defines the work needed to make deep ToolView mutation a
first-class training-data production path.

The current implementation already has the core building blocks:

- mutation-capable `ToolProfile` sampling
- native-tools real-provider runtime runs
- observed runtime exporter
- runtime-execution reconciliation
- training-prep for runtime-observed samples

What remains is to remove historical defaults and wire those pieces into one
clean, mutation-first production flow.

## Goal

The goal is to make this path first-class:

`base / mutated ToolView -> real provider run -> observed samples -> training-prep`

The immediate target is not broader mutation research. The immediate target is:

1. the right default deep-mutation mode set
2. a narrow real-provider data-generation entrypoint
3. mutation-first postrun summaries
4. one formal real-provider acceptance path covering all three deep modes

The mutation scope for this plan is fixed to:

- `argument_rename`
- `schema_flat_to_nested`
- `tool_reorder`

Legacy compatibility modes may remain in code, but they are not the primary
output path for this plan.

## Current Baseline

The current repository already supports the critical front-half:

- `pycodeagent/mutations/profile_sampler.py`
  - supports `argument_rename`, `schema_flat_to_nested`, `tool_reorder`
  - still also carries legacy compatibility modes such as `schema_only` and
    `name_description_schema`
- `pycodeagent/mutations/schema_mutator.py`
  - already distinguishes rename vs nested-schema mutations
- `configs/tools/mutation_v1.yaml`
  - already contains per-tool mutation candidates and schema categories
- real-provider runtime path
  - already runs through native tools
  - already preserves provider provenance and runtime trace
- `pycodeagent/rl/schema_following_from_runtime.py`
  - already exports observed emitted exposed tool calls
  - already preserves mutation metadata such as profile mode and schema category
- `pycodeagent/rl/training_prep.py`
  - already converts runtime-observed exports into training-ready inputs
- `pycodeagent/eval/runtime_observed_postrun.py`
  - already builds bundle summaries and reconciliation outputs

The remaining gaps are not missing core capabilities. They are missing
production-path alignment.

## Scope

This plan is limited to four concrete work items.

### 1. Correct the default mutation mode set

The default study and bundle paths still carry historical defaults that are not
aligned with the current goal. In particular, legacy composite modes still
appear where the intended mainline should be:

- `base`
- `argument_rename`
- `schema_flat_to_nested`
- `tool_reorder`

The implementation goal is to make that four-mode set the default
data-generation surface wherever a mutation-first runtime study or bundle is
being created.

### 2. Add a narrow real-provider data-generation entrypoint

The repository already has heavier real-provider paths such as credibility
bundles. What is missing is a small, explicit entrypoint dedicated to:

- selecting tasks
- selecting the deep mutation mode set
- running the real provider
- exporting observed raw data
- optionally running training-prep

This path should be a direct data-production path, not a larger evaluation
bundle.

### 3. Make postrun summaries mutation-first

Current sample metadata is already rich enough, but postrun summaries are not
yet centered on the three deep mutation axes. The result is that data can be
exported, but it is still too indirect to answer:

- which samples came from `argument_rename`
- which samples came from `schema_flat_to_nested`
- which samples came from `tool_reorder`
- how many training-ready samples each mode actually produced

This plan fixes that at the summary layer rather than by inventing a new data
path.

### 4. Freeze one real-provider acceptance path for all three deep modes

This is not an architecture driver. It is a release check for the production
path.

The target is one explicit acceptance path that proves:

- all three deep modes run under the real provider
- observed samples are produced
- emitted exposed tool calls are preserved
- training-prep still succeeds

## Implementation Roadmap

### M1: Default Mode-Set Cleanup

Objective:

- remove legacy-first defaults from mutation-oriented study and bundle paths

Primary implementation surfaces:

- `pycodeagent/eval/real_provider_credibility_bundle.py`
- `pycodeagent/eval/study_config.py`
- `pycodeagent/eval/experiment_config.py`
- any mutation-oriented runner/config surface still defaulting to
  `schema_only` or `name_description_schema`

Required changes:

- define the default mutation-first mode set as:
  - `base`
  - `argument_rename`
  - `schema_flat_to_nested`
  - `tool_reorder`
- keep legacy modes supported, but do not keep them as the default deep-mutation
  path
- update gate wording, mode wording, and bundle wording so they no longer assume
  `name_description_schema` is the main mutated comparison mode

Completion criteria:

- new mutation-oriented defaults use the four-mode deep set
- legacy modes remain callable explicitly
- no mutation-first orchestration path depends on `schema_only` or
  `name_description_schema` by default

### M2: Narrow Real-Provider Mutation Data-Generation Entry

Objective:

- add one explicit entrypoint for real-provider mutation data generation

Primary implementation surfaces:

- new script:
  - `run_toolview_mutation_data_generation.py`
- new or reused helper module:
  - `pycodeagent/eval/toolview_mutation_data_generation.py`
- existing provider-config resolution path
- existing runtime-observed exporter / training-prep entrypoints

Required behavior:

- accept tasks path
- accept profile modes, defaulting to the four-mode deep set
- accept fixed profile seed by mode
- accept repeat count
- run the real-provider local runtime for each task/mode/repeat
- export observed raw dataset from the resulting runs
- optionally run training-prep

Required outputs:

- source run root
- observed raw dataset root
- optional prepared dataset root
- machine-readable manifest summarizing:
  - tasks path
  - mode set
  - seed mapping
  - repeat count
  - provider provenance
  - discovered runs
  - included runs
  - observed sample count
  - training-prep status

Non-goals:

- no new benchmark protocol
- no new credibility gate stack
- no replacement of the existing real-provider credibility bundle

Completion criteria:

- one command can run deep-mutation real-provider data generation end to end
- observed raw samples are produced from actual emitted exposed calls
- optional training-prep runs on the same source without extra manual glue

### M3: Mutation-First Postrun Summary

Objective:

- make postrun outputs directly reflect the deep mutation data path

Primary implementation surfaces:

- `pycodeagent/eval/runtime_observed_postrun.py`
- `pycodeagent/rl/schema_following_from_runtime.py`
- any summary/result model that already exposes mode and sample distributions

Required changes:

- add or stabilize summary fields for:
  - sample count by `source_profile_mode`
  - sample count by `schema_variant_category`
  - sample count by canonical tool under each mode
  - sample count where `tool_reordered == true`
  - trainable sample count by mode
- keep `trajectory + tool_profile` as the observed exporter primary contract
- do not promote `runtime_trace` into the exporter primary input
- keep the actual emitted exposed call as the authoritative target

Recommended summary artifacts:

- extend existing `study_observed_summary.json`
- extend existing `runtime_observed_bundle.json`
- if needed, add one focused mutation summary artifact rather than a large new
  analysis framework

Completion criteria:

- summaries can answer which deep mode produced which samples
- summaries can distinguish rename, nested-schema, and reorder outputs without
  reopening raw sample JSONL by hand

### M4: Real-Provider Acceptance For All Three Deep Modes

Objective:

- freeze one explicit acceptance path proving the mutation data path works under
  the real provider

Primary implementation surfaces:

- the new mutation data-generation entrypoint from `M2`
- existing real-provider config resolution
- existing runtime-observed exporter and training-prep path

Acceptance run defaults:

- task pack:
  - a small fixed coding-task set already suitable for the real-provider local
    runtime
- modes:
  - `base`
  - `argument_rename`
  - `schema_flat_to_nested`
  - `tool_reorder`
- fixed seed per mode
- repeat count:
  - small but non-trivial, such as `1` or `3` depending on runtime cost

Acceptance criteria:

- each deep mode produces at least one completed run
- each deep mode produces at least one included observed sample
- observed sample metadata preserves:
  - `source_profile_mode`
  - `schema_variant_category` where applicable
  - reorder-related flags where applicable
- emitted exposed tool calls remain preserved as targets
- training-prep succeeds on the produced observed dataset

Non-goals:

- no pass-rate target
- no mutation failure taxonomy
- no new research bundle layer

Completion criteria:

- the deep mutation data path is no longer implicit
- the repository has one formal acceptance path for:
  - mutate schema
  - run real provider
  - export training data

## Implementation Surfaces

This plan should stay focused on these files and modules:

- `pycodeagent/mutations/profile_sampler.py`
- `pycodeagent/mutations/schema_mutator.py`
- `configs/tools/mutation_v1.yaml`
- `pycodeagent/eval/real_provider_credibility_bundle.py`
- `pycodeagent/eval/study_config.py`
- `pycodeagent/eval/experiment_config.py`
- `pycodeagent/rl/schema_following_from_runtime.py`
- `pycodeagent/eval/runtime_observed_postrun.py`
- `pycodeagent/rl/training_prep.py`
- new:
  - `pycodeagent/eval/toolview_mutation_data_generation.py`
  - `run_toolview_mutation_data_generation.py`

This plan should not reopen the runtime-core maturity roadmap unless a mutation
data-path bug forces a runtime fix.

## Acceptance Model

This plan uses three layers of acceptance.

### 1. Deterministic contract regression

Use and extend:

- `tests/test_profile_sampler.py`
- `tests/test_phase2_profile_runtime.py`
- `tests/test_e2e_smoke.py`

Purpose:

- prove mutation contracts and emitted-call preservation remain stable

### 2. Observed/export path acceptance

Use and extend:

- observed runtime exporter tests
- runtime-observed training-prep tests
- postrun summary tests

Purpose:

- prove mutated runtime runs become observed samples and training-ready outputs

### 3. Real-provider production-path acceptance

Use one explicit real-provider run path to verify:

- deep modes all execute
- observed sample export succeeds
- training-prep still works

Purpose:

- prove the repository has a usable deep-mutation data-production path, not
  just disconnected capabilities

## Short Summary

This plan makes deep ToolView mutation a narrow, first-class data-production
path:

- correct the default deep mode set
- add a direct real-provider data-generation entrypoint
- make summaries mutation-first
- freeze one explicit real-provider acceptance path

Practical instruction:

- do not rebuild a larger mutation research framework first
- wire the existing mutation, runtime, exporter, and training-prep pieces into
  one clean observed-data production flow
