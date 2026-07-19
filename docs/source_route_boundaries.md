# Source Route Boundaries

This document defines how the repository distinguishes its source-runtime
mainline from controlled baselines and auxiliary research routes. It is an
ownership and dependency contract, not a second construction schedule.

## Route Classes

| Class | Purpose | Canonical namespace | May drive current architecture? |
| --- | --- | --- | --- |
| Runtime-observed mainline | Produce audited traces from the repo-owned native-family runtime and prepare them for training | `pycodeagent.agent`, `env`, `tools`, `runtime_trace`, `rl.schema_following_from_runtime`, current `eval` runtime paths | Yes, under the codex-rs driver |
| Controlled baseline | Deterministic comparison, unit/contract testing, augmentation, and synthetic-first phase-one evidence | `pycodeagent.baselines` | No |
| Auxiliary route | Preserve non-mainline ingestion or transformation research that reuses shared contracts | `pycodeagent.auxiliary` | No |
| Shared kernel | Canonical trace, ToolView, serializer, loss-mask, tokenization, packing, and contract primitives reused by routes | Existing owning packages | Only within its contract scope |

The dependency direction is:

```text
controlled baseline ─┐
                     ├──> shared kernel <── runtime-observed mainline
auxiliary route ─────┘
```

The mainline must not import `pycodeagent.baselines` or
`pycodeagent.auxiliary`. Baseline and auxiliary routes may reuse the shared
kernel, but they may not redefine canonical trace semantics, ToolView
boundaries, serializer text, mask policy, or training bundle contracts.

## Controlled Baseline Policy

The public baseline namespace is `pycodeagent.baselines`. It owns:

- deterministic synthetic canonical-intent generation;
- extraction from already-recorded trajectories;
- synthetic profile/split planning used by those generators.

These outputs are allowed for:

1. deterministic unit and contract tests;
2. controlled comparisons against runtime-observed data;
3. augmentation experiments that label their source explicitly;
4. the phase-one synthetic mock contract in
   [`scaffold_phase1.md`](./scaffold_phase1.md).

They are not evidence of a realistic source runtime, model-visible request
capture, provider behavior, or production training quality. New callers import
from `pycodeagent.baselines`, not from compatibility implementation modules
under `pycodeagent.rl`.

The retained root command is explicitly a baseline command:

```bash
python -B generate_schema_following_data.py synthetic <output-dir>
python -B generate_schema_following_data.py trajectory-derived \
  <source-dir> <output-dir> --source-type batch
```

Synthetic and trajectory-derived `dataset_manifest.json` files record
`route_role = "controlled_baseline"` and
`artifact_owner = "pycodeagent.baselines"`. Trajectory-derived
`source_manifest.json` records the same ownership. Runtime-observed exporters
must never depend on this namespace or consume baseline manifests as source
runtime evidence.

The former `pycodeagent.rl` aggregate exports for synthetic/trajectory
generation have been removed. The underlying `pycodeagent.rl` module paths
remain as compatibility implementation details until a later mechanical move;
they are not the public route namespace.

## Auxiliary Admission Policy

A route belongs in auxiliary only when all of these are true:

1. it has current research or interoperability value;
2. it is not required to run the repo-owned runtime-observed mainline;
3. it can consume shared contracts without redefining them;
4. its source, artifacts, and limitations can be identified independently;
5. removing or disabling it would not invalidate mainline runtime artifacts.

`pycodeagent.auxiliary` intentionally exports nothing by default. The
machine-readable registry in `pycodeagent.auxiliary.policy` records two
`migrated` routes:

- `claude_api_ingestion`: gateway/session ingestion and conservative Claude
  API SFT preparation;
- `native_transformed`: transformed SFT/RL datasets, evaluation, reward, and
  smoke tooling derived from that ingestion route.

RC-030 completed their physical migration into
`pycodeagent.auxiliary.claude_api` and
`pycodeagent.auxiliary.native_transformed`. The old `pycodeagent.rl.*` and
`pycodeagent.traces.*` auxiliary module paths are intentionally breaking: they
are no longer present or re-exported. Root commands remain narrow transitional
compatibility entrypoints and import their implementations from the auxiliary
namespace. RC-031 subsequently removed the remaining broad legacy package
re-exports after all route migrations completed.

## Stable Package Facades

`pycodeagent.rl` is now a small facade for stable cross-route training-data
contracts only: prepared samples, serialization, loss masks, the canonical
training-bundle builder, and training-prep entrypoints. Tokenizers, packing,
dataset builders, evaluation helpers, SFT experiments, and operational bridge
utilities are imported from their owning submodules.

`pycodeagent.eval` exports the four active runtime campaign entrypoints:
native-family acceptance, real-provider behavior baseline, real-provider
credibility, and real-provider ToolView mutation generation. It also exports
the versioned `RunCampaign` and `RunMatrix` orchestration contracts defined by
RC-043. RC-044 backs the behavior, credibility, and ToolView-mutation
entrypoints with those contracts while leaving research-specific metrics in
their owning modules. Result models, executors, and internal stages remain
available from their owning submodules.

The exact symbol/owner matrix is machine-readable in
[`package_public_api_contract.json`](./repository_cleanup/package_public_api_contract.json).
Tracked code must not aggregate-import either package root. This keeps internal
module ownership explicit while preserving a deliberately small external
contract facade.

`pycodeagent.application` is the thin application-service boundary for the
formal CLI. It may compose active runtime/eval/training contracts, but it may
not implement tool execution, campaign loops, serialization, tokenization, or
verification rules. `pycodeagent.cli` owns parsing, config precedence, JSON
envelopes, and exit-code mapping only. Neither layer may import baseline,
auxiliary, or archived-study routes into the formal command tree.

## Auxiliary API and CLI Exposure

- Auxiliary modules must live below `pycodeagent.auxiliary` after migration.
- `pycodeagent.auxiliary.__init__` remains empty by default. A symbol may be
  re-exported only when another repository-owned route has a reviewed need for
  that stable API.
- Auxiliary code may import the shared-kernel prefixes recorded in
  `pycodeagent.auxiliary.policy`; the mainline may not import auxiliary code.
- Root wrappers are transitional compatibility surfaces. New general-purpose
  commands must not be added for an auxiliary route before the formal CLI work
  in RC-045.
- Auxiliary documentation stays outside the current implementation reading
  order and must label the route as non-mainline.

## Artifact Ownership and Deprecation

Auxiliary artifacts retain route-specific dataset/source types and prefixes,
including `claude_api_*` and `native_transformed_*`. They may reuse shared
serialized sample and loss-mask contracts, but must preserve their own source
provenance and may not be relabeled as `runtime_observed`.

An auxiliary route may be deprecated when it has no checked-in consumer or
its source protocol is unsupported. Deprecation requires:

1. an inventory of modules, entrypoints, tests, docs, and artifact types;
2. a replacement or explicit no-replacement statement;
3. a compatibility window when tracked callers still exist;
4. link, import-boundary, mainline, and full-suite verification;
5. no deletion of local sensitive artifacts without their retention decision.

Promotion from auxiliary or baseline to mainline requires a separate ADR and
evidence that the route improves source-runtime realism, observed-data
fidelity, or core contracts. Popularity or historical usage alone is not a
promotion criterion.
