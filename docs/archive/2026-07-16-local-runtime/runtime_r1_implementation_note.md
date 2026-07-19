# Runtime R1 Implementation Note

> Archived by RC-015 on 2026-07-16. This is historical implementation
> evidence, not a current construction schedule. See this archive's README for
> provenance, completion status, and replacement documents.

## Scope

This note records the first executable milestone from
`docs/local_runtime_realism_mainline_plan.md`:
`R1: Runtime Behavior Realism`.

The implementation stayed intentionally narrow:

- improve recoverability in the local runtime loop
- make completion behavior more disciplined after recoverable failures
- preserve downstream trajectory, runtime-trace, observed-exporter, and
  training-prep contracts
- add deterministic tests for a revise-after-failure loop

## Changed Files

- `pycodeagent/agent/runner.py`
  - added a small runtime loop state for recoverable parse/tool failures
  - deferred completion when a recoverable issue is still pending
  - recorded cumulative `parse_errors` in trajectory metadata
- `pycodeagent/agent/stopping.py`
  - stopped treating a single parse-only turn as an immediate hard stop
  - allowed `finish` / no-tool-call completion to be deferred when recovery is
    still required
- `tests/test_agent_runner.py`
  - added parse-recovery and schema/mapping-retry coverage
  - updated repeated-parse-error expectations to match the new recovery window
- `tests/test_e2e_smoke.py`
  - added a deterministic revise-after-failed-`python_run` smoke that proves:
    create/edit -> failed test -> premature finish deferred -> revise ->
    successful test -> finish
- `tests/test_runtime_trace_events.py`
  - added runtime-trace assertions for the deferred-finish revise loop

## New Runtime Behavior

- A single parse-only failure no longer forces immediate termination.
  The runtime now allows one recovery turn before escalating repeated
  parse-only failure into `stop_reason=parse_error`.
- Recoverable tool failures no longer imply that a later `finish` should always
  terminate the run.
  Examples now treated as recoverable:
  - exposed-schema / argument-mapping failures
  - failed validation runs from `python_run` / `run_command`
  - other runtime-generated recoverable tool failures
- `finish` and no-tool-call completion are now deferred when a recoverable
  issue is still pending.
  This is what enables a deterministic
  inspect -> edit -> run test -> inspect failure -> revise -> finish loop.
- Clear unrecoverable failures such as protected-path or command-policy
  rejection do not become mandatory recovery blockers for completion.

## Verification Commands

The following test commands were run after implementation:

```powershell
pytest tests/test_agent_runner.py tests/test_runtime_trace_events.py tests/test_runtime_trace_golden.py tests/test_e2e_smoke.py tests/test_coding_env.py -q
pytest tests/test_schema_following_from_runtime.py tests/test_schema_following_from_runtime_golden.py tests/test_runtime_observed_training_prep.py tests/test_runtime_observed_training_prep_golden.py tests/test_schema_following_training_prep.py tests/test_training_prep.py tests/test_phase2_profile_runtime.py tests/test_profile_sampler.py -q
```

Observed result:

- `25 passed, 36 skipped`
- `85 passed`

These commands cover the local runtime loop, runtime trace, existing golden
fixtures, observed runtime exporter, ToolView mutation flow, and
training-prep compatibility.
