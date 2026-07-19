# Step A Shared Process Primitives Implementation Plan

> Archived by RC-016 on 2026-07-16. Current native-family terminology and
> policy are defined by
> [ADR-0001](../../adr/0001-native-family-runtime-boundary.md). This file is a
> historical implementation record and cannot override that decision. See this
> archive's README for provenance and replacement mapping.

> Historical status note: this implementation-driver document was written
> before the later native-only cleanup. References below to legacy builtin
> shell tools or deleted builtin modules describe the pre-cutover baseline and
> are no longer the current repository surface.

## Goal

This document defines the detailed implementation plan for **Step A: Shared
Process Primitives** from
`docs/tool_runtime_family_split_implementation_plan.md`.

The purpose of Step A is to add one shared internal process-execution layer
that can be reused by multiple tool-runtime families without becoming a
model-visible tool surface.

The practical goal is narrow:

- centralize low-level process spawning and result collection
- support both foreground and background execution
- provide stable internal request/result types
- make later `ClaudeShellRuntime` and `CodexShellRuntime` implementations
  thinner and more explicit

This step is not trying to:

- define model-visible tool schemas
- decide Claude or Codex canonical tool identity
- implement PTY or session continuation semantics
- replace the legacy builtin tool surface
- introduce approval, sandbox, or exec-policy product controls

Step A is an internal implementation substrate, not a user-facing or
model-facing tool family.

## Current Repo Baseline

The current repo already has one reusable command-execution path, but it is
not the right shape for the new family-aware runtime work.

Current baseline:

- the former `pycodeagent/tools/builtin/bash.py` defined the legacy
  `run_command` canonical tool before native-only cleanup removed that module
- 历史文件 `pycodeagent/tools/command_safety.py`（已由 RC-038 删除）
  contains:
  - legacy allowlist and denylist policy
  - structured `subprocess.run()` execution
  - stable timing and truncation helpers

Current limitations relative to Step A:

- the legacy command path is tied to the `run_command` tool contract
- it assumes argv-oriented command execution rather than shell-string runtime
  semantics
- it mixes execution with command-policy concerns
- it has no background-task abstraction
- it does not provide family-neutral internal types for new runtimes

The Step A implementation must not mutate the meaning of the legacy
`run_command` path. Legacy command safety should remain intact during the
transition.

## Design Rules

Step A must follow these rules.

### Shared Code, Not Shared Tool Identity

The new process layer exists for implementation reuse only.

It must not:

- be registered as a `CanonicalTool`
- appear in `ToolView` catalogs
- emit model-visible schemas
- appear as a tool family in observed tool catalogs

### Runtime-Family Semantics Stay Above Step A

Step A does not decide:

- whether a caller is "Claude-like" or "Codex-like"
- whether a command should be surfaced as `Bash` or `exec_command`
- whether a tool requires read-before-edit semantics
- whether a patch is a shell operation or a dedicated editing capability

Those decisions belong to later steps.

### No Policy Or Schema Logic In Step A

Step A accepts already-normalized internal execution requests.

It must not:

- validate model-visible JSON schemas
- validate `ToolView` argument structure
- enforce workspace path policy
- enforce command allowlists or denylists
- enforce family-specific runtime behavior

Step A is intentionally lower than those concerns.

### POSIX-First Execution Model

Phase 1 Step A is POSIX-first.

Assumptions:

- commands are launched via a shell binary such as `bash`
- login-shell semantics map to `-lc`
- non-login shell semantics map to `-c`

Windows-specific shell parity is explicitly deferred.

## Target Module Layout

Add one new internal module:

- `pycodeagent/tools/process_exec.py`

Step A should keep its initial implementation in a single module rather than
splitting types, registry, and helpers across many files. The goal of Step A
is to establish a stable internal boundary with the smallest possible code
surface.

The module should contain:

- internal request and result dataclasses
- the background-task registry and handle types
- one shared executor class
- low-level spawn, timeout, and output helpers

Do **not** place Step A inside `command_safety.py`. That file should remain the
legacy command-policy core for `run_command`.

## Public Internal Interfaces

Step A introduces internal interfaces that later runtime families will depend
on. These are internal Python interfaces, not model-visible schemas.

### `ProcessExecRequest`

Add a stable dataclass equivalent to:

```python
@dataclass(frozen=True)
class ProcessExecRequest:
    command: str
    cwd: Path
    shell: str = "bash"
    login: bool = False
    timeout_ms: int | None = 60_000
    output_limit_chars: int = 50_000
    env_overrides: dict[str, str] = field(default_factory=dict)
```

Field semantics:

- `command`
  - raw shell command string
  - not parsed or rewritten by Step A
- `cwd`
  - already-resolved working directory
  - Step A does not validate workspace policy
- `shell`
  - shell binary name or path
- `login`
  - `True` means execute via `[shell, "-lc", command]`
  - `False` means execute via `[shell, "-c", command]`
- `timeout_ms`
  - foreground timeout budget
  - background tasks may also use this for optional timeout enforcement
- `output_limit_chars`
  - max inline capture for foreground `stdout` and `stderr`
- `env_overrides`
  - additional environment variables merged over `os.environ`

Step A deliberately does not include:

- model-visible field names
- tool-family metadata
- background flag

Foreground and background execution must be represented by separate executor
methods rather than by a single overloaded request boolean.

### `ProcessExecResult`

Add a stable dataclass equivalent to:

```python
@dataclass(frozen=True)
class ProcessExecResult:
    stdout: str
    stderr: str
    exit_code: int | None
    duration_ms: int
    timed_out: bool = False
    spawn_error: str | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
```

Field semantics:

- `stdout` and `stderr`
  - decoded text using UTF-8 with replacement semantics
- `exit_code`
  - normal process exit code
  - `None` when no valid exit code exists because spawn failed or timeout
    handling aborted before a clean exit code was captured
- `duration_ms`
  - wall-clock runtime of the call
- `timed_out`
  - `True` only when the foreground process exceeded `timeout_ms`
- `spawn_error`
  - set when process creation failed before normal execution
- `stdout_truncated` and `stderr_truncated`
  - indicate whether inline foreground capture exceeded the configured limit

This type is for foreground execution only.

### `BackgroundTaskHandle`

Add a stable dataclass equivalent to:

```python
@dataclass(frozen=True)
class BackgroundTaskHandle:
    task_id: str
    pid: int
    output_path: Path
    started_at_ms: int
```

Field semantics:

- `task_id`
  - stable executor-local background task identifier
- `pid`
  - shell process ID at launch time
- `output_path`
  - merged background output log path
- `started_at_ms`
  - UNIX epoch milliseconds for auditability

Phase 1 deliberately returns a merged output path rather than separate stdout
and stderr paths. This keeps background-task behavior simple and aligns with
the immediate Claude Bash requirement.

### `BackgroundTaskStatus`

Add a stable dataclass equivalent to:

```python
@dataclass(frozen=True)
class BackgroundTaskStatus:
    task_id: str
    state: Literal["running", "completed", "failed", "timed_out"]
    pid: int | None
    output_path: Path
    exit_code: int | None
    started_at_ms: int
    finished_at_ms: int | None = None
    duration_ms: int | None = None
    error_message: str | None = None
```

Field semantics:

- `state`
  - `running`: process is still alive
  - `completed`: process exited normally and produced an exit code
  - `failed`: process launch failed or internal background bookkeeping failed
  - `timed_out`: background timeout enforcement killed the process
- `finished_at_ms` and `duration_ms`
  - only populated after terminal completion
- `error_message`
  - background spawn or timeout-related failure text

## Executor Interface

Add one executor class:

```python
class SharedProcessExecutor:
    def run_foreground(self, request: ProcessExecRequest) -> ProcessExecResult: ...
    def run_background(
        self,
        request: ProcessExecRequest,
        *,
        artifact_root: Path | None = None,
    ) -> BackgroundTaskHandle: ...
    def get_background_status(self, task_id: str) -> BackgroundTaskStatus: ...
```

Phase 1 does not require:

- streaming callbacks
- session continuation
- stdin write support
- PTY support

Later families may wrap or extend this class, but Step A itself should stay
minimal.

## Execution Semantics

### Command Launching

Both foreground and background execution must use shell-string semantics.

Launch rule:

- `login=False`
  - `[shell, "-c", command]`
- `login=True`
  - `[shell, "-lc", command]`

Step A must not:

- parse command text into argv tokens
- reject shell syntax
- interpret command safety policy

Those decisions belong above Step A.

### Process Group Handling

Use `subprocess.Popen` for both foreground and background execution rather than
mixing `subprocess.run` and `Popen`.

Required behavior:

- launch each shell process in its own session or process group
- on timeout, terminate the process group rather than only the parent shell

This avoids leaving child processes alive when a timed-out shell command
spawned additional subprocesses.

POSIX-first implementation rule:

- use `start_new_session=True`
- kill by process group on timeout

### Foreground Execution

Foreground execution behavior:

- capture stdout and stderr separately
- decode with UTF-8 replacement semantics
- truncate each stream independently to `output_limit_chars`
- return a `ProcessExecResult`

Foreground timeout behavior:

- if `timeout_ms` is `None`, wait until process completion
- otherwise wait until the timeout budget expires
- on timeout:
  - terminate the process group
  - escalate to kill if graceful termination fails
  - set `timed_out=True`

### Background Execution

Background execution behavior:

- launch via `Popen`
- redirect both stdout and stderr to one merged log file
- return a `BackgroundTaskHandle` immediately
- store in-memory task metadata in the executor registry

The merged log file is an audit artifact and later tool runtimes may surface
its path directly to model-visible tools.

Phase 1 background execution does not provide:

- incremental output callbacks
- output streaming to the conversation
- stdin continuation

### Background Timeout Enforcement

Background tasks may still honor `timeout_ms`.

Phase 1 decision:

- if `timeout_ms` is not `None`, start a daemon timeout watcher for the
  background task
- if the task exceeds its timeout budget:
  - terminate the process group
  - mark status as `timed_out`
  - record `finished_at_ms`, `duration_ms`, and timeout reason

This keeps `timeout_ms` meaningful for both foreground and background requests
without introducing a session continuation system.

## Background Artifact Placement

Step A needs a deterministic rule for where background log files go.

### Artifact Root Input

`run_background()` must accept `artifact_root: Path | None`.

Placement rule:

- when `artifact_root` is provided
  - write logs under `<artifact_root>/background_tasks/`
- when `artifact_root` is omitted
  - write logs under a temp fallback root:
    - `Path(tempfile.gettempdir()) / "pycodeagent-process-tasks"`

### File Naming

Use stable executor-local task IDs:

- `bg_000001`
- `bg_000002`
- ...

Output path rule:

- `<background_root>/<task_id>.log`

This yields predictable, audit-friendly background artifact names while
remaining independent of model-visible tool identities.

### ToolContext Integration

Step A itself should not depend on `ToolContext`, but later runtime-family
handlers need a straightforward way to pass an artifact root into
`run_background()`.

Required follow-on change for later steps:

- extend `ToolContext` with an optional artifact-root field, such as
  `artifact_root: Path | None = None`

Step A should document this dependency but does not need to implement the
runtime-family plumbing itself.

## Registry Semantics

The background task registry is executor-local and in-memory.

Properties:

- task records live for the lifetime of the `SharedProcessExecutor` instance
- task records are not persisted across interpreter restarts
- status is refreshed lazily when `get_background_status()` is called

Phase 1 decision:

- no automatic record pruning is required in Step A
- no task reattachment or recovery is required in Step A

This keeps the first-pass implementation small while still supporting the
required Claude Bash background behavior.

## Failure Model

Step A must support four practical failure classes.

### Spawn Failure

Examples:

- shell binary not found
- invalid working directory passed in from higher layers
- permission error when opening the background output file

Foreground:

- return `ProcessExecResult` with `spawn_error` populated

Background:

- `run_background()` should raise a structured Python exception rather than
  fabricate a running task handle

Recommendation:

- define a dedicated internal exception such as `ProcessExecError`

### Foreground Timeout

Foreground timeout must return a normal `ProcessExecResult` with:

- `timed_out=True`
- `exit_code=None`
- captured partial output if any exists

### Background Timeout

Background timeout is represented in `BackgroundTaskStatus` as:

- `state="timed_out"`
- terminal timestamps and duration populated
- timeout error message recorded

### Unknown Task Lookup

`get_background_status(task_id)` on an unknown task should raise a structured
Python exception, not return a fake status object.

## Relationship To Legacy Command Safety

Step A must coexist cleanly with the current legacy command path.

Rules:

- do not modify the behavior of legacy `run_command`
- do not move `run_command` onto the Step A executor in the same pass
- do not merge Step A into `command_safety.py`

Why:

- legacy `run_command` is policy-coupled
- Step A is intentionally policy-agnostic
- changing both at once would make the migration harder to verify

Later work may choose to reuse some helper logic between the two paths, but
Step A should begin as a clearly separate module.

## Implementation Breakdown

Step A should be implemented in a narrow, low-risk sequence. The intent is to
land one stable internal execution primitive before any family-runtime wiring
begins.

### Pass 1: Create The Internal Module Boundary

Create `pycodeagent/tools/process_exec.py` with only the core types and
executor skeleton:

- `ProcessExecRequest`
- `ProcessExecResult`
- `BackgroundTaskHandle`
- `BackgroundTaskStatus`
- `ProcessExecError`
- `SharedProcessExecutor`

This first pass should establish the API boundary and type signatures even if
some methods still contain minimal placeholder logic during development.

The first-pass objective is to make the module importable and test-addressable
without touching:

- tool registry code
- tool profile builders
- legacy builtin tool modules
- runtime trace serializers

### Pass 2: Implement Foreground Execution Fully

Fill in `SharedProcessExecutor.run_foreground()` next.

Required implementation order:

1. build shell argv from `shell`, `login`, and `command`
2. merge `env_overrides` onto `os.environ`
3. spawn via `subprocess.Popen(..., stdout=PIPE, stderr=PIPE,
   start_new_session=True)`
4. wait using `communicate()` with timeout handling
5. terminate the full process group on timeout
6. drain any remaining output after timeout handling
7. decode and truncate `stdout` and `stderr` independently
8. return a stable `ProcessExecResult`

Foreground execution should be made fully correct before any background-task
work starts. That keeps the failure surface smaller and gives the later
family-runtime work one trusted synchronous path immediately.

### Pass 3: Implement Background Execution And Registry

Once foreground execution is stable, implement:

- executor-local background task ID generation
- artifact-root resolution
- merged log-file creation
- background process spawn
- in-memory registry storage
- status lookup
- timeout watcher thread
- terminal-state finalization

This pass should still stay entirely inside `process_exec.py`. Do not split the
registry into a separate module in Step A unless the file becomes genuinely
unmanageable.

### Pass 4: Add Step A-Only Tests

Add tests that target the shared executor directly rather than going through
tool runtime adapters.

This keeps the tests aligned with the real contract of Step A:

- internal execution primitives
- not model-visible tool schemas
- not family-specific runtime formatting

### Pass 5: Stop And Verify Boundaries

At the end of Step A, stop before wiring `ClaudeShellRuntime` or
`CodexShellRuntime`.

The desired landing point is:

- the shared executor exists
- it is tested
- it is not yet exposed as a canonical tool
- no legacy path has silently changed behavior

That pause is important because it preserves a clean before/after boundary for
the next runtime-family step.

## Module Skeleton

The initial module can stay compact. A reasonable first-pass shape is:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


class ProcessExecError(RuntimeError):
    ...


@dataclass(frozen=True)
class ProcessExecRequest:
    ...


@dataclass(frozen=True)
class ProcessExecResult:
    ...


@dataclass(frozen=True)
class BackgroundTaskHandle:
    ...


@dataclass(frozen=True)
class BackgroundTaskStatus:
    ...


class SharedProcessExecutor:
    def run_foreground(self, request: ProcessExecRequest) -> ProcessExecResult:
        ...

    def run_background(
        self,
        request: ProcessExecRequest,
        *,
        artifact_root: Path | None = None,
    ) -> BackgroundTaskHandle:
        ...

    def get_background_status(self, task_id: str) -> BackgroundTaskStatus:
        ...
```

The real implementation will likely also need:

- one private mutable record type for in-flight background state
- helper functions for decoding and truncation
- helper functions for timeout termination
- helper functions for shell argv building and env merging

Those helpers should stay private to the module in Step A.

## Code-Level Decisions

The implementation should make these concrete choices so later steps do not
have to reopen them.

### Use `Popen` Everywhere

Use `subprocess.Popen` for both foreground and background execution.

Reason:

- one process primitive is easier to reason about than mixing `run()` and
  `Popen()`
- timeout handling and process-group cleanup stay consistent
- later runtime families can rely on the same execution substrate

### Decode Late

Capture raw bytes from subprocess output and decode after process completion or
timeout cleanup.

Reason:

- avoids partial text-decoder edge cases during timeout handling
- keeps truncation logic explicit and deterministic
- matches the need for exact postprocess control

### Keep Background Registry In Memory

Store task metadata in an executor-local in-memory dictionary guarded by a
lock.

Reason:

- Step A only needs single-process runtime realism
- file-backed or database-backed persistence would add complexity before the
  family runtimes need it
- background output persistence is already covered by the log file itself

### Use Daemon Threads For Timeout Watching

Background timeout enforcement should run in daemon watcher threads.

Reason:

- avoids blocking interpreter shutdown
- keeps implementation small
- is sufficient for the current local-runtime experimental scaffold

### Prefer Explicit Terminal States

Do not overload one boolean to represent background completion. Use explicit
states:

- `running`
- `completed`
- `failed`
- `timed_out`

Reason:

- later Claude-family task reporting will need clear lifecycle states
- runtime traces are easier to interpret when terminal outcome is explicit

## Tests

Step A should add focused unit tests before any family-runtime integration
tests.

### Foreground Execution Tests

- successful foreground execution returns stdout, stderr, exit code, and
  duration
- `cwd` is honored
- `shell` and `login` select the expected shell argv shape
- inline truncation sets `stdout_truncated` and `stderr_truncated` correctly
- timeout returns partial output and sets `timed_out=True`
- spawn failure populates `spawn_error`

### Background Execution Tests

- background launch returns a valid `BackgroundTaskHandle`
- merged output file is created under the provided artifact root
- fallback temp artifact root is used when no artifact root is provided
- completed background task transitions from `running` to `completed`
- background timeout transitions to `timed_out`
- unknown task lookup raises a structured error

### Architecture Boundary Tests

- Step A types are not exposed through `ToolProfile.get_exposed_specs()`
- `SharedProcessExecutor` is not registered as a canonical tool
- legacy `run_command` tests remain green without being rewritten to use Step A

## Expected File Touches

Step A should remain intentionally narrow. The expected first implementation
pass should mostly touch:

- `pycodeagent/tools/process_exec.py`
- one new test module for shared process execution
- possibly a very small import-surface update if the repo exposes internal tool
  helpers through `pycodeagent/tools/__init__.py`

Step A should not require meaningful edits to:

- `pycodeagent/tools/bootstrap.py`
- `pycodeagent/tools/profile_factory.py`
- `pycodeagent/tools/registry.py`
- existing builtin tool schemas
- trajectory serializer contracts

If implementation starts requiring many edits outside those boundaries, that is
a signal that Step A is leaking family-runtime or bootstrap concerns too early.

## Acceptance Criteria

Step A is complete only when all of the following are true:

- `pycodeagent/tools/process_exec.py` exists with the shared executor and
  internal dataclasses
- the new module supports both foreground and background process execution
- background execution writes merged output logs to deterministic artifact
  paths
- foreground execution provides stable decoded text results with truncation and
  timeout handling
- background status can be queried by task ID
- the module is not model-visible and is not a canonical tool
- legacy `run_command` behavior remains unchanged
- Step A unit tests pass

## Explicit Defaults And Deferrals

Defaults chosen for Step A:

- module path: `pycodeagent/tools/process_exec.py`
- POSIX-first shell semantics
- `bash` as the default shell
- login shell flag maps to `-lc`
- foreground stdout and stderr are captured separately
- background output is persisted as one merged log file
- background task IDs are executor-local monotonic counters
- fallback artifact root is temp-based

Explicitly deferred from Step A:

- PTY support
- session continuation
- stdin write support
- output streaming callbacks
- model-visible task-output tools
- command allowlist or denylist policy
- workspace path validation
- approval and sandbox product controls
- background task persistence across interpreter restarts

## Immediate Next Step After Step A

Once Step A is implemented and tested, the next work should be:

- wire `ClaudeShellRuntime` to `SharedProcessExecutor`
- surface `run_in_background` through `claude_bash`
- then wire `CodexShellRuntime` to the same shared executor

That sequencing keeps Step A small, verifiable, and reusable before the
family-specific runtime behaviors are introduced.
