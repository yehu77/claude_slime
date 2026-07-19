# Step E Bootstrap And Registry Selection Implementation Plan

> Archived by RC-016 on 2026-07-16. Current native-family terminology and
> policy are defined by
> [ADR-0001](../../adr/0001-native-family-runtime-boundary.md). This file is a
> historical implementation record and cannot override that decision. See this
> archive's README for provenance and replacement mapping.

> Historical status note: this Step E plan describes the intermediate
> selectable-stack phase. References below to `legacy`, legacy default stack
> selection, or `build_base_tool_runtime()` are no longer current interface
> guidance after the native-only cleanup.

## Goal

This document defines **Step E** as the bootstrap and runtime-selection step
that lands after:

- Step C strict source-aligned canonical tools
- Step D native family profiles

The Step E goal is to make the landed native family stacks **explicitly
selectable** without changing the legacy default path.

Step E turns the existing pieces:

- strict family canonical registries
- native family `ToolProfile` builders
- `ToolRuntime`

into reusable bootstrap entrypoints that can assemble complete runtime stacks
for:

- `legacy`
- `native_claude`
- `native_codex`

This step is not about new tools or new profile mutation. It is about making
family-aware runtime selection concrete, safe, and reusable in the repo-owned
local runtime.

## Non-Goals

Step E does **not**:

- define new canonical tools
- change Step C tool contracts
- change Step D native profile metadata semantics
- create a mixed Claude+Codex registry or profile
- flip the repo-wide default path away from legacy
- add new mutation modes
- migrate every legacy caller in one pass
- add provider-specific prompt or planner behavior

## Current Repo Baseline

The current repo state after Step D is:

- strict Claude canonical builders exist
- strict Codex canonical builders exist
- native family profile builders exist
- the top-level bootstrap layer still only exposes the legacy path

Current bootstrap gap:

- `pycodeagent/tools/bootstrap.py` still only provides
  `build_builtin_registry()` and `build_base_tool_runtime()`
- the formal local runtime selection path in
  `pycodeagent/env/coding_env.py` still hardcodes the legacy bootstrap when
  it auto-builds a runtime
- a caller can now pass `build_native_claude_profile()` or
  `build_native_codex_profile()` manually, but if they omit `runtime`, the
  current fallback logic can still assemble a legacy runtime and silently
  create a mismatched stack

That mismatch risk is the most important Step E construction problem.

## Public Bootstrap Interfaces

Step E introduces explicit public bootstrap builders in
`pycodeagent/tools/bootstrap.py`:

```python
def build_native_claude_runtime(
    *,
    profile_id: str = "native_claude",
) -> tuple[ToolRegistry, ToolProfile, ToolRuntime]:
    ...

def build_native_codex_runtime(
    *,
    profile_id: str = "native_codex",
) -> tuple[ToolRegistry, ToolProfile, ToolRuntime]:
    ...
```

These builders should:

- construct the correct family registry
- construct the correct native family profile
- construct a `ToolRuntime` bound to that registry
- return a full `(registry, profile, runtime)` triple

Placement rules:

- add the builders to `pycodeagent/tools/bootstrap.py`
- re-export them from `pycodeagent/tools/__init__.py`

The existing legacy bootstrap path remains:

- `build_builtin_registry()`
- `build_base_tool_profile()`
- `build_base_tool_runtime()`

Those existing entrypoints must remain unchanged in behavior.

## Internal Selection Helper

Step E should also add one internal bootstrap-selection helper.

Recommended shape:

```python
ToolStackKind = Literal["legacy", "native_claude", "native_codex"]

def _build_tool_stack(
    kind: ToolStackKind,
    *,
    profile_id: str | None = None,
) -> tuple[ToolRegistry, ToolProfile, ToolRuntime]:
    ...
```

This helper does not need to be public in Step E.

Its job is to:

- centralize stack assembly logic
- avoid duplicating bootstrap branching in environment/runtime code
- preserve one explicit place where stack-kind selection rules live

Step E does **not** need a public string-dispatch bootstrap API unless a real
call site requires it. Separate explicit public builders are preferred.

## Registry And Profile Composition Rules

The new family bootstrap builders must compose exactly from the landed Step C
and Step D layers:

### `build_native_claude_runtime(...)`

Must assemble:

- registry from `build_claude_canonical_registry()`
- profile from `build_native_claude_profile(profile_id=...)`
- runtime from `ToolRuntime(registry)`

### `build_native_codex_runtime(...)`

Must assemble:

- registry from `build_codex_canonical_registry()`
- profile from `build_native_codex_profile(profile_id=...)`
- runtime from `ToolRuntime(registry)`

Required rules:

- no mixed registry
- no mixed profile
- no legacy builtin registry reuse for native family stacks
- preserve strict family separation
- preserve Step D profile ids unless caller overrides them

## Runtime Selection Semantics

Step E must make runtime selection explicit in the main local-runtime
resolution path.

Recommended integration point:

- `pycodeagent/env/coding_env.py`
- specifically the profile/runtime resolution helper currently named
  `_resolve_profile_and_runtime(...)`

Step E should extend that path with an explicit stack-kind concept:

```python
tool_stack_kind: Literal["legacy", "native_claude", "native_codex"] = "legacy"
```

Selection rules should be:

### Rule 1: Explicit runtime wins

If the caller passes a concrete `runtime`, Step E should not auto-build a new
runtime stack.

### Rule 2: Explicit profile without runtime must infer a matching runtime

If the caller passes a concrete `profile` but omits `runtime`, Step E must no
longer blindly fall back to the legacy runtime.

Instead, the resolver should infer the stack kind from profile provenance.

Minimum inference sources:

- `profile.metadata["native_profile_kind"]`
- `profile.metadata["family"]`
- legacy fallback when native-family provenance is absent

Expected inference:

- `native_claude` profile -> Claude registry/runtime
- `native_codex` profile -> Codex registry/runtime
- profile without native-family provenance -> legacy runtime

This rule is required to prevent profile/runtime mismatches.

### Rule 3: Auto-build path uses the requested stack kind

If neither `profile` nor `runtime` is supplied:

- `legacy` -> `build_base_tool_runtime()`
- `native_claude` -> `build_native_claude_runtime()`
- `native_codex` -> `build_native_codex_runtime()`

### Rule 4: Legacy profile sampling remains legacy-only in Step E

If the caller uses `profile_mode` / deterministic sampling, Step E should keep
that path limited to the legacy base-profile system unless the repo already has
a native-family mutation selector ready.

Required Step E decision:

- reject `profile_mode` together with `tool_stack_kind != "legacy"`

This keeps Step E focused on bootstrap/runtime selection instead of pulling
native-family mutation plumbing into the same pass.

### Rule 5: Ambiguous mixed-selection inputs should fail clearly

Step E should fail early and clearly on combinations such as:

- explicit native family profile plus conflicting explicit stack kind
- explicit runtime plus conflicting auto-selection request
- `profile_mode` plus explicit `profile`

The exact exception type may follow current local conventions, but the failure
must be deterministic and easy to diagnose.

## Provenance And Metadata Expectations

Step E is not the step that invents new native profile metadata. That already
landed in Step D.

However, Step E must preserve that metadata intact when it auto-selects
family-aware stacks.

Required observable results:

- `trajectory.tool_profile_id` stays the actual profile id
- `ToolResult.metadata["family"]` remains family-aware for strict native runs
- native family `ToolView` metadata survives through the normal runtime path
- legacy runs keep their current metadata behavior

Step E does not require new trajectory fields if existing profile/tool
metadata already preserves family provenance.

## Recommended Module Changes

Primary Step E construction work should land in:

- `pycodeagent/tools/bootstrap.py`
- `pycodeagent/tools/__init__.py`
- `pycodeagent/env/coding_env.py`

Possible optional helper placement:

- internal stack-kind inference helper in `pycodeagent/tools/bootstrap.py`
- or a very small local helper in `coding_env.py` if that keeps bootstrap
  imports simpler

Step E should not move strict family canonical builders or native profile
builders out of their current modules.

## Integration Scope

Step E should update the **formal local runtime selection path** first.

That means:

- the central runtime resolution path used by local coding runs should be able
  to choose `legacy`, `native_claude`, or `native_codex`
- the default remains `legacy`

Step E does **not** need to migrate every helper, evaluation script, or test
site that currently calls `build_base_tool_runtime()` directly. Those can stay
legacy until they explicitly opt into the new family-aware path.

This is a controlled opt-in step, not a repo-wide default flip.

## Test Plan

Step E should add or update tests in four groups.

### 1. Bootstrap definition tests

- `build_native_claude_runtime()` returns a Claude-family registry, native
  Claude profile, and working `ToolRuntime`
- `build_native_codex_runtime()` returns a Codex-family registry, native Codex
  profile, and working `ToolRuntime`
- custom `profile_id` overrides are preserved
- legacy `build_base_tool_runtime()` remains unchanged

### 2. Selection and inference tests

- default resolution path still uses legacy when no stack kind is supplied
- `tool_stack_kind="native_claude"` selects the Claude family stack
- `tool_stack_kind="native_codex"` selects the Codex family stack
- explicit `build_native_claude_profile()` plus omitted runtime infers Claude
  runtime instead of legacy runtime
- explicit `build_native_codex_profile()` plus omitted runtime infers Codex
  runtime instead of legacy runtime
- explicit legacy/base profile plus omitted runtime still infers legacy runtime
- `profile_mode` with non-legacy stack kind fails clearly

### 3. End-to-end runtime smoke tests

- one Claude-family smoke run can execute through the formal local runtime
  selection path without manually assembling registry/runtime
- one Codex-family smoke run can execute through the formal local runtime
  selection path without manually assembling registry/runtime
- Codex freeform `apply_patch` still works when the runtime stack is selected
  through Step E bootstrap logic

### 4. Compatibility tests

- `build_builtin_registry()` remains unchanged
- `build_base_tool_profile()` remains unchanged
- `build_base_tool_runtime()` remains unchanged
- existing legacy default-path tests remain green
- no mixed Claude/Codex registry is introduced
- no native family stack becomes the implicit default

## Acceptance Criteria

Step E is complete only when all of the following are true:

- the repo has public `build_native_claude_runtime(...)`
- the repo has public `build_native_codex_runtime(...)`
- each new bootstrap builder assembles the correct family-specific registry,
  profile, and runtime
- the formal local runtime resolution path can explicitly select `legacy`,
  `native_claude`, or `native_codex`
- passing a native family profile without a runtime no longer silently falls
  back to the legacy runtime
- `profile_mode` remains deterministic and legacy-only unless explicitly
  expanded later
- legacy default bootstrap behavior remains unchanged
- at least one Claude-family smoke run works through the Step E bootstrap path
- at least one Codex-family smoke run works through the Step E bootstrap path

## Assumptions And Defaults

- document path is
  `docs/tool_runtime_step_e_bootstrap_registry_selection_plan.md`
- Step E is bootstrap/runtime-selection work, not canonical-tool work
- public builder naming is:
  - `build_native_claude_runtime`
  - `build_native_codex_runtime`
- separate family registries remain required
- legacy remains the default stack kind
- native-family mutation plumbing beyond Step D compatibility is still later
- repo-wide caller migration is out of scope for this step
