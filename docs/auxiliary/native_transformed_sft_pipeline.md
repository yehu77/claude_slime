# Native Transformed SFT Pipeline

> **Auxiliary route:** This is a non-mainline compatibility pipeline registered
> by RC-029. Follow [source route boundaries](../source_route_boundaries.md);
> RC-030 completed its namespace migration.

This document describes the narrowest end-to-end path from a **real Claude API
trace** to a **training-prep output** for the native-transformed SFT line.

For the repository-level training infrastructure view, see
[agent_training_infra_architecture.md](../agent_training_infra_architecture.md).
For the prompt-only RL path built from the same native-transformed samples, see
[native_transformed_rl_pipeline.md](./native_transformed_rl_pipeline.md).

The scope here is intentionally narrow:

- source: real Claude API trace captured by `claude_gateway_proxy.py`
- schema source: request-side model-visible `tools`
- transformation scope: surface-only native view transformation
- training target: `text` and transformed `tool_use`
- downstream output: validated raw dataset plus current training-prep bundle

It does not cover:

- local runtime traces such as subprocess logs, diffs, or verifier output
- canonical capability mapping
- schema-changing mutation
- multi-agent generalization beyond Claude

## Overall Chain

The current minimal chain is:

```text
real Claude Code
  -> local Claude gateway proxy
  -> session JSONL API trace
  -> extracted request with request-side tools + assistant tool_use
  -> request-scoped native tool catalog
  -> base native ToolProfile
  -> transformed native ToolProfile
  -> transformed ClaudeApiSFTSample
  -> train.jsonl
  -> validation_report.json
  -> shared training bundle / tokenized.jsonl / packed.jsonl
```

The important identity of this pipeline is:

- preserve the **native tool schema actually shown to the model**
- transform that schema into alternate surface views
- keep tool-use supervision aligned with the transformed visible schema

## Downstream Consumers

The SFT artifacts currently feed three different downstream checks:

- HF SFT smoke: a lightweight local check that the tokenized native-transformed
  samples can be consumed by the existing Hugging Face causal LM SFT path.
- slime offline SFT smoke: a Megatron/slime path that consumes
  `tokenized.jsonl` or `smoke_tokenized.jsonl` directly through
  `slime.rollout.pycodeagent_offline.PyCodeAgentPreparedDataSource`.
- RL prompt export: a prompt-only conversion that writes `rl_prompts.jsonl` for
  online rollout and reward scoring.

Only the first two are SFT consumers. The RL path does not reuse SFT loss masks;
it reuses the same native-transformed source samples as reward references.

## Step 1: Capture Real Claude API Trace

Start the local gateway proxy:

```powershell
python claude_gateway_proxy.py --host 127.0.0.1 --port 4000
```

Point Claude Code at the local proxy. If your normal setup already uses an
Anthropic-compatible upstream such as a gateway, keep that auth configuration
and make the local proxy the visible `ANTHROPIC_BASE_URL`.

Example:

```powershell
$env:ANTHROPIC_BASE_URL = "http://127.0.0.1:4000"
claude
```

The proxy writes session JSONL files under:

```text
runs/claude_gateway_traces/<session_id>.jsonl
```

For this pipeline, the useful session is one where:

- request `N` contains a non-empty request-side `tools` list
- assistant response for request `N` contains at least one `tool_use`
- a later request contains the corresponding `tool_result`

That is the minimum trace shape needed for transformed tool-use training data.

## Step 2: Export Native-Transformed Raw SFT Dataset

Run the transformed dataset exporter on a directory of Claude session JSONL
files:

```powershell
python export_native_transformed_sft_dataset.py ^
  runs/claude_gateway_traces ^
  outputs/native_transformed_sft/v1
```

Optional:

```powershell
python export_native_transformed_sft_dataset.py ^
  runs/claude_gateway_traces ^
  outputs/native_transformed_sft/v1 ^
  --no-strict ^
  --continue-on-error
```

This step does the following internally:

1. read each Claude API session JSONL
2. iterate `/v1/messages` requests
3. keep only requests with:
   - non-empty request-side `tools`
   - assistant `tool_use`
4. build:
   - request-scoped `AgentToolCatalog`
   - base native `ToolProfile`
   - transformed native `ToolProfile` for each supported mode
5. emit transformed `ClaudeApiSFTSample` rows

Current transformation modes:

- `base`
- `name_only`
- `description_only`
- `name_description`

Current output directory:

```text
outputs/native_transformed_sft/v1/
  train.jsonl
  dataset_manifest.json
  split_metrics.json
```

Important behavior:

- `tool_specs` in each sample come from the **target transformed profile**
- assistant `tool_use` target uses the **transformed exposed tool name**
- tool-call arguments are preserved
- `thinking` does not enter trainable target
- `tool_result` does not enter trainable target
- `tool_result` is still retained in audit metadata

## Step 3: Validate The Exported Dataset

Validate the exported dataset before training prep:

```powershell
python validate_native_transformed_sft_dataset.py ^
  outputs/native_transformed_sft/v1
```

This writes:

```text
outputs/native_transformed_sft/v1/validation_report.json
```

The validator checks:

- `train.jsonl` rows parse as `ClaudeApiSFTSample`
- `dataset_manifest.json` exists and has:
  - `dataset_type = "native_transformed_claude_api_sft"`
  - `primary_sample_input = "train.jsonl"`
  - `present_splits = ["train"]`
- each sample has:
  - `metadata.transformation_mode`
  - non-empty visible `tool_specs`
  - required source metadata
  - remap report with no unmapped/dropped tool uses
- every assistant tool-call target name exists in visible tool specs
- no `thinking` or `tool_result` blocks appear in trainable target

If validation fails, fix the dataset export or the underlying trace handling
before proceeding.

## Step 4: Prepare Training Artifacts

Once the dataset is validated, run training prep:

```powershell
python prepare_native_transformed_sft_training_data.py ^
  outputs/native_transformed_sft/v1 ^
  outputs/native_transformed_sft/prepared ^
  --fake-tokenizer
```

For a real tokenizer path:

```powershell
python prepare_native_transformed_sft_training_data.py ^
  outputs/native_transformed_sft/v1 ^
  outputs/native_transformed_sft/prepared ^
  --tokenizer-name path-or-hf-tokenizer-name
```

This step adapts the Claude API source into PreparedSample v1 and delegates
tokenization, packing, contract verification and checksums to the shared
TrainingBundleBuilder. It does not introduce a new training sample format.

Current output directory:

```text
outputs/native_transformed_sft/prepared/
  bundle_manifest.json
  contract_report.json
  packed.jsonl
  samples.jsonl
  tokenized.jsonl
  tokenizer_config.yaml
  train_config.json
  training_prep.json
```

Semantics:

- primary upstream input: `train.jsonl`
- primary prepared input: `samples.jsonl`
- primary training input: `tokenized.jsonl`

Metadata stays explicit that this line is:

- `source_type = "native_transformed_claude_api_sft"`

and also preserves:

- `raw_source_type = "claude_api_trace"`

so downstream code can distinguish the transformed dataset identity from the
raw Claude API trace origin.

## Minimal End-To-End Command Sequence

From repo root:

```powershell
python claude_gateway_proxy.py --host 127.0.0.1 --port 4000
```

Run Claude Code against the proxy and generate a real tool-use session, then:

```powershell
python export_native_transformed_sft_dataset.py ^
  runs/claude_gateway_traces ^
  outputs/native_transformed_sft/v1
```

```powershell
python validate_native_transformed_sft_dataset.py ^
  outputs/native_transformed_sft/v1
```

```powershell
python prepare_native_transformed_sft_training_data.py ^
  outputs/native_transformed_sft/v1 ^
  outputs/native_transformed_sft/prepared ^
  --fake-tokenizer
```

## Artifact Meanings

### Raw trace input

```text
runs/claude_gateway_traces/<session_id>.jsonl
```

- real Claude API trace
- request-side tool schema source
- assistant `tool_use` / follow-up `tool_result` trajectory source

### Raw transformed dataset

```text
outputs/native_transformed_sft/v1/train.jsonl
```

- transformed native SFT samples
- one request may emit multiple rows, one per transformation mode
- still human-auditable and validator-friendly

### Validation output

```text
outputs/native_transformed_sft/v1/validation_report.json
```

- confirms transformed dataset structural correctness
- should be green before training prep

### Training-prep output

```text
outputs/native_transformed_sft/prepared/
```

- prepared serialized samples
- tokenized training dataset
- tokenizer config
- train config
- summary recommendation

## Current Boundaries

This pipeline is intentionally not yet:

- multi-agent generic
- schema-mutation aware
- canonicalization based
- runtime-trace aware

Current status is narrower and explicit:

- real Claude API trace ingestion
- native model-visible tool schema preservation
- surface-level schema view transformation
- transformed tool-use training sample export
- validated reuse of existing training-prep infrastructure
- tokenized sample adaptation for slime offline SFT smoke
- prompt-only RL dataset export for slime online RL smoke

Not yet proven in remote training:

- a completed slime/Megatron offline SFT optimizer step on A800
- a completed slime/Megatron online RL optimizer step on A800
- post-training model quality improvement
