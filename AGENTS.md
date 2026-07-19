# Repository Agent Instructions

This file is the tool-neutral source of truth for repository intent,
priorities, contracts, and decision rules. Agent-specific entrypoints should
link here and contain only genuine environment-specific differences.

## Project Goal

This repository is building a coding-agent research scaffold whose main
deliverable is not a polished coding product, but a robust multi-agent raw
trace collection and training-prep pipeline for tool-use trajectories.

The current end goal is:

> Build a reproducible, contract-aware multi-agent coding trace scaffold that
> can collect native tool schemas and raw traces from real coding agents,
> preserve the model-visible tool schema each agent actually exposes, apply
> schema mutation or view transformation, and route the resulting data through
> the existing serializer, loss-mask, and slime-compatible training-prep
> infrastructure.

In short:

**`pycodeagent` should collect high-integrity multi-agent trace artifacts,
preserve native tool schemas, transform those schemas in controlled ways, and
turn the result into slime-compatible training data.**

At the current stage, the highest-priority front-half for that goal is the
repo-owned local runtime: it should become a higher-fidelity, white-box,
observed ToolView training-data producer before the broader multi-agent
scaffold becomes the dominant mainline again.

---

## What This Repository Is

This repo is a combination of:

1. a coding-task and workspace execution harness
2. a repo-owned coding-agent runtime
3. a trajectory, verifier, reward, and status recorder
4. a rollout / dataset / tokenization / packing pipeline
5. a training-bundle preparation bridge to `slime`
6. a tool-schema mutation and view-transformation research harness
7. an observed ToolView training-data producer built on the local runtime
8. an evolving multi-agent raw trace collection scaffold

The intended end-to-end path is:

```text
task
  -> real agent adapter or repo-owned runtime
  -> raw tool catalog and raw trace
  -> canonical trace / trajectory
  -> schema mutation / view transformation
  -> dataset build
  -> tokenization
  -> loss-mask alignment
  -> packing
  -> contract verification
  -> slime-compatible training bundle
```

---

## What This Repository Is Not

This repository is not currently trying to be:

- a polished Codex clone
- an IDE extension
- a complete MCP platform
- a production coding assistant
- a benchmark-first eval repo
- a full RLHF / PPO / GRPO training stack
- a place to claim state-of-the-art coding-agent results

Those may become adjacent later, but they are not the current line of work.

---

## Current Primary Objective

The current primary objective is two-layered.

The current first-priority mainline is:

**mature the repo-owned local runtime into a higher-fidelity, white-box,
schema-controllable observed training-data producer without losing the current
data contracts.**

The concrete implementation rule inside that mainline is now:

- `codex-rs` subsystem implementation first
- small real-provider task packs second, as acceptance and regression

The next layer is:

**continue connecting that runtime-centered data path back into the broader
multi-agent raw-trace scaffold once the local source runtime is more realistic
and more auditable.**

That means current work should optimize for:

1. deterministic, reproducible outputs
2. explicit manifests and contracts
3. tool-profile and tokenizer version clarity
4. trajectory completeness
5. reward / verifier / status integrity
6. serializer and loss-mask correctness
7. native tool-catalog and raw-trace preservation
8. canonical capability normalization
9. tool-schema mutation and view transformation
10. downstream training-data compatibility
11. source runtime realism and observed-data fidelity

Do not optimize first for:

1. end-user UX
2. benchmark leaderboard results
3. broad product feature expansion
4. production sandbox claims
5. RL training claims before SFT/data quality is proven

---

## Core Research Question

The key question is:

> Can we preserve the real tool schema shown to a model by different coding
> agents, transform that schema in controlled ways, and generate training data
> that teaches schema-robust tool use rather than hard-coded tool names?

The model should learn that:

1. tool names may change
2. descriptions may be paraphrased
3. argument names may change
4. flat schemas may become nested
5. tool order may change
6. distractor tools may exist
7. the correct output must follow the exposed `ToolView`, not the canonical
   backend name

This means a backend-correct call can still be a schema-following failure if it
uses stale tool names or stale argument structure.

---

## Practical Success Criteria

At the current stage, this project is succeeding if:

1. coding tasks run consistently under controlled tool profiles
2. the same task can run end-to-end under multiple ToolViews
3. runs preserve complete structured trajectories and runtime trace bundles
4. verifier, reward, final status, and exposed/canonical tool boundaries are
   retained
5. observed runtime datasets are first-class outputs rather than side effects
6. schema mutation data is generated from realistic source runs rather than
   synthetic-only projection
7. rollouts and sample exports are deterministic
8. dataset manifests and contracts fail loudly on bad data
9. tokenization, masks, and packing stay aligned
10. prepared bundles can be consumed by `slime` without ad hoc manual fixes
11. the downstream serializer / loss-mask / training-prep path remains stable
    under transformed and runtime-observed samples

It is not necessary yet to prove:

- strong coding-agent pass-rate gains
- long-horizon autonomous bug fixing
- RL superiority over SFT
- production-readiness

---

## Existing Foundation To Preserve

The repo already has important foundations that should be extended, not
casually replaced:

1. provider-agnostic agent runtime and fake-client tests
2. canonical tool backend separated from exposed tool views
3. full trajectory representation as the source of truth for run data
4. append-only runtime trace bundles for local runtime runs
5. observed runtime exporter and runtime-observed training-prep
6. deterministic rollout/sample/tokenized/packed export
7. shared serializer and loss-mask alignment logic
8. read-only contract verification
9. slime-compatible training-prep bundle generation
10. Codex API trace ingestion can exist as an auxiliary source, but it should
    not redefine the repository's mainline away from runtime-centered and
    multi-agent trace collection

See [docs/auxiliary/native_transformed_sft_pipeline.md](./docs/auxiliary/native_transformed_sft_pipeline.md)
for the minimal end-to-end path from real Codex API trace to
native-transformed SFT training-prep output.

Important architectural principles:

1. `CanonicalTool -> ToolView -> ToolAdapter` remains the central abstraction.
2. Canonical backend semantics stay stable while model-visible schemas mutate.
3. Every run preserves task ID, tool profile ID, reward, status, and verifier
   output.
4. Internal contracts are more important than convenience shortcuts.
5. Canonical tool names must not leak where only exposed ToolViews should
   appear.

---

## Immediate Next Milestones

The next stage of work should generally follow this order:

1. Improve local runtime behavior realism and short-horizon recovery.
2. Refine prompt shape, stop rules, and post-error continuation behavior.
3. Continue hardening the realistic but controlled builtin tool surface.
4. Run deeper ToolView mutation studies on top of more realistic source runs.
5. Scale runtime-observed dataset generation through experiments and studies.
6. Continue preserving and extending the broader multi-agent raw-trace
   scaffold as a parallel and later integration target.
7. Normalize wider raw traces into canonical capabilities.
8. Reuse the existing tokenization / mask / packing / contract infrastructure.

The concrete build order for the runtime side should now be taken from:

- `docs/codex_rs_subsystem_implementation_plan.md`

That document is the implementation driver. `docs/local_runtime_industrial_gap_roadmap.md`
should now be read as the maturity and acceptance framework, not as the sole
construction schedule.

Phase-one rule:

- `RawAgentTrace` must exist as a first-class contract and artifact
- it does not need to come from a real external coding agent yet
- use `MockAdapter` and synthetic traces first to harden schema
  generalization, augmentation, contract checks, and slime bundle generation
- real external raw-trace ingestion is a later integration milestone
- Codex API trace and conservative SFT paths are useful side paths, not the
  top-level repository identity

If you need a single most important missing capability at the current stage, it
is:

**a more realistic, better-audited local coding runtime that can produce
higher-quality observed tool-use traces under controlled ToolViews.**

The broader multi-agent scaffold still matters, but the local runtime is
currently the fastest path to better schema-following data quality.

The canonical reference for that scaffold target is
`PYCODEAGENT_MULTI_AGENT_SCAFFOLD_DESIGN.md`.
The phase-one contract freeze and golden mock bundle live in
`docs/scaffold_phase1.md` and `examples/multi_agent_mock_run/`.

---

## Runtime Contract

The minimal agent loop is conceptually:

```python
while not done:
    response = llm.generate(messages, tools=current_tool_specs)
    assistant_msg, tool_calls = parse_response(response)
    trajectory.add_assistant(assistant_msg)

    for call in tool_calls:
        result = tool_runtime.execute(call, profile=tool_profile)
        trajectory.add_tool_result(call, result)
        messages.append(tool_result_message(result))

    done = should_stop(response, tool_calls, max_turns)
```

Required runtime properties:

1. the model only sees the currently exposed tool profile
2. actual execution always resolves to the canonical backend tool
3. exposed schema validation happens before backend execution
4. tool observations are returned to message history
5. the full run is recorded as one complete trajectory

---

## Training Data Contract

The training-data side should preserve, at minimum:

1. serialized text
2. segment structure
3. character-level trainability mask
4. token-level trainability mask
5. reward
6. status
7. verifier fields
8. task / profile / split metadata

For downstream SFT-style tool-use training, the intended loss-mask policy is:

**assistant tool-call tokens only**

Do not silently drop or reinterpret these fields anywhere in the pipeline.

---

## Non-Goals

Unless explicitly requested, do not prioritize:

- VS Code integration
- full CLI productization
- UI polish
- plugin ecosystems
- broad provider integration for its own sake
- large benchmark campaigns
- full RL engineering before SFT/data quality is stable
- major refactors that do not improve contracts, reproducibility, or
  schema-following data generation

---

## Decision Rule For Future Work

When choosing between tasks, prefer the one that most improves:

1. data integrity
2. reproducibility
3. contract clarity
4. source runtime realism and observed-data fidelity
5. training-data generation from transformed tool-use traces
6. downstream training compatibility
7. end-to-end stability from task run to training bundle

If two tasks both serve training data, prefer the one that more directly
improves the realism of the source runtime and the fidelity of the resulting
observed data.

More specifically:

- prefer direct `codex-rs` subsystem mapping over trying to infer runtime
  architecture from a tiny workload pack
- prefer subsystem maturity work over adding more small tasks when the tasks
  would not change the architecture decision
- use small real-provider workloads for acceptance, regression, and evidence,
  not as the primary architecture driver

Prefer not to spend time first on work that mainly improves:

1. polish
2. feature breadth
3. UI
4. non-essential abstraction
5. ambitious training claims without a stable, validated data path

---

## Short Summary For Other Agents

If you only need one sentence:

> This repository builds multi-agent coding trace infrastructure whose main job
> is to preserve native tool schemas, transform them in controlled ways, and
> feed the result into deterministic downstream training-data infrastructure.

If you need one practical instruction:

> Optimize first for a realistic, white-box local runtime that produces
> auditable observed training data, drive implementation by the most relevant
> `codex-rs` subsystems, and use small real-provider runs only to validate the
> resulting behavior before connecting that path into broader raw-agent and
> transformed-training-data infrastructure.
