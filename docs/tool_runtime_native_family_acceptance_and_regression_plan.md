# Tool Runtime Native Family Acceptance And Regression Plan

## Status

As of July 1, 2026, the repository mainline is already **native-family-only**.

That means older references to a later "legacy demotion" phase are now purely
historical. The legacy follow-up document is archival and has been superseded
by the implemented native-only cleanup.

## Goal

This document is the **active next-phase plan** after the Step A-F family-split
implementation mainline.

The goal is to move the landed native-family runtime path from
"implemented in code" to **accepted, regression-covered, and stable enough to
be treated as the repo's validated native-family path**.

This follow-up is specifically about:

- keeping the family-split runtime surface green
- auditing runtime-observed and training-prep artifacts for drift
- running small truthful acceptance tasks on top of the landed native stacks
- turning fixture and golden updates into an explicit, reviewable procedure

It should be read as the acceptance and stabilization driver for:

- shared process/runtime contracts
- strict source-aligned canonical tools
- native family profiles
- family-aware runtime selection
- native-family mutation and runtime-observed export

## Non-Goals

This follow-up does **not**:

- introduce new canonical tools
- redesign the Step A-F architecture
- change strict native tool names
- reintroduce a legacy default path
- reopen the archived legacy-demotion planning track
- claim full real-provider parity for every strict native contract

The remaining work in this document is acceptance, regression, and artifact
stabilization for the native-only path.

## Current Baseline

The post-Step-F baseline is already landed in the repo.

That baseline includes:

- shared process primitives
- family runtimes for Claude shell, Codex shell, Codex patch, and Codex
  `write_stdin`
- strict source-aligned canonical tool families
- native family profiles:
  - `native_claude`
  - `native_codex`
- family-aware bootstrap/runtime selection
- native-family mutation/runtime-observed integration
- freeform local/fake/runtime-observed support for Codex `apply_patch`

At this stage, the core question is no longer "what should the design be?"
The core question is:

> Is the landed native-family path stable, regression-covered, and truthful
> enough to use as the acceptance baseline for later cleanup and broader
> experiments?

## Acceptance Surface

The following public entrypoints define the acceptance surface for this
follow-up:

- `build_native_claude_runtime(...)`
- `build_native_codex_runtime(...)`
- `build_native_claude_profile(...)`
- `build_native_codex_profile(...)`
- `run_coding_task(..., tool_stack_kind=...)`
- `run_toolview_mutation_data_generation(..., tool_stack_kind=...)`

Acceptance in this document means those entrypoints continue to work with the
family-aware contract and produce stable traces, manifests, and
runtime-observed outputs.

## Acceptance Matrix

The acceptance work is split into three layers.

### 1. Local deterministic regression

This is the required always-green layer for the landed Step A-E surfaces.

Primary regression coverage:

- `tests/test_process_exec.py`
- `tests/test_shell_runtimes.py`
- `tests/test_patch_runtime.py`
- `tests/test_step_c0_tool_contracts.py`
- `tests/test_strict_family_tools.py`
- `tests/test_tools_bootstrap.py`
- `tests/test_tool_stack_selection.py`
- `tests/test_native_profile_transform.py`
- `tests/test_profile_sampler.py`
- `tests/test_schema_following_sample.py`

This layer should verify:

- shared execution primitives still behave deterministically
- Claude and Codex runtime-family behavior remains distinct
- strict canonical builders still expose the intended native tool families
- native profiles remain source-aligned and contract-aware
- freeform Codex `apply_patch` still survives local runtime dispatch
- bootstrap/runtime selection does not silently fall back to legacy

### 2. Runtime-observed and golden regression

This is the required always-green layer for the Step F data path.

Primary regression coverage:

- `tests/test_schema_following_from_runtime.py`
- `tests/test_schema_following_from_runtime_golden.py`
- `tests/test_runtime_observed_postrun.py`
- `tests/test_runtime_observed_postrun_golden.py`
- `tests/test_runtime_observed_training_prep_golden.py`
- `tests/test_toolview_mutation_data_generation.py`
- `tests/test_runtime_execution_reconciliation.py`

This layer should verify:

- native-family runtime-observed exports preserve family metadata
- `contract_kind` and `input_format` survive profile export and training-prep
- strict Codex freeform `apply_patch` remains freeform in observed artifacts
- serializer output remains stable enough for fixture-backed tests
- runtime-observed summaries and manifests remain consistent with the landed
  family-aware path

### 3. Small real-provider mini acceptance

This is the truth-check layer for the local runtime under a real provider.

Scope decision:

- `native_claude` real-provider mini acceptance is **in scope**
- `native_codex` real-provider acceptance is **not yet in scope** for the
  full strict path

Reason:

- the current OpenAI-compatible native client path is still function-only for
  provider transport
- strict Codex `apply_patch` is freeform
- that means the current real-provider transport cannot yet truthfully execute
  the full strict native Codex tool family end to end

This is an explicit transport limitation, not an accidental omission.

## Regression Suites And Fixture Ownership

The regression owner for this follow-up is the family-aware local runtime
path, including runtime-observed bundles and training-prep fixtures.

Fixture-backed directories that must be treated as owned acceptance artifacts:

- `tests/fixtures/runtime_observed_dataset_bundle`
- `tests/fixtures/runtime_observed_dataset_bundle_mutated`
- `tests/fixtures/runtime_observed_dataset_bundle_tool_reorder`
- `tests/fixtures/runtime_observed_study_bundle`
- `tests/fixtures/runtime_observed_training_prep_bundle`

Fixture-backed regression means:

- drift must fail loudly
- fixture refresh is never treated as a blind mechanical update
- profile-manifest, runtime-observed, serializer, and training-prep changes
  must be reviewed together

## Real-Provider Mini Acceptance

### Native Claude

`native_claude` should run a small real-provider acceptance pack on top of the
existing provider configuration flow.

Recommended task count:

- 1 to 3 small repo tasks

Recommended task shapes:

- one read-only smoke task
- one small single-file inspect/edit/verify task
- one small search-and-fix task that touches Claude-native `Read` / `Edit` /
  `Write` / `Grep` / `Glob` behavior

Recommended execution path:

- use the real-provider config already loaded by the repo
- call `run_coding_task(..., tool_stack_kind="native_claude")`
- store artifacts under a dedicated native-Claude acceptance output root

Minimum acceptance expectations:

- the run starts and completes through the strict Claude family stack
- observed traces show strict Claude visible tool names
- family-aware metadata survives the normal runtime path
- no silent fallback to legacy tool exposure occurs

### Native Codex

`native_codex` acceptance in this follow-up remains:

- local
- fake-client
- runtime-observed

Recommended task count:

- 1 to 3 small repo tasks

Recommended task shapes:

- one `exec_command` foreground task
- one `exec_command` plus `write_stdin` continuation task
- one `apply_patch` repo-fix task through the strict freeform local path

Current blocked real-provider note:

- strict real-provider Codex acceptance is blocked by the current
  function-only provider tool transport for freeform `apply_patch`
- this follow-up should record that block explicitly and keep local/fake
  acceptance green rather than faking parity

## Fixture Refresh Policy

Fixture refresh is in scope for this follow-up, but only under a strict audit
procedure.

Required refresh procedure:

1. Run the relevant targeted regression suite first and confirm the failure is
   real fixture drift rather than an unrelated test or environment issue.
2. Identify the drift class before updating files:
   - runtime behavior change
   - metadata change
   - serializer change
   - manifest/count change
   - path-normalization or portability fix
3. Refresh fixtures only after the drift source is understood and judged
   intentional.
4. Re-run the same golden/fixture suite immediately after refresh.
5. Re-run the broader acceptance regression surface before closing the change.

Fail-loud rules:

- unexplained drift is a blocker
- bulk fixture rewrites without diff review are not acceptable
- if a fixture update changes family metadata, contract kind, or freeform
  rendering, that change must be called out explicitly in the change summary

## Stabilization Exit Criteria

The native-family path is considered **stabilized** only when all of the
following are true:

- local deterministic regression for the Step A-E surface is green
- runtime-observed and golden regression for the Step F data path is green
- fixture-backed bundles are either unchanged or refreshed with explicit audit
- `build_native_claude_runtime(...)` and `build_native_codex_runtime(...)`
  remain usable entrypoints
- `build_native_claude_profile(...)` and `build_native_codex_profile(...)`
  remain the public native-profile entrypoints
- `run_coding_task(..., tool_stack_kind="native_claude")` and
  `run_coding_task(..., tool_stack_kind="native_codex")` complete at least one
  repo-task acceptance flow each
- `run_toolview_mutation_data_generation(..., tool_stack_kind=...)` remains
  green for both native families
- native Claude completes a small real-provider mini acceptance pack
- native Codex completes local/fake/runtime-observed acceptance for the strict
  family stack, including `write_stdin` and freeform `apply_patch`
- the current provider-transport limitation for strict Codex freeform
  `apply_patch` is documented as an open transport constraint rather than
  hidden by a partial claim

## Recommended Execution Order

The acceptance work should run in this order:

1. Keep the local deterministic Step A-E regression surface green.
2. Keep the runtime-observed/golden Step F regression surface green.
3. Run the native Claude real-provider mini acceptance pack.
4. Run the native Codex local/fake/runtime-observed acceptance pack.
5. Refresh fixtures only when drift is understood and intentional.
6. Call the native-family path stabilized only after the exit criteria above
   are satisfied.

## Status Rule

This is the **active** follow-up plan after Step F.

The archived legacy-demotion document should now be read only as historical
sequencing context. It is not a still-pending gate for current work.
