# Native-Family Runtime Acceptance

## Status

This document describes the active acceptance contract as of July 15, 2026.
The implementation source of truth is
`pycodeagent/eval/native_family_acceptance.py`; the stable command-line
entrypoint is `python -B -m pycodeagent acceptance`.

The terminology, explicit family-selection, no-silent-fallback, artifact, and
evidence boundaries used by this runbook are defined by
[ADR-0001](./adr/0001-native-family-runtime-boundary.md).

The repository has two distinct acceptance modes:

- **local-only** is the deterministic, offline gate used for cleanup and CI
  evidence.
- **real-provider** adds the native Claude provider pack and requires an
  explicit or locally resolved provider configuration.

Local-only acceptance does not claim network-provider behavior. Real-provider
acceptance is not part of the default offline gate.

## Commands

Run the offline acceptance pack:

```bash
python -B -m pycodeagent acceptance \
  --local-only \
  --output-root <output-root>
```

The report is written below `<output-root>/local_only/`.

Run the provider-backed variant:

```bash
python -B -m pycodeagent acceptance \
  --provider-config <provider-config.json> \
  --output-root <output-root>
```

If `--provider-config` is omitted in real-provider mode, the runner resolves
`real_provider_runtime.local.json` through the repository's normal local
configuration flow. Provider-backed output is written below a
`<client_mode>__<model>/` subdirectory.

The local-only command prints a versioned JSON result envelope and writes
`pycodeagent_cli_manifest.json`. The linked
`native_family_acceptance_report.json` is the authoritative application
result. A non-stabilized report returns contract-failure exit code `1`.

## Offline Regression Boundary

The acceptance runner executes two checked-in pytest suites. Every configured
path is validated before pytest starts, so a stale or missing test path fails
the run instead of being silently skipped.

| Suite | Checked-in tests |
| --- | --- |
| `native_runtime_mainline` | `tests/test_native_runtime_mainline.py`, `tests/test_task_pack_integrity.py`, `tests/test_realistic_task_consumers.py`, `tests/test_route_boundaries.py` |
| `runtime_observed_mainline` | `tests/test_runtime_observed_mainline.py` |

Each suite runs with `--strict-markers -m mainline`. The equivalent aggregate
gate is:

```bash
python -B -m pytest -q --strict-markers -m mainline \
  tests/test_native_runtime_mainline.py \
  tests/test_runtime_observed_mainline.py \
  tests/test_task_pack_integrity.py \
  tests/test_realistic_task_consumers.py \
  tests/test_route_boundaries.py
```

The acceptance runner uses this aggregate command. The GitHub Actions mainline
workflow runs it together with the repository's multi-agent golden and docs
taxonomy asset gates, without provider credentials or network access.

## Acceptance Components

### Entrypoint checks

The runner verifies both the runtime builders and profile builders:

- Claude exposes exactly `Bash`, `Read`, `Edit`, `Write`, `Grep`, and
  `Glob`.
- Codex exposes exactly `exec_command`, `write_stdin`, and `apply_patch`.
- Codex `apply_patch` remains a freeform contract.

### Native Codex local pack

Three deterministic repo tasks are always required:

1. an `exec_command` read-only smoke;
2. an `exec_command` plus `write_stdin` continuation smoke;
3. an `apply_patch` repository repair.

The runner also performs a direct runtime flow covering all three Codex tools.
Missing required tool use, verifier failure, unexpected workspace mutation, or
an incomplete trajectory marks the corresponding result as failed.

### Runtime-observed generation smokes

The runner dynamically generates observed data for both native families using
the current mutation configuration. It verifies:

- Claude samples retain `family=claude` and function contracts;
- Codex samples retain `family=codex` and freeform contracts;
- the generated raw dataset and training-prep contract both succeed.

These outputs are generated under the acceptance output root. Legacy
`family=legacy` runtime-observed directories under `tests/fixtures/` are not
owned acceptance artifacts and must not be treated as current goldens.

### Native Claude real-provider pack

Real-provider mode additionally runs three Claude tasks:

1. a read-only `Read` smoke;
2. a small repair requiring `Read` and at least one of `Edit` or `Write`;
3. a search-and-repair task requiring `Glob`, `Grep`, and at least one of
   `Edit` or `Write`.

The strict Codex real-provider path remains explicitly transport-limited
because the current OpenAI-compatible provider transport is function-only
while strict Codex `apply_patch` is freeform. Codex acceptance therefore
remains local/fake in both modes.

## Required Families And Failure Semantics

There is no user-selectable `required-families` CLI parameter. The required
family surface is fixed by the runner:

- both Claude and Codex entrypoint checks are always required;
- the Codex local task pack, Codex direct flow, and both-family generation
  smokes are always required;
- the Claude real-provider task pack is required only in real-provider mode.

`stabilized` is true only when:

1. every entrypoint check passes;
2. both regression commands pass;
3. all three native Codex tasks pass;
4. the native Codex direct flow passes;
5. both generation smokes pass; and
6. in real-provider mode, at least one Claude task exists and every Claude task
   passes.

An empty `real_provider_tasks` list is expected in local-only mode. The
`codex_real_provider_transport_limited` field is an explicit capability note,
not a local-only failure.

Individual task failures retain `required_tools_all`,
`required_tools_any`, observed tool names, verifier status, workspace-change
status, and explanatory notes. Regression failures retain the command, exit
code, duration, and stdout/stderr paths. A missing configured regression file
raises before acceptance execution.

The formal CLI converts a false aggregate result into contract-failure exit
code `1`. Automation should require both a successful exit and
`stabilized=true` in the linked report.

## Report Contract

`native_family_acceptance_report.json` contains:

- `provider`
- `entrypoint_checks`
- `regression_commands`
- `real_provider_tasks`
- `native_codex_tasks`
- `native_codex_direct_flow`
- `generation_smokes`
- `codex_real_provider_transport_limited`
- `codex_real_provider_transport_note`
- `stabilized`

The report and generated subdirectories are run artifacts. They are not
committed fixture ownership declarations.

## Change Validation

Changes to the native-family acceptance path should run:

```bash
python -B -m pytest -q --strict-markers \
  tests/test_native_family_acceptance.py \
  tests/test_runtime_observed_mainline.py

python -B -m pycodeagent acceptance \
  --local-only \
  --output-root <unique-temp-root>
```

Run the provider-backed mode only when provider behavior is intentionally in
scope and credentials/configuration are available. Do not present a
provider-free local-only result as evidence of real-provider success.
