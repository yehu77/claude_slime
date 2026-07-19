# Step C0 Native Tool Contract Expansion Plan

> Archived by RC-016 on 2026-07-16. Current native-family terminology and
> policy are defined by
> [ADR-0001](../../adr/0001-native-family-runtime-boundary.md). This file is a
> historical implementation record and cannot override that decision. See this
> archive's README for provenance and replacement mapping.

> Historical status note: references below to "legacy function-only flows"
> describe the repository's older object-only compatibility assumptions, not a
> still-supported legacy builtin tool family.

## Goal

This document defines the missing prerequisite between the landed runtime
family work and the strict source-aligned canonical tool layer.

The purpose of **Step C0** is to remove the repository's current
**object-function-only tool contract assumption** so the local runtime can
represent and execute native tool families whose model-visible contracts are
not all JSON-object function tools.

The immediate reason this step exists is simple:

- strict source alignment cannot start at canonical tool definitions
- the current repo contract assumes function-style tools with object arguments
  end-to-end
- Codex `apply_patch` is a real counterexample because its native visible form
  is freeform, not a wrapped object payload

Step C0 is therefore an **end-to-end contract expansion step**, not a
runtime-only patch.

Its output is a mainline contract that can carry both:

- function tools with object arguments
- freeform tools with raw text input

without breaking the existing function-tool path.

## Non-Goals

Step C0 is not trying to:

- define the strict Step C canonical tool set itself
- redesign schema mutation for freeform tools
- force immediate real-provider transport parity for every provider
- replace `ToolAdapter` with a generalized freeform mutation engine
- delete legacy function-only flows

Step C0 exists so Step C can be source-aligned later without first fighting
the repo's object-only plumbing.

## Why Step C0 Is Necessary

The current repo contract is still function-only in several connected places.
That means strict native alignment cannot begin at the canonical tool layer.

Current blockers in the repo:

- [`pycodeagent/trajectory/schema.py`](../../../pycodeagent/trajectory/schema.py)
  stores `ToolCall.arguments` as `dict[str, Any]`
- [`pycodeagent/tools/spec.py`](../../../pycodeagent/tools/spec.py)
  stores `ToolView.input_schema` as `dict[str, Any]`
- [`pycodeagent/tools/spec.py`](../../../pycodeagent/tools/spec.py)
  stores `CanonicalTool.canonical_schema` as `dict[str, Any]`
- [`pycodeagent/agent/llm_client.py`](../../../pycodeagent/agent/llm_client.py)
  defines `GenerateRequest.tools` as `list[dict[str, Any]]` with a
  function-shaped assumption
- [`pycodeagent/agent/llm_client.py`](../../../pycodeagent/agent/llm_client.py)
  defines `ToolCallCandidate.arguments_obj` as `dict[str, Any] | None`
- [`pycodeagent/agent/parser.py`](../../../pycodeagent/agent/parser.py)
  rejects provider candidates that do not yield a parsed object
- [`pycodeagent/tools/runtime.py`](../../../pycodeagent/tools/runtime.py)
  validates and maps tool calls through JSON-object argument mapping only
- [`pycodeagent/rl/serializer.py`](../../../pycodeagent/rl/serializer.py) and
  native-transformed helpers render tool calls assuming an object payload
- [`pycodeagent/traces/tool_catalog_snapshot.py`](../../../pycodeagent/traces/tool_catalog_snapshot.py)
  assumes `input_schema` is a mapping

As long as those assumptions remain true, the repo can only model native tools
that fit the current function-object path. That would force Step C to adapt
real source contracts before the local runtime can even represent them.

That is exactly what this step is meant to avoid.

## Contract Target

Step C0 must define a new end-to-end native tool contract that spans the full
local runtime data path:

- provider request contract
- provider response candidate contract
- runtime dispatch contract
- trajectory and tool-call storage contract
- serializer and training-data rendering contract
- tool-catalog and profile snapshot contract

The result should be a repo contract that can faithfully represent a visible
tool definition and a tool call payload even when the payload is not a JSON
object.

## Core Design Decisions

Step C0 locks the following design decisions.

### 1. Add a discriminated internal tool contract kind

The repo should move from one implicit function-only tool schema assumption to
an explicit internal tool-contract union with two kinds:

- `function`
- `freeform`

Function tools stay on the current JSON-object path.

Freeform tools add a raw-text input path suitable for native contracts such as
Codex `apply_patch`.

This is an internal repo contract, not a promise that every external provider
transport already supports both kinds.

### 2. Add a discriminated tool-call payload kind

Tool-call payloads should no longer be modeled as "object arguments only".

Instead the runtime should support two payload kinds:

- `arguments_object`
- `input_text`

`arguments_object` is the current path used by function tools.

`input_text` is the new raw-text path used by freeform tools.

### 3. Keep function tools unchanged where possible

Step C0 is a contract expansion step, not a rewrite of the function path.

Requirements:

- existing function tools should continue to use JSON-object validation
- existing function tool execution should continue to use the current adapter
  path
- existing function-only tests and flows should remain compatible

### 4. Keep `ToolAdapter` function-only in Step C0

Freeform schema mutation design is explicitly deferred.

Step C0 should not pretend freeform mutation is solved just because freeform
identity exposure is now representable.

Required boundary:

- `ToolAdapter` remains function-oriented in Step C0
- freeform tools may be identity-exposed only
- mutation work for freeform tools is deferred beyond Step C0

### 5. Require fake/local end-to-end support

Real-provider transport expansion may remain a later integration task where
necessary, but Step C0 must still support freeform tools end-to-end through:

- fake responses
- parser
- runtime
- trajectory
- serializer
- runtime-observed export paths

Strict Step C cannot depend on hypothetical provider parity that the local
runtime cannot exercise.

## Required Interface Changes

Step C0 should require the following conceptual interface changes.

### `CanonicalTool`

Replace the single `canonical_schema` assumption with a contract union.

Requirements:

- canonical tool definitions must declare whether they are `function` or
  `freeform`
- canonical tool metadata must carry stable family and source information
- the repo must no longer assume every canonical tool has an object schema

### `ToolView`

Replace the single `input_schema` assumption with an exposed contract union.

Requirements:

- exposed tool definitions must declare their contract kind
- function views retain JSON-object schemas
- freeform views carry a native freeform contract representation rather than a
  fake object wrapper

### `ToolCall`

`ToolCall` must store payload kind and must support raw freeform text.

Required capability:

- function calls store object arguments
- freeform calls store raw input text
- trajectory storage must preserve which kind was actually used

### `ToolCallCandidate`

Provider-level candidates must support raw native freeform payloads.

Requirements:

- function candidates may continue to provide parsed object arguments
- freeform candidates must be representable without forcing a fake object
  parse
- parse errors should remain explicit and structured per payload kind

### `GenerateRequest.tools`

Stop treating this as an untyped list of function-only dicts.

Required target:

- request tools become a structured list of exposed tool specs
- each spec records its contract kind
- provider transport code can branch by kind

### `ToolRuntime`

Runtime dispatch must branch by tool kind.

Requirements:

- function calls continue through exposed-schema validation and adapter mapping
- freeform calls dispatch through a raw-text path
- the runtime must no longer assume all tools are validated through JSON-object
  schemas

### Serializer and reward/eval helpers

The serializer and native-transformed helpers must support freeform call
payload rendering.

Requirements:

- tool-call rendering must remain deterministic
- freeform payloads must serialize without being rewritten as fake JSON
  objects
- downstream reward and dataset helpers must preserve payload kind

### Tool catalog and profile snapshot contracts

Catalog and profile snapshot helpers must support non-object tool
definitions.

Requirements:

- snapshot contracts must no longer assume `input_schema: dict`
- native visible tool definitions should preserve their contract kind
- profile exports must remain precise enough for later mutation and filtering

## Implementation Plan

Step C0 should be implemented by subsystem rather than by file inventory.

### A. Contract type expansion

Introduce stable internal contract types for:

- exposed tool specs
- canonical tool specs
- tool-call payloads

This step should give the repo one explicit internal representation for:

- function tool definition plus object schema
- freeform tool definition plus raw input contract
- object tool-call payload
- text tool-call payload

### B. Provider request plumbing

Update request-building paths so `GenerateRequest.tools` can carry structured
exposed tool specs instead of raw function-style dicts only.

Requirements:

- current function-tool request generation remains supported
- provider clients can branch on tool kind
- fake/local request paths can round-trip both kinds

### C. Provider response candidate and parser plumbing

Update `ToolCallCandidate` and parser logic so native freeform tool payloads
can be accepted and turned into internal `ToolCall` records.

Requirements:

- function candidates keep the current parsed-object path
- freeform candidates use raw text payload storage
- parser errors stay explicit and deterministic

### D. Runtime dispatch plumbing

Update `ToolRuntime` so dispatch branches on tool kind.

Requirements:

- function path still validates and maps through `ToolAdapter`
- freeform path bypasses object-schema mapping
- runtime metadata preserves whether the call came through function or
  freeform dispatch

### E. Trajectory and serializer plumbing

Update trajectory storage and serialization so tool calls can preserve and
render payload kind.

Requirements:

- trajectory records must preserve raw freeform text
- tool-call rendering must remain stable for training-data generation
- reward, export, and evaluation helpers must not silently erase payload kind

### F. Tool-catalog and profile snapshot plumbing

Update tool-catalog, profile export, and native snapshot helpers to support
non-object tool definitions.

Requirements:

- visible tool definitions preserve contract kind
- catalogs remain deterministic and serializable
- source-native freeform tools can be represented without synthetic object
  wrappers

### G. Compatibility pass

After contract expansion lands, confirm that function-only flows still behave
as before.

Requirements:

- legacy builtin profiles still work
- function-only fake clients still work
- runtime-observed exports remain compatible for function-only runs

## Boundaries That Stay Deferred

Step C0 must explicitly defer the following:

- freeform schema mutation beyond identity exposure
- cross-provider transport parity when a provider API cannot yet carry the new
  contract natively
- any claim that strict Step C is already landed just because the contract can
  now represent it

Step C0 is about removing the contract bottleneck, not about finishing the
native tool family work.

## Acceptance Criteria

Step C0 is complete only when all of the following are true:

- function tools still work unchanged through the mainline runtime path
- freeform tool specs can be represented in requests, profiles, and catalogs
- freeform tool calls can be parsed, stored, dispatched, serialized, and
  exported
- object-function-only assumptions are removed from the mainline runtime path
- legacy function-only flows remain compatible

The acceptance criterion is **contract breadth**, not tool count.

## Test Plan

Require tests in the following groups.

### Contract tests

- function and freeform tool definitions both validate
- function and freeform tool-call payloads both round-trip through internal
  types
- legacy function-only definitions remain valid

### Parser and runtime tests

- function tool candidates still parse into object payloads
- freeform candidates parse into raw-text payloads
- runtime dispatch selects the correct validation and execution path by tool
  kind

### Trajectory and serializer tests

- trajectories preserve payload kind
- serialized tool calls remain deterministic for both payload kinds
- native-transformed helpers do not erase freeform payload identity

### Catalog and profile tests

- profile exports preserve contract kind
- tool-catalog snapshots can represent non-object tool definitions
- legacy function-only snapshot flows remain compatible

### Compatibility tests

- legacy builtin bootstrap continues to work
- existing function-only tests remain green
- fake/local runtime-observed flows still export usable artifacts

## Assumptions And Defaults

- Step C0 is end-to-end across runtime, trajectory, serializer, and
  tool-catalog contracts.
- Step C0 introduces two internal tool-contract kinds: `function` and
  `freeform`.
- Step C0 introduces two internal tool-call payload kinds:
  `arguments_object` and `input_text`.
- `ToolAdapter` remains function-only in Step C0.
- Real-provider transport parity for freeform tools may remain a later
  integration task, but fake/local end-to-end support is required now.
