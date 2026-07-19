# Codex-rs Subsystem Implementation Plan For Local Runtime

## Goal

This document defines the current implementation driver for maturing the
repo-owned local runtime in `pycodeagent`.

The goal is to use the most relevant `codex-rs` subsystems as implementation
references and push the local runtime toward a more mature industrial
white-box runtime shape without turning the repository into a Codex clone
product.

The target is not:

- feature parity with `codex-rs`
- a TUI, app-server, or plugin-platform roadmap
- a benchmark or pass-rate plan
- a product-surface rewrite

The practical target is narrower and more relevant to this repository:

- make runtime behavior, state, policy, and execution boundaries more mature
- keep those changes white-box and auditable
- keep the resulting source runs useful for observed training-data production

Native-family terminology, explicit stack selection, fallback rules, and
artifact boundaries are fixed by
[ADR-0001](./adr/0001-native-family-runtime-boundary.md). This plan orders
implementation work but does not redefine that contract.

The optional ignored `codex-rs/` source tree is governed by the
[reference lock and bootstrap contract](./codex_rs_reference.md) and the
machine-readable
[`references/codex-rs.lock.json`](../references/codex-rs.lock.json). The
current reference is the official `openai/codex` `codex-rs` subtree at the
full immutable commit recorded there. Before using local source as subsystem
evidence, run:

```bash
python -B -m pycodeagent.dev.codex_reference verify
```

An absent tree does not block repository runtime or tests. A mismatched tree
must not be used as implementation evidence until it has been reconciled; do
not infer its version from the containing repository's Git `HEAD`.

## Role Separation

This document is the current local-runtime implementation mainline.

The work is split across three distinct roles:

- `codex-rs`
  - tells us how mature runtime subsystems can be decomposed and implemented
- `docs/local_runtime_industrial_gap_roadmap.md`
  - defines what counts as industrial-grade-like maturity and what gaps remain
- small real-provider task packs
  - validate whether the implemented subsystem changes actually improved
    runtime behavior

This means the design rule is now explicit:

- do not use task-pack outcomes as the primary source of runtime architecture
- use `codex-rs` subsystem structure as the primary implementation reference
- use real-provider runs as acceptance, regression, and evidence

For `S3-S5`, this rule is stricter:

- do not treat repeated task failures as the main way to discover context,
  execution, or policy architecture
- first identify the nearest mature `codex-rs` subsystem pattern
- then implement the corresponding runtime contract in `pycodeagent`
- only after that use real-provider runs to verify whether the behavior
  actually became more realistic or more stable

In other words:

- `codex-rs` drives subsystem design
- real-provider runs validate subsystem effectiveness
- small workload packs do not decide what the subsystem should look like

## Current Repo vs Codex-rs Mapping

### Session / turn lifecycle / state

Current repo baseline:

- local multi-turn runtime loop
- explicit recovery and stopping state
- append-only runtime trace
- formal turn-state and context-selection contracts already started

Nearest `codex-rs` reference area:

- `core` session and turn lifecycle
- `message-history`
- `state`

Current gap:

- session-level state is still narrower than a mature runtime
- pending issue carryover and turn lifecycle policy remain relatively light

Why it matters for data quality:

- without stronger session and turn structure, observed runs remain too toy-like
  and under-expressive

### Validation / recovery / stop policy

Current repo baseline:

- validation-aware recovery state
- finish deferral and validation gating
- explicit stop reasons and runtime-trace evidence

Nearest `codex-rs` reference area:

- `core` session policy
- execution outcome handling around command/tool boundaries

Current gap:

- validation-driven continuation is still not mature enough to be the normal
  runtime behavior
- correction discipline after failure is still comparatively narrow

Why it matters for data quality:

- realistic coding traces depend on failure inspection and correction, not just
  tool-call availability

### Context shaping / message history

Current repo baseline:

- full-history and bounded context policies
- deterministic compaction and turn-state traceability

Nearest `codex-rs` reference area:

- `message-history`
- `protocol`
- prompt/config-related session surfaces

Current gap:

- context shaping, carryover, and history management are still simpler than a
  mature runtime
- long-lived context behavior is not yet a strong source-run property

Why it matters for data quality:

- visible context shape directly changes tool-call and recovery distributions

### Tool execution / filesystem / patch / command boundaries

Current repo baseline:

- structured high-frequency builtin tools
- workspace/path enforcement and a shared process-execution substrate
- normalized tool results and error metadata

Nearest `codex-rs` reference area:

- `file-system`
- `file-search`
- `apply-patch`
- `shell-command`

Current gap:

- execution boundaries are stronger than before but still not fully mature in
  sequencing, result fidelity, and composition under more realistic loops

Why it matters for data quality:

- if high-frequency coding actions are not expressed through stable contracts,
  the observed tool-use data becomes less structured and less credible

### Permission / execpolicy / trace evidence

Current repo baseline:

- structured protected-path boundaries and trace-visible execution metadata
- runtime trace events for request, parse, mapping, execution, and stop

Nearest `codex-rs` reference area:

- `execpolicy`
- `shell-command`
- `rollout-trace`
- sandbox-related policy layers

Current gap:

- no active command-policy engine exists; the legacy two-state argv allowlist
  was deleted by RC-038 rather than activated
- permission-like runtime facts are still thinner than in a mature runtime
- trace explains more than before, but policy visibility still has room to grow

Why it matters for data quality:

- safety and permission boundaries shape runtime behavior and must remain
  auditable in downstream artifact interpretation

## Implementation Order

### S1: Session / Turn Lifecycle And State

Objective:

- make lifecycle and state handling look more like a mature white-box coding
  runtime

In-scope subsystem work:

- formalize session-level state objects
- strengthen turn lifecycle boundaries
- make pending issue carryover explicit
- keep runtime-trace alignment with lifecycle state

Explicit out-of-scope work:

- no persistent thread-store architecture
- no product-oriented remote session control

Expected code artifacts:

- stronger session-state contracts
- clearer turn lifecycle and pending-issue state objects
- richer turn-state trace payloads where needed

Acceptance checks via real-provider runs:

- at least one short real-provider run should show stable multi-turn state
  progression without collapsing into read-once-then-finish

### S2: Validation / Recovery / Stop Policy

Objective:

- make validation-driven continuation and finish gating the normal runtime
  policy rather than a narrow special path

In-scope subsystem work:

- strengthen validation-driven continuation
- refine finish gating
- refine recovery taxonomy across validation, parse, and execution outcomes
- make corrective behavior more disciplined after failure

Explicit out-of-scope work:

- no planner framework
- no benchmark-specific validator zoo

Expected code artifacts:

- stronger recovery and stop-policy contracts
- clearer validation and correction taxonomy
- richer stop-decision evidence where needed

Acceptance checks via real-provider runs:

- at least one real-provider run should show validation failure followed by
  correction and successful completion or a clearly justified blocked finish

### S3: Context Shaping / History Management

Objective:

- mature the visible context contract so request-time message selection looks
  more like a real sessioned runtime

Execution principle:

- do not wait for long-context failures in small workloads to discover what
  history management should be
- directly reference the nearest `codex-rs` session/history/compaction pattern
  first
- then validate with real-provider runs that the new context shaping does not
  introduce dominant drift

In-scope subsystem work:

- refine context selection policy
- strengthen history-window and carryover rules
- formalize compaction hooks and history shaping behavior
- keep the full trajectory distinct from request-visible context

Explicit out-of-scope work:

- no provider-specific prompt zoo
- no summary-model pipeline as a prerequisite

Expected code artifacts:

- explicit context-shaping policy layer
- stronger message-history and carryover contracts
- trace-visible history-selection evidence

Acceptance checks via real-provider runs:

- repeated real-provider runs should remain stable under nontrivial history
  shaping without obvious context drift becoming the dominant failure mode

### S4: Tool Execution And Result Boundary Maturity

Objective:

- mature the current structured tool surface instead of expanding tool count

Execution principle:

- do not use task-pack failures as the main source of file/patch/command
  boundary design
- directly reference the nearest `codex-rs` execution-boundary and result
  contract pattern first
- then validate with real-provider runs that structured actions remain stable
  under realistic inspect/edit/validate loops

In-scope subsystem work:

- refine file, patch, validation, and command execution boundaries
- strengthen result fidelity and delta reporting
- improve composition of inspect/edit/validate paths

Explicit out-of-scope work:

- no quantity-first tool expansion
- no product-mimic wrappers whose main value is naming parity

Expected code artifacts:

- stronger tool-result contracts
- more mature filesystem and patch boundaries
- clearer validation-tool and command-tool interaction patterns

Acceptance checks via real-provider runs:

- realistic short bug-fix runs should rely on structured actions rather than
  collapsing into generic command overload

### S5: Permission / Safety / Policy Visibility

Objective:

- make permission-like runtime facts and policy visibility more mature without
  turning this into a sandbox-product project

Execution principle:

- do not infer permission or policy architecture mainly from ad hoc denied-run
  examples
- directly reference the nearest `codex-rs` policy-visibility and exec-policy
  pattern first
- then validate with real-provider runs that denied or constrained behavior is
  stable, explicit, and auditable

In-scope subsystem work:

- strengthen explicit policy-decision surfaces
- refine environment capability visibility
- expose permission-like runtime facts more clearly in artifacts and traces

Explicit out-of-scope work:

- no production sandbox claims
- no large cross-platform containment program

Expected code artifacts:

- clearer permission and policy metadata contracts
- stronger trace-visible policy facts
- more uniform policy surfaces across command and file actions

Acceptance checks via real-provider runs:

- policy-denied and policy-limited outcomes should remain behaviorally stable
  and easy to audit in real-provider traces

### S6: Real-Provider Regression And Credibility Program

Objective:

- turn real-provider runs into the formal acceptance layer for subsystem work

In-scope subsystem work:

- repeated-run audit outputs
- realistic workload-pack evolution
- credibility-oriented regression bundles
- per-subsystem acceptance reports

Explicit out-of-scope work:

- no benchmark leaderboard campaign
- no claim that small workload packs define runtime architecture

Expected code artifacts:

- repeated-run reports
- behavior-baseline and credibility summaries
- regression-friendly real-provider acceptance paths

Acceptance checks via real-provider runs:

- every earlier subsystem milestone should have at least one real-provider
  acceptance case and a stable audit artifact

## Subsystem-by-Subsystem Milestones

### S1 first

Do first:

- strengthen formal session and turn state
- make lifecycle boundaries explicit
- improve pending issue carryover

Do not do first:

- deep new tooling
- workload expansion as a substitute for lifecycle design

### S2 second

Do first:

- validation-driven continuation
- finish gating
- recovery taxonomy tightening

Do not do first:

- speculative planner abstractions
- prompt tuning as a substitute for policy design

### S3 third

Do first:

- context selection
- history-window rules
- compaction hooks and visible context shaping

Do not do first:

- large summary-generation infrastructure
- provider-specific context heuristics

### S4 fourth

Do first:

- mature file, patch, test, and command boundaries
- make execution/result contracts more stable

Do not do first:

- broad tool-count expansion
- overlapping wrappers with weak data value

### S5 fifth

Do first:

- permission-like runtime facts
- policy visibility in trace and metadata

Do not do first:

- full sandbox-product engineering
- approval UX and product-control layers

### S6 throughout, but formalized last

Do first:

- keep small real-provider acceptance cases attached to each subsystem
- accumulate repeated-run evidence and credibility reports as milestones land

Do not do first:

- treat workload packs as the runtime architecture source
- try to prove benchmark-scale coverage before subsystem work matures

## Real-Provider Acceptance Model

The acceptance model is explicit.

Fake client remains for:

- deterministic regression
- parser and trace fixtures
- contract freeze and golden tests

Real-provider runs are for:

- behavior acceptance
- regression evidence
- repeated-run credibility checks

The workflow rule is:

- implement the subsystem by directly referencing `codex-rs`
- then validate it with a small real-provider acceptance path
- do not invert that order by trying to derive the subsystem design from a
  tiny workload pack

This is especially important for `S3-S5`.

Those stages should not follow a loop of:

- run a few real tasks
- observe a failure shape
- guess a subsystem design from that failure
- patch the runtime locally

Instead they should follow:

- map the missing capability to a concrete `codex-rs` subsystem pattern
- implement the corresponding contract in `pycodeagent`
- use real-provider runs only to confirm whether the implementation improved
  realism, robustness, or auditability

Every subsystem milestone should add or reuse at least one small real-provider
acceptance path. That acceptance does not need to be a benchmark. It only needs
to show whether the intended behavior became more mature or more stable.

## Decision Rule

When these options conflict:

- directly reference `codex-rs` and implement the subsystem
- run more tasks first and guess the architecture from outcomes

prefer the first.

For `S3-S5`, treat that as a hard default rather than a soft preference.

When these options conflict:

- add more small tasks
- mature a more important runtime subsystem

prefer the second.

When multiple subsystem implementations are plausible, prefer the one that:

- more directly improves source runtime realism
- keeps the runtime white-box and auditable
- preserves downstream data contracts
- can be validated cleanly with small real-provider runs afterward

Do not use real-provider failures as the main architecture discovery loop
unless:

- the nearest `codex-rs` reference is genuinely unclear for the subsystem, or
- two candidate subsystem mappings remain equally plausible after inspection

## Short Summary

If you need one sentence:

> The current local-runtime implementation mainline is to follow the most
> relevant `codex-rs` subsystems directly, and then use small real-provider
> runs only as acceptance and evidence.

If you need one practical instruction:

> Build the next runtime milestone by mapping it to a concrete `codex-rs`
> subsystem first, and only after implementation use a small real-provider run
> to verify the behavior improved.
