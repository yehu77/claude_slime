# Step C Strict Source-Aligned Canonical Tool Definitions Plan

> Archived by RC-016 on 2026-07-16. Current native-family terminology and
> policy are defined by
> [ADR-0001](../../adr/0001-native-family-runtime-boundary.md). This file is a
> historical implementation record and cannot override that decision. See this
> archive's README for provenance and replacement mapping.

> Historical status note: this Step C document remains accurate about strict
> native visible tool identity. References below to coexistence with legacy
> builtins are archival landing-time context only; the later native-only
> cleanup removed that legacy surface.

## Goal

This document defines **Step C** as the canonical-tool layer that lands after
Step B runtime-family work and Step C0 native contract expansion.

The Step C goal is to represent a scoped native shell and file-edit family
subset as **strict source-aligned, visible-tools-only canonical tools**.

This means:

- use the exact native visible tool names for the scoped subset
- preserve family identity instead of flattening families into synthetic local
  names
- reuse the Step B runtimes where they already exist
- depend on Step C0 so native freeform contracts can stay freeform

This document intentionally replaces the earlier adaptation-first idea of
family-prefixed synthetic canonical naming.

## Non-Goals

Step C is not trying to:

- define the native family profile builders yet
- replace the legacy default bootstrap path
- flatten hidden runtime companions into the visible tool set
- generalize freeform schema mutation
- remove legacy builtins
- claim full product parity outside the scoped family subset

Step C is specifically about the **strict source-aligned canonical tool
definitions** for the chosen visible subset.

## Strictness Boundary

Step C uses the following strictness boundary:

- visible native tools only
- hidden or dispatch-only runtime companions are recorded as notes, not
  promoted into the Step C canonical tool set

This means:

- Claude source-native visible tool names stay visible as `Bash`, `Read`,
  `Edit`, `Write`, `Grep`, `Glob`
- Codex source-native visible tool names stay visible as `exec_command`,
  `write_stdin`, `apply_patch`
- Codex hidden or dispatch-only `shell_command` is documented as a source note
  but is not part of the Step C canonical tool set

## Source-Aligned Canonical Tool Set

Step C canonical tools are the following.

### Claude Code family

- `Bash`
- `Read`
- `Edit`
- `Write`
- `Grep`
- `Glob`

### Codex family

- `exec_command`
- `write_stdin`
- `apply_patch`

This tool set is strict source-aligned for the scoped visible subset. It is
not a mixed local abstraction layer and it is not a synthetic canonical naming
scheme.

## Registry Rule

Step C must use **separate family registries**, not one mixed registry.

This is required because source-aligned names can coexist with legacy local
names or other family-local names only when family separation is explicit.

This is especially important for:

- source-aligned Codex `apply_patch`
- legacy local builtin `apply_patch`

Required rule:

- same-name tools from different families or legacy layers must not be forced
  into one duplicate-prone mixed registry
- family metadata must be present on every Step C canonical tool

## Source Truth Categories

Step C must clearly separate three different categories of facts.

### 1. Exact source-visible schema facts

These are the fields the model can actually see in the scoped native tool
subset.

### 2. Exact source-visible behavioral facts

These are the behavior rules that are directly encoded in the native tools and
matter for realistic local runtime reproduction.

### 3. Contextual visibility notes

These are source-true conditions that change exposure without turning hidden
or config-gated differences into separate canonical tools.

Examples:

- Codex `shell_command` exists as a hidden or dispatch-only companion
- Codex `exec_command` can conditionally include fields such as `shell`,
  `login`, `environment_id`, or `additional_permissions`
- Claude `Bash` can conditionally omit `run_in_background` when background
  tasks are disabled

The Step C canonical tool set must stay source-aligned without pretending that
every conditional source field is always universally visible.

## Exact Source-Visible Schema Facts

The following are the strict Step C canonical contracts for the scoped subset.

### Claude `Bash`

Native visible name:

- `Bash`

Source-visible schema facts:

- `command: string`
- `timeout?: number`
- `description?: string`
- `run_in_background?: boolean`
- `dangerouslyDisableSandbox?: boolean`

Contextual visibility note:

- the model-facing schema omits the internal `_simulatedSedEdit`
- `run_in_background` may be conditionally omitted when Claude background
  tasks are disabled by configuration

### Claude `Read`

Native visible name:

- `Read`

Source-visible schema facts:

- `file_path: string`
- `offset?: integer`
- `limit?: integer`
- `pages?: string`

Strict decision:

- Step C keeps Claude's absolute-path-first contract rather than replacing it
  with a local relative-path abstraction

### Claude `Edit`

Native visible name:

- `Edit`

Source-visible schema facts:

- `file_path: string`
- `old_string: string`
- `new_string: string`
- `replace_all?: boolean`

Strict decision:

- Step C keeps the native `old_string` / `new_string` / `replace_all` surface

### Claude `Write`

Native visible name:

- `Write`

Source-visible schema facts:

- `file_path: string`
- `content: string`

### Claude `Grep`

Native visible name:

- `Grep`

Source-visible schema facts:

- `pattern: string`
- `path?: string`
- `glob?: string`
- `output_mode?: enum("content", "files_with_matches", "count")`
- `-B?: number`
- `-A?: number`
- `-C?: number`
- `context?: number`
- `-n?: boolean`
- `-i?: boolean`
- `type?: string`
- `head_limit?: number`
- `offset?: number`
- `multiline?: boolean`

Strict decision:

- Step C keeps the broader native `Grep` parameter surface rather than the
  earlier trimmed local subset

### Claude `Glob`

Native visible name:

- `Glob`

Source-visible schema facts:

- `pattern: string`
- `path?: string`

### Codex `exec_command`

Native visible name:

- `exec_command`

Source-style parameter surface:

- `cmd: string`
- `workdir?: string`
- `tty?: boolean`
- `yield_time_ms?: number`
- `max_output_tokens?: number`
- `shell?: string`
- `login?: boolean`
- `sandbox_permissions?: string`
- `justification?: string`
- `prefix_rule?: string[]`
- `additional_permissions?: object`
- `environment_id?: string`

Contextual visibility notes:

- `shell` is conditionally included by the source tool builder
- `login` is conditionally included when login-shell support is enabled
- `environment_id` is conditionally included in multi-environment exposure
- `additional_permissions` is conditionally included when permission approval
  features are enabled

Strict decision:

- Step C keeps the source-style parameter surface and records visibility
  conditions instead of collapsing it into a simplified local-only schema

### Codex `write_stdin`

Native visible name:

- `write_stdin`

Source-visible schema facts:

- `session_id: number`
- `chars?: string`
- `yield_time_ms?: number`
- `max_output_tokens?: number`

Strict decision:

- `write_stdin` is part of Step C and is not deferred from the strict native
  path

### Codex `apply_patch`

Native visible name:

- `apply_patch`

Source-visible schema facts:

- freeform tool
- grammar-based input contract
- lark syntax

Strict decisions:

- `apply_patch` stays freeform
- it is not wrapped as an object payload in strict Step C
- Step C depends on Step C0 so the repo can represent and dispatch freeform
  calls natively

## Exact Source-Visible Behavioral Facts

Step C must preserve the following source-visible behavioral facts for the
scoped subset.

### Claude behavior

`Bash`

- one-shot shell execution is the core behavior
- native visible schema includes `run_in_background`
- background execution is part of the visible tool contract when enabled

`Read`

- `file_path` is absolute-path-first in the native contract
- line-windowing through `offset` and `limit` is native behavior
- `pages` is part of native PDF-reading behavior

`Edit`

- read-state enforcement is part of native semantics
- edit attempts fail if the file was not read first
- edit attempts fail if the file was modified after the recorded read
- `old_string == new_string` is rejected
- non-unique matches are rejected when `replace_all` is false
- empty `old_string` on a nonexistent file is valid native creation behavior
- empty `old_string` on an existing non-empty file is rejected

`Write`

- overwriting an existing file requires prior read state
- writing fails if the file changed after it was read
- creating a new file is allowed without prior read

`Grep`

- regex-oriented search semantics are native behavior
- the broader parameter surface is operational, not decorative

`Glob`

- deterministic file pattern matching is a native visible capability

### Codex behavior

`exec_command`

- unified-exec foreground execution is the visible shell baseline
- output may return completion output or a live `session_id`
- session continuation is part of the source-visible story, not a later add-on

`write_stdin`

- writes to an existing unified-exec session
- empty `chars` acts as a poll
- non-empty `chars` continues an existing interactive command

`apply_patch`

- patch editing is a first-class visible tool
- patch editing is not modeled as generic shell usage in native source terms

## Contextual Visibility Notes

The following source facts should be documented in Step C but must not be
promoted into extra Step C canonical tools.

### Codex hidden or dispatch-only companions

- `shell_command` may still be registered as a hidden or dispatch-only shell
  companion
- it is a source fact, but not a Step C canonical tool

### Codex environment and feature gating

- native visible shell exposure depends on unified-exec availability
- some visible fields depend on runtime configuration or feature flags
- these visibility differences belong to registry/profile construction and
  metadata, not to synthetic tool renaming

### Claude conditional visibility

- native `Bash` visibility can change when background-task support is disabled
- internal-only fields omitted from the model-facing schema stay omitted in the
  strict canonical surface

## Handler Wiring Requirements

Step C canonical handlers must wire into the family runtimes and native local
semantics without collapsing family identity.

### Claude handlers

- `Bash` delegates to `ClaudeShellRuntime`
- `Read`, `Edit`, `Write`, `Grep`, and `Glob` use dedicated Claude-family
  handlers rather than legacy generic builtins renamed in place
- Claude file tools preserve read-state discipline in local runtime behavior

### Codex handlers

- `exec_command` delegates to `CodexShellRuntime`
- `write_stdin` delegates to a Codex session-continuation runtime path owned by
  the Codex family boundary
- `apply_patch` delegates to `CodexApplyPatchRuntime`

Strict rule:

- `apply_patch` canonical semantics remain separate from generic shell
  execution even if the local repo reuses helper code underneath

## Metadata Requirements

Every Step C canonical tool must carry stable family metadata.

Required metadata concepts:

- `family`
- `native_source`
- `native_visibility`
- `source_tool_name`

This is required so exact-name collisions remain safe across separate
registries and so later mutation work can distinguish source-native families.

## Step C Boundaries

Step C must not:

- invent family-prefixed synthetic final canonical names
- treat the native Codex continuation tool as outside the strict native path
- wrap strict Codex `apply_patch` in a JSON object
- use Step C itself to solve object-only contract limits

Those boundaries now belong elsewhere:

- Step B handles the runtime-family layer
- Step C0 removes object-only contract limits
- Step C defines strict source-aligned canonical tools
- later steps build native profiles, bootstrap selection, and mutation work

## Acceptance Criteria

Step C is complete only when all of the following are true:

- the repo can build a Claude strict source-aligned canonical registry with
  `Bash`, `Read`, `Edit`, `Write`, `Grep`, and `Glob`
- the repo can build a Codex strict source-aligned canonical registry with
  `exec_command`, `write_stdin`, and freeform `apply_patch`
- no strict Step C canonical tool relies on a synthetic family-prefixed final
  name
- Codex hidden `shell_command` remains documented as a source note rather than
  promoted into the Step C canonical set
- strict Step C canonical tools preserve family metadata and can coexist with
  legacy builtin names via separate family registries

## Test Plan

Require tests in the following groups.

### Definition tests

- Claude strict source-aligned tools build with the exact scoped native names
- Codex strict source-aligned tools build with the exact scoped native names
- family metadata is present on every canonical tool
- `apply_patch` is represented as freeform rather than an object-wrapped
  payload

### Runtime delegation tests

- `Bash` delegates to `ClaudeShellRuntime`
- `exec_command` delegates to `CodexShellRuntime`
- `write_stdin` delegates to the Codex continuation runtime path
- `apply_patch` delegates to `CodexApplyPatchRuntime`

### Behavioral tests

- Claude `Edit` local semantics preserve read-state and uniqueness rules
- Claude `Write` local semantics preserve read-before-overwrite rules
- Claude `Grep` preserves the broader native parameter surface
- Codex `write_stdin` behaves as session continuation rather than a new shell
  command

### Registry and compatibility tests

- separate family registries avoid name collisions with legacy builtins
- strict source-aligned Codex `apply_patch` coexists with legacy local
  `apply_patch`
- strict Step C tools are not silently injected into the legacy default path

## Assumptions And Defaults

- Step C builds on Step B runtime-family work and Step C0 contract expansion.
- Strict Step C is visible-tools-only.
- Claude tools keep source-native capitalization and names.
- Codex tools keep source-native lowercase names.
- `apply_patch` is freeform in strict Step C.
- `write_stdin` belongs to the strict native Codex path and is not deferred.
- Claude file tools keep their absolute-path-first native contract.
