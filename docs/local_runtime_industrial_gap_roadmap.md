# Local Runtime Industrial-Grade Gap And Execution Roadmap

## Goal

This document defines the next-step execution roadmap for pushing the
repo-owned local runtime in `pycodeagent` toward more
industrial-grade-like runtime realism.

It should now be read primarily as a gap taxonomy, acceptance framework, and
maturity map. It is no longer the current step-by-step implementation driver
for runtime work.

The current implementation driver is:

- `docs/codex_rs_subsystem_implementation_plan.md`

The native-family runtime boundary used by this maturity framework is fixed by
[ADR-0001](./adr/0001-native-family-runtime-boundary.md). This roadmap defines
gaps and acceptance expectations, not alternate family-selection semantics.

That companion document defines the concrete subsystem-by-subsystem build
order. This document defines what maturity gaps still exist and what kinds of
runtime properties count as meaningful progress.

The target is not to claim that the current runtime is already industrial
grade, nor to turn the repository into a Codex clone product. The target is
to move from a well-instrumented research runtime and white-box observed-data
producer toward runtime behavior that looks more like a mature coding-agent
system.

The goal is explicitly not:

- building a TUI-first product surface
- building a plugin platform
- claiming a production-ready sandbox
- claiming feature parity with `codex-rs`
- replacing the repository identity with external closed-agent ingestion

The practical reason for this roadmap is straightforward: the current runtime
can already emit auditable traces, controlled ToolViews, and downstream
training-prep artifacts, but observed tool-use data becomes more convincing
only when the source runtime behavior itself is closer to a realistic coding
agent.

## Why R1-R6 Were Necessary But Not Sufficient

`R1-R6` were necessary because they established the runtime realism
infrastructure layer:

- a white-box local runtime loop
- append-only runtime trace bundles
- canonical-tool to ToolView separation
- deterministic ToolView mutation modes
- runtime-observed exporter
- prepared and tokenized training-prep outputs
- study-scale observed bundle generation

That work solved the problem of whether the repository can produce
schema-controllable, auditable, regression-testable runtime data at all.

It did not solve the higher-level problem of whether the source runtime already
behaves like a mature industrial coding runtime.

`R1-R6` did not fully solve:

- richer replanning after failed validation
- longer-lived context and session state management
- realistic context shaping and compaction behavior
- validation-driven runtime discipline as a first-class runtime policy
- realistic workload breadth beyond deterministic smoke loops
- runtime behavior analysis at the distribution level rather than via feature
  checklist only

The key distinction is:

- `R1-R6` made the local runtime a well-instrumented research runtime and
  white-box observed-data producer
- this roadmap addresses the next layer: industrial-grade-like runtime realism

The relationship between the two is:

```text
R1-R6 foundation
  -> auditable source runs
  -> observed dataset production
  -> downstream training-prep stability
  -> industrial-grade-like runtime realism roadmap
```

## Current Baseline After R1-R6

After `R1-R6`, the repository already has a real local runtime mainline with
important foundations in place.

Current baseline capabilities:

- a repo-owned multi-turn local runtime loop in `pycodeagent/agent/runner.py`
- explicit system prompt, tool rendering, parser, recovery, and stopping logic
- append-only runtime trace bundles beside `trajectory.json`
- structured builtin canonical tools:
  - `list_files`
  - `read_file`
  - `write_file`
  - `create_file`
  - `search_code`
  - `apply_patch`
  - `run_command`
  - `python_run`
  - `finish`
- deterministic ToolView mutation modes:
  - `base`
  - `name_only`
  - `description_only`
  - `argument_rename`
  - `schema_flat_to_nested`
  - `tool_reorder`
  - `schema_only`
  - `name_description_schema`
- runtime-observed exporter and runtime-observed training-prep
- study-scale observed bundle generation with fixture-backed regression tests

Current runtime identity:

- a well-instrumented research runtime
- a white-box observed-data producer
- a schema-controllable local source runtime

What is still simplified or still toy-like:

- source runs are still primarily fake-client and deterministic-smoke driven
- the short bug-fix loop exists, but it is not yet strong enough to resemble a
  mature runtime under broader task variation
- context shaping remains comparatively simple
- session and turn state are still lighter-weight than in a mature runtime
- validation is supported, but runtime behavior is not yet consistently
  organized around validation outcomes
- recovery policy exists, but still looks narrower than a stronger industrial
  coding runtime
- workload realism is still thin relative to the claims one would want to make
  about source-data credibility

The current biggest gap is no longer "can the repo export data" but "does the
source runtime behavior distribution look realistic enough to support strong
claims about that data."

## Industrial Reference Mapping

`codex-rs` should be treated here as an industrial subsystem reference, not as
a feature-parity target and not as a product-clone target.

### `rollout-trace`

Current repo foundation:

- `runtime_trace` already records append-only event evidence
- hot-path run execution is separated from later observed export and
  training-prep reduction

Current gap:

- trace is audit-strong, but not yet paired with richer runtime state and
  behavior interpretation layers
- the runtime does not yet generate enough realistic turn variety for the trace
  to reflect mature behavior

Worth following soon:

- yes, for deeper runtime evidence boundaries
- yes, for clearer turn-state and event interpretation contracts

Do not follow:

- no state database
- no app-server style product control plane

### `protocol / dynamic tools`

Current repo foundation:

- visible ToolView is already a first-class runtime object
- exposed/canonical mapping is preserved in runtime trace and observed exports

Current gap:

- visible tool contracts are strong, but broader runtime protocol boundaries
  around session state, permissions, and continuation policy are still thinner

Worth following soon:

- yes, for more explicit runtime protocol objects
- yes, for clearer per-turn state and continuation contracts

Do not follow:

- no protocol sprawl for product surfaces that do not improve data realism

### `shell-command / execpolicy`

Current repo foundation:

- workspace/path enforcement and shared process execution exist
- execution and path-policy facts are surfaced through structured metadata
- the legacy two-state argv allowlist was deleted by RC-038 rather than
  activated

Current gap:

- no active command-policy engine currently evaluates shell commands
- permission-like runtime decisions remain narrower than a mature runtime
- the runtime does not yet expose a broader permission or escalation model as
  a formal runtime contract

Worth following soon:

- yes, for permission-state modeling
- yes, for stronger approval-like runtime policy summaries

Do not follow:

- no premature full approval UX or product workflow system

### `file-system / file-search / apply-patch`

Current repo foundation:

- high-frequency file and patch actions already exist as narrow tools
- result metadata is substantially richer than before

Current gap:

- there is still room to make file-operation, patch-delta, and validation
  follow-up behavior more mature and more consistent across loops

Worth following soon:

- yes, for richer delta/result surfaces
- yes, for more realistic sequencing between inspect/edit/validate steps

Do not follow:

- no quantity-first tool surface expansion
- no misleading product-mimic tool names just for coverage

### `message-history / state / session`

Current repo foundation:

- the runtime has explicit messages and tool-result reinjection
- recovery state already exists in minimal form

Current gap:

- there is no mature session-state or turn-state layer
- context compaction, carryover, and summarization hooks are still limited
- behavior remains closer to a controlled loop than to a long-lived runtime

Worth following soon:

- yes, this is one of the highest-leverage follow-up areas
- especially for explicit turn state, context selection, and compaction policy

Do not follow:

- no heavy thread-store or remote-control infrastructure as a first move

### `core session / turn lifecycle`

Current repo foundation:

- turn lifecycle boundaries are much clearer than before
- stop reasons, pending issues, and recovery outcomes are now explicit

Current gap:

- replanning, retry budgets, validation gating, and correction-turn discipline
  remain lighter than in a mature runtime
- runtime behavior is not yet organized around a stronger session-level policy

Worth following soon:

- yes, this is the main behavior-realism frontier

Do not follow:

- no attempt to copy the full `codex-rs` session architecture wholesale

## Industrial Runtime Gap Axes

### Agent Behavior Realism

Current state:

- the runtime can perform short inspect/edit/test/revise/finish loops
- deterministic smoke tasks cover revise-after-failure behavior

Target state:

- revise-after-failure becomes normal runtime behavior, not a single smoke
  trick
- correction turns, replanning, and evidence-backed completion become routine
  runtime patterns

Why it matters for data credibility:

- observed data is only convincing if the runtime emits behavior that looks
  like real coding work rather than scripted tool sequences

Nearest `codex-rs` reference:

- `core` turn/session lifecycle
- `rollout-trace`

What not to overbuild:

- no long-horizon planner framework before short-horizon realism is strong

### Context And Prompt Realism

Current state:

- prompt contract and tool rendering are clear and stable
- message history is explicit but relatively simple

Target state:

- context shaping, tool-result reinjection, and long-turn prompt continuity
  look more like realistic runtime usage
- compaction and summary hooks become explicit runtime behaviors

Why it matters for data credibility:

- prompt shape directly changes tool-call distributions and correction behavior

Nearest `codex-rs` reference:

- `protocol`
- prompt/config surfaces
- message-history-related subsystems

What not to overbuild:

- no provider-specific prompt zoo
- no prompt-tuning campaign disconnected from runtime behavior

### Session / Turn State Management

Current state:

- the runtime has trajectory state plus lightweight recovery state

Target state:

- explicit turn-state and pending-issue state become formal runtime objects
- session-level carryover and compaction decisions are visible and auditable

Why it matters for data credibility:

- mature runtime behavior requires explicit state transitions rather than
  implicit control flow only

Nearest `codex-rs` reference:

- `core` session/turn handling
- `state`
- `message-history`

What not to overbuild:

- no thread-store or persistent app-server architecture as the first step

### Validation And Recovery Discipline

Current state:

- recovery policy exists for parse, tool failure, and validation-related cases

Target state:

- runtime policy becomes explicitly validation-driven
- unresolved failures block completion more systematically
- retry and revise budgets become clearer runtime decisions

Why it matters for data credibility:

- realistic coding traces are organized around inspecting failures and
  correcting them, not just around calling tools

Nearest `codex-rs` reference:

- `core` turn/session policy
- command and tool event handling around execution outcomes

What not to overbuild:

- no large planner abstraction just to express revise-after-failure

### Tool Surface And Execution Fidelity

Current state:

- the current structured tool set already covers high-frequency short loops

Target state:

- tool boundaries remain narrow, stable, and realistic under more complex loop
  behavior
- validation and edit actions compose more naturally

Why it matters for data credibility:

- tool schemas define what kinds of behavior become trainable rather than
  hidden in free-form command strings

Nearest `codex-rs` reference:

- `file-system`
- `file-search`
- `apply-patch`
- command execution subsystems

What not to overbuild:

- no tool-count vanity expansion
- no overlapping wrappers with weak data value

### Permission / Safety / Sandbox Boundary

Current state:

- protected write-surface and workspace cwd rules are enforced
- command results carry policy-shaped metadata, but this is not evidence that
  an executable allowlist or approval policy was enforced

Target state:

- permission-like runtime decisions become more explicit and visible
- environment capability and policy state become formal runtime facts

Why it matters for data credibility:

- permissions and safety rules shape what actions the model can attempt and how
  traces should later be interpreted

Nearest `codex-rs` reference:

- `shell-command`
- `execpolicy`
- `linux-sandbox`

What not to overbuild:

- no production-sandbox claim
- no platform-spanning containment program as a prerequisite

### Trace / Audit / Replay Fidelity

Current state:

- runtime trace is already an evidence layer for request, parse, mapping,
  execution, and stop decisions

Target state:

- runtime state transitions and policy choices become richer and easier to
  analyze across repeated runs
- auditability expands from "what happened" toward "why this runtime kept
  going, revised, or stopped"

Why it matters for data credibility:

- industrial-grade-like realism needs artifacts that can justify claims about
  runtime behavior, not just show outputs

Nearest `codex-rs` reference:

- `rollout-trace`
- session/turn lifecycle evidence

What not to overbuild:

- no full replay database or distributed event store

### Workload Realism And Data Credibility

Current state:

- deterministic toy smoke and controlled fake-client tasks dominate coverage

Target state:

- a small but more realistic workload program exists
- repeated-run analysis can explain what kinds of behavior the runtime actually
  exhibits

Why it matters for data credibility:

- without more realistic workloads, the data path is auditable but still not
  maximally convincing

Nearest `codex-rs` reference:

- not a single crate, but the overall session/turn stack is a reminder that
  mature systems are judged by behavior over realistic workloads, not by
  isolated feature demos

What not to overbuild:

- no benchmark-first campaign
- no premature claims about pass-rate wins

## Priority Decision

The current priority is behavior realism first.

That priority statement now acts as a maturity and acceptance rule, not as the
literal day-to-day implementation sequence. Concrete implementation order
should be taken from:

- `docs/codex_rs_subsystem_implementation_plan.md`

This document should instead be used to check whether the chosen subsystem work
is actually covering the intended realism gaps.

Priority order:

1. behavior realism
2. context, validation, and recovery realism
3. session, state, and orchestration maturity
4. stronger safety and permission contract maturity
5. broader product-like infrastructure later, if it still directly improves
   runtime realism or data credibility

This means the next move is not:

- adding more shallow ToolView mutations first
- building TUI or product shell infrastructure
- designing plugin or platform abstractions
- expanding tool count for surface-area vanity
- broadening multi-agent product orchestration ahead of local runtime realism

The central decision rule is:

- if two tasks both improve training data, choose the one that more directly
  improves source runtime realism and observed-data credibility

## Roadmap

### I1: Behavior-Realistic Short-Horizon Coding Loop

Objective:

- make inspect/edit/test/revise/finish a normal runtime pattern rather than a
  smoke-only special case

Exact in-scope changes:

- stronger replanning after failed validation
- finish only after evidence-backed completion
- more stable correction-turn discipline after failed tool or validation steps
- stronger mixed-content, tool-only, and corrective-turn policies

Explicit out-of-scope changes:

- no long-horizon planner framework
- no multi-agent orchestration redesign
- no benchmark result claims

Acceptance criteria:

- multiple deterministic tasks can exercise revise-after-failure, not just one
- validation failure regularly leads to corrective action before finish
- finish is deferred until completion evidence exists

Artifacts/tests expected:

- a new runtime-behavior smoke suite
- at least one multi-step correction-loop fixture
- trace assertions for replanning and deferred finish behavior

### I2: Context And State Realism

Objective:

- make context selection, history carryover, and runtime state handling look
  more like a real sessioned coding runtime

Exact in-scope changes:

- explicit message-window policy
- explicit summary/compaction hooks
- a formal turn-state object
- pending-issue state that persists beyond the current minimal recovery path

Explicit out-of-scope changes:

- no persistent thread-store architecture
- no app-server style remote session control

Acceptance criteria:

- context inclusion and exclusion rules become explicit runtime contract
- turn state is inspectable and traceable
- compaction or summary boundaries can be regression-tested

Artifacts/tests expected:

- context/state contract draft
- turn-state test fixtures
- trace fields covering state transitions and compaction decisions

### I3: Validation-Driven Runtime Policy

Objective:

- make validation a first-class runtime policy surface rather than a tool that
  merely exists in the loop

Exact in-scope changes:

- validation-loop templates
- issue classification for failures
- retry and revise budget rules
- stronger stop gating on unresolved validation failures

Explicit out-of-scope changes:

- no benchmark-specific validator zoo
- no complex planner-critic architecture

Acceptance criteria:

- unresolved validation failures are visible runtime facts
- retries and revise attempts follow stable policy
- stop decisions explicitly reflect validation state

Artifacts/tests expected:

- validation/recovery taxonomy expansion
- stop-policy regression tests
- trace enrichment around validation outcomes and retry budgets

### I4: Tool And Execution Boundary Maturity

Objective:

- mature the current high-frequency tool surface instead of expanding tool
  quantity

Exact in-scope changes:

- richer file operation contracts
- structured test and lint execution policy where it improves realism
- stronger patch and delta reporting
- execution-result normalization across file, patch, and validation tools

Explicit out-of-scope changes:

- no large tool-count increase
- no misleading product-mimic wrappers

Acceptance criteria:

- short realistic bug-fix loops rely on structured tools rather than command
  overload
- result surfaces remain stable under richer loop behavior

Artifacts/tests expected:

- richer result metadata fixtures
- execution-boundary contract tests
- behavior smoke that mixes read/write/patch/validate actions

### I5: Permission / Safety / Environment Maturity

Objective:

- make environment capability and permission-like runtime decisions more
  explicit without turning the project into a sandbox-first product effort

Exact in-scope changes:

- explicit permission states
- environment capability summary
- safer command and file escalation model
- stronger per-turn policy visibility in runtime trace

Explicit out-of-scope changes:

- no production-ready sandbox claim
- no platform-wide enforcement program

Acceptance criteria:

- permission and safety decisions become visible runtime facts
- traces can distinguish policy-denied, policy-limited, and allowed execution
  more clearly

Artifacts/tests expected:

- permission/safety contract draft
- policy trace fixtures
- safety-oriented repeated-run audit cases

### I6: Realistic Workload And Data Credibility Program

Objective:

- show that runtime source runs look credible beyond deterministic toy smoke

Exact in-scope changes:

- a small but more realistic workload pack
- repeated-run behavior analysis
- per-gap-axis audit metrics
- an observed-data credibility checklist

Explicit out-of-scope changes:

- no leaderboard campaign
- no broad benchmark harness as the immediate next step

Acceptance criteria:

- repeated runs over a realistic workload pack expose analyzable behavior
  distributions
- observed-data credibility can be argued from artifacts rather than inferred
  informally
- regressions in runtime realism become catchable

Artifacts/tests expected:

- a more realistic workload pack
- repeated-run audit outputs
- behavior-realism regression bundle
- credibility checklist for observed datasets

## Execution Order And Dependencies

This section should now be interpreted as a dependency-shaped maturity map,
not as the repository's sole concrete construction schedule.

The dependency chain for implementation is:

```text
I1 -> I2 -> I3
          \-> I4 (partially parallel after core behavior contracts stabilize)
I5 after I1-I4 are mostly stable
I6 throughout as feedback, but formal credibility program last
```

Execution order:

1. build stronger short-horizon behavior realism first
2. formalize context and state once the loop behavior is clearer
3. make validation policy drive runtime continuation and stopping
4. mature tool and execution boundaries under those stronger loop rules
5. then deepen permission and environment policy visibility
6. finally, prove the result on a more realistic workload and repeated-run
   audit program

Do not do first:

- rewriting runtime architecture
- building product shell infrastructure
- broadening multi-agent orchestration

## Success Criteria

This roadmap is succeeding when the following become true and remain stable:

1. source runs show revise-after-failure as normal behavior, not a single smoke
   trick
2. completion is gated by evidence-backed validation
3. context shaping is explicit and auditable
4. runtime state transitions are traceable turn by turn
5. tool execution boundaries remain structured under more realistic loops
6. permission and safety decisions become visible runtime facts
7. observed datasets come from more realistic source behavior
8. these properties remain regression-testable

## Short Summary

This document explains how to move from the current well-instrumented research
runtime and white-box observed-data producer toward industrial-grade-like
runtime realism without pretending that `R1-R6` already solved that harder
problem.

If choosing the next implementation move, prioritize stronger short-horizon
behavior realism, then context/state realism, then validation-driven runtime
policy, and only after that broaden the surrounding runtime infrastructure.
