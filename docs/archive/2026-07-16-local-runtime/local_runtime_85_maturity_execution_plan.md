# Local Runtime 85% Maturity Execution Plan

> Archived by RC-015 on 2026-07-16. This is historical implementation
> evidence, not a current construction schedule. See this archive's README for
> provenance, completion status, and replacement documents.

## Goal

The goal of this document is to push `pycodeagent` local runtime toward
roughly 85% maturity relative to the most relevant `codex-rs` runtime-core
subsystems.

This does not mean product parity. It does not mean cloning Codex UX, TUI,
app-server behavior, plugin surfaces, or cloud orchestration. It means that
the runtime layers most responsible for source-run credibility and observed
tool-use data quality become much closer to a mature industrial white-box
runtime.

The practical end goal remains:

- produce more credible observed tool-use source runs
- make schema-mutation research sit on top of a stronger runtime
- keep the data path auditable from runtime execution to training-prep

This document is the runtime implementation reference for 85% maturity work.
Concrete implementation should follow the nearest local `codex-rs` crate or
module boundary, not only subsystem names.

## How This Document Relates To Existing Plans

This repository now has four distinct planning layers:

- `docs/local_runtime_realism_mainline_plan.md`
  - defines the repository mainline and why runtime realism comes first
- `docs/codex_rs_subsystem_implementation_plan.md`
  - defines the general subsystem-first construction order
- `docs/local_runtime_industrial_gap_roadmap.md`
  - defines the maturity-gap map and acceptance framework
- `docs/local_runtime_85_maturity_execution_plan.md`
  - defines the higher-bar, source-mapped implementation blueprint for getting
    the runtime close to 85% maturity on the runtime-core subsystems that most
    affect data credibility

The existing `S1-S6` / `P1-P5` direction is still valid. This document does
not replace the mainline or the gap taxonomy. It tightens them into a harder
execution standard.

If these documents appear to overlap, use them this way:

- architecture direction and repo identity:
  `local_runtime_realism_mainline_plan.md`
- generic subsystem ordering:
  `codex_rs_subsystem_implementation_plan.md`
- maturity lens and acceptance criteria:
  `local_runtime_industrial_gap_roadmap.md`
- source-mapped 85% build target:
  this document

If there is tension between abstract planning and concrete implementation,
prefer:

1. `codex-rs` subsystem shape for implementation design
2. `industrial_gap_roadmap` for maturity interpretation
3. this document for the concrete 85% execution bar

## What Counts Toward 85%

Only five runtime-core subsystems count toward the 85% target in this
document.

### Protocol / Tool-Call Boundary

#### Relevant codex-rs crates

- `protocol`
- `codex-api`
- `model-provider`

#### Core objects / boundaries to reference

- structured response items
- function call output payloads
- SSE / streaming response item handling
- provider capability surfaces

#### Current pycodeagent baseline

`pycodeagent` already has a native tool-calling path and real-provider
integration, plus a text-mode fallback path.

#### Current gap

The runtime is not yet fully protocol-first. Text parsing still occupies too
much conceptual weight, provider capability boundaries are not yet the primary
contract, and fallback behavior is not yet as explicit as it should be.

#### Required next implementation moves

- make native structured tool-calling the default runtime path wherever the
  provider supports it
- reduce text-mode parser to compatibility fallback status
- make provider capability and protocol provenance visible in runtime artifacts
- harden malformed-provider and unsupported-provider fallback contracts

#### What counts as 85% for this subsystem

This subsystem reaches the 85% bar when the mainline runtime boundary is
provider-typed tool/result items plus JSON argument validation, not custom text
markers; when provider capability/protocol provenance is explicit; and when the
fallback path is clearly secondary rather than the practical center of gravity.

### Session / Turn Lifecycle / State

#### Relevant codex-rs crates

- `core`
- `state`

#### Core objects / boundaries to reference

- `Session`
- `TurnContext`
- turn lifecycle boundaries
- session metadata extraction and turn-context items

#### Current pycodeagent baseline

`pycodeagent` already has typed runtime state objects such as
`RuntimeSessionState`, `RuntimeTurnState`, recovery state, pending-issue
records, and traceable stop/continue facts.

#### Current gap

That state is still a baseline, not a mature lifecycle system. It is more
formal than before, but not yet close enough to the session/turn discipline
seen in `codex-rs core` and `state`.

#### Required next implementation moves

- deepen turn-scoped lifecycle phases beyond “typed state exists”
- make turn context and continuation taxonomy more explicit and more uniform
- tighten session-level carryover for unresolved issues, validation status, and
  blocked/continue decisions
- align post-run extraction and trace interpretation with typed turn-state
  boundaries rather than scattered local variables

#### What counts as 85% for this subsystem

This subsystem reaches the 85% bar when runtime execution is driven by a real
session/turn lifecycle model rather than mostly by local control flow, and when
session-level continuation, blocked, and stop facts can be reconstructed
cleanly from typed state and trace evidence.

Current note:

- completed `P2` work is a baseline milestone, not full subsystem completion
  at the 85% bar

### Context / History / Compaction

#### Relevant codex-rs crates

- `message-history`
- `core`
- `context-fragments`

#### Core objects / boundaries to reference

- append-only message history
- history lookup and metadata
- compaction boundaries
- selected-vs-retained history split

#### Current pycodeagent baseline

`pycodeagent` has explicit context policy modes, selected-context evidence, and
deterministic compaction-oriented state hooks.

#### Current gap

The runtime still relies too heavily on in-memory history and request-time
selection views. It does not yet have a true append-only retained history layer
with clear separation from request-time selected context.

#### Required next implementation moves

- make retained history a formal runtime artifact rather than only an in-memory
  message list
- separate retained history from request-time selected history as distinct
  contracts
- add deterministic compaction artifacts, summary slots, and carried-forward
  state in a way that resembles `codex-rs message-history` and adjacent
  context-shaping structure
- ensure long-session context shaping is auditable without reconstructing it
  from request payloads alone

#### What counts as 85% for this subsystem

This subsystem reaches the 85% bar when the runtime has an append-only retained
history layer, explicit selection and compaction boundaries, and formal
separation between “everything retained” and “what the model saw this turn.”
In-memory-only history is not enough for 85%.

### Tool Execution / Result / Safety Contract

#### Relevant codex-rs crates

- `shell-command`
- `execpolicy`
- `file-system`
- `apply-patch`
- `core`

#### Core objects / boundaries to reference

- prefix-rule policy evaluation
- permission and sandbox inputs
- unified exec context
- typed execution results and delta surfaces

#### Current pycodeagent baseline

`pycodeagent` already has canonical tools, structured tool results, command
safety helpers, protected-path rules, and richer metadata for builtin tool
results.

#### Current gap

These pieces are still not unified enough into one coherent execution contract.
The runtime has better safety and metadata than before, but it is not yet close
enough to the execpolicy/unified-exec style maturity of `codex-rs`.

#### Required next implementation moves

- tighten a shared execution context for file, patch, python, and command
  actions
- make permission-like policy facts first-class runtime facts rather than
  mostly implicit helper behavior
- improve delta/result fidelity so execution outputs are easier to reconcile
  with later audit and observed-data export
- keep tool growth disciplined; prioritize contract maturity over tool count

#### What counts as 85% for this subsystem

This subsystem reaches the 85% bar when execution boundaries are coherent
across high-frequency tools, permission-like decisions are explicit, typed
result metadata is stable and composable, and the runtime naturally supports
edit/validate loops without tool contracts feeling ad hoc.

### Trace / Audit / Runtime Evidence

#### Relevant codex-rs crates

- `rollout-trace`
- `state`

#### Core objects / boundaries to reference

- raw event envelope
- raw payload refs
- thread and turn trace context
- tool-dispatch trace
- post-run extraction and reconciliation

#### Current pycodeagent baseline

`pycodeagent` already emits append-only runtime trace bundles, externalized
payload refs, and observed exporters that preserve exposed/canonical tool-view
relationships.

#### Current gap

The trace layer is still thinner than `codex-rs rollout-trace`. It does not
yet fully separate protocol/runtime/tool-dispatch evidence layers or provide
the same degree of post-run reconciliation maturity.

#### Required next implementation moves

- strengthen trace layering between provider protocol, turn lifecycle, tool
  dispatch, and runtime policy evidence
- make post-run extraction and reconciliation more systematic
- tighten sample/trajectory/profile/trace cross-artifact alignment
- preserve auditability without overloading the trajectory contract

#### What counts as 85% for this subsystem

This subsystem reaches the 85% bar when runtime trace can explain protocol,
state, policy, and tool-dispatch boundaries in one coherent evidence chain, and
when observed sample export can be reconciled against trace, trajectory, and
source profile without manual guessing.

## Subsystem Maturity Matrix

The five counted subsystems above are the only maturity axes that count toward
the 85% target in this plan. They should be read as a build matrix, not as an
open-ended wishlist.

The practical interpretation is:

- `Protocol / Tool-Call Boundary`
  - move the runtime away from fragile free-text boundaries and toward
    provider-typed items
- `Session / Turn Lifecycle / State`
  - move from typed-state baseline to stronger lifecycle discipline
- `Context / History / Compaction`
  - make retained history and request-time context explicit, durable, and
    auditable
- `Tool Execution / Result / Safety Contract`
  - unify execution context, policy facts, and result fidelity
- `Trace / Audit / Runtime Evidence`
  - make cross-artifact reconciliation and evidence layering first-class

No product-only subsystem should be allowed to displace these five areas from
the 85% runtime-core target.

## Source-Mapped Build Order

Future work should follow this practical order:

1. finish the remaining `P1` protocol-first hardening
2. deepen `P2` from typed-state baseline into stronger `codex-rs`-aligned
   session/turn discipline
3. prioritize `P3` as the next major source-mapped subsystem push
4. follow with `P4` and `P5` together as execution, policy, and audit
   hardening
5. use real-provider runs only after each subsystem milestone as acceptance

Explicit rule:

- the next planning pass for any milestone must name the relevant `codex-rs`
  crates and core objects before proposing implementation steps in
  `pycodeagent`

This order is deliberate:

- `P1` removes the biggest protocol-level fragility
- `P2` gives the runtime a stronger internal control model
- `P3` is the next strongest push because context/history maturity is still one
  of the largest remaining runtime-core gaps
- `P4` and `P5` should then harden policy, execution, and evidence on top of a
  stronger protocol/session/context base

## Implementation Roadmap

### P1: Protocol-First Runtime Boundary

#### M1

- make native structured tool-calling the default path for providers that
  support it
- explicitly reference `codex-rs/protocol`, `codex-rs/codex-api`, and
  `codex-rs/model-provider` when refining request/response boundaries
- treat text-mode parsing as compatibility fallback only

Expected `pycodeagent` surfaces:

- `pycodeagent/agent/llm_client.py`
- `pycodeagent/agent/parser.py`
- `pycodeagent/agent/runner.py`
- provider config and capability surfaces

#### M2

- harden structured finish and stop boundaries where provider structure allows
  it
- make malformed-provider and unsupported-provider fallback contracts explicit
- preserve capability and protocol provenance in runtime artifacts

Expected `pycodeagent` surfaces:

- provider client implementations
- runtime artifact metadata
- runtime trace provenance fields

Completion criteria:

- native tools are the default path
- capability and protocol provenance is visible in artifacts
- malformed-provider fallback is explicit rather than ad hoc
- parse robustness is no longer the dominant runtime fragility

### P2: Session / Turn Lifecycle / State

#### M1

- keep `core` session/turn lifecycle and `state` extraction style as the
  immediate implementation references
- maintain typed `RuntimeSessionState` and `RuntimeTurnState`, but deepen them
  into stronger lifecycle boundaries
- tighten turn-scoped state transitions, pending-issue carryover, and explicit
  session-level continuation facts

Expected `pycodeagent` surfaces:

- `pycodeagent/agent/turn_state.py`
- `pycodeagent/agent/recovery.py`
- `pycodeagent/agent/stopping.py`
- `pycodeagent/agent/runner.py`

#### M2

- move from “formal typed state exists” to “turn-scoped lifecycle and
  session-level continuation taxonomy are `codex-rs`-aligned in shape”
- add retry, validation, unresolved-issue, and blocked/continue boundaries as
  typed session facts rather than scattered locals
- align post-run extraction and trace interpretation with turn-context-shaped
  session evidence

Expected `pycodeagent` surfaces:

- session-state extraction helpers
- turn lifecycle trace payloads
- run-level summary/audit surfaces

Completion criteria:

- runtime is not primarily driven by scattered locals
- turn-scoped lifecycle is explicit
- session-level continuation and blocked taxonomy is typed and auditable
- current completed `P2` remains recognized as baseline only, not full 85%
  completion

### P3: Context / History / Compaction

This is the next strongest source-mapped subsystem push.

`message-history` should be treated as the primary reference here, not just as
general inspiration.

#### M1

- make context-selection policy explicit and durable
- keep selected-context evidence first-class
- align context selection with a clearer retained-history vs selected-history
  split

Expected `pycodeagent` surfaces:

- `pycodeagent/agent/turn_state.py`
- `pycodeagent/agent/history_manager.py`
- request-construction surfaces in `pycodeagent/agent/runner.py`

#### M2

- add deterministic compaction artifacts
- add summary slots
- add carried-forward state objects
- ensure compaction is explainable from runtime artifacts rather than inferred
  from request deltas alone

Expected `pycodeagent` surfaces:

- history selection/compaction helpers
- retained-history artifact module
- runtime trace context-selection payloads

#### M3

- move closer to a `codex-rs`-style history discipline
- introduce an append-only retained-history artifact separated from the
  request-time selected-context view
- make long-session context shaping auditable without relying on in-memory-only
  reconstruction

Expected `pycodeagent` surfaces:

- new append-only history contract
- retained-history serialization
- request-time selection view builder

Completion criteria:

- request-time context is explicit and auditable
- compaction is deterministic and evidenced
- retained history is not just an in-memory list
- in-memory-only history is no longer the main runtime history model

### P4: Validation / Recovery / Stop Policy

This stage is downstream of:

- `core` turn lifecycle discipline
- structured execution results
- provider-typed tool/result boundaries

The goal is not plannerization. The goal is a `codex-rs`-like light runtime
policy with stronger typed stop and continue facts.

#### M1

- keep stop hooks lightweight
- keep validation and recovery policy tied to typed runtime facts
- reduce premature finish and obvious unresolved-failure exits without turning
  the runtime into a heavyweight planner

Expected `pycodeagent` surfaces:

- `pycodeagent/agent/stopping.py`
- `pycodeagent/agent/recovery.py`
- turn-state continuation facts

#### M2

- make validation-aware continuation policy more explicit
- strengthen finish evidence gating where the runtime has enough typed facts to
  justify it
- type unrecovered-failure and no-progress cases more clearly

Expected `pycodeagent` surfaces:

- typed stop decision codes
- run-level failure buckets
- runtime trace stop/continue payloads

#### M3

- make revise, revalidate, and unresolved-failure handling a normal runtime
  path when needed
- keep policy nudges minimal and typed
- avoid adding planner-heavy behavior that exceeds the runtime-core scope

Completion criteria:

- stop and continue behavior is typed and auditable
- premature finish and unrecovered validation collapse are materially reduced
- runtime policy stays lightweight rather than becoming a planner surrogate

### P5: Tool Execution / Safety / Audit Fidelity

This stage should be read in three linked parts:

- execution contract maturity
- policy visibility
- audit and reconciliation maturity

It should be explicitly anchored to:

- `shell-command`
- `execpolicy`
- `file-system`
- `apply-patch`
- `rollout-trace`

#### M1

- unify execution contract maturity across file, patch, python, and command
  paths
- strengthen coherent execution context and result metadata
- make permission-like policy facts more explicit

Expected `pycodeagent` surfaces:

- `pycodeagent/tools/runtime.py`
- `pycodeagent/tools/command_safety.py`
- `pycodeagent/env/path_policy.py`
- builtin tool modules

#### M2

- improve policy visibility at turn and run level
- improve delta/result evidence for edits and execution
- make trace-to-observed-to-trajectory reconciliation more systematic

Expected `pycodeagent` surfaces:

- runtime trace enrichment
- post-run reconciliation helpers
- observed exporter metadata alignment

#### M3

- build subsystem-level acceptance reporting for execution, policy, and audit
- make repeated-run credibility bundles reflect execution/safety/audit maturity
- finalize the 85%-readiness surfaces for these execution-heavy subsystems

Completion criteria:

- execution context is coherent across high-frequency tools
- permission-like policy facts are explicit runtime facts
- trace-to-observed-to-trajectory reconciliation is stable and explainable
- execution, policy, and audit surfaces feel like one subsystem rather than a
  collection of helpers

## Acceptance Model

Three validation layers remain in force:

1. deterministic regression
   - proves contract stability
2. subsystem acceptance
   - small real-provider checks after each milestone
3. 85% maturity acceptance
   - repeated real-provider workload bundle as final credibility evidence

Rules:

- deterministic regression proves that contracts did not drift
- real-provider runs prove that the implemented subsystem still behaves
  plausibly under real model interaction
- neither of those replaces source-mapped design from local `codex-rs`

Anti-drift rule:

- do not let repeated task failures define architecture when the local
  `codex-rs/` source tree already contains the closer subsystem pattern

Real-provider runs are acceptance, regression, and credibility evidence. They
are not the primary architecture driver for the 85% program.

## Deliverables

This 85% program should always maintain these execution artifacts:

- this source-mapped 85% execution document
- one subsystem checklist table covering the five runtime-core areas
- one milestone tracker covering `P1-P5` and their `M1/M2/M3` slices
- one 85%-readiness checklist
- one real-provider acceptance matrix
- one explicit “not in 85% scope” appendix

The implementation output should also trend toward:

- provider/protocol provenance in runtime artifacts
- typed session and continuation evidence
- retained-history and request-selection artifacts
- unified execution and policy facts
- stronger trace-to-observed reconciliation surfaces

## Success Criteria

The 85% program is succeeding when all of the following become true:

1. native structured tool-calling is the mainline, not text parsing
2. session and turn state are formal runtime contracts
3. request-time context shaping is explicit and auditable
4. validation, recovery, and stop policy is mature but still lightweight
5. tool execution and safety boundaries are structured and composable
6. runtime trace explains protocol, state, policy, and execution decisions
7. observed datasets come from source runs with materially higher realism
8. these properties are regression-testable and real-provider verifiable

## Short Summary

This document is the source-mapped 85% execution blueprint for the runtime-core
subsystems that most affect observed-data credibility.

Practical instruction:

- build by `codex-rs` subsystem mapping first
- validate with real-provider runs second
- judge completion by the five runtime-core subsystems, not by product surface

## Current Primary Source References

Future runtime-core implementation work should treat these local directories as
primary sources:

- `codex-rs/protocol`
- `codex-rs/codex-api`
- `codex-rs/model-provider`
- `codex-rs/core`
- `codex-rs/state`
- `codex-rs/message-history`
- `codex-rs/context-fragments`
- `codex-rs/shell-command`
- `codex-rs/execpolicy`
- `codex-rs/file-system`
- `codex-rs/apply-patch`
- `codex-rs/rollout-trace`

Exclusion:

- do not treat `tui`, `app-server`, plugin/platform, or cloud-orchestration
  crates as part of the 85% runtime-core target
