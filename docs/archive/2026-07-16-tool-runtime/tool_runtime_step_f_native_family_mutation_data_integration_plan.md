# Step F Native Family Mutation And Observed Data Integration Plan

> Archived by RC-016 on 2026-07-16. Current native-family terminology and
> policy are defined by
> [ADR-0001](../../adr/0001-native-family-runtime-boundary.md). This file is a
> historical implementation record and cannot override that decision. See this
> archive's README for provenance and replacement mapping.

> Historical status note: this document remains the implementation record for
> mutation/data-path integration. References below to preserving legacy
> bootstrap or legacy mutation defaults are landing-time constraints only and
> were superseded by the later native-only cutover.

## Goal

This document defines **Step F** as the implementation pass that turns the
landed native family stacks into a real **mutation and observed-data mainline**
for the local runtime.

Step F lands after:

- Step C strict source-aligned canonical tools
- Step D native family profiles
- Step E bootstrap and registry selection

The Step F goal is to make the following path first-class for both strict
family subsets:

`native family source profile -> mutated ToolView profile -> local runtime run -> runtime-observed export -> training-prep`

Required outcomes:

- native Claude and native Codex profiles become valid mutation source
  profiles, not just static identity snapshots
- mutation work proceeds **within family** rather than collapsing back to the
  legacy builtin surface
- runtime-observed exports preserve family provenance, contract kind, and
  freeform-tool fidelity
- Codex freeform `apply_patch` survives the local observed-data path without
  being forced back into object-shaped arguments
- the existing local runtime can produce family-aware observed artifacts that
  are useful for later schema-mutation studies and training-data generation

## Non-Goals

Step F does **not**:

- define new canonical tools
- change Step B or Step C runtime semantics
- replace the legacy default bootstrap/profile path
- create a mixed Claude+Codex source profile
- redesign provider transport for freeform tools beyond the already-landed
  local/fake contract path
- make every older evaluation path freeform-aware in the same pass
- replace the existing Claude API native-transformed export path with the local
  runtime path
- solve generalized freeform schema mutation beyond identity-preserving support

Step F is specifically about making the **family-aware local runtime mutation
and observed-data path** concrete and reusable.

## Current Repo Baseline

After Step E, the repo already has:

- strict source-aligned Claude and Codex canonical tool builders
- native family `ToolProfile` builders:
  - `build_native_claude_profile()`
  - `build_native_codex_profile()`
- family-aware runtime bootstraps:
  - `build_native_claude_runtime()`
  - `build_native_codex_runtime()`
- Step C0 freeform tool contracts in the main runtime path
- Step D compatibility preservation for `contract_kind` and `input_format` in
  `build_native_transformed_profile()`

However, the mutation and data-generation path is still not family-aware
end-to-end.

Current gaps that Step F must close:

- `ToolProfileSampler` still anchors itself to `build_base_tool_profile()`
  unless explicitly extended
- `configs/tools/mutation_v1.yaml` is still keyed to the legacy builtin tool
  surface rather than strict Claude/Codex native names
- `pycodeagent/eval/toolview_mutation_data_generation.py` still builds source
  runs from the legacy runtime path
- deterministic runtime-observed test helpers still primarily materialize
  legacy builtin profiles and `finish`-style trajectories
- `pycodeagent/rl/schema_following_from_runtime.py` still assumes object
  arguments during canonical-intent recovery and target-call export
- runtime-observed profile manifests currently omit `contract_kind` and
  `input_format`, which makes freeform-tool export lossy
- the local runtime observed-data path still lacks one clean “native family
  source -> mutated family view -> observed sample” mainline

Step F therefore closes an **integration gap**, not a runtime-family gap.

## Core Step F Decisions

### 1. Native family profiles remain the source profiles

Step F must treat the landed Step D profiles as the only native-family source
roots for this pass:

- `native_claude`
- `native_codex`

Rules:

- mutation begins from one of these source profiles
- no mixed-family source profile is introduced
- legacy mutation paths remain available for compatibility, but they are not
  the Step F mainline

### 2. Source family and mutation mode stay separate

Step F must not overload one field to mean both “which family this run came
from” and “what mutation was applied”.

The important distinctions are:

- source family:
  - `claude`
  - `codex`
- native profile kind:
  - `native_claude`
  - `native_codex`
- mutation mode:
  - `base`
  - `name_only`
  - `description_only`
  - `name_description`
  - `argument_rename`
  - `schema_flat_to_nested`
  - `tool_reorder`

Required rule:

- downstream exports must be able to distinguish “Codex base profile” from
  “Codex argument-rename profile” from “Claude tool-reorder profile” without
  inferring that from tool names alone

### 3. Freeform tools remain freeform

Step F must preserve Codex `apply_patch` as a freeform tool throughout:

- source profile
- mutated profile
- tool runtime dispatch
- trajectory storage
- runtime-observed export
- training-prep inputs

Explicit rules:

- `apply_patch` must keep `contract_kind = freeform`
- `apply_patch` must keep its `input_format`
- `apply_patch` must not be wrapped into object arguments during mutation
- `argument_rename` and `schema_flat_to_nested` do **not** invent fake object
  schemas for `apply_patch`

Freeform mutation beyond identity preservation remains deferred. In Step F,
freeform Codex tools may still participate in:

- identity/base views
- name mutation
- description mutation
- tool reorder

but not in synthetic object-schema adaptation.

### 4. Mutation config must become family-aware

Step F must not pretend the legacy mutation config is source-aligned just
because the new runtime path exists.

Required config decision:

- keep `configs/tools/mutation_v1.yaml` as the legacy builtin mutation config
- add a new native-family mutation config, for example:
  - `configs/tools/native_family_mutation_v1.yaml`

Recommended shape:

```yaml
families:
  claude:
    tool_variants:
      Bash: ...
      Read: ...
      Edit: ...
      Write: ...
      Grep: ...
      Glob: ...
  codex:
    tool_variants:
      exec_command: ...
      write_stdin: ...
      apply_patch: ...
```

This new config should:

- key tools by their strict Step C visible native names
- keep families separate so name collisions remain safe
- allow per-tool omission of unsupported mutation axes
- allow freeform tools to expose name/description candidates without requiring
  fake schema variants

### 5. Runtime-observed exports must become contract-aware

Step F must preserve the same tool-contract distinctions that Step C0 added to
the runtime path.

That means runtime-observed export must preserve, at minimum:

- canonical tool name
- exposed tool name
- `contract_kind`
- `input_format`
- family
- native profile kind
- mutation source family
- mutation mode

This is required so later filtering can answer questions such as:

- which samples came from Codex freeform tools
- which samples came from Claude-native source profiles
- which observed samples came from deep schema mutation versus surface-only
  mutation

## Mutation Construction Rules

### Extend the existing sampler instead of forking the profile layer

Step F should keep the existing mutation construction entrypoint shape, but
make it source-profile-aware.

Recommended change:

```python
class ToolProfileSampler:
    def __init__(
        self,
        seed: int = 0,
        *,
        mutation_config_path: str | Path | None = None,
        base_config_path: str | Path | None = None,
        base_profile: ToolProfile | None = None,
    ) -> None:
        ...
```

Required behavior:

- when `base_profile is None`, current legacy behavior remains unchanged
- when `base_profile` is a native family profile, sampling stays inside that
  family
- the sampler must preserve `contract_kind` and `input_format` from the source
  profile
- the sampler must preserve freeform tools as freeform tools

The existing helper should also be extended accordingly:

```python
def build_sampled_tool_profile(
    mode: str,
    *,
    seed: int = 0,
    config_path: str | Path | None = None,
    base_profile: ToolProfile | None = None,
) -> ToolProfile:
    ...
```

### Keep surface transforms and deep runtime mutations distinct

Step D already preserved native profile compatibility for
`build_native_transformed_profile()`.

Step F should **not** overload that surface-transform helper with the full deep
runtime mutation workload.

The intended split is:

- `build_native_transformed_profile(...)`
  - native surface-level transforms
  - `base`
  - `name_only`
  - `description_only`
  - `name_description`
- family-aware sampler path
  - native runtime mutation source profiles
  - `argument_rename`
  - `schema_flat_to_nested`
  - `tool_reorder`
  - compatibility support for `base`

This keeps the trace-derived native-transform path and the local-runtime
observed-mutation path related but not confused.

### Per-tool identity fallback is allowed

Not every strict native tool needs a non-trivial schema mutation on day one.

Step F may allow a tool to remain identity-preserving for a given mutation axis
when:

- no safe source-aligned schema mutation has been defined for that tool yet
- the tool is freeform and object-schema mutation is out of scope
- the tool is operationally secondary in the current smoke workflows

However:

- the profile-level mutation mode is still real
- metadata must still make it clear which tools mutated and which stayed at
  identity
- the sampler must not silently collapse the entire family profile back to the
  legacy builtin surface

## ToolProfile And Dataset Contract Follow-Through

### Add contract-aware projection helpers on `ToolProfile`

The current `ToolProfile.map_call_arguments(...)` and
`ToolProfile.project_canonical_call(...)` helpers are still function/object
only.

Step F should keep those helpers for compatibility, but add contract-aware
helpers for the family-aware observed-data path.

Recommended additions:

```python
def map_call_payload(...)
def project_canonical_payload(...)
```

Required behavior:

- branch by `contract_kind`
- support both object arguments and freeform `input_text`
- preserve roundtrip checks for both function and freeform tools
- avoid forcing freeform tools through object-only adapter code

Step F runtime-observed export should use these contract-aware helpers rather
than reusing the legacy object-only methods.

### Extend schema-following sample contracts for freeform tool calls

Step F is not complete if runtime-observed samples can only represent function
tool calls.

Required contract decision:

- extend the schema-following sample models so both the **target exposed call**
  and the **canonical intent** can carry either:
  - `arguments_object`
  - `input_text`

Recommended direction:

- keep the current canonical `<|tool|> ... <|end|>` block format
- for function tools, keep rendering:
  - `{"id": "...", "name": "...", "arguments": {...}}`
- for freeform tools, render:
  - `{"id": "...", "name": "...", "input_text": "..."}`

This contract should align with the Step C0 payload vocabulary rather than
inventing a second naming scheme inside training-data models.

### Keep freeform evaluation explicitly out of scope for now

`pycodeagent/rl/schema_following_eval.py` currently rejects freeform target
calls.

Step F should not attempt to finish freeform evaluation parity in the same
pass. The acceptable Step F behavior is:

- runtime-observed export supports freeform samples
- serializer and training-prep support freeform samples
- evaluation paths may continue to reject or skip freeform samples until a
  later dedicated pass

## Runtime-Observed And Postrun Integration

### Runtime-observed exporter

`pycodeagent/rl/schema_following_from_runtime.py` must be upgraded from
object-only projection to contract-aware observed export.

Required changes:

- preserve `contract_kind` and `input_format` in profile-manifest exports
- recover canonical intent through the new contract-aware `ToolProfile` helper
- roundtrip-check freeform calls as well as function calls
- emit freeform observed targets for `apply_patch` when they occur
- preserve family metadata from the source profile and source tool views

Required new metadata in exported observed samples:

- `source_family`
- `source_native_profile_kind`
- `mutation_source_family`
- `source_contract_kind`
- `source_input_format`
- `source_tool_contract_kind`
- `source_tool_input_format`

Step F should also extend summary counts to make native family filtering easy,
for example:

- sample count by family
- sample count by native profile kind
- sample count by contract kind
- sample count by mutation mode

### Runtime-observed postrun bundles

`pycodeagent/eval/runtime_observed_postrun.py` should remain the study-scale
wrapper, but Step F must make it family-aware.

Required bundle/report additions:

- counts by `family`
- counts by `native_profile_kind`
- counts by `contract_kind`
- counts by `canonical_tool_name`
- counts by `exposed_tool_name`

The postrun layer should be able to show, for example:

- how many observed samples came from Codex `apply_patch`
- how many samples came from Claude native profiles
- how many samples came from freeform versus function tools

## Mutation Data-Generation Entry Points

Step F should make the current mutation data-generation path family-aware
without replacing its legacy default behavior.

Recommended changes to:

- `pycodeagent/eval/toolview_mutation_data_generation.py`

Required interface extension:

```python
tool_stack_kind: Literal["legacy", "native_claude", "native_codex"] = "legacy"
```

Required behavior:

- `legacy` keeps the current path
- `native_claude` builds the Step E Claude stack and uses the resulting profile
  as the mutation source profile
- `native_codex` builds the Step E Codex stack and uses the resulting profile
  as the mutation source profile

Required default-mode rule for the runtime-observed family-aware path:

- keep the deep runtime mutation mainline focused on:
  - `base`
  - `argument_rename`
  - `schema_flat_to_nested`
  - `tool_reorder`

Native surface-only transform modes may remain separately callable, but they
should not displace the deep runtime mutation mainline in Step F.

### No silent family/runtime mismatch

When a mutation data-generation path chooses a native family source profile, it
must run under the matching Step E runtime stack.

Required rules:

- native Claude mutated profiles run under the Claude registry/runtime stack
- native Codex mutated profiles run under the Codex registry/runtime stack
- no native mutated profile is paired with the legacy registry by fallback

## Recommended Module Changes

Primary Step F construction work should land in:

- `configs/tools/native_family_mutation_v1.yaml`
- `pycodeagent/mutations/profile_sampler.py`
- `pycodeagent/tools/spec.py`
- `pycodeagent/rl/schema_following.py`
- `pycodeagent/rl/schema_following_from_runtime.py`
- `pycodeagent/eval/runtime_observed_postrun.py`
- `pycodeagent/eval/toolview_mutation_data_generation.py`
- `pycodeagent/testing/runtime_observed.py`

Step F may also require smaller compatibility updates in:

- serializer helpers that render or inspect target tool calls
- profile-manifest exporters/loaders
- any bundle summary helper that currently assumes object-only tool payloads

Step F should avoid broad, unrelated changes to:

- Step B runtime implementations
- strict Step C canonical tool builders
- Step D native profile builders
- Step E bootstrap selection semantics

## Test Plan

Step F should add or update tests in five groups.

### 1. Family-aware mutation builder tests

- `ToolProfileSampler(base_profile=native_claude)` can sample native Claude
  family mutations
- `ToolProfileSampler(base_profile=native_codex)` can sample native Codex
  family mutations
- legacy `ToolProfileSampler()` behavior remains unchanged when no source
  profile is passed
- family-aware sampled profiles preserve `contract_kind`
- family-aware sampled profiles preserve `input_format`
- sampled Codex `apply_patch` remains freeform

### 2. Mutation config tests

- native-family mutation config loads successfully
- strict Claude tool entries are keyed by exact native names
- strict Codex tool entries are keyed by exact native names
- missing per-tool mutation candidates fall back to identity without breaking
  the full family profile
- freeform tools can carry name/description candidates without fake object
  schema variants

### 3. Runtime-observed export tests

- runtime-observed exporter preserves `contract_kind` and `input_format` in
  profile-manifest outputs
- runtime-observed exporter can roundtrip and export a freeform `apply_patch`
  observed call
- runtime-observed sample metadata preserves:
  - family
  - native profile kind
  - mutation source family
  - mutation mode
- observed summaries include counts by family and contract kind

### 4. End-to-end native family smoke tests

- one deterministic native Claude runtime-observed smoke flow runs from a
  native family source profile through a mutated profile and observed export
- one deterministic native Codex runtime-observed smoke flow runs from a
  native family source profile through a mutated profile and observed export
- Codex smoke flow proves freeform `apply_patch` survives trajectory ->
  observed sample -> training-prep
- existing strict family smoke flows can switch from ad hoc profile wiring to
  the public Step D and Step E builders

### 5. Compatibility tests

- legacy mutation sampling still works
- legacy runtime-observed export still works for function-only profiles
- legacy bootstrap/runtime entrypoints remain unchanged
- freeform-aware observed export does not break function-only serializer output
- freeform-unaware evaluation paths continue to fail clearly rather than
  silently mis-scoring samples

## Acceptance Criteria

Step F is complete only when all of the following are true:

- native Claude and native Codex profiles are valid mutation source profiles
  for the local runtime path
- family-aware mutation sampling no longer depends on the legacy builtin tool
  surface
- native-family mutation config exists and is keyed by strict Step C native
  visible names
- runtime-observed exports preserve family provenance, `contract_kind`, and
  `input_format`
- Codex `apply_patch` survives the runtime-observed export path as a freeform
  tool
- at least one native Claude mutation smoke flow runs end to end
- at least one native Codex mutation smoke flow runs end to end
- training-prep succeeds on observed outputs from both family stacks
- legacy mutation/data-generation paths remain intentionally compatible

## Assumptions And Defaults

- document path is
  `docs/tool_runtime_step_f_native_family_mutation_data_integration_plan.md`
- Step F is the first mutation/data-path step after Step E
- native family source profiles remain separate; no mixed-family profile is
  introduced
- the runtime-observed family-aware mainline defaults to the deep mutation set:
  - `base`
  - `argument_rename`
  - `schema_flat_to_nested`
  - `tool_reorder`
- native surface-only transforms remain supported through
  `build_native_transformed_profile()`, but that is not the Step F runtime
  mutation mainline
- freeform schema mutation beyond identity-preserving support remains deferred
- freeform evaluation parity remains a later dedicated task
- legacy default bootstrap/profile/runtime behavior remains untouched during
  this step
