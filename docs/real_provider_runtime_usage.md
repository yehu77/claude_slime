# Real-Provider Native Runtime Runbook

This runbook operates the repository-owned local runtime against a real
OpenAI-compatible provider. It is an acceptance and evidence path, not a
separate architecture driver. Read
[ADR-0001](./adr/0001-native-family-runtime-boundary.md) for the canonical
family, fallback, artifact, and transport boundaries.

## Supported Boundary

Provider transport and model-visible tool family are separate choices.

- `RuntimeProviderConfig.client_mode` selects the transport client. The only
  accepted values are `mimo_native_tools` and `openai_native_tools`.
- The formal real-provider commands default to
  `tool_stack_kind="native_claude"` through `--family native_claude`; they do
  not infer the family from provider, model, task metadata, or exposed tool
  names.
- Internal mutation and credibility APIs also accept an explicit
  `native_codex` selection. The current OpenAI-compatible function transport
  cannot faithfully carry the freeform Codex `apply_patch` contract, so the
  checked-in provider wrappers do not silently switch to it.
- Real-provider results are acceptance/regression evidence for runtime
  behavior. They do not prove provider parity, production sandboxing,
  benchmark quality, or training gains.

For deterministic offline evidence, use the
[native-family acceptance runbook](./tool_runtime_native_family_acceptance_and_regression_plan.md)
instead of calling a provider.

## Prerequisites and Secrets

Run commands from the repository root with the project dependencies installed.
The minimal environment is:

```bash
export PYCODEAGENT_API_KEY="<real-secret>"
export PYCODEAGENT_MODEL="<provider-model-name>"
```

Optional transport overrides are:

```bash
export PYCODEAGENT_CLIENT_MODE="openai_native_tools"
export PYCODEAGENT_BASE_URL="https://provider.example/v1"
export PYCODEAGENT_API_KEY_ENV="PYCODEAGENT_API_KEY"
```

Configuration precedence is:

1. hard defaults;
2. an optional machine-local JSON file;
3. environment-variable overrides.

The resolver loads the first available dotenv file from an explicit
`PYCODEAGENT_ENV_FILE`, the current directory, the repository root, or the
machine-local config directory. Existing process environment variables win
over dotenv values. The shortest setup is to copy
[`.env.example`](../.env.example) to the ignored `.env` file and replace its
placeholders.

For richer non-secret settings, copy
[`real_provider_runtime.local.example.json`](../configs/local/real_provider_runtime.local.example.json)
to either:

- the directory selected by `PYCODEAGENT_LOCAL_CONFIG_DIR`; or
- the platform-local pycodeagent config directory.

The repository fallback path `configs/local/real_provider_runtime.local.json`
is also ignored, but a machine-local directory is preferable.

Never put `api_key` in JSON. The schema rejects inline keys; `api_key_env`
names the environment variable containing the secret. Do not commit `.env`,
`*.local.json`, provider responses, or run directories.

## Preflight and Offline Gate

Before spending provider quota, run the deterministic gate:

```bash
python -B -m pycodeagent acceptance \
  --local-only \
  --output-root /tmp/native-family-acceptance
```

Success is exit code `0`, `ok=true` in the JSON stdout envelope, and
`stabilized=true` in
`/tmp/native-family-acceptance/local_only/native_family_acceptance_report.json`.
This command does not validate credentials, network reachability, or the
remote model.

Provider configuration is resolved when a provider-backed command starts.
A fresh environment without a model produces an explanatory
`Unable to resolve runtime provider config` error. A configured model without
the environment variable named by `api_key_env` produces
`Missing API key for runtime provider config`. Unsupported or removed client modes fail schema
validation rather than falling back to text parsing.

## Provider-Backed Commands

The stable command surface is
[`python -m pycodeagent`](./formal_cli.md). Commands below explicitly use
`native_claude`; automation should consume `pycodeagent_cli_manifest.json`
and the linked application manifest.

### 1. Single-run smoke

```bash
python -B -m pycodeagent run \
  --tasks datasets/tasks/real_provider_smoke_tasks.jsonl \
  --task-id real_provider_smoke_read_then_finish \
  --output-root runs/real_provider_smoke \
  --family native_claude
```

This runs a short native-Claude read task over
`examples/runtime_rewrite_greeter` and writes to
`runs/real_provider_smoke/`.

Inspect at least `trajectory.json`, `tool_profile.json`, `verifier.json`,
`runtime_trace.jsonl`, and `runtime_trace_manifest.json`. A valid family
selection has `tool_profile.json.metadata.family = "claude"` and
`native_profile_kind = "native_claude"`.

### 2. Repeated behavior baseline

```bash
python -B -m pycodeagent campaign \
  --kind behavior \
  --output-root runs/real_provider_behavior_baseline \
  --family native_claude
```

This loads
[`datasets/tasks/realistic_runtime_tasks.jsonl`](../datasets/tasks/realistic_runtime_tasks.jsonl),
runs the base profile three times per task, and writes:

```text
runs/real_provider_behavior_baseline/
```

The top-level evidence is `runtime_behavior_audit.json`,
`behavior_baseline_summary.json`, and `failure_buckets.json`. The summary must
record `tool_stack_kind = "native_claude"`; each source run preserves its exact
family in `tool_profile.json` and its observed events in `runtime_trace.jsonl`.
`runs/profile_campaign_group_spec.json` and
`runs/profile_campaign_group_manifest.json` bind the resumable source-run
matrix.

### 3. ToolView mutation data generation

```bash
python -B -m pycodeagent campaign \
  --kind toolview \
  --output-root runs/toolview_mutation_data_generation \
  --family native_claude \
  --fake-tokenizer
```

This runs the same realistic tasks once under each current mode: `base`,
`argument_rename`, `schema_flat_to_nested`, and `tool_reorder`. It writes:

```text
runs/toolview_mutation_data_generation/
```

The primary entry artifacts are
`toolview_mutation_data_generation_manifest.json` and
`toolview_mutation_data_generation_summary.json`. Both must record
`tool_stack_kind = "native_claude"`. The directory also contains source runs,
the runtime-observed raw dataset, acceptance report, and fake-tokenizer
training-prep output. Fake tokenization validates contracts; it is not a
production tokenizer claim. The source-run `runs/` directory is a campaign
group: each ToolView mode owns one versioned RunCampaign so its configured seed
remains paired with that mode.

### 4. Repeated credibility bundle

```bash
python -B -m pycodeagent campaign \
  --kind credibility \
  --output-root runs/real_provider_credibility_bundle \
  --family native_claude \
  --fake-tokenizer
```

This runs all four modes three times per realistic task, then adds behavior
audit, observed export, execution reconciliation, training prep, and
credibility gates. Output is:

```text
runs/real_provider_credibility_bundle/
```

Start inspection with `real_provider_credibility_manifest.json`,
`real_provider_credibility_summary.json`, and
`real_provider_credibility_gates.json`. The manifest and summary must record
`tool_stack_kind = "native_claude"`; `contract_ok=true` means the implemented
bundle gates passed, not that the provider or dataset is production-ready.
The manifest links the campaign-group spec and manifest used to produce the
source runs.

For all three repeated commands, rerunning the same output root resumes
terminal runs without another provider call and never removes an earlier
attempt. Changing tasks, modes, seeds, provider provenance, repeat count, or
family is spec drift and must use a new output root. Inspect the terminal
`campaign_run_record.json` artifact paths instead of assuming each trajectory
is a direct child of `runs/`.

### 5. Provider-backed acceptance pack

For the small native-Claude acceptance workload plus all offline family gates:

```bash
python -B -m pycodeagent acceptance \
  --provider-config <machine-local-provider-config.json> \
  --output-root runs/native_family_acceptance
```

Omit `--provider-config` to use normal local/env resolution. The authoritative
result is `native_family_acceptance_report.json` below the generated
`<client_mode>__<model>/` directory. Provider-backed acceptance is intentionally
small; the realistic behavior/mutation/credibility commands above serve
different evidence purposes.

## Programmatic Usage

Family selection is mandatory even when provider configuration is already
resolved:

```python
from pathlib import Path

from pycodeagent.agent import resolve_runtime_provider_config
from pycodeagent.env.coding_env import run_coding_task_with_provider
from pycodeagent.env.task import CodingTask

provider = resolve_runtime_provider_config(
    Path("/machine-local/real_provider_runtime.local.json")
)
task = CodingTask(
    task_id="manual_native_claude_smoke",
    repo_path=Path("examples/runtime_rewrite_greeter"),
    prompt="Inspect greeter.py and report what it does without changing files.",
    test_command=["python", "-c", "print('ok')"],
    max_turns=4,
)
trajectory = run_coding_task_with_provider(
    task,
    provider,
    Path("runs/manual_native_claude_smoke"),
    tool_stack_kind="native_claude",
)
```

For batch APIs, `run_real_provider_behavior_baseline`,
`run_real_provider_toolview_mutation_data_generation`, and
`run_real_provider_credibility_bundle` likewise require an explicit
`tool_stack_kind` keyword. Do not copy family/profile/provider selectors into
`CodingTask.metadata`.

## Provenance and Sensitive Artifacts

Non-secret provider provenance is stored in `trajectory.json ->
metadata.provider`, `runtime_trace.jsonl -> run_started.data.provider`, and
runtime-observed source manifests. It includes provider kind, client mode,
model, base URL, API-key environment-variable name, timeout, retry budget,
temperature, and output-token limit. The resolved API-key value is not written.

Treat every provider-backed run directory as sensitive anyway. Prompts,
model responses, tool arguments/results, workspace paths, diffs, verifier
output, request context, retained history, and provider-specific metadata may
contain private data. `runs/` is ignored; keep it untracked, inspect before
sharing, and scrub or archive it only under the repository's retention policy.

## Failure Diagnosis

Use this order:

1. **Config failure before a request:** check `PYCODEAGENT_MODEL`, the variable
   named by `api_key_env`, client mode, base URL, and local JSON syntax.
2. **HTTP/provider failure:** inspect the terminal error and
   `trajectory.json.metadata.provider`; do not paste secrets into artifacts or
   retry by changing tool family.
3. **Schema or tool-call failure:** compare `tool_profile.json` with
   `runtime_trace.jsonl` mapping/validation events. A stale exposed name or
   payload is a schema-following failure, not permission to use a generic alias.
4. **Verifier/runtime failure:** inspect `verifier.json`, `final.patch`, the
   behavior audit, failure buckets, and reconciliation report where present.
5. **Bundle gate failure:** read the corresponding manifest/summary/gates file
   before rerunning a larger campaign.

Do not use the legacy study route as a substitute for these commands. Its
disposition is governed separately by the cleanup ledger; the realistic
provider path is the smoke → behavior baseline → mutation generation or
credibility sequence documented here.
