# Step B Family Runtime Integration Implementation Plan

> Archived by RC-016 on 2026-07-16. Current native-family terminology and
> policy are defined by
> [ADR-0001](../../adr/0001-native-family-runtime-boundary.md). This file is a
> historical implementation record and cannot override that decision. See this
> archive's README for provenance and replacement mapping.

> Supersession note: Step B remains the valid family-runtime implementation
> step. However, its original forward edge assumed canonical tool definitions
> would come next on top of the repo's object-only tool contract. That
> assumption is now superseded. The required next step is
> `docs/tool_runtime_step_c0_native_tool_contract_expansion_plan.md`, followed
> by strict source-aligned Step C canonical tools.
>
> Historical status note: references below to leaving legacy `run_command`,
> legacy `apply_patch`, or legacy bootstrap behavior intact were landing-time
> constraints only. The later native-only cleanup removed that legacy surface.

## Goal

This document defines the detailed implementation plan for **Step B: Family
Runtime Integration** from
`docs/tool_runtime_family_split_implementation_plan.md`.

The purpose of Step B is to add the **runtime-family behavior layer** above the
shared Step A execution substrate.

The practical goal is:

- wire `ClaudeShellRuntime` onto the shared Step A process execution kernel
- wire `CodexShellRuntime` onto the shared Step A process execution kernel
- introduce `CodexApplyPatchRuntime` as a dedicated non-shell Codex runtime
  boundary
- preserve family-specific runtime behavior before Step C introduces canonical
  tool identity

This step is not trying to:

- define model-visible canonical tools
- define native family `ToolProfile` builders
- define family-specific registry builders
- land `codex_write_stdin` inside Step B itself
- introduce PTY or interactive session continuation
- migrate or replace legacy `run_command`
- migrate or replace legacy `apply_patch`

This document replaces the earlier shell-only interpretation of Step B. Even
though the filename remains
`tool_runtime_step_b_shell_runtime_integration_plan.md`, the scope here matches
the master plan: **three family runtimes**

- `ClaudeShellRuntime`
- `CodexShellRuntime`
- `CodexApplyPatchRuntime`

## Current Repo Baseline

The repo now has the shared Step A execution substrate, but it still lacks the
family runtime layer that will consume it.

Current baseline:

- [`pycodeagent/tools/process_exec.py`](../../../pycodeagent/tools/process_exec.py)
  provides:
  - `ProcessExecRequest`
  - `ProcessExecResult`
  - `BackgroundTaskHandle`
  - `BackgroundTaskStatus`
  - `ProcessExecError`
  - `SharedProcessExecutor`
- [`pycodeagent/tools/runtime.py`](../../../pycodeagent/tools/runtime.py)
  already expects canonical handlers to return final `ToolResult` objects
- [`pycodeagent/tools/context.py`](../../../pycodeagent/tools/context.py)
  provides `workspace_root` and `task`, but not yet `artifact_root`
- legacy shell behavior was concentrated in the former
  `pycodeagent/tools/builtin/bash.py` before native-only cleanup removed it
- legacy patch behavior was concentrated in the former
  `pycodeagent/tools/builtin/patch.py` before native-only cleanup removed it

Current limitations relative to Step B:

- no `ClaudeShellRuntime` exists yet
- no `CodexShellRuntime` exists yet
- no `CodexApplyPatchRuntime` exists yet
- no runtime-family shell code translates `ProcessExecResult` into stable
  `ToolResult` payloads
- no dedicated Codex patch runtime boundary exists yet
- `ToolContext` cannot yet route Claude background logs into run artifacts

The Step B implementation must not mutate the meaning of the legacy
`run_command` or legacy `apply_patch` paths. Those paths must remain intact
during this pass.

## Design Rules

Step B must follow these rules.

### Runtime Families Stay Distinct

Step B introduces three runtime families:

- `ClaudeShellRuntime`
- `CodexShellRuntime`
- `CodexApplyPatchRuntime`

They must remain separate runtime classes with separate method boundaries,
defaults, metadata, and behavior rules.

Step B must not:

- collapse Claude and Codex shell behavior into one generic runtime class
- collapse Codex patching into shell execution semantics
- collapse runtime-family metadata into one generic command contract

### Shell Runtimes Reuse Step A, Patch Runtime Does Not

Only the shell runtimes should consume `SharedProcessExecutor`:

- `ClaudeShellRuntime`
- `CodexShellRuntime`

`CodexApplyPatchRuntime` is a dedicated non-shell runtime. It must not be
forced through `SharedProcessExecutor`, because patch editing is a distinct
canonical capability boundary in the master plan.

This is the intended runtime-family split:

- shared process code for shell execution reuse
- dedicated patch code for patch semantics

### Step B Must Not Redefine Step A

Step B must not:

- push family-specific flags into `ProcessExecRequest`
- make Step A model-visible
- add family-specific state to `SharedProcessExecutor`
- introduce profile or schema logic into `process_exec.py`

Step A remains pure shared execution infrastructure.

### Final Output Of Step B Is `ToolResult`

All three runtime-family classes must return final `ToolResult` objects
directly.

This is required because:

- current `ToolRuntime` expects canonical handlers to return `ToolResult`
- trajectory recording already consumes `ToolResult`
- runtime trace emission already extracts execution metadata from `ToolResult`

Step B therefore lands the runtime-family behavior layer in a form that Step C
can later expose as canonical tools with minimal glue.

### No Legacy Policy Coupling For New Runtime Boundaries

Step B shell runtimes must not route through:

- `parse_command_argv`
- `classify_command_argv`
- legacy allowlist or denylist checks
- `run_subprocess()` from `command_safety.py`

Step B patch runtime must not be modeled as:

- a shell command
- a subprocess wrapper
- a call into `bash -c "apply patch ..."`

The new runtime-family layer can reuse implementation helpers, but must not
reuse legacy canonical tool identity or old product-shape assumptions.

### Shared Text Shape, Family-Distinct Metadata

Foreground shell output text should remain deterministic and stable across the
two shell families:

- `[stdout]`
- `[stderr]`
- `[exit code]`

Patch output text should remain deterministic and patch-specific rather than
shell-shaped.

Metadata must remain runtime-family-distinct:

- Claude shell should report `operation="claude_bash"`
- Codex shell should report `operation="codex_exec_command"`
- Codex patch should report `operation="codex_apply_patch"`

This keeps trace content stable while preserving family identity in observed
runtime outputs.

## Target Module Layout

Step B should introduce two new runtime-family modules and one shared patch
implementation module:

- `pycodeagent/tools/shell_runtimes.py`
  - `ClaudeShellRuntime`
  - `CodexShellRuntime`
- `pycodeagent/tools/patch_runtime.py`
  - `CodexApplyPatchRuntime`
- `pycodeagent/tools/patch_apply.py`
  - shared internal patch-application helpers extracted from legacy builtin
    patch code

Design intent:

- shell runtimes stay grouped because they both consume `SharedProcessExecutor`
- patch runtime stays separate because it is not a shell runtime
- low-level patch parsing and workspace mutation helpers move into a shared
  internal module so both the legacy builtin patch tool and the new Codex patch
  runtime can reuse them

Do **not** place Step B inside:

- `command_safety.py`
- `builtin/bash.py`
- `process_exec.py`
- long-term inside `builtin/patch.py`

Those files belong to other layers:

- `command_safety.py`
  - legacy shell policy and argv execution
- `builtin/bash.py`
  - legacy canonical shell tool
- `process_exec.py`
  - shared low-level shell process execution
- `builtin/patch.py`
  - legacy canonical patch tool wrapper

## Public Internal Interfaces

Step B introduces internal runtime-family interfaces that later canonical tools
will delegate to. These are internal Python interfaces, not model-visible
schemas.

### `ClaudeShellRuntime`

Add a stable internal class equivalent to:

```python
class ClaudeShellRuntime:
    def __init__(self, executor: SharedProcessExecutor | None = None) -> None:
        ...

    def execute_bash(
        self,
        command: str,
        timeout: int | float | None = None,
        run_in_background: bool = False,
        *,
        ctx: ToolContext | None = None,
    ) -> ToolResult:
        ...
```

Required interface decisions:

- inject a `SharedProcessExecutor`; do not use module-level singleton runtimes
- if no executor is provided, create one per runtime instance
- runtime instances should be long-lived and reusable
- `execute_bash()` returns a final `ToolResult`

### `CodexShellRuntime`

Add a stable internal class equivalent to:

```python
class CodexShellRuntime:
    def __init__(self, executor: SharedProcessExecutor | None = None) -> None:
        ...

    def execute_command(
        self,
        cmd: str,
        workdir: str | None = None,
        shell: str | None = None,
        login: bool | None = None,
        *,
        ctx: ToolContext | None = None,
    ) -> ToolResult:
        ...
```

Required interface decisions:

- inject a `SharedProcessExecutor`; do not use module-level singleton runtimes
- if no executor is provided, create one per runtime instance
- runtime instances should be long-lived and reusable
- `execute_command()` returns a final `ToolResult`

### `CodexApplyPatchRuntime`

Add a stable internal class equivalent to:

```python
class CodexApplyPatchRuntime:
    def apply_patch(
        self,
        patch: str,
        *,
        ctx: ToolContext | None = None,
    ) -> ToolResult:
        ...
```

Required interface decisions:

- `CodexApplyPatchRuntime` does not depend on `SharedProcessExecutor`
- `apply_patch()` returns a final `ToolResult`
- `patch` is a raw patch payload string; Step B does not yet decide the final
  model-visible argument name or whether the future Codex-facing tool is
  freeform vs wrapped

### Shared Private Helpers

`shell_runtimes.py` should include private helpers equivalent to:

- `_missing_context_error(...)`
- `_invalid_timeout_error(...)`
- `_path_policy_error_result(...)`
- `_process_exec_error_result(...)`
- `_foreground_result_to_tool_result(...)`
- `_render_foreground_output(...)`

`patch_runtime.py` should include private helpers equivalent to:

- `_missing_context_error(...)`
- `_empty_patch_error(...)`
- `_patch_error_result(...)`
- `_patch_success_result(...)`

`patch_apply.py` should contain extracted shared implementation helpers from the
legacy builtin patch path, such as:

- file-header parsing
- patch target resolution
- hunk matching
- workspace file mutation
- patch summary construction

Step B should keep these helpers private to their modules. They are runtime
integration helpers, not stable cross-repo public interfaces.

## Claude Shell Runtime Contract

`ClaudeShellRuntime.execute_bash(...)` should implement the following behavior.

### Context Requirement

Claude shell execution requires `ToolContext`.

If `ctx` is missing:

- return a structured `ToolResult` error
- set `error_type="missing_context"`
- set `stage="context_check"`
- set `operation="claude_bash"`
- set `execution_kind="command_exec"` if foreground was requested
- set `execution_kind="command_background"` if background was requested

Do not raise a raw Python exception for missing context.

### Fixed Shell Semantics

Claude shell behavior is intentionally narrow in Step B.

Execution rules:

- `cwd` is always `ctx.workspace_root`
- `shell` is always `"bash"`
- `login` is always `False`
- command text is passed through as raw shell text

This means Claude background and foreground execution both use shell-string
semantics via:

- `bash -c <command>`

Step B must not introduce Claude-side `workdir`, `shell`, or `login` controls.

### Timeout Semantics

Claude timeout behavior must use milliseconds.

Required rules:

- accepted unit is milliseconds
- default timeout is `60_000`
- accepted range is `1..600_000`
- `None` means use default `60_000`

If timeout is invalid:

- return a structured `ToolResult` error
- use `error_type="invalid_timeout"`
- use `stage="validate_input"`
- include the raw requested timeout in metadata

Step B should not silently clamp invalid timeouts.

### Foreground Execution

When `run_in_background=False`:

- build a `ProcessExecRequest` with:
  - `command=<raw command>`
  - `cwd=ctx.workspace_root`
  - `shell="bash"`
  - `login=False`
  - `timeout_ms=<validated timeout>`
- call `SharedProcessExecutor.run_foreground()`
- translate the resulting `ProcessExecResult` into a final `ToolResult`

Foreground success text must use the stable deterministic layout:

- `[stdout]`
- `[stderr]`
- `[exit code]`

### Background Execution

When `run_in_background=True`:

- build a `ProcessExecRequest` with the same shell defaults as foreground
- call `SharedProcessExecutor.run_background()`
- pass `ctx.artifact_root` through as `artifact_root`
- return a final `ToolResult` success immediately

Background success content must be deterministic and human-readable. It should
contain:

- the background task ID
- the absolute output file path
- a short instruction to use future Claude `Read` on that file

### Claude Foreground Metadata

Foreground success metadata must include at minimum:

- `operation="claude_bash"`
- `execution_kind="command_exec"`
- `execution_stage="result_finalize"`
- `command_family="claude_bash"`
- `run_in_background=False`
- `timeout_ms`
- `shell="bash"`
- `login=False`
- `workspace_root`
- `resolved_cwd`
- `exit_code`
- `duration_ms`
- `stdout_truncated`
- `stderr_truncated`

If the process timed out:

- return `ToolResult(ok=False, is_error=True, ...)`
- set `error_type="timeout"`
- keep partial rendered output in `content` when available
- preserve duration and truncation flags in metadata

If process spawn failed:

- return `ToolResult(ok=False, is_error=True, ...)`
- set `error_type="execution"`
- include `spawn_error` text in content and metadata

### Claude Background Metadata

Background success metadata must include at minimum:

- `operation="claude_bash"`
- `execution_kind="command_background"`
- `execution_stage="result_finalize"`
- `command_family="claude_bash"`
- `run_in_background=True`
- `timeout_ms`
- `shell="bash"`
- `login=False`
- `workspace_root`
- `resolved_cwd`
- `background_task_id`
- `background_output_path`
- `background_pid`
- `background_started_at_ms`

If background launch fails:

- return `ToolResult(ok=False, is_error=True, ...)`
- set `error_type="execution"`
- set `stage="execute"`
- include the underlying `ProcessExecError` message

## Codex Shell Runtime Contract

`CodexShellRuntime.execute_command(...)` should implement the following
behavior.

### Context Requirement

Codex shell execution requires `ToolContext`.

If `ctx` is missing:

- return a structured `ToolResult` error
- set `error_type="missing_context"`
- set `stage="context_check"`
- set `operation="codex_exec_command"`
- set `execution_kind="command_exec"`

Do not raise a raw Python exception for missing context.

### Working Directory Resolution

Codex shell runtime should resolve `workdir` via:

- `normalize_workdir(workdir, ctx.workspace_root)`

Required rules:

- `workdir=None` means use workspace root
- invalid working directories must return a clear `ToolResult` error
- invalid workdir errors must not raise raw exceptions to the caller

This intentionally reuses the existing workspace-boundary validation logic
without reusing legacy argv command-policy logic.

### Shell And Login Defaults

Codex shell behavior is more configurable than Claude shell in Step B.

Execution rules:

- `shell or "bash"`
- `login if provided else True`
- command text is passed through as raw shell text

This means the default Codex execution path is:

- `bash -lc <cmd>`

Step B must not add `yield_time_ms`, `tty`, or session continuation semantics.

### Foreground-Only Phase 1 Behavior

Codex shell runtime always runs in the foreground in Step B.

Required rules:

- no background mode
- no task handles
- no stdin continuation
- no session registry

Background or interactive continuation belongs to later phases.

### Codex Metadata

Codex foreground success metadata must include at minimum:

- `operation="codex_exec_command"`
- `execution_kind="command_exec"`
- `execution_stage="result_finalize"`
- `command_family="codex_exec_command"`
- `shell`
- `login`
- `workspace_root`
- `resolved_cwd`
- `exit_code`
- `duration_ms`
- `stdout_truncated`
- `stderr_truncated`

If the process timed out:

- return `ToolResult(ok=False, is_error=True, ...)`
- set `error_type="timeout"`
- keep partial rendered output in `content` when available

If the process spawn failed:

- return `ToolResult(ok=False, is_error=True, ...)`
- set `error_type="execution"`
- include `spawn_error` text in content and metadata

If workdir validation fails:

- return `ToolResult(ok=False, is_error=True, ...)`
- set `stage="validate_cwd"`
- preserve the `PathPolicyError.error_type`
- include `requested_workdir` in metadata

## Codex Apply Patch Runtime Contract

`CodexApplyPatchRuntime.apply_patch(...)` should implement the following
behavior.

### Context Requirement

Codex patch execution requires `ToolContext`.

If `ctx` is missing:

- return a structured `ToolResult` error
- set `error_type="missing_context"`
- set `stage="context_check"`
- set `operation="codex_apply_patch"`
- set `execution_kind="patch_apply"`

Do not raise a raw Python exception for missing context.

### Dedicated Patch Path

Codex patch runtime must remain separate from shell execution.

Required rules:

- do not route patch application through `bash`
- do not call `SharedProcessExecutor`
- do not model patch application as command execution metadata
- do reuse shared internal patch parsing and file-mutation helpers extracted
  from the legacy builtin patch path

This is the key Step B runtime-family boundary beyond the two shell runtimes.

### Patch Input

Required rules:

- patch payload is a raw string
- empty or whitespace-only patch payload returns a structured validation error
- Step B does not yet decide whether the future model-visible Codex tool is
  freeform or wrapped

The internal runtime method should accept the minimal shape:

- `patch: str`

### Shared Patch Implementation Reuse

Step B should extract the pure patch-application core from the former legacy
patch module into [`pycodeagent/tools/patch_apply.py`](../../../pycodeagent/tools/patch_apply.py).

The extracted shared implementation should cover:

- parsing unified diff headers
- collecting patch targets
- resolving writable workspace targets
- applying hunks to files
- producing patch operation summaries

Then both:

- legacy `_apply_patch_handler(...)`
- `CodexApplyPatchRuntime.apply_patch(...)`

should become thin wrappers that build their own `ToolResult` metadata
envelopes around the same shared patch core.

### Codex Patch Success Metadata

Codex patch success metadata must include at minimum:

- `operation="codex_apply_patch"`
- `execution_kind="patch_apply"`
- `execution_stage="result_finalize"`
- `policy_domain="filesystem"`
- `policy_decision="allow"`
- `workspace_root`
- `resolved_target_paths`
- `target_files`
- `file_operations`
- `patch_applied=True`
- `content_delta_kind="patch"`
- `hunks_applied`

The metadata shape should stay close enough to legacy patch success metadata
that downstream patch analytics remain stable, while still using a family-aware
operation name.

### Codex Patch Failure Cases

`CodexApplyPatchRuntime` must translate these cases into structured
`ToolResult` errors:

- missing context
- empty patch payload
- workspace path policy violations
- patch parse or hunk-application failures
- unexpected runtime-layer exceptions

Required failure metadata policy:

- empty patch
  - `error_type="empty_diff"`
  - `stage="validate_input"`
- path policy error
  - preserve `PathPolicyError.error_type`
  - use `stage="validate_target"` when appropriate
- patch apply failure
  - `error_type="patch_apply"`
  - `stage="handler_execution"`
- unexpected failure
  - `error_type="patch_unexpected"`
  - `stage="handler_execution"`

## Shared Result Construction Rules

Step B should make result construction explicit so all runtime families remain
consistent where they should, and distinct where they must.

### Foreground Shell Content Rendering

Use one shared private helper inside `shell_runtimes.py` for rendering
foreground command output.

Rendering rules:

- include `[stdout]` only if stdout is non-empty
- include `[stderr]` only if stderr is non-empty
- include `[exit code]` only if exit code is not `None`
- join sections with newline separators

This rendering should match the current legacy subprocess output shape closely
enough to preserve trace stability.

### Metadata Envelope

All three runtime families should build metadata via
`build_execution_metadata(...)` from
[`pycodeagent/tools/execution_contract.py`](../../../pycodeagent/tools/execution_contract.py).

Required metadata policy:

- keep `operation` runtime-family-specific
- keep `execution_kind` aligned with shell foreground, shell background, or
  patch apply
- keep `execution_stage` stable as `context_check`, `validate_input`,
  `validate_cwd`, `validate_target`, `execute`, `handler_execution`, or
  `result_finalize`

This ensures runtime trace emission continues to work with minimal change.

### Error Translation

Step B must translate these failure sources into structured `ToolResult`
errors:

- missing `ToolContext`
- invalid Claude timeout
- `PathPolicyError`
- shell foreground timeout
- shell background launch failure
- shell foreground spawn failure
- patch application failure
- unexpected runtime-layer exceptions

Do not leak raw exceptions through the runtime-family interfaces.

## Context And Environment Plumbing

Step B must route artifact roots into Claude background execution.

### `ToolContext` Extension

Extend [`pycodeagent/tools/context.py`](../../../pycodeagent/tools/context.py) with:

```python
artifact_root: Path | None = None
```

Required rules:

- default must remain `None`
- no other `ToolContext` semantics should change
- task-level file constraint behavior must remain intact

### Environment Wiring

Update the local runtime environment path that constructs `ToolContext` so it
sets:

- `artifact_root=output_dir`

This allows Claude background logs to land under:

- `<output_dir>/background_tasks/<task_id>.log`

The key implementation location is the local runtime path in
[`pycodeagent/env/coding_env.py`](../../../pycodeagent/env/coding_env.py) where the
workspace `ToolContext` is created for a run.

## Registry And Bootstrap Boundaries

Step B must stop before canonical tool and profile integration.

Required deferrals:

- no `CanonicalTool` definitions for `claude_bash`
- no `CanonicalTool` definitions for `codex_exec_command`
- no `CanonicalTool` definitions for `codex_apply_patch`
- no `build_native_claude_profile()`
- no `build_native_codex_profile()`
- no family-specific bootstrap entrypoints
- no family-specific registry builders

Why:

- Step B is only about runtime-family behavior
- canonical identity belongs to the next implementation layer
- stopping here preserves a clean boundary for Step C

## Implementation Breakdown

Step B should be implemented in a narrow, low-risk sequence.

### Pass 1: Add Runtime Module Skeletons

Create:

- `pycodeagent/tools/shell_runtimes.py`
- `pycodeagent/tools/patch_runtime.py`

with:

- `ClaudeShellRuntime`
- `CodexShellRuntime`
- `CodexApplyPatchRuntime`
- private helper skeletons for content rendering, metadata, and error results

### Pass 2: Extract Shared Patch Core

Extract the low-level patch parsing and application helpers out of
`builtin/patch.py` into:

- `pycodeagent/tools/patch_apply.py`

The first objective is to make the shared patch implementation reusable without
changing legacy patch semantics.

### Pass 3: Implement Shared Shell Result Helpers

Implement:

- shared shell foreground content renderer
- shared helper for translating `ProcessExecResult`
- shared helper for structured shell execution errors
- shared helper for `PathPolicyError` translation in shell runtimes

### Pass 4: Implement `ClaudeShellRuntime`

Implement:

- timeout validation
- foreground execution path
- background execution path
- metadata construction
- background task success message

### Pass 5: Implement `CodexShellRuntime`

Implement:

- workdir validation
- shell/login defaults
- foreground execution path
- metadata construction

### Pass 6: Implement `CodexApplyPatchRuntime`

Implement:

- empty-patch validation
- missing-context handling
- shared patch-core invocation
- family-aware metadata construction
- family-aware success and failure text

### Pass 7: Add `ToolContext` Artifact Root Plumbing

Implement:

- `artifact_root` on `ToolContext`
- `artifact_root=output_dir` in local runtime environment setup

### Pass 8: Add Step B Tests

Add:

- `tests/test_shell_runtimes.py`
- `tests/test_patch_runtime.py`

and any narrow compatibility smoke coverage needed through `ToolRuntime`.

### Pass 9: Verify Legacy Isolation

Before closing Step B, verify:

- `build_builtin_registry()` remains unchanged
- `build_base_tool_profile()` remains unchanged
- legacy `run_command` tests still pass
- legacy `apply_patch` tests still pass

## Tests

Step B should add focused unit tests before any family-profile integration
tests.

### Claude Runtime Tests

- Claude foreground command success returns deterministic content and metadata
- Claude foreground timeout returns `error_type="timeout"`
- Claude background execution writes under
  `ctx.artifact_root/background_tasks/`
- Claude background result includes task id and output path
- Claude shell accepts real shell syntax such as pipes or shell composition,
  proving it does not use argv parsing
- Claude missing-context and invalid-timeout errors return structured
  `ToolResult`s

### Codex Shell Runtime Tests

- Codex `workdir` resolves inside workspace
- invalid Codex `workdir` is rejected with `stage="validate_cwd"`
- Codex default `login=True` and explicit `login=False` produce different shell
  argv behavior, validated with a fake shell script
- Codex custom `shell` is passed through to `SharedProcessExecutor`
- Codex spawn failures become structured `ToolResult` errors
- Codex missing-context errors return structured `ToolResult`s

### Codex Patch Runtime Tests

- Codex patch success modifies files through the dedicated patch path
- empty patch payload returns `error_type="empty_diff"`
- missing context returns `error_type="missing_context"`
- path-policy violations are preserved through structured error metadata
- patch application failures return `error_type="patch_apply"`
- patch success metadata preserves patch summary fields such as target files and
  hunks applied

### Context And Wiring Tests

- `ToolContext` accepts `artifact_root`
- `coding_env` populates `artifact_root` from `output_dir`
- Claude background output paths use the run artifact root when present

### Compatibility Smoke Tests

Add compatibility-style smoke coverage that:

- wraps one shell runtime method in a temporary `CanonicalTool`
- wraps `CodexApplyPatchRuntime.apply_patch(...)` in a temporary `CanonicalTool`
- executes through `ToolRuntime`
- verifies returned metadata survives the normal runtime and trajectory path

### Legacy Isolation Tests

- `build_builtin_registry()` remains unchanged
- `build_base_tool_profile()` remains unchanged
- legacy `run_command` tests remain green
- legacy `apply_patch` tests remain green

## Acceptance Criteria

Step B is complete only when all of the following are true:

- `pycodeagent/tools/shell_runtimes.py` exists with both shell runtime-family
  classes
- `pycodeagent/tools/patch_runtime.py` exists with `CodexApplyPatchRuntime`
- `pycodeagent/tools/patch_apply.py` exists with extracted shared patch
  implementation helpers
- both shell runtime classes consume `SharedProcessExecutor`
- `CodexApplyPatchRuntime` exists as a dedicated non-shell runtime-family
  boundary
- Claude foreground and background shell behavior both return stable
  `ToolResult` payloads
- Codex foreground shell behavior returns stable `ToolResult` payloads
- Codex patch behavior returns stable `ToolResult` payloads through a dedicated
  patch path
- Claude background execution routes logs through `ctx.artifact_root` when
  available
- `ToolContext` supports `artifact_root`
- local runtime environment wiring populates `ToolContext.artifact_root` from
  `output_dir`
- runtime-family metadata is preserved through the existing trace-facing
  `ToolResult` contract
- no canonical tool definitions or family profiles were introduced in the same
  pass
- legacy builtin registry/profile behavior remains unchanged
- Step B unit tests pass

## Expected File Touches

Step B should remain intentionally narrow. The expected implementation pass
should mostly touch:

- `pycodeagent/tools/shell_runtimes.py`
- `pycodeagent/tools/patch_runtime.py`
- `pycodeagent/tools/patch_apply.py`
- `pycodeagent/tools/context.py`
- `pycodeagent/env/coding_env.py`
- `pycodeagent/tools/builtin/patch.py`
- new runtime-family test modules

Step B should not require meaningful edits to:

- builtin canonical shell tool definitions
- `pycodeagent/tools/bootstrap.py`
- `pycodeagent/tools/profile_factory.py`
- mutation samplers or transformed profile builders

## Explicit Defaults And Deferrals

Defaults chosen for Step B:

- document language: English only
- shell runtime module path: `pycodeagent/tools/shell_runtimes.py`
- patch runtime module path: `pycodeagent/tools/patch_runtime.py`
- shared patch implementation module path: `pycodeagent/tools/patch_apply.py`
- Step B scope: three family runtimes
- Claude default shell behavior: `bash -c`
- Codex default shell behavior: `bash -lc`
- Claude timeout unit: milliseconds
- Claude timeout default: `60_000`
- Claude timeout accepted range: `1..600_000`
- Codex timeout source: Step A `ProcessExecRequest` default
- foreground shell output text format: `[stdout]`, `[stderr]`, `[exit code]`
- patch runtime path: dedicated non-shell patch apply path
- runtime metadata envelope: `build_execution_metadata(...)`

Explicitly deferred from Step B:

- model-visible canonical tool definitions
- native Claude and Codex profile builders
- family-specific registry builders
- family-specific bootstrap entrypoints
- `codex_write_stdin` implementation inside Step B itself; strict Step C still
  includes it in the native Codex visible tool set
- PTY and session continuation fidelity
- approval and sandbox product controls
- replacement of legacy `run_command`
- replacement of legacy `apply_patch`

## Immediate Next Step After Step B

Once Step B is implemented and tested, the next work should be:

- land Step C0 native tool contract expansion
- then add strict source-aligned canonical tools on top of the expanded
  contract
- then add family-specific native profile builders
- then wire those native profiles into family-aware bootstrap paths

That sequencing preserves the intended architecture:

- Step A
  - shared process execution
- Step B
  - runtime-family shell and patch behavior
- Step C0
  - native tool contract expansion
- Step C
  - canonical tool identity and family-aware profile exposure
