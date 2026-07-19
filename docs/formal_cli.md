# Formal pycodeagent CLI

Status: active, contract version 1, defined by RC-045 on 2026-07-18.

Owner: runtime, evaluation, and training-data maintainers.

## Boundary

The stable entrypoint is:

```bash
python -B -m pycodeagent <subcommand> [options]
```

The CLI is a thin adapter over repository-owned application services. It
parses and merges configuration, calls exactly one service, writes a common
manifest, emits one JSON object, and maps the result to a documented exit
code. Runtime loops, campaign expansion, export logic, training preparation,
verification, and acceptance logic remain in their owning modules.

The version 1 command tree is:

| Subcommand | Application service | Owned contract |
| --- | --- | --- |
| `run` | `pycodeagent.application.cli_services.run_service` | one `CodingTask` through `run_coding_task` |
| `campaign` | `campaign_service` | active behavior, credibility, or ToolView campaign through RunCampaign-backed services |
| `export` | `export_service` | runtime-observed ToolView export |
| `prep` | `prep_service` | canonical slime-compatible training bundle |
| `verify` | `verify_service` | slime contract verification |
| `acceptance` | `acceptance_service` | native-family acceptance and regression |

Operational dev commands, auxiliary routes, archived studies, vendor
maintenance, and runs lifecycle mutation are not part of this public command
tree.

## Configuration and precedence

Optional command configuration uses:

```json
{
  "schema": "pycodeagent-cli-config/v1",
  "command": "acceptance",
  "arguments": {
    "local_only": true,
    "output_root": "runs/native_family_acceptance"
  }
}
```

Pass the config before the subcommand:

```bash
python -B -m pycodeagent \
  --config configs/local/pycodeagent_cli.acceptance.example.json \
  acceptance
```

Precedence is strictly:

```text
built-in defaults < config.arguments < explicit CLI options
```

The config `command` must equal the selected subcommand. Unknown keys, schema
drift, command mismatch, invalid enum values, and missing required arguments
fail before service dispatch. A config cannot select the command itself.

Paths and non-secret settings may be configured. Provider credentials must
remain in the environment variable named by a provider config's
`api_key_env`; neither formal CLI config nor output manifests accept inline
credentials.

Campaign mode/seed values remain paired. `--profile-modes` accepts a
comma-separated list and `--profile-seeds` accepts a JSON object. An omitted
seed uses the active campaign default for that mode, then zero. Seeds for
unselected modes are rejected.

Real tokenization requires `--tokenizer-name`. Offline contract checks must
explicitly select `--fake-tokenizer`; fake tokenization is never an implicit
training claim.

## Required arguments and examples

Run one task from a task pack:

```bash
python -B -m pycodeagent run \
  --tasks datasets/tasks/realistic_runtime_tasks.jsonl \
  --task-id realistic_patch_calculator_001 \
  --output-root runs/formal_cli/single_run \
  --provider-config <machine-local-provider-config.json> \
  --family native_claude \
  --profile-mode base \
  --profile-seed 0
```

Run an active campaign:

```bash
python -B -m pycodeagent campaign \
  --kind behavior \
  --output-root runs/formal_cli/behavior \
  --provider-config <machine-local-provider-config.json>
```

`credibility` always requires explicit tokenizer selection. `toolview`
requires it when training prep is enabled:

```bash
python -B -m pycodeagent campaign \
  --kind toolview \
  --output-root runs/formal_cli/toolview \
  --profile-modes base,tool_reorder \
  --profile-seeds '{"base":0,"tool_reorder":7}' \
  --fake-tokenizer
```

Export, prepare, and verify:

```bash
python -B -m pycodeagent export \
  --source-dir runs/formal_cli/behavior/runs \
  --output-dir runs/formal_cli/observed \
  --source-type batch

python -B -m pycodeagent prep \
  --source-dir runs/formal_cli/behavior/runs \
  --output-dir runs/formal_cli/prepared \
  --source-type batch \
  --fake-tokenizer

python -B -m pycodeagent verify \
  --source-dir runs/formal_cli/behavior/runs \
  --output-dir runs/formal_cli/verified \
  --source-type batch \
  --fake-tokenizer
```

Offline acceptance:

```bash
python -B -m pycodeagent acceptance \
  --local-only \
  --output-root /tmp/pycodeagent-acceptance
```

## Machine-readable output

Success and contract-failure results are one JSON object on stdout with schema
`pycodeagent-cli-result/v1`. Parse/config/input/application errors are one JSON
object on stderr with schema `pycodeagent-cli-error/v1`. Human-readable
application logs may precede the final object only when an owned application
service already emits them; consumers should use the manifest path as the
durable result.

Every dispatched service writes `pycodeagent_cli_manifest.json` under its
effective output root. Schema `pycodeagent-cli-manifest/v1` always includes:

- `version` and command;
- final `status`;
- `task_ids`;
- profile modes and seed mapping;
- native `family` scope (`native_claude`, `native_codex`, or
  `multi_native` for acceptance), or explicit `null` when not applicable;
- result type;
- the owned application manifest path;
- the structured service result.

This common manifest does not replace trajectory, campaign, dataset,
training-bundle, verification, or acceptance manifests. It points to them.

## Exit codes

| Code | Meaning |
| ---: | --- |
| `0` | application service completed and its contract/gates passed |
| `1` | service completed, artifacts were retained, but contract/gates failed |
| `2` | CLI usage or versioned config error; service was not called |
| `3` | missing, malformed, or schema-invalid input |
| `4` | provider, runtime, or application-service failure |
| `130` | user/system interruption |

Contract failure is not converted into an exception and does not delete
artifacts. Errors never fall back to another command or auxiliary route.

## Retired compatibility entrypoints

RC-046 audited every root-level Python wrapper and retired the seven wrappers
that had complete formal replacements. The historical replacement map is:

| Retired wrapper | Formal command |
| --- | --- |
| `run_real_provider_behavior_baseline.py` | `campaign --kind behavior` |
| `run_real_provider_credibility_bundle.py` | `campaign --kind credibility` |
| `run_toolview_mutation_data_generation.py` | `campaign --kind toolview` |
| `run_native_family_acceptance.py` | `acceptance` |
| `prepare_slime_training_data.py` | `prep` |
| `verify_slime_contract.py` | `verify` |
| `run_runtime_smoke_real_provider.py` | `run --tasks datasets/tasks/real_provider_smoke_tasks.jsonl --task-id real_provider_smoke_read_then_finish` |

The fixed smoke task now has a versioned repository task-pack identity.
Auxiliary, controlled-baseline, compatibility-gateway, and external-agent
scripts without an equivalent application service remain route-specific
entrypoints; they are not alternate names for the mainline commands.

The complete machine-readable disposition, including repository consumers,
unknown external-consumer status, rationale, and retained route ownership, is
[`root_wrapper_disposition.json`](./repository_cleanup/root_wrapper_disposition.json).

## Verification

The formal CLI gate is:

```bash
python -B -m pytest -q --strict-markers tests/test_formal_cli.py
```

It freezes the six-command tree, single-service dispatch, config/CLI
precedence, unknown-key rejection, success and contract-failure envelopes,
exit-code taxonomy, and required manifest dimensions. Repository local
acceptance additionally runs `python -B -m pycodeagent acceptance
--local-only`.
