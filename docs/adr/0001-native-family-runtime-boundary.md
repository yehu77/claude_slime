# ADR-0001: Native-Family Runtime Boundary

- Status: Accepted
- Date: 2026-07-16
- Owners: runtime-maintainers, training-data-maintainers
- Decision scope: local runtime tool identity, family selection, artifacts, and
  acceptance

## Context

The repository previously passed through a generic-tool phase and a staged
Claude/Codex family split. Those implementation plans remain useful historical
evidence, but they contain landing-time compatibility constraints and no
longer define the current runtime contract.

The runtime now needs one stable decision record that separates:

- task semantics from tool-family selection;
- canonical execution from the schema exposed to the model;
- runtime family from provider transport;
- deterministic offline acceptance from provider-backed evidence.

This ADR records implemented behavior unless a paragraph is explicitly marked
as migration work.

## Decision

### 1. Terminology and abstraction boundary

A **native family** is a source-aligned tool identity and contract family. The
supported local runtime families are:

| `tool_stack_kind` | Family metadata | Base profile | Model-visible base tools |
| --- | --- | --- | --- |
| `native_claude` | `family=claude`, `native_profile_kind=native_claude` | `native_claude` | `Bash`, `Read`, `Edit`, `Write`, `Grep`, `Glob` |
| `native_codex` | `family=codex`, `native_profile_kind=native_codex` | `native_codex` | `exec_command`, `write_stdin`, `apply_patch` |

The central boundary remains:

```text
CanonicalTool -> ToolView -> ToolAdapter -> ToolRuntime
```

- `CanonicalTool` owns executable backend semantics and its canonical payload
  contract.
- `ToolView` is the model-visible name, description, schema or freeform input
  contract.
- `ToolAdapter` maps an exposed payload to the canonical payload without
  changing family identity.
- `ToolRuntime` validates the exposed call before resolving and executing the
  canonical backend.

Base native profiles currently use identity names, but that is not permission
to collapse the layers: mutated ToolViews may rename tools, descriptions,
arguments, nesting, or order while canonical execution remains stable.

### 2. Family-neutral task contract

`CodingTask` describes behavior and workspace constraints: task ID, repository,
prompt, verifier command, turn budget, allowed files, forbidden files, and
behavioral metadata. It does not select a native tool family.

New family-neutral behavioral metadata uses the reserved `metadata.task_contract`
object. Version 1 is strict:

| Field | Required | Contract |
| --- | --- | --- |
| `schema_version` | yes | literal `1`; missing and unknown versions fail |
| `required_capabilities` | yes | non-empty, unique values from `workspace_read`, `workspace_write`, `command_execution`, `validation`, and `failure_recovery` |
| `behavioral_requirements` | no | ordered, unique, non-empty behavior statements; never exposed tool names |
| `require_runtime_validation_evidence` | no | boolean, default `false`; gates completion on observed validation evidence |

Task identity, workspace, prompt, verifier command, turn budget, and file
constraints remain top-level `CodingTask` fields. Descriptive metadata such as
`category`, `difficulty`, and `description` may remain adjacent to
`task_contract`; they are not runtime selectors.

Family selection belongs to the runtime invocation through the required
`tool_stack_kind` argument. Therefore:

- one task may be run under either family when its behavior is expressible by
  both;
- task prompts and acceptance criteria should describe required behavior, not
  hard-code exposed tool names;
- profile mutation is selected separately through a concrete `profile` or the
  deterministic `profile_mode/profile_seed` path;
- runtime-owned keys such as `tool_stack_kind`, family/profile identity,
  adapter identity, and provider identity are invalid in task metadata;
- `task_contract` cannot coexist with legacy `primary_tools` or
  `expected_pattern`, preventing ambiguous mixed-generation records.

Backward migration is fail-open only for pre-versioned behavioral metadata:
tasks without `task_contract` load as legacy v0 so existing packs retain task
IDs and remain readable. Legacy `require_runtime_validation_evidence` keeps its
current meaning. Tool-name hints still present in legacy task metadata are
migration debt, never a runtime-selection contract. RC-021 freezes this rule,
and RC-022 migrated the realistic runtime pack to v1; other legacy packs may
remain v0 until their owning route is migrated or archived. Once a task declares
`task_contract`, validation is fail-closed for missing versions, unknown
versions, unknown fields, unknown capabilities, duplicates, and legacy/v1
conflicts.

At invocation time, `tool_stack_kind` remains required. A concrete `profile`
and `profile_mode` are mutually exclusive; any supplied profile must carry
native family metadata matching `tool_stack_kind`. `profile_seed` only applies
to deterministic sampled profiles. Adapter/provider selection belongs to the
caller and transport setup, not to `CodingTask`.

### 3. Selection and fallback rules

Family selection is explicit and fail-closed:

1. `run_coding_task` requires `tool_stack_kind`.
2. Only `native_claude` and `native_codex` are valid stack kinds.
3. A supplied profile must carry native family metadata matching the selected
   stack; missing or conflicting metadata raises before agent execution.
4. An unknown tool name, invalid exposed payload, missing adapter mapping, or
   incompatible canonical contract is an observable validation/mapping
   failure. It must not be retried through generic or cross-family aliases.
5. Provider clients on the formal mainline use native tool calling and declare
   `text_fallback_allowed=false`.
6. Provider transport limitations must remain explicit. In particular, the
   current OpenAI-compatible function transport cannot silently wrap the
   freeform Codex `apply_patch` contract or substitute the Claude family.

This rule does not ban explicitly named, recorded recovery policies inside a
different subsystem, such as deterministic context-compaction fallback. It
bans silent fallback that changes the selected tool family or model-visible
tool contract.

Provider family and tool family are separate concepts. A provider transport
does not determine `tool_stack_kind`, and selecting a tool family does not
claim that every provider can transport every contract kind.

### 4. Artifact and provenance contract

Every completed or failed local runtime run must preserve enough information
to reconstruct what the model saw, what was executed, and how the run ended.
The primary persisted contract is:

- `trajectory.json`: task/profile identity, messages, exposed and canonical
  calls, observations, status, reward, verifier fields, and final diff;
- `tool_profile.json`: exact model-visible ToolViews, adapters, versions,
  family metadata, mutation metadata, and tool order;
- `verifier.json` and `final.patch`;
- `runtime_trace.jsonl`, `runtime_trace_manifest.json`, and referenced payloads
  for append-only validation, mapping, execution, stop, and provider evidence;
- retained-history and request-context logs/manifests used by the current
  context audit path.

Derived runtime-observed samples must preserve, at minimum:

- source profile ID, `family`, `native_profile_kind`, and mutation source;
- exposed tool name and canonical tool name;
- source contract kind and payload shape;
- task, status, reward, verifier, and execution provenance needed by downstream
  contract verification.

Canonical names must not replace exposed ToolView names in model-visible
messages or targets. Conversely, exposed aliases must not redefine backend
semantics.

### 5. Acceptance boundary

Acceptance has three deliberately different evidence levels:

1. **Offline mainline tests** validate deterministic native runtime behavior,
   task assets, runtime-observed training preparation, golden contracts, and
   documentation governance without network access.
2. **Local-only native-family acceptance** validates both family builders,
   the Codex local task/direct-flow pack, and observed-data generation for both
   families. Its JSON report must satisfy `stabilized=true`.
3. **Real-provider acceptance** adds a small native Claude task pack. It is
   provider evidence, not an architecture driver or a default CI requirement.

Strict Codex real-provider acceptance remains transport-limited while the
formal OpenAI-compatible transport is function-only and Codex `apply_patch` is
freeform. Local/fake Codex acceptance is evidence for the runtime contract,
not proof of provider parity.

These gates do not claim production sandboxing, broad benchmark performance,
provider completeness, or industrial product readiness.

## Consequences

- Runtime and dataset code may branch on explicit native family metadata, but
  may not infer a family from stale task tool-name hints.
- Schema mutation must transform ToolViews while preserving family and
  canonical provenance.
- New transports must either support the selected family contract faithfully
  or reject it with an explicit limitation.
- New run writers or exporters must extend, not silently reinterpret, the
  artifact fields above.
- Small provider workloads remain acceptance/regression inputs; subsystem
  design continues to be driven by the current codex-rs implementation plan.

## Superseded planning records

This ADR replaces the RC-016 Tool Runtime planning cluster as the source of
current native-family terminology and selection policy. That cluster includes
the family split and legacy-demotion plans, implementation Steps A through F,
and the staged ToolView mutation plan. It remains available as historical
evidence in the
[RC-016 archive manifest](../archive/2026-07-16-tool-runtime/README.md).

The manifest records every original path, its status at archival time, its
replacement, and why it was retained. The current
[documentation map](../README.md) owns the repository-wide classification and
replacement relationships.

## Current sources of truth

- Runtime selection: [`coding_env.py`](../../pycodeagent/env/coding_env.py) and
  [`bootstrap.py`](../../pycodeagent/tools/bootstrap.py)
- Tool/profile boundary: [`spec.py`](../../pycodeagent/tools/spec.py),
  [`profile_factory.py`](../../pycodeagent/tools/profile_factory.py), and
  [`runtime.py`](../../pycodeagent/tools/runtime.py)
- Native family definitions: [`tools/families/`](../../pycodeagent/tools/families/)
- Provider capability boundary:
  [`provider_runtime.py`](../../pycodeagent/agent/provider_runtime.py)
- Runtime-observed provenance:
  [`schema_following_from_runtime.py`](../../pycodeagent/rl/schema_following_from_runtime.py)
- Acceptance implementation:
  [`native_family_acceptance.py`](../../pycodeagent/eval/native_family_acceptance.py)

Future implementation work is ordered by the
[codex-rs subsystem plan](../codex_rs_subsystem_implementation_plan.md), while
the [industrial gap roadmap](../local_runtime_industrial_gap_roadmap.md)
defines maturity and acceptance expectations.
