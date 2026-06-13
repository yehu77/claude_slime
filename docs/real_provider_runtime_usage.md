# Real Provider Runtime Usage

This repository now has a formal real-provider runtime path for the local
runtime mainline.

Current default assumptions:

- `client_mode = "mimo_native_tools"`
- `base_url = "https://token-plan-cn.xiaomimimo.com/v1"`
- the API key is provided only through `api_key_env`
- the real-provider mainline now prefers native tool-calling instead of the
  older text-mode prompt/parser contract

## Env-First Usage

The real-provider runtime now resolves config with this precedence:

1. hard defaults
2. optional local JSON config
3. environment variables

For the common case, you only need these environment variables:

- `PYCODEAGENT_API_KEY`
- `PYCODEAGENT_MODEL`

Optional overrides:

- `PYCODEAGENT_CLIENT_MODE`
- `PYCODEAGENT_BASE_URL`
- `PYCODEAGENT_API_KEY_ENV`

PowerShell example:

```powershell
$env:PYCODEAGENT_API_KEY = "fill-your-real-key"
$env:PYCODEAGENT_MODEL = "fill-your-model-name"
```

If you are happy with the defaults, that is enough to run the smoke and study
entrypoints.

Important mainline rule:

- `mimo_native_tools` and `openai_native_tools` are the only formal
  real-provider runtime entry modes
- the env-first resolver and real-provider scripts reject text-only client
  modes outright

The runtime now auto-loads a basic `.env` file before resolving provider
config. It checks, in order:

1. an explicit file from `PYCODEAGENT_ENV_FILE`
2. `.env` in the current working directory
3. `.env` in the repo root
4. `.env` in the machine-local config directory

So the simplest setup is:

1. copy [.env.example](../.env.example) to `.env`
2. fill `PYCODEAGENT_API_KEY` and `PYCODEAGENT_MODEL`
3. run the smoke or study script

Shell-exported variables still win over `.env` values.

## Optional Local JSON Fallback

You can still use
[configs/local/real_provider_runtime.local.example.json](../configs/local/real_provider_runtime.local.example.json)
as a machine-local fallback, for example when you want to pin a model, base
URL, retry budget, or timeout without re-exporting many env vars.

Recommended path examples:

- `%LOCALAPPDATA%\\pycodeagent\\configs\\real_provider_runtime.local.json`
- a directory pointed to by `PYCODEAGENT_LOCAL_CONFIG_DIR`

Rules:

- do not add inline `api_key`
- export the API key through the environment variable named by `api_key_env`
- keep real `*.local.json` files out of the repo
- `.env` is the preferred simple path; local JSON is for richer non-secret runtime config
- if the JSON sets `client_mode` to a removed text value, runtime config
  validation will fail

## Single-Run Smoke

Run a minimal real-provider smoke:

```powershell
python run_runtime_smoke_real_provider.py
```

This smoke:

- resolves config from env first, then optional `real_provider_runtime.local.json`
- builds the configured native-tools real provider client
- runs a short `read_file -> finish` task over `examples/runtime_rewrite_greeter`
- writes normal local-runtime artifacts under `runs/real_provider_smoke/...`

Expected artifacts include:

- `trajectory.json`
- `tool_profile.json`
- `runtime_trace_manifest.json`
- `runtime_trace.jsonl`

## Study Run

Run the first mutation-sensitivity study with the same provider config:

```powershell
python run_first_study_real_provider.py
```

This uses:

- study config: `configs/studies/first_mutation_sensitivity.json`
- provider config: env-first, with optional `real_provider_runtime.local.json`
- output root: `runs/studies/first_mutation_sensitivity_real_provider`

## Credibility Bundle

Run the repeated-run credibility bundle path:

```powershell
python run_real_provider_credibility_bundle.py
```

This path is the formal P5-M3 acceptance bundle. It is intentionally narrower
than a generic study run and more comprehensive than the behavior baseline.

Current fixed defaults:

- tasks: `datasets/tasks/realistic_runtime_tasks.jsonl`
- modes: `base` and `name_description_schema`
- fixed profile seed per mode: `0`
- repeat count: `3`
- output root:
  `runs/real_provider_credibility_bundle/<client_mode>__<model>/`

It emits:

- repeated source runs under `runs/`
- `runtime_behavior_audit.json`
- `behavior_baseline_summary.json`
- `failure_buckets.json`
- nested `runtime_observed_bundle/`
- `real_provider_credibility_summary.json`
- `real_provider_credibility_manifest.json`
- `real_provider_credibility_gates.json`

How it differs from the other real-provider paths:

- smoke:
  validates that one real-provider run works end to end
- behavior baseline:
  focuses on repeated-run runtime behavior and failure buckets
- credibility bundle:
  adds observed export, reconciliation, postrun bundle, and top-level
  credibility gates on top of repeated real-provider runs

## Programmatic Usage

Single task:

```python
from pathlib import Path

from pycodeagent.agent import resolve_runtime_provider_config
from pycodeagent.env.coding_env import run_coding_task_with_provider
from pycodeagent.env.task import CodingTask

provider = resolve_runtime_provider_config(
    "C:/path/to/real_provider_runtime.local.json"
)

task = CodingTask(
    task_id="smoke_task",
    repo_path=Path("examples/runtime_rewrite_greeter"),
    prompt="Read greeter.py and finish.",
    test_command=["python", "-c", "print('ok')"],
    max_turns=4,
)

trajectory = run_coding_task_with_provider(
    task,
    provider,
    Path("runs/manual_smoke"),
)
```

Study:

```python
from pycodeagent.eval import run_study_from_provider_config

result = run_study_from_provider_config(
    "configs/studies/first_mutation_sensitivity.json",
    "C:/path/to/real_provider_runtime.local.json",  # optional fallback path
)
```

## Artifact Provenance

For real-provider runs, the runtime writes structured non-secret provider
provenance into:

- `trajectory.json -> metadata.provider`
- `runtime_trace.jsonl -> run_started.data.provider`
- runtime-observed exporter metadata (`source_provider_kind`, `source_model`, etc.)

The stored fields are:

- `provider_kind`
- `client_mode`
- `model`
- `base_url`
- `api_key_env`
- `timeout_seconds`
- `max_retries`
- `temperature`
- `max_output_tokens`

The real API key is never written into these artifacts.
