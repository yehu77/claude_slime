# claude_slime

`claude_slime` is a research repository for **coding-agent tool-use data**.

Its focus is not building a polished coding assistant. The focus is building a
trustworthy path from:

- a coding task
- to the tool schema a model actually sees
- to the tool calls it actually emits
- to deterministic training data and `slime`-compatible bundles

In practical terms, this repo is about one question:

> If the visible tool schema changes, will the model still follow the tool
> interface it is shown, instead of relying on memorized names and argument
> shapes?

## What This Project Does

This repository combines four things:

1. a repo-owned local coding-agent runtime
2. tool-schema mutation and ToolView control
3. trace and trajectory capture with audit artifacts
4. downstream training-data preparation for tool-use learning

The end-to-end path looks like this:

```text
task
  -> local runtime or external trace source
  -> visible tool schema / ToolView
  -> assistant tool calls + tool results
  -> trajectory + runtime trace
  -> observed dataset export
  -> tokenization + loss-mask alignment
  -> contract verification
  -> slime-compatible training bundle
```

## Why It Exists

Most tool-use training setups quietly assume the tool interface is fixed.
Real systems are messier:

- tool names can change
- argument names can change
- flat schemas can become nested
- tool order can change
- different runtimes can expose different views of the same backend capability

This repo is built to study exactly that setting. The goal is to produce data
that teaches **schema-following behavior**, not just memorization of canonical
tool names.

## What Is Already Working

The current repository already supports:

- a white-box local coding-agent runtime with native tool-calling
- canonical backend tools separated from exposed ToolViews
- controlled ToolView mutation, including:
  - argument rename
  - flat-to-nested schema mutation
  - tool reorder
- runtime traces and structured trajectories for local runs
- observed dataset export from real runtime runs
- training-prep output with tokenization and assistant-tool-call-only loss masks
- `slime`-compatible downstream bundle generation
- real-provider runs through an OpenAI-compatible endpoint

That means the mainline is no longer just “can we simulate this?” It is already
possible to:

1. change the visible tool schema
2. run a real model against that schema
3. export the resulting tool-use traces as training data

## Current Mainline

The current mainline is:

**make the repo-owned local runtime realistic enough to serve as a credible
source of observed tool-use data, then use that runtime to study schema
mutation under real provider runs.**

Concretely, the repository now emphasizes:

- runtime realism and auditability
- observed data over synthetic-only projection
- ToolView mutation as a first-class research surface
- deterministic downstream training-data contracts

## Quick Start

Run the test suite:

```powershell
python -B -m pytest tests -q
```

Run a real-provider smoke test:

```powershell
python run_runtime_smoke_real_provider.py
```

Run the real-provider ToolView-mutation data path:

```powershell
python run_toolview_mutation_data_generation.py
```

Prepare a training bundle from study / experiment / batch outputs:

```powershell
python prepare_slime_training_data.py runs/studies/first_mutation_sensitivity_mimo_v25pro runs/training_prep ^
  --source-type study ^
  --fake-tokenizer
```

If you are using a real tokenizer, replace `--fake-tokenizer` with:

```powershell
--tokenizer-name path-or-hf-tokenizer-name
```

## Repository Layout

- `pycodeagent/`: runtime, tools, mutation logic, export code, and training-prep
- `tests/`: owned regression suite and golden fixtures
- `configs/`: tool mutation config and local runtime/provider config
- `datasets/`: task packs used for runtime studies
- `docs/`: design notes, implementation plans, and runbooks
- `examples/`: small example workspaces and tasks
- `slime-main/`: vendored `slime` tree plus the repo-owned bridge layer
- `codex-rs/`: local reference source tree for runtime-subsystem alignment work

## What This Project Is Not

This repository is not currently trying to be:

- a Codex clone product
- an IDE extension
- a benchmark-first coding-agent repo
- a production sandbox
- a full RLHF / PPO / GRPO stack
- a place to claim state-of-the-art coding performance

The value here is **data quality, runtime transparency, schema control, and
training contract integrity**.

## Important Documents

If you want the shortest path into the repo:

- [CLAUDE.MD](./CLAUDE.MD): project intent and decision rules
- [AGENTS.md](./AGENTS.md): repository-level guidance for agents and implementers
- [docs/local_runtime_realism_mainline_plan.md](./docs/local_runtime_realism_mainline_plan.md):
  why runtime realism is the current front-half priority
- [docs/local_runtime_85_maturity_execution_plan.md](./docs/local_runtime_85_maturity_execution_plan.md):
  the higher-bar runtime maturity plan
- [docs/codex_rs_subsystem_implementation_plan.md](./docs/codex_rs_subsystem_implementation_plan.md):
  subsystem-by-subsystem runtime implementation order
- [docs/toolview_mutation_data_generation_plan.md](./docs/toolview_mutation_data_generation_plan.md):
  the current real-provider schema-mutation data generation path
- [docs/native_transformed_sft_pipeline.md](./docs/native_transformed_sft_pipeline.md):
  minimal path from real API trace to training-prep output
- [PYCODEAGENT_MULTI_AGENT_SCAFFOLD_DESIGN.md](./PYCODEAGENT_MULTI_AGENT_SCAFFOLD_DESIGN.md):
  broader long-term raw-trace scaffold direction

## Notes

- Keep secrets in environment variables or machine-local config.
- Large model weights and caches should stay outside the source tree.
- If you change rollout, export, tokenizer, serializer, or contract behavior,
  update tests in the same turn.

