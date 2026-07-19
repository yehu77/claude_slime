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
- fail-closed retention manifests, indexes, and checksums for every new run
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

```bash
python -B -m pytest tests -q
```

Inspect the stable command tree:

```bash
python -B -m pycodeagent --help
```

Run deterministic offline acceptance:

```bash
python -B -m pycodeagent acceptance \
  --local-only \
  --output-root /tmp/pycodeagent-acceptance
```

Run the real-provider ToolView-mutation data path:

```bash
python -B -m pycodeagent campaign \
  --kind toolview \
  --output-root runs/formal_cli/toolview \
  --provider-config /path/to/machine-local-provider.json \
  --fake-tokenizer
```

Prepare a training bundle from campaign runs:

```bash
python -B -m pycodeagent prep \
  --source-dir runs/formal_cli/toolview/runs \
  --output-dir runs/formal_cli/training_prep \
  --source-type batch \
  --fake-tokenizer
```

Fake tokenization is for deterministic contract checks. For real
tokenization, replace `--fake-tokenizer` with
`--tokenizer-name path-or-hf-tokenizer-name`. See
[the formal CLI contract](./docs/formal_cli.md) for configuration precedence,
exit codes, JSON output, and all six subcommands.

## Repository Layout

- `pycodeagent/`: runtime, tools, mutation logic, export code, and training-prep
- `tests/`: owned regression suite and golden fixtures
- `configs/`: tool mutation config and local runtime/provider config
- `datasets/`: task packs used for runtime studies
- `docs/`: design notes, implementation plans, and runbooks
- `examples/`: small example workspaces and tasks
- `slime-main/`: vendored `slime` tree plus the repo-owned bridge layer; its
  exact upstream source is frozen in
  [`references/slime-upstream.lock.json`](./references/slime-upstream.lock.json)
  and its nine repo-owned files are governed by
  [`references/slime-overlay.manifest.json`](./references/slime-overlay.manifest.json)
- `codex-rs/`: optional ignored reference tree for runtime-subsystem alignment;
  its exact source and checksum are tracked in
  [`references/codex-rs.lock.json`](./references/codex-rs.lock.json), and no
  runtime or ordinary test depends on its presence

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

- [AGENTS.md](./AGENTS.md): canonical, tool-neutral project intent and decision
  rules
- [CLAUDE.md](./CLAUDE.md): Claude Code compatibility entrypoint; repository
  rules remain canonical in `AGENTS.md`
- [docs/README.md](./docs/README.md): the canonical documentation map, reading
  order, ownership, and archive boundary
- [docs/adr/0001-native-family-runtime-boundary.md](./docs/adr/0001-native-family-runtime-boundary.md):
  native-family terminology, selection, fallback, artifact, and acceptance contract
- [docs/codex_rs_subsystem_implementation_plan.md](./docs/codex_rs_subsystem_implementation_plan.md):
  the sole current subsystem-by-subsystem construction driver
- [docs/codex_rs_reference.md](./docs/codex_rs_reference.md): exact source,
  checksum verification, and optional bootstrap for the ignored `codex-rs/`
  reference tree
- [docs/formal_cli.md](./docs/formal_cli.md): stable subcommands, configuration
  precedence, exit codes, and machine-readable output
- [docs/local_runtime_industrial_gap_roadmap.md](./docs/local_runtime_industrial_gap_roadmap.md):
  maturity map and acceptance framework
- [docs/tool_runtime_native_family_acceptance_and_regression_plan.md](./docs/tool_runtime_native_family_acceptance_and_regression_plan.md):
  current native-family acceptance runbook
- [docs/source_route_boundaries.md](./docs/source_route_boundaries.md): controlled
  baseline and auxiliary-route ownership/dependency rules
- [PYCODEAGENT_MULTI_AGENT_SCAFFOLD_DESIGN.md](./PYCODEAGENT_MULTI_AGENT_SCAFFOLD_DESIGN.md):
  broader long-term raw-trace scaffold direction

## Notes

- Keep secrets in environment variables or machine-local config.
- Large model weights and caches should stay outside the source tree.
- If you change rollout, export, tokenizer, serializer, or contract behavior,
  update tests in the same turn.
