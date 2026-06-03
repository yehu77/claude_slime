# PYCODEAGENT_MULTI_AGENT_SCAFFOLD_DESIGN

## 1. Purpose

This document defines the next repo-level architecture target:

> Build `pycodeagent` into a multi-agent coding trace collection scaffold that
> can run real coding agents, preserve their native tool schemas and raw
> execution traces, preserve the model-visible tool schemas those agents
> actually expose, normalize them into canonical capabilities when useful,
> apply schema mutation or view transformation, and then hand the resulting
> datasets to the existing slime-compatible training pipeline.

This is a broader target than the current single-runtime research harness.

The key shift is:

```text
from:
single repo-owned coding runtime
  -> trajectory
  -> rollout / dataset / schema-following train/eval

to:
multiple real coding agents
  -> raw tool catalogs and raw traces
  -> canonical traces
  -> schema mutation / view transformation
  -> training datasets
  -> slime-compatible train/eval bundles
```

---

## 2. What Must Stay

The new scaffold should extend the existing strengths of this repo, not replace
them.

Existing foundations to preserve:

1. `CanonicalTool -> ToolView -> ToolAdapter` as the core semantic abstraction
2. full structured trajectory capture and deterministic export
3. serializer, mask alignment, tokenization, packing, and contract checking
4. schema-following sample generation and projection APIs as downstream
   consumers of transformed traces
5. slime-compatible training-prep bundle generation
6. local SFT / eval proof path already implemented for schema following

The new scaffold should add a multi-agent ingestion front half while reusing the
existing post-normalization back half.

---

## 3. One-Sentence Repo Positioning

After this redesign, the repo should be described as:

> A multi-agent coding trace collection and schema-generalization research
> scaffold that captures native tool-use traces from real coding agents,
> preserves the tool schemas actually exposed to the model, mutates or
> transforms those schemas in controlled ways, generates training/eval data,
> and prepares slime-compatible bundles for downstream training.

---

## 4. End-To-End Target Pipeline

The intended top-level flow is:

```text
task / repo / tests
  -> agent adapter
  -> native tool catalog capture
  -> raw trace capture
  -> canonical trace normalization
  -> schema mutation / view transformation
  -> training dataset generation
  -> tokenization / mask / packing / contract verification
  -> slime-compatible training bundle
  -> optional downstream slime training
```

---

## 5. Layered Architecture

### 5.1 Task Layer

This layer defines what work an agent should attempt.

Inputs:

- repository path or checkout source
- base commit or snapshot ID
- task prompt or issue text
- verifier/test command
- allowed/forbidden file constraints
- metadata such as language, repo family, difficulty, benchmark source

Current mapping:

- extend existing `CodingTask`

Recommended additions:

- `base_commit`
- `repo_snapshot_id`
- `task_source`
- `expected_branch`
- `verifier_kind`

### 5.2 Agent Adapter Layer

This layer makes real coding agents pluggable.

Important design rule:

- the agent adapter should only be responsible for running the agent and
  returning raw run artifacts
- it should not also own tool catalog inference, trace normalization, or
  augmentation rendering

Recommended protocol:

```python
class AgentAdapter(Protocol):
    def agent_id(self) -> str: ...
    def agent_version(self) -> str: ...
    def run_task(self, task: CodingTask, workspace_dir: Path) -> RawAgentRunResult: ...
```

`RawAgentRunResult` is the run-level artifact index returned by the adapter. It
is not the trace body itself.

Initial adapters:

- `MockAdapter`
- `CodexCliAdapter`
- `ClaudeCodeAdapter`
- `KiloCodeAdapter`
- `CustomAgentAdapter`

### 5.2.1 Tool Catalog Provider Layer

This layer describes or extracts the native tool interface available to an
agent.

Recommended protocol:

```python
class ToolCatalogProvider(Protocol):
    def agent_id(self) -> str: ...
    def get_tool_catalog(
        self,
        *,
        task: CodingTask | None = None,
        workspace_dir: Path | None = None,
        run_artifacts: RawAgentRunResult | None = None,
    ) -> AgentToolCatalog | None: ...
```

Initial providers:

- `MockToolCatalogProvider`
- `CodexCatalogProvider`
- `ClaudeCodeCatalogProvider`
- `KiloCatalogProvider`

### 5.2.2 Trace Normalizer Layer

This layer converts raw traces into canonical traces.

Recommended protocol:

```python
class TraceNormalizer(Protocol):
    def agent_id(self) -> str: ...
    def normalize(
        self,
        raw_trace: RawAgentTrace,
        *,
        tool_catalog: AgentToolCatalog | None = None,
    ) -> CanonicalTrace:
        ...
```

Initial normalizers:

- `MockTraceNormalizer`
- `CodexTraceNormalizer`
- `ClaudeCodeTraceNormalizer`
- `KiloTraceNormalizer`

### 5.2.3 Augmentation Renderer Layer

This layer converts canonical traces or canonical intents into alternate
ToolViews and transformed training samples.

Recommended protocol:

```python
class AugmentationRenderer(Protocol):
    def render_from_trace(
        self,
        canonical_trace: CanonicalTrace,
        *,
        target_profiles: list[ToolProfile],
    ) -> list[SchemaFollowingSample]:
        ...
```

The first implementation can keep using the existing schema-following generation
modules as one downstream renderer implementation, but those modules should be
treated as consumers of the transformed-trace scaffold rather than the top-line
repo identity.

### 5.3 Execution Harness

This layer is agent-agnostic orchestration around adapters, catalog providers,
and normalizers.

Responsibilities:

1. prepare isolated workspace
2. materialize task inputs
3. invoke chosen agent adapter
4. collect stdout/stderr/log files
5. resolve tool catalog through the configured `ToolCatalogProvider`
6. normalize raw trace through the configured `TraceNormalizer`
7. collect final diff
8. run verifier/tests
9. attach reward/status
10. write raw artifacts and normalized artifacts

This should evolve from the current `env/` plus study runner logic, not be
rebuilt from zero.

### 5.4 Trace And Artifact Layer

This layer must preserve both truth and normalization.

There are five first-class artifact types:

1. `RawAgentRunResult`
2. `AgentToolCatalog`
3. `RawAgentTrace`
4. `CanonicalTrace`
5. `NormalizationReport`

Raw and canonical artifacts must both be kept.

Auxiliary ingestion note:

- API-trace-only sources such as the Claude gateway proxy can be useful
  additional trace inputs.
- They should be treated as auxiliary ingestion paths, not as replacements for
  the main multi-agent raw trace + native tool schema scaffold.

Important phase boundary:

- `RawAgentTrace` must exist from the beginning as a first-class contract and
  artifact type.
- In the first scaffold phase, it may be produced by `MockAdapter` or a
  synthetic trace generator rather than a real external coding agent.
- Real native raw-trace ingestion is a later integration milestone, not a
  prerequisite for establishing the scaffold contracts.

### 5.5 Augmentation Layer

This layer starts from canonical semantics, not from raw string replacement.

Flow:

```text
raw trace
  -> canonical trace
  -> canonical intent / canonical action slices
  -> re-render under alternate ToolViews
  -> schema-following samples
```

Allowed first-phase augmentation:

- tool name changes
- parameter name changes
- flat-to-nested and nested-to-flat parameter structure changes
- tool description paraphrases
- observation presentation changes

Forbidden first-phase augmentation:

- changing tool semantics
- changing call order
- changing task outcome semantics
- altering verifier truth

### 5.6 Dataset / Train / Eval Layer

This repo already has most of this layer.

Expected outputs:

- rollout-like datasets
- schema-following SFT datasets
- tokenized / packed contract-checked bundles
- slime-compatible train bundle
- local base-vs-trained eval reports

---

## 6. Core Data Models

### 6.1 RawAgentRunResult

Purpose:

- represent the artifact index for one agent run
- point to trace and log artifacts without duplicating the trace payload itself

Important distinction:

- this is not the raw trace
- this is the run-level artifact manifest returned by `AgentAdapter.run_task(...)`

Minimum fields:

```text
run_id
task_id
agent_id
agent_version
status

tool_catalog_path
raw_trace_path
stdout_path
stderr_path
final_diff_path
verifier_result_path

workspace_before_hash
workspace_after_hash

error
metadata
```

The adapter may inline extra execution metadata, but the trace body itself
should live in `raw_trace.jsonl` or an equivalent raw trace artifact referenced
from this object.

### 6.2 AgentToolCatalog

Purpose:

- describe the native tool interface available to a specific agent in a
  specific run mode

Minimum fields:

```text
catalog_id
agent_name
agent_version
capture_mode
source_kind
captured_at
tools[]
metadata
```

Per-tool fields:

```text
raw_tool_name
description
input_schema
output_format_hint
availability_conditions
tool_family
metadata
```

Important distinction:

- `static tool catalog`: inferred from source/config
- `effective runtime tool catalog`: what the agent actually saw during a run

### 6.3 RawAgentTrace

Purpose:

- preserve native tool-use behavior without forcing early normalization

Minimum fields:

```text
trace_id
agent_name
agent_version
task_id
workspace_dir
tool_catalog_id
events[]
final_diff
verifier_result
status
metadata
```

Recommended event kinds:

- `assistant_text`
- `tool_call`
- `tool_result`
- `command_exec`
- `file_edit`
- `approval_event`
- `agent_plan`
- `run_end`

### 6.4 CanonicalAction

Purpose:

- represent one normalized capability step independent of agent-specific naming

Minimum fields:

```text
action_id
capability
canonical_args
raw_event_refs
raw_tool_name
mapping_confidence
normalization_notes
metadata
```

### 6.5 CanonicalTrace

Purpose:

- represent one run as a sequence of canonical capability steps while still
  referencing raw evidence

Minimum fields:

```text
trace_id
task_id
agent_name
agent_version
actions[]
final_diff
verifier_result
status
metadata
```

### 6.6 NormalizationReport

Purpose:

- make normalization inspectable instead of implicit

Minimum fields:

```text
trace_id
catalog_id
mapped_events
unmapped_events
ambiguous_events
warnings
errors
```

---

## 7. Canonical Capability Taxonomy V1

The first version should stay intentionally narrow.

Recommended capability set:

- `LIST_FILES`
- `READ_FILE`
- `SEARCH_CODE`
- `EDIT_FILE`
- `RUN_COMMAND`
- `FINISH`

Possible future additions:

- `OPEN_BROWSER`
- `RUN_TESTS`
- `WRITE_NOTE`
- `PLAN_STEP`
- `GIT_OPERATION`
- `EXTERNAL_WEB_SEARCH`

For V1, do not expand the taxonomy until the first multi-agent ingestion path is
stable.

---

## 8. Adapter Maturity Levels

### Level 0: Catalog-Only

What works:

- static tool catalog can be registered
- no live execution required

Useful for:

- early scaffold bring-up
- documenting real agent schema surfaces

### Level 0.5: Synthetic-Raw-Trace-Capable

What works:

- `RawAgentTrace` artifacts exist
- traces are emitted by `MockAdapter` or synthetic generators
- canonical normalization can already be tested end to end

Useful for:

- proving the raw-trace contract before any external agent integration
- hardening schema generalization, augmentation, contract checks, and slime
  bundle generation with deterministic inputs

### Level 1: Raw-Trace-Capable

What works:

- tasks can run through the real agent
- raw trace and artifacts are collected
- normalization may still be partial

Useful for:

- early real-data ingestion
- catalog validation

### Level 2: Canonicalized

What works:

- raw tool calls can map into canonical capabilities
- normalization reports exist

Useful for:

- downstream dataset generation

### Level 3: Augmentation-Ready

What works:

- canonical actions can be re-rendered into alternate ToolViews
- schema-following datasets can be built automatically

Useful for:

- training and evaluation

---

## 9. Artifact Directory Layout

Recommended run bundle:

```text
runs/
  multi_agent/
    <study_or_batch_id>/
      <agent_name>/
        <task_id>__<run_id>/
          task.json
          workspace_manifest.json
          tool_catalog.json
          raw_trace.jsonl
          raw_trace_summary.json
          canonical_trace.json
          normalization_report.json
          trajectory.json
          verifier.json
          final.diff
          stdout.log
          stderr.log
          adapter_metadata.json
```

Important note:

- `trajectory.json` can remain as a repo-native normalized trajectory artifact
- it should not replace `raw_trace.jsonl`

---

## 10. Relationship To Existing Repo Modules

### Reuse As-Is Or With Light Extension

- `pycodeagent/tools/spec.py`
- `pycodeagent/mutations/`
- `pycodeagent/rl/schema_following*.py`
- `pycodeagent/rl/serializer.py`
- `pycodeagent/rl/contract.py`
- `pycodeagent/rl/training_prep.py`
- `pycodeagent/rl/schema_following_eval.py`
- `pycodeagent/rl/schema_following_sft.py`

### Extend Significantly

- `pycodeagent/env/task.py`
- `pycodeagent/env/coding_env.py`
- `pycodeagent/eval/experiment_runner.py`
- `pycodeagent/trajectory/schema.py`

### Add New

- `pycodeagent/adapters/`
- `pycodeagent/harness/`
- `pycodeagent/traces/`

---

## 11. Proposed New File Structure

```text
pycodeagent/
  adapters/
    __init__.py
    base.py
    mock_adapter.py
    codex_catalog_adapter.py
    codex_cli_adapter.py
    claude_code_adapter.py
    kilo_code_adapter.py
    custom_agent_adapter.py
  harness/
    __init__.py
    run_bundle.py
    agent_harness.py
    artifact_writer.py
  traces/
    __init__.py
    tool_catalog.py
    raw_trace.py
    canonical_trace.py
    normalize.py
    normalizers/
      __init__.py
      codex.py
      claude_code.py
      kilo.py
```

---

## 12. Integration With Existing Schema-Following Pipeline

The critical invariant is:

```text
multi-agent raw traces
  -> canonical trace
  -> canonical intent extraction
  -> existing schema-following sample generation
  -> existing tokenization / contract / training prep
  -> existing local SFT / eval and slime handoff
```

The repo should not fork into two different downstream training pipelines.

Instead:

1. new front-end ingestion layers feed
2. existing schema-following dataset and contract layers

This keeps the current Phase 3-6 work valuable.

---

## 13. What This Scaffold Is Not

This scaffold is not trying to do all of the following at once:

- prove full autonomous coding ability
- replace each vendor's product UX
- claim production sandbox completeness
- solve RL training generally
- normalize every possible tool in V1

The narrow claim should remain:

> We can collect native traces from multiple coding agents, preserve their
> schema differences, normalize them into canonical capabilities, and generate
> contract-checked schema-generalization datasets for downstream training and
> evaluation.

---

## 14. First Implementation Phase

The first implementation phase should not start with full runtime support for
every agent.

It should do this instead:

1. freeze scaffold-level data contracts
2. add `RawAgentRunResult`, `AgentToolCatalog`, `RawAgentTrace`,
   `CanonicalTrace`
3. add `AgentAdapter`, `ToolCatalogProvider`, `TraceNormalizer`, and
   `AugmentationRenderer` protocols
4. add `MockAdapter`
5. add `MockToolCatalogProvider`
6. add a synthetic trace generator that emits `RawAgentTrace`
7. add `MockTraceNormalizer`
8. add `AgentHarness`
9. add `raw -> canonical` normalization interfaces

The first phase should explicitly avoid depending on a real external agent's
observable boundary. The goal is to make the contract-heavy downstream path
solid first:

```text
MockAdapter / synthetic raw trace
  -> RawAgentTrace
  -> CanonicalTrace
  -> schema-preserving augmentation
  -> contract check
  -> slime-compatible bundle
```

Only then start real runtime adapters:

1. `CodexCliAdapter`
2. `ClaudeCodeAdapter`
3. `KiloCodeAdapter`

Reason:

- the scaffold should be structurally correct before deep per-agent work begins

---

## 15. Acceptance Criteria For The Scaffold

The scaffold is meaningfully in place when:

1. at least one adapter can provide a tool catalog
2. `RawAgentTrace` artifacts can be produced, even if initially from
   `MockAdapter` or synthetic trace generation
3. at least one normalizer can emit canonical traces
4. canonical traces can feed the existing schema-following dataset path
5. schema-augmented data can be prepared into slime-compatible training bundles
6. local base-vs-trained schema-following evaluation still works on those
   generated datasets

Real external raw-trace collection is the next milestone after this baseline,
not part of the minimum definition of a functioning scaffold.

---

## 16. Recommended Next Step

The immediate next step after adopting this document is:

> implement the scaffold contracts first, starting with
> `RawAgentRunResult`, `AgentToolCatalog`, `RawAgentTrace`,
> `CanonicalTrace`, and `AgentAdapter`.

Do not start with agent-specific reverse engineering before these contracts
exist, and do not block the scaffold on real external raw traces in phase one.
