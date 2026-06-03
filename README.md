# claude_slime

`claude_slime` is a coding-agent research repo focused on one job:
build a reproducible, contract-aware multi-agent coding trace scaffold that can
collect real agent raw traces, preserve the native tool schemas those agents
actually expose to the model, mutate or transform those schemas into alternate
views, and turn the result into deterministic training data plus
slime-compatible training bundles.

This repo is not trying to become a polished Claude Code clone, a full
production coding product, or a complete RL training stack. The current story
is narrower and more defensible:

1. Run the same coding task under multiple real or repo-owned agent backends.
2. Preserve the native tool schema actually shown to the model.
3. Preserve raw traces and run artifacts from those agents.
4. Normalize or reinterpret those traces through canonical capabilities when
   needed.
5. Apply schema mutation or view transformation to produce alternate
   model-visible tool schemas.
6. Export deterministic training datasets from those traces and transformed
   schemas.
7. Reuse the existing serializer, tokenizer, loss-mask, packing, and
   contract-checking stack.
8. Prepare slime-compatible downstream training bundles.

Primary design guidance lives in [CLAUDE.MD](./CLAUDE.MD). The current
repository-level target architecture lives in
[PYCODEAGENT_MULTI_AGENT_SCAFFOLD_DESIGN.md](./PYCODEAGENT_MULTI_AGENT_SCAFFOLD_DESIGN.md).

## Core Idea

The main research question is:

> Can a model follow the current tool schema shown in the prompt, instead of
> memorizing fixed canonical tool names and argument names?

That means the important output of this repo is not "a strong coding agent".
The important output is a trustworthy data pipeline:

```text
task
  -> repo-owned runtime or real agent adapter
  -> native tool catalog / raw trace
  -> canonical trace / trajectory
  -> schema mutation / view transformation
  -> dataset build
  -> tokenization
  -> loss-mask alignment
  -> packing
  -> contract verification
  -> slime-compatible training bundle
```

## Repository Layout

- `pycodeagent/`: main runtime, tool system, mutation logic, eval code, and
  RL/training-prep pipeline
- `tests/`: repo-owned test suite for the pycodeagent stack
- `configs/`: tool profiles, study config, and local runtime config
- `examples/`: small local example repos and tasks
- `slime-main/`: vendored upstream slime tree plus the pycodeagent offline
  bridge
- `models/`: legacy in-repo local model assets; new weights and caches should
  live outside the source tree

## Current Repo State

The repo already has the core foundation for:

- controlled tool-profile rendering through canonical tools, ToolViews, and
  adapters
- full trajectory capture and verifier/reward/status recording
- deterministic rollout export and dataset manifests
- shared serializer and mask-alignment logic
- contract verification and training-prep bundle generation
- repo hygiene checks and machine-local config/model path support
- schema-following synthetic and trajectory-derived data generation
- schema-following local SFT and before/after evaluation reports

The current downstream schema-following pipeline is already implemented.
It should now be treated as downstream infrastructure, not the repo's primary
identity. The main line is the broader front-end scaffold:

- multi-agent coding trace collection
- native tool-catalog capture
- raw-to-canonical trace normalization
- schema mutation and view transformation
- slime-compatible downstream training bundles

That broader scaffold direction is defined in
[PYCODEAGENT_MULTI_AGENT_SCAFFOLD_DESIGN.md](./PYCODEAGENT_MULTI_AGENT_SCAFFOLD_DESIGN.md).
The phase-one scaffold contract freeze and golden bundle are documented in
[docs/scaffold_phase1.md](./docs/scaffold_phase1.md).
The external CLI sidecar handoff is documented in
[docs/external_agent_sidecar_protocol.md](./docs/external_agent_sidecar_protocol.md).
The API-trace-only Claude gateway usage is documented in
[docs/claude_gateway_proxy.md](./docs/claude_gateway_proxy.md).
That path is a useful auxiliary trace source, not the main repository
positioning.

## Near-Term Roadmap

The next implementation line should be:

1. Define scaffold-level contracts: `RawAgentRunResult`,
   `AgentToolCatalog`, `RawAgentTrace`, `CanonicalTrace`, `AgentAdapter`,
   `ToolCatalogProvider`, `TraceNormalizer`, and `AugmentationRenderer`.
2. Add `MockAdapter`, `MockToolCatalogProvider`, and synthetic
   `RawAgentTrace` generation.
3. Add `MockTraceNormalizer`.
4. Add a catalog-level real provider.
5. Normalize raw traces into canonical capabilities.
6. Apply tool-schema mutation and view transformation to those traces.
7. Feed the resulting transformed traces into the existing training-data path.
8. Keep the current slime-compatible training path as the downstream consumer.

Phase-one note:

- do not block on real external raw-trace collection
- keep `RawAgentTrace` as a first-class artifact from day one
- let `MockAdapter` and synthetic traces harden augmentation, contract checks,
  and slime bundle generation first

Current claims should stay narrow:

- "training-prep infrastructure"
- "tool-use trajectory pipeline"
- "contract-aware dataset generation"
- "multi-agent raw trace ingestion"
- "native tool schema preservation"
- "tool-schema mutation and view transformation"

Avoid overstating the repo as:

- a full coding-agent RL system
- a production sandbox
- a benchmark-first coding product

## Minimal Developer Loop

Run the owned test suite:

```powershell
python -B -m pytest tests -q
```

Check repo hygiene:

```powershell
python -B -m pycodeagent.dev.repo_hygiene check
```

Audit machine-local files that should not live in the repo:

```powershell
python -B -m pycodeagent.dev.repo_hygiene audit-local
```

Optional local pre-commit run:

```powershell
pre-commit run --all-files
```

## Core Workflows

Run a local study:

```powershell
python run_first_study_mimo.py
```

Preferred machine-local path layout:

- `PYCODEAGENT_LOCAL_CONFIG_DIR`: directory for `*.local.json`
- `PYCODEAGENT_MODEL_DIR`: local model weights
- `PYCODEAGENT_HF_CACHE_DIR`: Hugging Face cache root

If those environment variables are unset, pycodeagent falls back to a
machine-local cache root such as `%LOCALAPPDATA%\pycodeagent\...` on Windows or
`~/.cache/pycodeagent/...` on Unix-like systems.

`run_first_study_mimo.py` and `run_schema_attribution_mimo.py` first look for
`mimo_v25pro.local.json` in that machine-local config directory, then fall back
to `configs/local/mimo_v25pro.local.json` for compatibility. New setups should
prefer the external path.

Verify rollout data against the slime contract:

```powershell
python verify_slime_contract.py runs/studies/first_mutation_sensitivity_mimo_v25pro runs/verified ^
  --source-type study ^
  --fake-tokenizer
```

Prepare a training bundle from study / experiment / batch outputs:

```powershell
python prepare_slime_training_data.py runs/studies/first_mutation_sensitivity_mimo_v25pro runs/training_prep ^
  --source-type study ^
  --fake-tokenizer
```

For a real tokenizer path, replace `--fake-tokenizer` with:

```powershell
--tokenizer-name path-or-hf-tokenizer-name
```

The prepare step writes the canonical downstream bundle:

- `rollouts.jsonl`
- `samples.jsonl`
- `tokenized.jsonl`
- `tokenizer_config.yaml`
- `train_config.json`
- `training_prep.json`

## slime-main Boundary

`slime-main/` is vendored, not fully absorbed into the repo's default test
loop.

Owned here:

- `slime-main/slime/rollout/pycodeagent_offline.py`
- `slime-main/examples/pycodeagent_offline/`
- repo-side bridge and contract compatibility work needed for offline rollout
  export

Not yet true:

- `pytest slime-main/tests -q` is not part of the default green path
- vendored slime sync/update policy is still intentionally lightweight

See [slime-main/VENDORING.md](./slime-main/VENDORING.md) and
[slime-main/examples/pycodeagent_offline/README.md](./slime-main/examples/pycodeagent_offline/README.md).

## Related Docs

- [CLAUDE.MD](./CLAUDE.MD): project intent and decision rules for agents
- [PYCODEAGENT_MULTI_AGENT_SCAFFOLD_DESIGN.md](./PYCODEAGENT_MULTI_AGENT_SCAFFOLD_DESIGN.md):
  repo-level design target for multi-agent raw trace collection plus downstream
  schema-generalization training
- [docs/claude_gateway_proxy.md](./docs/claude_gateway_proxy.md):
  API-trace-only local gateway for Claude Code session JSONL capture as an
  auxiliary ingestion path
- [docs/native_transformed_sft_pipeline.md](./docs/native_transformed_sft_pipeline.md):
  minimal end-to-end path from real Claude API trace to native-transformed SFT
  training-prep output

## Notes

- Local secrets belong in environment variables. Treat `*.local.json` as
  machine-local metadata only. See [configs/local/README.md](./configs/local/README.md).
- Large weights and Hugging Face caches should stay outside the source tree.
- If you change rollout, dataset, serializer, tokenizer, or contract behavior,
  update tests in the same turn. This repo is intentionally contract-heavy.
