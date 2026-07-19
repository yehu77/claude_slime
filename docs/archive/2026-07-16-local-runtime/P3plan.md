# P3 Continuation: Codex-rs-Aligned Context / Compaction Deepening Plan

> Archived by RC-015 on 2026-07-16. This is historical implementation
> evidence, not a current construction schedule. See this archive's README for
> provenance, completion status, and replacement documents.

## Summary

The next step should stop treating `Context`, `History`, and `Compaction` as scattered features and instead deepen them as one formal runtime subsystem, aligned to the way `codex-rs` separates these concerns.

This should be split into **two milestones**:

1. **P3-A: Context / History Selection Discipline**
2. **P3-B: Model-Backed Compaction Backend**

The primary `codex-rs` references for this work are:

- `codex-rs/core/src/session/turn.rs`
- `codex-rs/core/src/context_manager/history.rs`
- `codex-rs/core/src/compact.rs`
- `codex-rs/core/src/compact_remote.rs`
- `codex-rs/core/src/compact_remote_v2.rs`
- `codex-rs/message-history/src/lib.rs`

The repo already has:
- typed `TurnState`
- deterministic `tail_window` / `deterministic_compaction`
- retained-history artifacts
- an early separation between full trajectory and request-time selected context

So this is not a greenfield plan. The goal is to move the current implementation from “works” to “resembles a real codex-rs-style context/history subsystem.”

## P3-A: Context / History Selection Discipline

### Goal

First make the boundary between **retained runtime history** and **the exact context sent in the current request** fully explicit, closer to the `codex-rs` `message-history + for_prompt(...)` model.

This milestone should **not** use a real summarization model yet. It should harden the context/history contract first.

### Key Changes

- Add a formal compaction/context orchestration layer, preferably in `pycodeagent/agent/compaction.py`.
  - Do not keep spreading this logic across `turn_state.py`, `history_manager.py`, and `runner.py`.
  - This layer should own:
    - compaction trigger decisions
    - retained-vs-selected history splitting
    - replacement summary slot planning
    - carried-forward state assembly
    - compaction artifact generation

- Narrow the role of `RuntimeHistoryManager`.
  - It should own retained-history persistence and replacement-history persistence.
  - It should no longer make implicit compaction policy decisions on its own.
  - Policy decisions should come from the new compaction/context orchestration layer.

- Freeze two history views as formal runtime concepts:
  - `retained_history`
    - append-only runtime history artifact
    - includes original messages, replacement summaries, carried-forward state, and history-control facts
  - `selected_context`
    - the actual message view sent to the model for the current request
    - a request-time projection, not the source-of-truth history

- Make compaction triggering an explicit contract instead of “if too long, trim.”
  - At minimum support:
    - `full_history`
    - `tail_window`
    - `deterministic_compaction`
  - Reserve a formal mode for later:
    - `model_backed_compaction`
  - Trigger decisions must record:
    - why compaction was considered
    - why it was or was not applied
    - what span was replaced
    - what pinned messages were preserved

- Harden the carried-forward state contract.
  - There is already an early carried-forward-state shape. P3-A should freeze it as a formal structure.
  - At minimum preserve:
    - pending issue summary
    - latest validation status summary
    - unresolved failure summary
    - important recent tool/result facts
  - It should remain a deterministic artifact, not a model-generated summary.

- Strengthen runtime trace coverage without adding a second trace system.
  - Either add explicit events such as:
    - `context_selection_planned`
    - `context_compaction_applied`
    - `context_compaction_skipped`
  - Or make the existing `model_request_built` evidence fully sufficient and stable.
  - The trace must answer:
    - why full history was not used
    - which turn/message span was compacted
    - what replacement summary and carried-forward state were used

### Likely Implementation Surface

Focus changes on:

- `pycodeagent/agent/history_manager.py`
- `pycodeagent/agent/turn_state.py`
- `pycodeagent/agent/runner.py`
- new `pycodeagent/agent/compaction.py`
- `pycodeagent/agent/retained_history.py`

### P3-A Acceptance Standard

This milestone is complete when:

- the runtime has a formal retained-history vs selected-context contract
- deterministic compaction is no longer just a one-off pre-request transformation
- trace data can explain compaction decisions in a stable way
- full trajectory remains preserved, but is no longer implicitly equal to request-time context
- long-history behavior is no longer just “dump all messages into the request”

## P3-B: Model-Backed Compaction Backend

### Goal

Once P3-A freezes the contract, add a true **model-backed compaction backend** following the shape of `codex-rs/core/src/compact_remote.rs` and `compact_remote_v2.rs`.

The point is not merely “write a summary prompt.” The point is to make compaction a **first-class runtime request kind with its own artifacts and provider contract**.

### Key Changes

- Extend the `GenerateRequest` / `GenerateResponse` contract so compaction becomes a formal request type.
  - Recommended additions:
    - `request_kind: "agent_turn" | "context_compaction"`
    - `response_format` or `structured_schema`
  - `GenerateResponse` should gain:
    - `structured_output`
    - minimal structured response payload support for compaction
  - Compaction must stop pretending to be a normal agent turn.

- Extend client capability contracts.
  - `RuntimeClientCapabilities` should explicitly carry:
    - whether model-backed compaction is supported
    - whether structured compaction output is supported
    - provider-family expectations for compaction
  - Do not add hidden probing. Keep capability explicit.

- Add a formal compaction request/response schema.
  - This should stay as structured as possible.
  - Compaction output should at minimum include:
    - summary text
    - carried-forward state object
    - compacted span metadata
    - unresolved issues carried forward
  - If a provider cannot produce stable structured compaction output, treat the backend as unavailable instead of silently degrading to arbitrary text.

- Add a dedicated compaction prompt builder in `prompt.py`.
  - Explicitly separate:
    - normal agent prompt construction
    - compaction prompt construction
  - The compaction prompt input should be fixed to:
    - retained-history span
    - pinned context
    - current pending issue / validation state
    - output schema contract
  - This should align with the `codex-rs` “compact task” mental model, not ordinary conversational prompting.

- Add a formal summary-slot update mechanism in the history subsystem.
  - After successful model-backed compaction:
    - retained history receives a summary artifact
    - selected context uses the replacement summary instead of the old long span
  - On compaction failure:
    - record the failure explicitly
    - fall back to deterministic compaction or no compaction only via explicit policy
  - No silent fallback.

- Add compaction-specific trace evidence.
  - At minimum record:
    - compaction requested
    - compaction backend used
    - compaction success / failure
    - summary payload ref
    - carried-forward state payload ref
    - fallback decision
  - This is required so later audits can explain how a request-time context was shaped.

### Likely Implementation Surface

Focus changes on:

- `pycodeagent/agent/llm_client.py`
- `pycodeagent/agent/openai_native_client.py`
- `pycodeagent/agent/mimo_native_client.py`
- `pycodeagent/agent/prompt.py`
- `pycodeagent/agent/compaction.py`
- `pycodeagent/agent/history_manager.py`
- `pycodeagent/agent/runner.py`

### P3-B Acceptance Standard

This milestone is complete when:

- compaction is a formal runtime subsystem rather than incidental logic
- model-backed compaction requests are clearly separated from normal agent turns
- compaction output follows a structured contract rather than free-form summary text
- compaction success, failure, and fallback are natively auditable in trace artifacts
- long-history context shaping is materially closer to the `codex-rs` runtime shape than to simple truncation

## Test Plan

### Deterministic Tests

- Extend `tests/test_context_policy.py`
  - retained vs selected context split is stable
  - deterministic compaction span, pinned messages, and carried-forward state are stable
- Extend `tests/test_history_manager.py`
  - retained-history append-only behavior
  - replacement-summary and carried-forward-state persistence
- Extend `tests/test_agent_runner.py`
  - request-time selected context remains separate from full trajectory
  - compaction trigger / skip / apply is testable
- Extend `tests/test_runtime_trace_events.py`
  - context/compaction evidence is fully visible in runtime trace

### Model-Backed Compaction Tests

- Add mocked client tests for compaction backend behavior:
  - structured compaction output success
  - malformed compaction output
  - capability disabled
  - explicit fallback path
- Add runner-level orchestration tests:
  - normal turn
  - compaction request
  - compaction result reinjected into selected context
- If golden traces are maintained, add one compaction-specific golden bundle
  - at least one real compaction replacement path should be frozen

### Real-Provider Acceptance

After each milestone, run a small acceptance check, but do not let it define architecture:

- After P3-A:
  - run a longer-history task and confirm deterministic compaction artifacts are produced correctly
- After P3-B:
  - run a longer-history real-provider task
  - confirm model-backed compaction actually triggers
  - confirm trace contains compaction request / result / replacement summary evidence

## Assumptions And Defaults

- The P3 “history baseline” is already done; this plan is specifically for deepening `Context / Compaction`.
- Splitting into two milestones is the preferred control strategy:
  - P3-A hardens the contract and orchestration
  - P3-B adds the model-backed compaction backend
- `codex-rs` is the implementation reference, especially:
  - `message-history` for retained-history discipline
  - `core` for turn lifecycle and compaction-task boundaries
  - `compact_remote` for model-backed compaction shape
- Real-provider runs are acceptance only, not architecture drivers.
- This plan should not expand into:
  - new tool growth
  - stop-policy rewrite
  - dataset-schema redesign
  - product/TUI work
