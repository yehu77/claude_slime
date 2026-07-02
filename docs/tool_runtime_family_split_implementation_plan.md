# Tool Runtime Family Split Implementation Plan

## Status

As of July 1, 2026, the implementation mainline described in this document
has been landed through **Step F**, and the later **native-only cleanup**
has also been implemented in the repository codebase.

That means this document should now be read primarily as:

- the architecture and sequencing record for the native-first family split
- the completion reference for the A-F implementation mainline

It should no longer be treated as the primary construction checklist for the
next increment of work.

The next phase is **acceptance and stabilization**, not another extension of
this implementation-driver plan. Follow-up work should now focus on:

- full regression coverage in a complete test environment
- fixture and golden refresh plus audit for the new family-aware paths
- native Claude and native Codex acceptance runs on small real tasks
- provider-facing acceptance and artifact audit for the native-only mainline

Active follow-up documents:

- [`docs/tool_runtime_native_family_acceptance_and_regression_plan.md`](./tool_runtime_native_family_acceptance_and_regression_plan.md)
  is the active acceptance and stabilization driver
- [`docs/tool_runtime_legacy_demotion_followup_plan.md`](./tool_runtime_legacy_demotion_followup_plan.md)
  is now an archive-only record because the legacy demotion path was
  superseded by the implemented native-only removal

In short:

- **A-F implementation mainline:** complete in code
- **native-only cleanup:** complete in code
- **acceptance/stabilization:** the remaining active follow-up through the
  native-family acceptance plan
- **legacy demotion planning:** archived and no longer an active next step

## Goal

This document defines the native-first implementation mainline for the local
tool system in `pycodeagent`.

The goal is to replace the current monolithic builtin tool surface as the
local-runtime mainline with a **family-aware runtime scaffold** that can:

- preserve native tool families from Codex and Claude Code
- separate low-level execution reuse from higher-level tool semantics
- support later `ToolView` mutation experiments without collapsing family
  differences too early
- generate more realistic observed traces for downstream training-data work

The goal is **not**:

- full product parity with Codex or Claude Code
- immediate session or PTY parity everywhere
- immediate removal of all legacy tools
- a one-tool-only shell runtime mainline
- contract adaptation as the first step before native alignment

This plan is a companion document to the broader local-runtime and
`codex-rs` subsystem plans. It narrows one specific transition: moving from a
generic builtin tool surface to a native-first family-aware runtime while
preserving the existing
`CanonicalTool -> ToolView -> ToolAdapter -> ToolRuntime` architecture.

## Why The Plan Is Now Native-First

The current local runtime already has two strengths worth preserving:

- it separates canonical backends from model-visible `ToolView`s
- it already records structured trajectories and runtime-observed artifacts

The current weakness is not just schema shape. It is that the mainline local
tool surface still assumes a generic local toolkit such as:

- `list_files`
- `read_file`
- `write_file`
- `create_file`
- `search_code`
- `apply_patch`
- `run_command`
- `python_run`
- `finish`

That generic surface was useful for a white-box MVP, but it is no longer the
best mainline for native schema preservation or realistic source traces.

The critical lesson from the Codex and Claude source trees is:

- family differences live partly in visible schemas
- family differences also live in runtime behavior
- some native visible tools are not object-shaped function tools
- if the repo adapts too early, strict source alignment becomes a later
  migration tax instead of the mainline

That is why the plan now inserts **Step C0** before strict canonical tool
definitions.

## Core Architecture

The local tool system should now be understood as five layers.

### Layer 1: Shared Process Primitives

This is a non-model-visible internal execution layer for:

- foreground process execution
- background process execution
- stdout and stderr capture
- exit-code and duration collection
- shell selection
- login-shell handling
- background-task persistence

This is code reuse only. It is not a canonical tool family and not a schema
mutation target.

### Layer 2: Runtime Family Layer

This layer owns family-specific runtime behavior on top of shared execution
primitives.

Current runtime-family boundaries are:

- `ClaudeShellRuntime`
- `CodexShellRuntime`
- `CodexApplyPatchRuntime`

This layer is where family behavior diverges:

- Claude background command behavior
- Codex exec-session behavior
- Codex dedicated patch-edit behavior

### Layer 3: Native Tool Contract Layer

This layer is the missing Step C0 prerequisite.

It expands the repo contract so the local runtime can represent both:

- function tools with object arguments
- freeform tools with raw text input

Without this layer, strict source-aligned canonical tools would be forced back
through a synthetic function-only adaptation path.

### Layer 4: Strict Source-Aligned Canonical Tool Layer

This layer defines the scoped native visible tool families using exact
source-aligned names for the chosen subset.

Scoped strict Step C tool set:

- Claude family
  - `Bash`
  - `Read`
  - `Edit`
  - `Write`
  - `Grep`
  - `Glob`
- Codex family
  - `exec_command`
  - `write_stdin`
  - `apply_patch`

This layer uses visible native tools only. Hidden or dispatch-only source
companions are documented as notes, not promoted into the Step C canonical
tool set.

### Layer 5: ToolView, Profile, And Mutation Layer

The public architectural center remains:

```text
CanonicalTool -> ToolView -> ToolAdapter -> ToolRuntime
```

The rule is now:

- native family behavior first
- native tool contract support first
- strict source-aligned canonical tools next
- `ToolView` mutation after native family preservation is in place

## Step Order

The implementation order is now:

1. Step A: shared process primitives
2. Step B: family runtimes
3. Step C0: native tool contract expansion
4. Step C: strict source-aligned canonical tools
5. Step D: native family profiles
6. Step E: bootstrap and registry selection
7. Step F: native family mutation and observed-data integration
8. later study-scale family-aware mutation expansion and cleanup

This step order is intentional:

- Step B lands family runtime behavior
- Step C0 removes the object-only contract bottleneck
- Step C then defines strict source-aligned canonical tools without
  adaptation-first compromises
- Step D turns strict family tools into reusable native profiles
- Step E makes those profiles selectable without changing the legacy default
  path
- Step F turns those native family stacks into a real mutation and
  runtime-observed data-generation mainline

## Step A

Step A adds the shared process substrate:

- foreground execution
- background execution
- stable request and result types
- background task metadata and persistence

Step A is internal implementation reuse only.

Primary companion document:

- [`docs/tool_runtime_step_a_shared_process_primitives_plan.md`](./tool_runtime_step_a_shared_process_primitives_plan.md)

## Step B

Step B adds the runtime-family behavior layer:

- `ClaudeShellRuntime`
- `CodexShellRuntime`
- `CodexApplyPatchRuntime`

Step B remains valid as the family-runtime implementation step. It is not the
place where strict canonical tool identity is finalized.

Primary companion document:

- [`docs/tool_runtime_step_b_shell_runtime_integration_plan.md`](./tool_runtime_step_b_shell_runtime_integration_plan.md)

## Step C0

Step C0 is the new prerequisite for strict native alignment.

Its purpose is to expand the repo contract from one implicit
object-function-only path into an explicit internal contract that supports:

- `function` tools
- `freeform` tools

and tool-call payload kinds:

- `arguments_object`
- `input_text`

Step C0 is not runtime-only. It spans:

- provider request contracts
- provider response candidate contracts
- runtime dispatch
- trajectory storage
- serializer and training-data helpers
- tool-catalog and profile snapshot contracts

This step is what makes strict freeform Codex `apply_patch` possible later.

Primary companion document:

- [`docs/tool_runtime_step_c0_native_tool_contract_expansion_plan.md`](./tool_runtime_step_c0_native_tool_contract_expansion_plan.md)

## Step C

Step C defines the strict source-aligned canonical tools for the scoped native
visible subset.

Strict Step C decisions:

- no family-prefixed synthetic final names
- Claude tools keep source-native capitalization
- Codex tools keep source-native lowercase names
- `write_stdin` is part of the strict native Codex path and is not deferred
- `apply_patch` remains freeform
- Step C no longer performs the contract expansion itself

Step C assumes Step C0 has already removed the repo's object-only limits.

Primary companion document:

- [`docs/tool_runtime_step_c_canonical_tool_definitions_plan.md`](./tool_runtime_step_c_canonical_tool_definitions_plan.md)

## Step D

Step D introduces explicit native family profiles:

- `native_claude`
- `native_codex`

This step should:

- add public native family profile builders
- preserve strict family-specific `ToolView` exposure
- preserve native contract kind and input format at the profile layer
- provide the metadata baseline needed for later mutation work
- include the minimum transform-compatibility work required so freeform Codex
  tools remain freeform through the native-transform profile path

Primary companion document:

- [`docs/tool_runtime_step_d_native_family_profiles_plan.md`](./tool_runtime_step_d_native_family_profiles_plan.md)

## Step E

Step E adds explicit bootstrap and registry selection for family-aware runs.

This step should:

- add explicit native family bootstraps
- keep the legacy default path unchanged
- make family-aware runtime selection explicit rather than implicit

Separate family registries remain required so source-aligned names can coexist
with legacy names without duplicate-registration conflicts.

Primary companion document:

- [`docs/tool_runtime_step_e_bootstrap_registry_selection_plan.md`](./tool_runtime_step_e_bootstrap_registry_selection_plan.md)

## Step F

Step F turns the landed native family stacks into a family-aware mutation and
runtime-observed data-generation path.

This step should:

- treat `native_claude` and `native_codex` as the source profiles for local
  runtime mutation work
- preserve family provenance, `contract_kind`, and `input_format` through
  runtime-observed export
- keep Codex `apply_patch` freeform in the observed-data path
- connect native family source runs to the existing training-prep path without
  collapsing back to the legacy builtin tool surface

Primary companion document:

- [`docs/tool_runtime_step_f_native_family_mutation_data_integration_plan.md`](./tool_runtime_step_f_native_family_mutation_data_integration_plan.md)

## Later Mutation Work

After Step F, mutation work should scale outward from the native family
profiles rather than from an already-adapted generic shell surface.

### Native family profiles remain the source profile layer

The native profile builders should remain the starting point for:

- Claude native source-aligned views
- Codex native source-aligned views

These profiles should preserve family and visibility provenance.

The most important metadata to preserve in later mutation experiments is:

- canonical tool name
- exposed tool name
- family
- native versus mutated status
- mutation source family
- tool contract kind

## Scoped Native Family Subset

The current strict native-first scope is the shell and file-edit family
subset, not the full Codex or Claude product surfaces.

### Claude scoped subset

- `Bash`
- `Read`
- `Edit`
- `Write`
- `Grep`
- `Glob`

### Codex scoped subset

- `exec_command`
- `write_stdin`
- `apply_patch`

Hidden or dispatch-only source companions such as Codex `shell_command` remain
source notes rather than Step C canonical tools.

## Legacy Transition Strategy

Use a parallel-track migration.

Rules:

- keep the current builtin tool set intact as legacy
- do not delete old tool modules in the first pass
- do not make the current `build_base_tool_profile()` the main experimental
  path for family-aware native runs
- add family-aware registries and native profile builders alongside legacy
  builders
- preserve enough compatibility for existing tests and downstream pipeline
  assumptions during the transition

Later cleanup milestone:

- once native family registries, profiles, and tests are stable, demote legacy
  entrypoints
- remove or quarantine obsolete builtin assumptions in a separate follow-up
  pass

## Finish Tool Policy

The strict native-first path must not introduce `finish` as a model-visible
tool in the new family-aware runtime mainline.

However:

- do not remove legacy `finish` in the same pass
- keep legacy `finish` compatibility isolated to legacy flows
- handle stop-policy refactoring as a later migration concern

## Acceptance Criteria

This plan is on track only when all of the following become true:

- Step A shared process primitives are reused by family runtimes
- Step B family runtimes exist and remain family-distinct
- Step C0 removes the mainline object-only contract bottleneck
- Step C can represent strict source-aligned visible tools without synthetic
  final names
- strict Codex `apply_patch` is freeform in the local runtime path
- `write_stdin` is included in the strict native Codex path
- separate family registries preserve exact-name safety and family metadata
- legacy function-only flows remain compatible while the new path lands

## Explicit Defaults And Deferrals

Defaults:

- the documentation line is now native-first
- Step C0 is end-to-end, not runtime-only
- strict Step C is visible-tools-only
- separate family registries are required

Deferred work:

- PTY and session fidelity beyond the scoped strict native path
- generalized freeform schema mutation
- broad approval and sandbox product-control parity
- aggressive legacy removal
