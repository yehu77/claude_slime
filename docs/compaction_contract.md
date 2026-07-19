# Runtime Compaction Contract v1

This document freezes the request-history compaction behavior accepted by
RC-033. It is a runtime contract, not a new implementation schedule. Changes
to the inputs, selection boundaries, failure taxonomy, event order, or
persistence fields below require a contract-version decision and corresponding
contract-test updates.

## Authority and Ownership

`pycodeagent.agent.compaction` is the canonical owner of request-history
selection, compaction planning, model-backed output validation, and fallback.
`pycodeagent.agent.turn_state` owns the state models and token estimator and
keeps `select_request_messages` only as a compatibility entrypoint that
delegates to the canonical owner. RC-034 removed its private selector and
compaction-helper copies after proving that the public delegation and this
contract suite remained unchanged.

The active result type is `ContextSelectionPlan`. The structured response from
the compaction request is `ModelBackedCompactionOutput`.
`ModelBackedCompactionResult` was removed by RC-033 because it had no consumer
and duplicated state already represented by `ContextSelectionPlan`.

## Inputs and Outputs

A selection decision receives:

- an ordered, append-only list of trajectory messages;
- one policy mode: `full_history`, `tail_window`,
  `deterministic_compaction`, or `model_backed_compaction`;
- an optional message limit;
- an optional context-token limit plus tool and response reserves;
- runtime session state and turn index when a summary must carry recovery
  state.

It returns one `ContextSelectionPlan`. The plan records the selected messages,
selection indices, budget measurements, whether the budget is satisfied,
compacted turns, synthetic summary, compaction artifact, model-backed status,
and any explicit fallback evidence. Selection changes the model-visible
request only; it never deletes or rewrites the raw trajectory.

## Frozen Behavior Matrix

| Mode | Selection and summary behavior | Budget boundary |
| --- | --- | --- |
| `full_history` | Retain every message in original order; do not synthesize a summary. | Report overflow explicitly; do not truncate history. |
| `tail_window` | Pin the leading system/user context and retain the newest remaining messages in original order; do not synthesize a summary. | Apply both message and token limits; set `budget_satisfied` false if the pinned/minimal window alone cannot fit. |
| `deterministic_compaction` | Start from the tail-window boundary, compact complete older turns only, preserve the recent/pending-issue window, and insert a deterministic summary with carried-forward recovery state. | The summary participates in the budget calculation; an impossible budget remains explicit rather than causing hidden deletion. |
| `model_backed_compaction` | First create exactly the deterministic plan and compacted span, then request a structured replacement for that summary. | Accept the replacement only when its message, turn, and pinned spans exactly match the deterministic plan; otherwise retain the deterministic plan. |

For the same corpus and limits, the legacy private selectors and the canonical
selectors were byte-equivalent under `model_dump(mode="json")` when RC-033 was
frozen. That equivalence is temporary deletion evidence, not shared ownership.

## Model-Backed Output and Failure Policy

The structured output has exactly three required top-level fields:
`summary_text`, `carried_forward_state`, and `compacted_span`. The model may
rewrite the summary and carried state, but it may not choose a different source
span.

The only model-backed backend in contract v1 is `inline_model`. Every accepted
failure falls back to `deterministic_compaction`:

| Failure kind | Meaning | Required result |
| --- | --- | --- |
| `capability_unavailable` | Client cannot issue the structured compaction request. | Keep the deterministic plan and continue. |
| `provider_error` | The compaction request raised a provider/runtime error. | Keep the deterministic plan and continue. |
| `structured_output_parse_error` | No parseable structured output was returned. | Keep the deterministic plan and continue. |
| `schema_validation_error` | Parsed output violates the v1 schema. | Keep the deterministic plan and continue. |
| `compacted_span_mismatch` | Output claims a different compacted or pinned span. | Keep the deterministic plan and continue. |

Unknown backend names, fallback policies, and failure kinds fail loudly. A new
failure kind is therefore a contract change rather than an untracked string.

## Append-Only Event Order and Continuation

On success, one compaction attempt records this order before the ordinary model
request:

```text
context_compaction_requested
context_compaction_completed
context_selection_planned
context_compaction_applied
model_request_built
```

On failure, `context_compaction_failed` replaces the completed event. The
fallback plan is then recorded and the ordinary agent request still runs:

```text
context_compaction_requested
context_compaction_failed
context_selection_planned
context_compaction_applied
model_request_built
model_response_received
```

The failed event must record its failure kind, deterministic fallback policy,
and `fallback_applied=true`. The applied event must retain
`model_backed_requested=true`, `model_backed_used=false`, and the selected
deterministic summary. A compaction failure is evidence, not a terminal agent
error.

## Persistence and Recovery

The runtime trace remains append-only. Compaction evidence is persisted through
the request context, retained-history lineage, selection plan, and versioned
compaction artifact. The artifact keeps source message and turn indices,
pinned indices, summary slot, carried-forward state, and the relationship to
the retained request history. Recovery state used by a later turn must come
from this recorded plan/artifact, never from an unrecorded mutation of the raw
messages.

## Canonical-Owner Gate

The RC-034 deletion established these ongoing requirements:

1. all callers use the canonical module or the delegating compatibility
   entrypoint;
2. the behavior corpus and budget-boundary tests remain green;
3. model-backed success and every frozen failure kind retain the same output;
4. append-only success/failure event-order tests remain green; and
5. private selection and compaction helpers are defined only by the canonical
   module.

The executable contract is primarily covered by
`tests/test_compaction_contract.py`, `tests/test_context_policy.py`, and
`tests/test_p3b_compaction_acceptance.py`.
