# Local Agent Runtime Maturation Plan

## Goal

This document defines a concrete maturation plan for the existing repo-owned
local agent runtime in `pycodeagent`.

The goal is not to build a full Codex clone, a product-grade TUI, or a
production sandbox. The goal is to evolve the current local runtime into a
more mature, white-box, schema-controllable coding-agent runtime that can:

1. expose controlled `ToolView` schemas to the model
2. execute real canonical backend tools
3. record a detailed, auditable runtime trace
4. generate downstream training-ready artifacts through the existing
   serializer / loss-mask / training-prep stack

This plan intentionally treats the local runtime as its own mainline. It does
not require unifying the local runtime with the multi-agent raw-trace scaffold.

## Scope Boundary

In scope:

- improving the existing local text-mode agent loop
- adding trace-first runtime recording
- hardening tool contracts and tool execution boundaries
- expanding the builtin canonical tool set in a controlled way
- making the runtime easier to use for schema-following data generation

Out of scope for this plan:

- rebuilding the repo around the external-agent scaffold
- TUI / CLI product polish
- plugin ecosystems
- reproducing all of `codex-rs`
- production-grade multi-OS sandboxing
- large benchmark campaigns

## Current Local Runtime

The current repo already has a real MVP local runtime:

- `pycodeagent/env/task.py`
  - `CodingTask` task contract
- `pycodeagent/agent/prompt.py`
  - system prompt and `<tools>` rendering
- `pycodeagent/agent/parser.py`
  - text-mode assistant and tool-call parser
- `pycodeagent/agent/stopping.py`
  - minimal stop rules
- `pycodeagent/agent/runner.py`
  - multi-turn agent loop
- `pycodeagent/tools/spec.py`
  - `CanonicalTool -> ToolView -> ToolAdapter -> ToolProfile`
- `pycodeagent/tools/runtime.py`
  - exposed-call resolution, argument mapping, canonical handler execution
- `pycodeagent/tools/bootstrap.py`
  - builtin registry + base profile assembly
- `pycodeagent/trajectory/schema.py`
  - run-time trajectory contract
- `pycodeagent/trajectory/recorder.py`
  - run artifact persistence
- `pycodeagent/env/coding_env.py`
  - workspace prep, verifier, diff, reward orchestration

This means the local runtime already supports:

1. task input
2. model-visible tool rendering
3. assistant tool-call parsing
4. exposed-call to canonical-tool mapping
5. real tool execution
6. tool-result reinjection
7. complete trajectory recording

The main weakness is not lack of a runtime. The weakness is that the runtime
is still trajectory-first instead of trace-first, and its tool/command
boundaries are not yet recorded richly enough for downstream research use.

## Design Principle

The local runtime should continue to center this abstraction:

```text
CanonicalTool -> ToolView -> ToolAdapter -> ToolRuntime
```

Interpretation:

- `CanonicalTool`
  - stable backend capability
- `ToolView`
  - model-visible schema for the current run
- `ToolAdapter`
  - mapping from exposed arguments to canonical arguments
- `ToolRuntime`
  - actual execution boundary

The runtime should train and evaluate schema following against `ToolView`,
while keeping backend semantics stable in canonical tools.

## Why Reference `codex-rs`

`codex-rs` should be treated as an industrial reference implementation, not as
something to copy wholesale.

The most useful reference areas are:

- `codex-rs/rollout-trace/`
  - append-only trace writing
  - payload indirection
  - dispatch lifecycle recording
- `codex-rs/protocol/src/dynamic_tools.rs`
  - explicit tool spec / tool call / tool response contracts
- `codex-rs/shell-command/`
  - shell command parsing and safety layering
- `codex-rs/file-system/`, `codex-rs/file-search/`, `codex-rs/apply-patch/`
  - mature tool input/output boundaries

The runtime should borrow these ideas:

1. append-only event logging
2. payload refs for large request/response blobs
3. explicit tool dispatch start/end events
4. stronger command/tool execution contracts

It should not borrow:

1. TUI architecture
2. thread store / state DB
3. plugin system
4. full sandbox stack
5. remote-control infrastructure

## Target End State

After this maturation plan, the local runtime should be able to run a coding
task and emit:

```text
task
  -> workspace materialization
  -> visible ToolView rendering
  -> model request
  -> assistant parse result
  -> tool-call validation
  -> exposed->canonical mapping
  -> tool execution
  -> tool result reinjection
  -> turn stop decision
  -> append-only runtime trace
  -> trajectory
  -> downstream serializer / training-prep
```

The important identity is:

- white-box
- repo-owned
- schema-controllable
- trace-first
- training-data-oriented

## Maturation Phases

### Phase 1: Add Trace-First Runtime Recording

This is the highest-priority upgrade.

#### Objective

Keep the current local runtime logic, but record a detailed append-only trace
for every run.

#### New Artifacts

Under each local run directory, add:

- `runtime_trace_manifest.json`
- `runtime_trace.jsonl`
- `payloads/*.json`

Keep existing artifacts:

- `trajectory.json`
- `tool_profile.json`
- `verifier.json`
- `final.patch`

#### New Python Module

Add:

- `pycodeagent/runtime_trace/`

Suggested files:

- `pycodeagent/runtime_trace/schema.py`
- `pycodeagent/runtime_trace/writer.py`
- `pycodeagent/runtime_trace/payloads.py`

#### Suggested Trace Event Types

Minimum event types:

1. `run_started`
2. `workspace_materialized`
3. `tool_profile_exposed`
4. `turn_started`
5. `model_request_built`
6. `model_response_received`
7. `assistant_parse_completed`
8. `tool_call_validation_completed`
9. `tool_call_mapping_completed`
10. `tool_execution_started`
11. `tool_execution_completed`
12. `tool_execution_failed`
13. `tool_result_appended`
14. `turn_stop_decision`
15. `run_completed`

#### Per-Tool-Call Minimum Record

Each tool call should preserve both views:

```json
{
  "tool_view_id": "base::turn_2",
  "exposed_call": {
    "name": "read_file",
    "arguments": {
      "path": "main.py"
    }
  },
  "canonical_call": {
    "name": "file.read",
    "arguments": {
      "path": "main.py"
    }
  },
  "validation": {
    "schema_valid": true,
    "mapping_valid": true
  }
}
```

#### Large Payload Strategy

Follow the `codex-rs/rollout-trace/src/writer.rs` idea:

- small event metadata stays inline in JSONL
- large payloads go into `payloads/`
- trace events reference payload IDs and relative file paths

Examples of payload-worthy objects:

- rendered request messages
- full tool specs
- raw model response text
- shell stdout/stderr for large outputs

#### Existing Files To Modify

- `pycodeagent/agent/runner.py`
  - emit trace events during the loop
- `pycodeagent/tools/runtime.py`
  - expose richer execution metadata to the trace writer
- `pycodeagent/trajectory/recorder.py`
  - optionally persist runtime trace bundle beside trajectory artifacts
- `pycodeagent/env/coding_env.py`
  - initialize trace writer at run start and finalize at run end

#### Exit Criteria

One local toy task run should produce:

- valid `trajectory.json`
- valid `runtime_trace.jsonl`
- visible tool profile snapshot in the trace
- model request/response payload refs
- one or more tool-call lifecycle events

### Phase 2: Harden Tool Contracts And Results

After trace recording exists, improve tool quality.

#### Objective

Make builtin tools more uniform, structured, and auditable.

#### Current Situation

Current `ToolRuntime` returns `ToolResult`, but individual handlers are still
allowed to be relatively loose.

#### Target Contract

Every canonical tool should have:

1. stable canonical name
2. explicit canonical JSON schema
3. predictable structured `ToolResult.metadata`
4. consistent failure modes

#### Suggested ToolResult Metadata Standards

Examples:

- file tools
  - `resolved_path`
  - `bytes_read`
  - `bytes_written`
  - `workspace_relative_path`
- shell tools
  - `command`
  - `cwd`
  - `exit_code`
  - `timeout_ms`
  - `duration_ms`
- patch tools
  - `target_files`
  - `patch_applied`
  - `hunks_applied`

#### Existing Files To Modify

- `pycodeagent/tools/runtime.py`
  - standardize failure reporting
- builtin tool files under `pycodeagent/tools/builtin/`
  - return richer metadata

#### Exit Criteria

All builtin tools should return:

- deterministic `ToolResult.content`
- structured metadata adequate for tracing and debugging

### Phase 3: Expand Builtin Canonical Tools Carefully

Do not optimize for quantity first. Optimize for coverage of common coding
agent actions.

#### Recommended First Expansion Set

Priority order:

1. `file.write`
2. `file.create`
3. `search.regex`
4. `git.diff`
5. `git.status`
6. `python.run`

Potential later additions:

7. `file.move`
8. `file.delete` (dangerous; likely gated)
9. `test.run`
10. `lint.run`

#### Implementation Rule

Every new canonical tool must add:

1. canonical schema
2. builtin handler
3. base ToolView
4. trace metadata standard
5. tests

#### Existing Files To Modify

- `pycodeagent/tools/builtin/`
- `pycodeagent/tools/builtin/__init__.py`
- `pycodeagent/tools/profile_factory.py`
- tests under `tests/`

#### Exit Criteria

The local runtime should handle a realistic small bug-fix loop using:

- listing files
- reading files
- searching code
- editing/applying patch
- running commands/tests
- finishing

### Phase 4: Strengthen Shell And Workspace Safety

This phase should be practical, not over-engineered.

#### Objective

Make command/file tools safer and more explicit without building a full
cross-platform secure sandbox.

#### Improvements

1. workspace-root enforcement
2. command timeout enforcement
3. explicit cwd tracking
4. command metadata recording
5. dangerous-command classification

#### `codex-rs` References

- `codex-rs/shell-command/src/lib.rs`
- `codex-rs/shell-command/src/command_safety/`

#### Suggested Python Additions

- `pycodeagent/tools/command_safety.py`

Suggested helpers:

- `is_safe_command(...)`
- `is_dangerous_command(...)`
- `normalize_workdir(...)`

#### Exit Criteria

The runtime should fail loudly when:

- a tool escapes the workspace
- a shell command exceeds timeout
- a destructive command violates policy

### Phase 5: Make ToolView Control First-Class In The Local Runtime

This is where the runtime becomes the main schema-controllable data producer.

#### Objective

Allow the local runtime to run the same task under multiple visible tool
schemas while keeping canonical backend execution stable.

#### Minimum Runtime Support

Per run, choose a `ToolProfile` mode such as:

- `base`
- `name_only`
- `description_only`
- `name_description`

Later, extend to:

- argument rename
- flat -> nested argument shapes
- reordered tools
- distractor tools

#### Existing Code To Reuse

- `pycodeagent/mutations/name_mutator.py`
- `pycodeagent/mutations/description_mutator.py`
- `pycodeagent/mutations/schema_mutator.py`
- `pycodeagent/traces/native_profile_transform.py`

#### Required Runtime Trace Fields

For each run and turn:

- `tool_profile_id`
- `tool_view_version`
- exact visible tool specs
- tool ordering
- per-call exposed/canonical mapping

#### Exit Criteria

The local runtime should be able to run one task under multiple `ToolView`
variants and emit separate traces that preserve:

- current visible schema
- model-emitted exposed call
- mapped canonical call

### Phase 6: Improve Dataset Producer Integration

After the local runtime is trace-first and schema-controllable, make it easier
to route its outputs into existing downstream training prep.

#### Objective

Preserve the local runtime as the active front-half data producer and reuse the
existing downstream data stack.

#### Existing Downstream Modules To Reuse

- `pycodeagent/rl/serializer.py`
- `pycodeagent/rl/loss_mask.py`
- `pycodeagent/rl/tensorize.py`
- `pycodeagent/rl/training_prep.py`

#### Desired Outcome

One local runtime run should be convertible into:

- a trajectory-based training sample
- a schema-following sample
- tokenized training input

without needing a separate external-agent ingestion path.

## Concrete File-Level Plan

### New Files

Add:

- `pycodeagent/runtime_trace/schema.py`
- `pycodeagent/runtime_trace/writer.py`
- `pycodeagent/runtime_trace/__init__.py`
- `pycodeagent/tools/command_safety.py`
- tests:
  - `tests/test_runtime_trace_writer.py`
  - `tests/test_runtime_trace_events.py`
  - `tests/test_command_safety.py`

### Existing Files To Extend

- `pycodeagent/agent/runner.py`
  - insert trace hooks around each loop boundary
- `pycodeagent/tools/runtime.py`
  - return richer execution metadata and trace-friendly details
- `pycodeagent/env/coding_env.py`
  - create runtime trace bundle per run
- `pycodeagent/trajectory/recorder.py`
  - persist runtime trace outputs alongside trajectory artifacts
- `pycodeagent/tools/builtin/*.py`
  - standardize metadata and safety behavior
- `pycodeagent/tools/profile_factory.py`
  - optionally support runtime-selected transformed profiles

## Suggested Event Hook Points In `run_agent_task()`

Inside `pycodeagent/agent/runner.py`, add hooks at these exact points:

1. after initial messages are built
   - record visible tool schema snapshot
2. before `client.generate(...)`
   - record request payload
3. after `client.generate(...)`
   - record raw model response
4. after `parse_assistant_response(...)`
   - record parse result and parse errors
5. before each tool execution
   - record exposed tool call
6. after argument mapping
   - record canonical tool call
7. after tool handler returns
   - record tool result
8. after stop decision
   - record reason and loop status
9. at final return
   - record run summary

## Recommended Tool Expansion Order

Implement in this order:

1. strengthen existing tools
2. add `file.write`
3. add `file.create`
4. add `search.regex`
5. add `git.diff`
6. add `git.status`
7. add `python.run`

Rationale:

- these cover the majority of short-horizon coding actions
- they increase task realism without requiring large sandbox complexity
- they produce higher-value trajectories for downstream training

## Testing Strategy

### Unit Tests

Add or extend tests for:

- tool argument mapping
- runtime trace event emission
- payload-ref writing
- command safety checks
- tool metadata consistency

### Golden Trace Tests

Create a stable fixture bundle for one toy task run with:

- `runtime_trace_manifest.json`
- `runtime_trace.jsonl`
- payload files
- `trajectory.json`

This should be the local-runtime analogue of the existing mock scaffold golden
bundle strategy.

### Smoke Tests

Target one toy repository task such as:

- inspect repo
- read file
- edit bug
- run test
- finish

Success conditions:

1. agent loop completes
2. tool calls execute
3. trace is complete
4. trajectory is complete
5. downstream serializer/training-prep can consume the result

## Recommended First Milestone

If only one milestone is pursued first, it should be:

### Milestone M1: Trace-First Local Runtime

Deliverables:

1. local runtime still runs existing toy tasks
2. every run writes:
   - `runtime_trace_manifest.json`
   - `runtime_trace.jsonl`
   - `payloads/`
3. every tool call records:
   - visible tool name
   - canonical tool name
   - mapped arguments
   - result / error
4. tests cover:
   - event emission order
   - payload refs
   - exposed/canonical mapping preservation

This is the shortest path from the current MVP to a meaningfully more mature
local agent runtime.

## Anti-Goals During Maturation

Avoid these while implementing this plan:

1. rewriting the runtime in Rust
2. copying large `codex-rs` subsystems wholesale
3. building a TUI or product CLI first
4. adding dozens of tools before hardening trace contracts
5. blocking on a perfect sandbox
6. forcing unification with the multi-agent raw-trace scaffold

## Summary

The local runtime already exists and already works as an MVP.

The next correct move is not to replace it, but to mature it along three
dimensions:

1. trace quality
2. tool/runtime contract quality
3. schema-control quality

The single most important upgrade is to make it trace-first using an
append-only runtime trace bundle, borrowing the right ideas from
`codex-rs/rollout-trace/` without importing the rest of the `codex-rs`
architecture.
