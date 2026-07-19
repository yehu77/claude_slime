# Local Runtime Realism And Data Quality Mainline Plan

> Archived by RC-015 on 2026-07-16. This is historical implementation
> evidence, not a current construction schedule. See this archive's README for
> provenance, completion status, and replacement documents.

## Goal

This document defines the current mainline development plan for the repo-owned
local coding-agent runtime in `pycodeagent`.

The current goal is to mature the local runtime into a high-fidelity,
white-box, auditable coding-agent runtime that can generate higher-quality
observed tool-use training data.

`codex-rs` is now an explicit industrial reference for this effort. The point
is not to clone its product surface, but to study its white-box runtime
subsystems and selectively borrow the parts that most directly improve data
quality, auditability, and contract discipline in `pycodeagent`.

The current concrete implementation path is now:

- `codex-rs subsystem implementation first`
- `small real-provider workload acceptance second`

That means runtime architecture should be driven primarily by subsystem mapping
to `codex-rs`, while small real-provider runs act as validation, regression,
and evidence rather than as the architecture source.

This goal is explicitly not:

- building a Codex-like product
- building a TUI-first interface
- building a full MCP platform
- claiming a production-grade sandbox
- claiming state-of-the-art coding-agent task performance

The immediate purpose of this mainline is to improve the quality of the source
runs that later feed:

- runtime traces
- observed schema-following datasets
- tokenized training-prep bundles
- downstream schema mutation and ToolView studies

## Why This Becomes The Mainline Now

The local runtime becomes the current first-priority mainline for three linked
reasons.

First, the research value of schema mutation depends on the source run being
realistic enough. If the source runtime behaves like a toy loop, then even a
rich ToolView mutation study is still studying tool use on top of a weak data
source. The model may learn to follow renamed or nested schemas, but the
underlying trajectories still underrepresent real coding-agent behavior.

Second, the quality of observed datasets depends directly on runtime behavior.
The repository now preserves actual emitted exposed tool calls, runtime traces,
and training-prep outputs. That means the runtime itself is now the source of
truth for a growing part of the data path. If the runtime's loop, prompt,
error-recovery, and tool surface are too simplified, then the observed dataset
inherits those simplifications.

Third, the repo already has the right downstream foundations:

- append-only runtime trace bundles
- canonical-tool to ToolView separation
- observed runtime exporter
- runtime-observed training-prep
- golden fixtures and deterministic regression coverage

Because the downstream path is already usable, the largest remaining leverage
is no longer "can we export data at all," but "how realistic and useful is the
source runtime behavior that produces that data?"

There is also now a practical implementation reference for how a mature
white-box coding runtime can be decomposed. `codex-rs` already separates:

- rollout tracing from offline interpretation
- visible tool contracts from tool execution
- command safety from command schema
- filesystem/search/patch capabilities into explicit tool boundaries

That does not mean `pycodeagent` should become a Rust reimplementation. It
does mean the repo now has a concrete example of the kind of runtime maturity
that is worth pursuing because it changes the quality of the emitted traces and
tool-use data.

This also changes how later runtime iterations should be chosen:

- `codex-rs` becomes the current implementation-first reference
- `docs/local_runtime_industrial_gap_roadmap.md` becomes the maturity and
  acceptance framework
- small real-provider workloads become the behavior acceptance layer

The practical implication is straightforward: doing increasingly complex schema
mutation on top of a weak source runtime has limited value. Improving runtime
realism first makes every later mutation mode, observed dataset, and study more
meaningful.

## Current State Snapshot

The current local runtime is already a real white-box MVP, not a stub.

It currently has:

- a local multi-turn agent loop
- canonical tool backends separated from exposed `ToolView`s
- append-only runtime trace bundles beside `trajectory.json`
- an observed runtime exporter that preserves actual emitted exposed tool calls
- runtime-observed training-prep that reaches prepared and tokenized bundles
- a structured builtin tool surface
- profile-driven ToolView mutation support with deterministic modes

The current runtime foundations already include:

- `CanonicalTool -> ToolView -> ToolAdapter -> ToolRuntime`
- exposed-to-canonical argument mapping
- runtime trace events for request, parse, mapping, execution, and stop
- observed dataset manifests and prepared bundle fixtures
- deterministic smoke and golden regression coverage

Relative to a more mature white-box system like `codex-rs`, the repo is still
missing several implementation layers that matter for data realism:

- a richer separation between hot-path runtime events and later audit/replay
- a more mature prompt, permissions, and stop-policy surface
- a more unified command execution and safety core
- narrower and more explicit tool execution contracts on more paths
- a stronger recovery model after parse, mapping, and execution failures

The current builtin canonical tools cover the high-frequency short-horizon
coding loop:

- `list_files`
- `read_file`
- `write_file`
- `create_file`
- `search_code`
- `apply_patch`
- `run_command`
- `python_run`
- `finish`

The current formal ToolView control surface already supports:

- `base`
- `name_only`
- `description_only`
- `argument_rename`
- `schema_flat_to_nested`
- `tool_reorder`
- `schema_only`
- `name_description_schema`

The runtime can already emit:

- `runtime_trace_manifest.json`
- `runtime_trace.jsonl`
- payload refs for request, response, and tool-result blobs
- `trajectory.json`
- `tool_profile.json`
- observed schema-following raw datasets
- prepared and tokenized runtime-observed bundles

What is still not realistic enough:

- the runtime loop is still mostly fake-client driven and short-horizon
- prompt shape and stop policy remain relatively simple
- recovery behavior after parse, mapping, and tool failures is still narrow
- the inspect/edit/test/revise loop is not yet mature enough to resemble a
  stronger industrial coding runtime
- safety boundaries are clearer than before, but still not organized as a
  fully mature runtime contract
- the tool surface is useful, but not yet tuned primarily for realistic data
  generation behavior
- there is still no claim that the runtime can solve long-horizon tasks
  robustly

## Design Principle

The local runtime should continue to center this abstraction:

```text
CanonicalTool -> ToolView -> ToolAdapter -> ToolRuntime
```

This remains the core design rule:

- `CanonicalTool` provides stable backend semantics
- `ToolView` defines the model-visible schema for one run
- `ToolAdapter` maps exposed arguments back to canonical semantics
- `ToolRuntime` is the actual execution boundary

The runtime must remain white-box. It should not depend on hidden internal
state from an external closed agent. All important runtime decisions should be
either explicit in code or recoverable from artifacts.

`codex-rs` should be treated as a subsystem reference, not as a product target.
The most relevant reference areas today are:

- `codex-rs/rollout-trace/`
  - the "observe first, interpret later" split between hot-path event writing
    and offline reduction
- `codex-rs/protocol/src/dynamic_tools.rs`
  - explicit visible tool spec, tool call, and tool response contracts
- `codex-rs/shell-command/` and `codex-rs/execpolicy/`
  - shared command parsing, safety classification, and policy evaluation
- `codex-rs/file-system/`, `codex-rs/file-search/`, `codex-rs/apply-patch/`
  - narrow capability boundaries with explicit inputs, outputs, and failure
    handling
- `codex-rs/linux-sandbox/` and related sandboxing crates
  - separation between runtime behavior, policy summary, and OS-specific
    enforcement backends

The repo should selectively borrow these ideas:

1. append-only runtime evidence before interpretation
2. explicit model-visible tool contracts
3. shared execution and safety cores instead of duplicated boundary logic
4. stable, structured tool result and failure contracts
5. policy metadata that survives into traces and later dataset filtering

The repo should explicitly not borrow these things as current priorities:

1. TUI or app-server product architecture
2. plugin platform machinery
3. state database and remote-control layers
4. full production sandbox claims
5. product mimicry whose main effect is UI or feature breadth instead of
   better source traces

The runtime trace is an audit surface, not a replacement for trajectory
artifacts. `trajectory.json` remains the compact run contract used by existing
downstream consumers, while `runtime_trace.jsonl` records richer lifecycle
boundaries and payload indirection.

Observed samples must come from the source run's actual emitted exposed tool
call. They must not silently substitute synthetic reprojection as the default
runtime mainline.

Schema mutation remains a first-class research axis, but it is a second-order
capability built on top of runtime realism. The priority is not product mimicry
for its own sake. The priority is data-relevant realism: behavior that makes
the resulting traces and observed datasets more faithful and useful.

## Target End State

The intended local-runtime mainline is:

```text
task
  -> workspace materialization
  -> runtime prompt construction
  -> visible ToolView exposure
  -> model request
  -> assistant parse
  -> exposed-call validation
  -> exposed-to-canonical mapping
  -> tool dispatch
  -> tool result reinjection
  -> recovery / continue / stop decision
  -> runtime trace
  -> trajectory
  -> observed schema-following dataset
  -> tokenization / training-prep
  -> downstream training bundle
```

The target system should have five properties.

It should be realistic enough that short coding loops resemble real coding
agent behavior instead of a synthetic toy protocol.

It should be deterministic enough that key runtime artifacts can still be
frozen in golden fixtures and regression tests.

It should be contract-auditable, so that exposed tool schemas, canonical
mapping, stop reasons, safety decisions, and tool results can all be
reconstructed from artifacts.

It should be schema-controllable, so that the same canonical intent can be run
under multiple visible ToolViews without losing exposed-to-canonical alignment.

It should be directly consumable by the existing downstream training-data stack
without requiring a separate external-agent ingestion path for the local
runtime mainline.

## Maturity Axes

### Agent Loop Realism

Why it matters:
The runtime loop determines what kinds of trajectories are even possible. If
the loop can only do a shallow read-then-finish pattern, the resulting
observed dataset underrepresents real coding-agent behavior.

Current state:
The runtime supports multi-turn tool use, but typical coverage is still short,
deterministic, and fake-client driven.

Target state:
The runtime should naturally support short inspect/edit/test/revise/finish
loops and continue reasoning after recoverable failures.

Industrial reference:
`codex-rs/rollout-trace/` is useful here not because it solves planning, but
because it records enough runtime boundary information to make richer loops
auditable. `pycodeagent` should use that level of boundary visibility while
keeping a much smaller runtime core.

What not to over-optimize:
Do not turn this into a large planner or product agent framework before the
data path gains from it are clear.

### Prompt And Context Realism

Why it matters:
The visible prompt, tool rendering, and reinjected tool results directly shape
the distribution of tool calls that the model emits.

Current state:
The prompt contract is stable and clear, but still relatively simplified.

Target state:
The runtime should expose a more realistic context shape, clearer role
constraints, and more stable post-tool continuation behavior.

Industrial reference:
`codex-rs/protocol/` and prompt templates show the value of separating prompt
surface, permissions/sandbox messaging, and tool schema rendering into stable
contracts rather than ad hoc strings inside the loop.

What not to over-optimize:
Do not explode into provider-specific prompt variants or tune prompts as a
benchmark exercise.

### Tool Surface Realism

Why it matters:
The tool surface defines what actions the agent can express structurally. If
everything is shoved through one general command tool, the resulting training
data is less structured and less reusable.

Current state:
The runtime already has a useful core tool set with structured file-write and
Python execution support.

Target state:
The tool surface should stay focused on high-frequency coding actions whose
schemas improve data quality and make tool-use targets more explicit.

Industrial reference:
`codex-rs/file-system/`, `codex-rs/file-search/`, and
`codex-rs/apply-patch/` demonstrate why mature systems keep filesystem,
search, and patch capabilities as narrow contracts with explicit result
surfaces instead of burying everything under one shell tool.

What not to over-optimize:
Do not add tools for vanity coverage, naming mimicry, or overlapping weak-value
capabilities.

### Tool Result And Error Contract Quality

Why it matters:
Stable result metadata and failure types make traces filterable, debuggable,
and useful for later dataset curation.

Current state:
Tool results and runtime errors are already substantially structured.

Target state:
Every success and failure path should remain machine-readable, stable, and
directly useful for trace audit and sample selection.

Industrial reference:
`codex-rs/apply-patch/` is especially useful here because it treats patch
execution as a typed boundary with parse errors, partial-application semantics,
and committed-delta reporting rather than just "patch failed" text.

What not to over-optimize:
Do not chase elaborate result schemas that add complexity without downstream
data value.

### Runtime Trace And Audit Fidelity

Why it matters:
If runtime artifacts cannot prove what the model saw, emitted, and caused to
happen, then the repo cannot support strong claims about schema-following data
quality.

Current state:
Append-only runtime trace bundles already exist, with payload refs and lifecycle
events.

Target state:
The trace should capture all boundaries that materially affect training-data
meaning: visible tools, request/response, parse result, mapping, execution,
safety outcome, stop reason, and run summary.

Industrial reference:
`codex-rs/rollout-trace/README.md` states the right principle directly:
observe first, interpret later. `pycodeagent` should keep using
`trajectory.json` as the compact downstream contract, while making
`runtime_trace` the evidence layer that explains how the trajectory happened.

What not to over-optimize:
Do not turn the runtime trace into a state database or replay framework before
there is a concrete need.

### Safety And Workspace Policy Clarity

Why it matters:
Safety policy changes what actions the runtime can take and therefore changes
the distribution of observed traces. Unclear policy also makes trace analysis
harder.

Current state:
The runtime already has workspace-root and protected-path constraints, plus
structured safety metadata in key tool results.

Target state:
The runtime should expose consistent safety decisions across command execution
and file writes, with stable metadata that can be traced and filtered.

Industrial reference:
`codex-rs/shell-command/`, `codex-rs/execpolicy/`, and
`codex-rs/linux-sandbox/` show a useful separation: policy classification,
execution wrapper, and OS-enforcement backend are distinct layers. That is the
right maturity direction even if `pycodeagent` keeps a much smaller
cross-platform scope.

What not to over-optimize:
Do not market this as a production sandbox or block the mainline on a full
cross-platform containment stack.

### ToolView Control And Mutation Depth

Why it matters:
Schema-following research depends on the runtime being able to vary the visible
ToolView while keeping canonical semantics stable.

Current state:
The runtime now supports name, description, argument rename, flat-to-nested
schema, reorder, and compatibility composite modes.

Target state:
The runtime should support deeper but still controlled ToolView studies built
on realistic runs rather than on purely synthetic projection.

Industrial reference:
`codex-rs/protocol/src/dynamic_tools.rs` is a reminder that visible tool
contracts are first-class runtime objects. Mutation should therefore act on
that visible contract layer, not on canonical backend semantics.

What not to over-optimize:
Do not expand into mutation combinator explosion or distractor-heavy taxonomies
before the realistic runtime source behavior is stronger.

### Observed Dataset And Training-Prep Integration

Why it matters:
The local runtime only becomes a true data producer if its outputs reach the
existing serializer, mask, and tokenization path cleanly.

Current state:
Observed exporter and runtime-observed training-prep already exist, with
regression fixtures.

Target state:
The runtime should be a first-class front-half producer for study-scale
observed datasets and prepared bundles.

Industrial reference:
`codex-rs/rollout-trace/` is useful again here because it draws a clear line
between evidence capture and later interpretation. `pycodeagent` should keep
observed exporter and training-prep as explicit post-run stages rather than
hiding them inside the runtime loop.

What not to over-optimize:
Do not prematurely automate every post-run export path or invent elaborate eval
split taxonomies before the main contract is stable.

## Roadmap

### R1: Runtime Behavior Realism

Objective:
Make the local runtime's short multi-turn behavior look more like a real coding
agent rather than a toy tool-call script.

In scope:

- improve support for inspect -> edit -> run test -> inspect failure -> revise
  -> finish loops
- make finish behavior more disciplined and less eager
- allow recoverable tool failures to lead into further turns rather than
  immediate collapse
- stabilize assistant mixed-content, tool-only, and empty-content handling
- borrow from `codex-rs` the idea that richer lifecycle boundaries make richer
  runtime behavior debuggable, without copying its product-level orchestration

Out of scope:

- long-horizon planner design
- multi-agent collaboration
- benchmark pass-rate claims

Acceptance criteria:

- deterministic smoke tasks can exercise at least one revise-after-failure loop
- tool failure does not always force immediate run termination
- finish decisions better reflect task completion rather than just tool-call
  count

### R2: Prompt / Stop / Recovery Refinement

Objective:
Make the prompt contract, stop logic, and post-error continuation behavior
closer to realistic runtime distributions.

In scope:

- refine system prompt role constraints
- refine `<tools>` rendering so schemas are clear and stable
- refine tool-result reinjection patterns
- make stop reasons more explicit and better bucketed
- define recovery policy for parse, mapping, and execution errors
- separate these concerns into explicit runtime contracts in the same spirit as
  `codex-rs/protocol/`, instead of leaving them implicit in the agent loop

Out of scope:

- provider-specific prompt families
- large prompt-tuning campaigns

Acceptance criteria:

- runtime trace can distinguish stop reasons more cleanly
- recoverable error cases continue in predictable ways
- prompt and tool-rendering changes stay regression-testable

### R3: Tool Surface And Result Fidelity

Objective:
Prioritize a realistic, structured high-frequency coding tool surface over raw
tool-count expansion.

In scope:

- preserve and harden the current high-value tool set
- continue emphasizing explicit file creation, file writing, patching, and
  structured Python execution
- keep `run_command` as a general escape hatch, but not as the default schema
  for all actions
- add or refine tools only when they materially improve high-frequency data
  structure
- use `codex-rs/file-system/`, `codex-rs/file-search/`, and
  `codex-rs/apply-patch/` as reference points for narrowing contracts and
  stabilizing result surfaces

Out of scope:

- quantity-first tool expansion
- misleading `git_*` imitation tools
- overlapping low-value search or command wrappers

Acceptance criteria:

- short bug-fix loops can be expressed with structured tools rather than
  command-string overload
- tool results and error metadata remain stable and trace-friendly

### R4: Safety Boundary Consolidation

Objective:
Consolidate existing safety boundaries into clearer runtime contracts without
turning the project into a sandbox-first engineering effort.

In scope:

- shared command safety and execution boundary logic
- protected write-surface policy for sensitive directories
- normalized safety decision metadata for tool results and traces
- follow the layer split illustrated by `codex-rs/shell-command/`,
  `codex-rs/execpolicy/`, and `codex-rs/linux-sandbox/`: classify first,
  execute through a shared boundary second, and keep enforcement details
  decoupled from the model-visible schema

Out of scope:

- full sandbox productization
- broad OS-specific containment claims

Acceptance criteria:

- command and write policy decisions are structured, auditable, and stable
- trace payloads make safety rejections easy to analyze later

### R5: Deep ToolView Mutation Research Modes

Objective:
Make the highest-value mutation modes formal runtime capabilities backed by
realistic source runs.

In scope:

- first-class argument rename support
- first-class flat-to-nested schema support
- first-class tool reorder support
- trace and observed metadata that preserve exposed/canonical relationships
- treat the visible ToolView as the primary mutation surface in the same spirit
  that `codex-rs/protocol/src/dynamic_tools.rs` treats dynamic tool specs as
  explicit runtime contracts

Out of scope:

- distractor tools as an early priority
- broad mutation taxonomy expansion
- combinatorial mutation explosion

Acceptance criteria:

- the same canonical intent can be run under these deeper ToolViews
- exposed/canonical audit fields remain intact in runtime trace and observed
  exporter outputs

### R6: Study-Scale Observed Data Production

Objective:
Use the local runtime as a formal study-scale data producer for observed
schema-following datasets.

In scope:

- repeated multi-profile runtime runs
- observed exporter as a first-class post-run path
- prepared and tokenized runtime-observed bundles
- contract freeze through golden fixtures
- study and experiment orchestration that can consume realistic runtime runs
- preserve a separation between hot-path run execution and later dataset
  reduction, similar in spirit to `codex-rs/rollout-trace/`

Out of scope:

- automatically wiring exporter into every runner default path
- inventing a complex observed eval split taxonomy too early

Acceptance criteria:

- study-scale repeated runs can produce stable observed datasets
- prepared bundles remain compatible with the existing downstream stack
- fixture-backed regressions guard the observed-data contract

## What This Changes About Multi-Agent Scaffold Work

This plan does not reject or devalue the multi-agent scaffold direction.

What changes is priority and sequencing.

The broader multi-agent raw-trace scaffold moves from "current first mainline"
to "parallel secondary mainline and later integration target." The reason is
practical: the repo-owned local runtime is currently the fastest path to
high-integrity, schema-controllable, auditable observed training data.

The local runtime is therefore the current preferred front-half data producer.
Once that front-half becomes more realistic and stable, its contracts and
artifacts can later be connected back into the broader raw-agent scaffold.

The revised relationship is:

- local runtime realism first
- observed runtime data production second
- deeper ToolView mutation on realistic runs third
- wider multi-agent raw-trace integration after those foundations are stronger

The multi-agent scaffold remains important, but it is not the fastest current
path to better schema-following training data quality.

## Success Criteria

This mainline is succeeding if the following become true and remain stable.

1. The same task can run end-to-end under multiple ToolViews.
2. Runtime trace artifacts preserve exposed tool schema and
   exposed-to-canonical boundaries.
3. Runtime-observed exporter preserves the source run's actual emitted exposed
   tool call.
4. Prepared and tokenized runtime-observed bundles remain stable and loadable.
5. Tool results and safety decisions are structured enough for trace audit and
   sample filtering.
6. Short bug-fix loops are supported more naturally than the earlier toy
   runtime pattern.
7. Schema mutation research data comes from realistic runtime behavior rather
   than from synthetic-only reprojection.
8. All of the above remain regression-testable through deterministic smoke
   tasks and golden fixtures.

## Anti-Goals

Do not treat the following as current priorities.

- building a Codex clone product
- TUI-first polish
- plugin platform design
- premature production sandbox claims
- tool-count vanity expansion
- training win claims before source data quality is demonstrated
- replacing the repo identity with external closed-agent ingestion

## Recommended Next Milestones

The next recommended milestone order is:

First, improve runtime loop realism and recovery so that observed runs capture
more meaningful coding-agent behavior.

Second, refine prompt shape, stop logic, and result formatting so that the
runtime's visible context and continuation rules better match realistic source
behavior.

Third, run larger repeated observed studies under deeper mutation modes so that
schema-following experiments are grounded in more realistic source traces.

The concrete construction order for those runtime improvements is no longer
meant to be inferred from workload gaps alone. It should now follow:

- `docs/codex_rs_subsystem_implementation_plan.md`

That document is the current implementation driver. Small real-provider task
packs remain important, but only as acceptance, regression, and credibility
evidence.

When choosing concrete implementation references, prefer these `codex-rs`
subsystems first:

- `rollout-trace/` for runtime evidence boundaries
- `protocol/src/dynamic_tools.rs` for visible tool contracts
- `shell-command/` plus `execpolicy/` for shared command safety structure
- `file-system/`, `file-search/`, and `apply-patch/` for narrow tool contracts

Avoid getting pulled first into the `codex-rs` areas whose main payoff is
product breadth rather than training-data realism, such as TUI, app-server,
plugin, or remote-control infrastructure.

The guiding rule is simple: prioritize the next change that most directly
improves source runtime realism and observed data fidelity without destabilizing
the existing downstream contracts.

## Short Summary

This repository's current mainline is to make the repo-owned local coding
runtime realistic enough, controllable enough, and auditable enough to become a
high-quality observed training-data producer.

If choosing between features, prefer the work that most directly improves
runtime realism, exposed/canonical audit fidelity, and observed training-data
quality before expanding broader raw-agent integration or product-like surface
area.

## Relationship To The Earlier Maturation Plan

`docs/local_runtime_maturation_plan.md` remains a useful earlier maturation
baseline for the local runtime.

This document is the current mainline planning document. It supersedes the old
plan as the primary description of current runtime priorities, but it does not
delete, rename, or invalidate the earlier baseline.

The earlier plan already pointed at `codex-rs` as an industrial reference.
This document tightens that positioning by making runtime realism and observed
data quality the actual decision center for how those references should be
used.

`docs/local_runtime_industrial_gap_roadmap.md` also remains important, but it
should now be read as the industrial-grade-like maturity and acceptance
framework rather than as the concrete subsystem build order.

The concrete subsystem build order is now defined in:

- `docs/codex_rs_subsystem_implementation_plan.md`
