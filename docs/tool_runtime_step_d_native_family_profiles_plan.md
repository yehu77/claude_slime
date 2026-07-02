# Step D Native Family Profiles Implementation Plan

> Historical status note: this document remains the record for how native
> family profiles were introduced. Any references below to leaving a legacy
> default registry/profile path untouched are historical implementation
> constraints, not the current repo state.

## Goal

This document defines **Step D** as the profile-layer implementation step that
lands after strict Step C canonical tools and before Step E bootstrap and
runtime selection.

The Step D goal is to turn the landed strict source-aligned canonical tool
families into two real, reusable, model-visible native profiles:

- `native_claude`
- `native_codex`

Step D is not runtime work and not bootstrap work. It is the step that makes
the strict family tool sets usable as first-class `ToolProfile` inputs for:

- local runtime execution through `ToolRuntime`
- trajectory and runtime-observed trace generation
- later native-to-mutated `ToolView` transformation work

Step D must also include the minimum compatibility work needed so the current
native-transformed profile path can accept these new native profiles without
silently degrading freeform tools such as Codex `apply_patch`.

## Non-Goals

Step D does **not**:

- define new canonical tools
- change Step C runtime behavior
- add new family runtimes
- add combined runtime/bootstrap builders
- change the legacy default registry/profile/runtime path
- create one mixed Claude+Codex profile
- fabricate synthetic `source_catalog_id` values
- add new mutation modes beyond compatibility preservation

## Current Repo Baseline

The repo now has the strict Step C canonical tool layer in place:

- strict Claude canonical builders already exist
- strict Codex canonical builders already exist
- separate family registries already exist
- strict family smoke tests currently build ad hoc identity profiles inside
  tests instead of using public profile builders

Current gaps that Step D must close:

- no public `build_native_claude_profile(...)`
- no public `build_native_codex_profile(...)`
- no repo-owned profile-layer entrypoint that exposes the strict family tools
  as reusable model-visible native profiles
- native-transform code does not yet guarantee preservation of
  `contract_kind` and `input_format`, which is required for freeform Codex
  tools

The Step D implementation should treat the landed strict Step C canonical
tool builders as the source of truth, not the legacy builtin tool surface.

## Public Builder Interfaces

Step D introduces two new public profile builders:

```python
def build_native_claude_profile(
    profile_id: str = "native_claude",
) -> ToolProfile:
    ...

def build_native_codex_profile(
    profile_id: str = "native_codex",
) -> ToolProfile:
    ...
```

Placement rules:

- add these builders to `pycodeagent/tools/profile_factory.py`
- re-export them from `pycodeagent/tools/__init__.py`

Step D should not add any Step E-style runtime/bootstrap assembly helper such
as:

- `build_native_claude_runtime(...)`
- `build_native_codex_runtime(...)`
- `build_native_family_stack(...)`

If a generic helper is useful for code reuse, it should stay internal to the
profile factory module.

## Source Of Truth And Construction Rules

The new profile builders must source their ToolViews from the landed strict
Step C canonical tool builders:

- Claude profile sources from the strict Claude canonical tool set
- Codex profile sources from the strict Codex canonical tool set

Construction rules:

- preserve strict Step C canonical order exactly
- build separate family profiles only
- do not build a mixed family profile
- do not depend on legacy builtin tools
- keep `exposed_name == canonical_name` in this step
- keep adapters identity-only in this step

Each ToolView in a Step D native profile must:

- copy `canonical_name` from the strict canonical tool
- copy `description`
- deep-copy `input_schema`
- copy `contract_kind`
- copy `input_format`
- copy `version`
- preserve canonical metadata and extend it with Step D profile metadata

The Codex native profile must preserve freeform `apply_patch` exactly:

- `contract_kind` must remain `FREEFORM`
- `input_format` must remain the strict grammar contract
- `input_schema` must not be used to object-wrap `apply_patch`

Step D must not treat `native_codex` as “function tools plus one compatibility
exception.” Freeform Codex tools are part of the native profile contract.

## Metadata Contract

Step D must define a stable metadata baseline for both ToolView metadata and
profile metadata so later mutation work can distinguish:

- native Claude
- native Codex
- mutated-from-Claude
- mutated-from-Codex

### ToolView metadata

Each Step D ToolView should preserve existing canonical metadata and add at
least:

- `family`
- `native_name`
- `native_profile_kind`
- `mutation_source_family`
- `canonical_mapping_status = "native_identity_not_canonicalized"`
- `transformation_mode = "base"`
- `name_mutated = False`
- `description_mutated = False`
- `schema_mutated = False`
- `tool_order_index_base`
- `tool_order_index_exposed`
- `tool_reordered = False`
- `name_variant_id`
- `description_variant_id`
- `schema_variant_id`
- `schema_variant_category = None`

Variant-id rule:

- use stable native-base identifiers derived from the exposed native name
- do not reuse legacy builtin variant ids that imply the legacy tool family

### Profile metadata

Each Step D native family profile should include at least:

- `family`
- `native_profile_kind`
- `mutation_source_family`
- `profile_origin = "strict_family_canonical_tools"`
- `transformation_mode = "base"`
- `native_schema_snapshot = True`
- `canonical_mapping_status = "native_identity_not_canonicalized"`
- `tool_order_preserved = True`
- `mode = "native_family_base"`
- `seed = 0`
- `mutation_manifest_version = 1`
- `mutation_axes = []`
- `compat_mode = None`
- `reorder_anchor_policy = "preserve_source_order"`
- `tool_order_seed = None`
- `schema_variant_categories`
- `selected_variant_ids`

Explicit Step D rule:

- do **not** fabricate `source_catalog_id`

Reason:

- these Step D native family profiles are real local strict-family profiles,
  not catalog-derived snapshots
- later catalog/export steps can add catalog-linked source metadata when that
  layer exists

## Native-Transform Compatibility Is In Scope

Step D includes one compatibility task outside the profile builders:

- update `pycodeagent/traces/native_profile_transform.py` so transformed
  ToolViews preserve `contract_kind` and `input_format` from the base native
  profile

This is required because Step D should produce native profiles that can serve
as real mutation starting points. The transformed-profile path must not
silently degrade:

- freeform Codex `apply_patch`
- family provenance
- native profile provenance

Minimum transform-preservation requirements:

- `contract_kind`
- `input_format`
- `family`
- `native_profile_kind`
- `mutation_source_family`
- `canonical_mapping_status`

No new mutation modes are added in Step D. This is compatibility
preservation only.

## Recommended Module Changes

Primary Step D construction changes should land in:

- `pycodeagent/tools/profile_factory.py`
- `pycodeagent/tools/__init__.py`
- `pycodeagent/traces/native_profile_transform.py`

Recommended implementation shape:

- add one internal helper that builds a `ToolProfile` from a strict family
  canonical-tool list
- call that helper from `build_native_claude_profile(...)`
- call that helper from `build_native_codex_profile(...)`
- keep family-specific metadata explicit at the public-builder boundary

Do not move the strict canonical builders themselves in Step D.

## Test Plan

Step D should add or update tests in four groups.

### 1. Builder definition tests

- `build_native_claude_profile()` returns a `ToolProfile` with exactly
  `Bash / Read / Edit / Write / Grep / Glob`
- `build_native_codex_profile()` returns a `ToolProfile` with exactly
  `exec_command / write_stdin / apply_patch`
- tool order matches strict Step C canonical order
- `exposed_name == canonical_name` for every tool
- `native_codex` preserves freeform `apply_patch`
- versions are explicit and preserved
- family metadata and native-profile metadata are present

### 2. Runtime integration tests

- strict Claude registry + `build_native_claude_profile()` execute through
  `ToolRuntime`
- strict Codex registry + `build_native_codex_profile()` execute through
  `ToolRuntime`
- existing strict family smoke flows switch from ad hoc identity-profile
  helpers to the Step D public builders
- trajectory `tool_versions` and observation metadata remain family-aware

### 3. Transform compatibility tests

- `build_native_transformed_profile()` accepts `native_claude`
- `build_native_transformed_profile()` accepts `native_codex`
- Codex `apply_patch` stays freeform after base/name/description transforms
- transformed profiles preserve `contract_kind`
- transformed profiles preserve `input_format`
- transformed profiles preserve family and native-profile provenance metadata

### 4. Compatibility tests

- `build_base_tool_profile()` remains unchanged
- `build_builtin_registry()` remains unchanged
- legacy bootstrap/runtime entrypoints remain unchanged
- no native family profile becomes the implicit default path
- no mixed Claude/Codex profile is introduced

## Acceptance Criteria

Step D is complete only when all of the following are true:

- the repo has public `build_native_claude_profile(...)`
- the repo has public `build_native_codex_profile(...)`
- both profile builders expose the strict Step C tool sets in source order
- Step D native profiles preserve `contract_kind` and `input_format`
- Codex `apply_patch` remains freeform in `native_codex`
- strict family smoke tests can use the new public profile builders
- transformed native profiles preserve freeform Codex tools and family
  provenance
- the legacy default path remains unchanged

## Assumptions And Defaults

- document path is `docs/tool_runtime_step_d_native_family_profiles_plan.md`
- Step D is profile-layer only
- short public builder naming is locked:
  - `build_native_claude_profile`
  - `build_native_codex_profile`
- no synthetic `source_catalog_id` is added in Step D
- native-transform compatibility for freeform Codex tools is included in Step D
- bootstrap/runtime selection remains a later Step E concern
- legacy default path remains untouched during this step
