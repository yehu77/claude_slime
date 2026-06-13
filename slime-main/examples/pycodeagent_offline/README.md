# PyCodeAgent slime Training Smoke

This directory contains the pycodeagent-owned slime smoke entrypoints. It now
covers two paths:

- offline SFT-style training from prepared/tokenized data
- online RL-style training from native-transformed prompt data and a custom
  reward function

These scripts are infrastructure smoke tests. They are meant to prove that data
can enter slime/Megatron and complete at least a tiny train step, not to produce
a useful tuned model.

## Offline SFT Bridge

The offline path uses:

- `slime.rollout.pycodeagent_offline.PyCodeAgentPreparedDataSource`
- `slime.rollout.pycodeagent_offline.generate_rollout`

to feed pre-built `pycodeagent` rollouts or tokenized SFT samples directly into
the training path.

Supported inputs:

- legacy prepared bundle directory containing `rollouts.jsonl`
- prepared directory containing `tokenized.jsonl`
- direct path to `tokenized.jsonl`
- direct path to `smoke_tokenized.jsonl`

For legacy rollout bundles, point `--prompt-data` at a prepared bundle
directory, for example:

```text
runs/training_prep/schema_failure_attribution_v1_mimo_v25pro/
```

That directory should contain at least:

- `rollouts.jsonl`
- `tokenizer_config.yaml`
- `train_config.json`

For native-transformed SFT smoke, use the already trimmed tokenized file:

```text
outputs/native_transformed_sft/qwen_smoke_run_trim/train/smoke_tokenized.jsonl
```

Run:

```bash
cd /home/kas/claude_slime/slime-main

CODEX_REPO=/home/kas/claude_slime \
MEGATRON_DIR=/home/kas/claude_slime/Megatron-LM \
MODEL_HF_DIR=/home/kas/claude_slime/Qwen3-0.6B \
MODEL_TORCH_DIST_DIR=/home/kas/claude_slime/Qwen3-0.6B_torch_dist \
PREPARED_BUNDLE_DIR=/home/kas/claude_slime/outputs/native_transformed_sft/qwen_smoke_run_trim/train/smoke_tokenized.jsonl \
NUM_GPUS=1 \
ROLLOUT_BATCH_SIZE=1 \
GLOBAL_BATCH_SIZE=1 \
NUM_ROLLOUT=2 \
bash examples/pycodeagent_offline/run_qwen3_0p6b_native_transformed_smoke.sh
```

This script uses `--debug-train-only`, `--loss-type sft_loss`, and does not
start SGLang rollout servers.

## Online RL Bridge

The online RL path uses:

- `slime.rollout.pycodeagent_native_rl.PyCodeAgentNativeRLDataSource`
- `slime.rollout.sglang_rollout.generate_rollout`
- `slime.rollout.pycodeagent_native_rl.reward_func`

Expected input:

```text
outputs/native_transformed_rl/qwen_smoke_tiny/train/rl_prompts.jsonl
```

Run:

```bash
cd /home/kas/claude_slime/slime-main

CODEX_REPO=/home/kas/claude_slime \
MEGATRON_DIR=/home/kas/claude_slime/Megatron-LM \
MODEL_HF_DIR=/home/kas/claude_slime/Qwen3-0.6B \
MODEL_TORCH_DIST_DIR=/home/kas/claude_slime/Qwen3-0.6B_torch_dist \
RL_PROMPT_DATA_DIR=/home/kas/claude_slime/outputs/native_transformed_rl/qwen_smoke_tiny \
NUM_GPUS=1 \
ROLLOUT_BATCH_SIZE=1 \
GLOBAL_BATCH_SIZE=1 \
NUM_ROLLOUT=1 \
bash examples/pycodeagent_offline/run_qwen3_0p6b_native_transformed_rl_smoke.sh
```

This script starts the normal online rollout path through SGLang and scores
generated completions with pycodeagent's native-transformed tool-call reward.

## Model And Megatron Setup

For the first end-to-end smoke run, use:

- `Qwen3-0.6B`

Both SFT and RL slime smokes need:

- a Hugging Face checkpoint, for example `/home/kas/claude_slime/Qwen3-0.6B`
- a Megatron `torch_dist` checkpoint, for example
  `/home/kas/claude_slime/Qwen3-0.6B_torch_dist`
- a Megatron-LM checkout
- a Python/CUDA environment with Megatron dependencies and
  `transformer_engine`

Before training, convert the HF checkpoint into Megatron `torch_dist` format if
the converted directory does not exist:

```bash
cd /home/kas/claude_slime/slime-main

CODEX_REPO=/home/kas/claude_slime \
MEGATRON_DIR=/home/kas/claude_slime/Megatron-LM \
MODEL_HF_DIR=/home/kas/claude_slime/Qwen3-0.6B \
MODEL_TORCH_DIST_DIR=/home/kas/claude_slime/Qwen3-0.6B_torch_dist \
bash examples/pycodeagent_offline/convert_qwen3_0p6b_to_torch_dist.sh
```

This should produce:

- `/home/kas/claude_slime/Qwen3-0.6B_torch_dist`

Known environment pitfalls:

- `MEGATRON_DIR` defaults to `/root/Megatron-LM`; override it if Megatron-LM is
  under `/home/kas/claude_slime` or another user directory.
- Installing `transformer-engine` as a `0.0.0` placeholder does not provide the
  importable `transformer_engine` PyTorch extension.
- If `MODEL_TORCH_DIST_DIR` is missing, both smoke scripts fail before training.
- The full RL prompt dataset can contain very long prompts; use
  `qwen_smoke_tiny` for the first online RL smoke.

## Legacy Offline Runs

The older offline scripts are still available:

```bash
cd /workspace/claude_slime/slime-main
bash examples/pycodeagent_offline/run_qwen3_4b_offline.sh
```

For the smaller 0.6B smoke setup:

```bash
cd /workspace/claude_slime/slime-main
bash examples/pycodeagent_offline/run_qwen3_0p6b_offline.sh
```

Before running, edit the path variables at the top of the script or override
them via environment variables:

```bash
CODEX_REPO=/workspace/claude_slime \
MODEL_HF_DIR=/models/Qwen3-4B \
MODEL_TORCH_DIST_DIR=/models/Qwen3-4B_torch_dist \
PREPARED_BUNDLE_DIR=/workspace/claude_slime/runs/training_prep/schema_failure_attribution_v1_mimo_v25pro \
TRAIN_OUTPUT_DIR=/runs/slime_qwen3_4b_pycodeagent \
bash examples/pycodeagent_offline/run_qwen3_4b_offline.sh
```

Or for the 0.6B smoke path:

```bash
CODEX_REPO=/workspace/claude_slime \
MODEL_HF_DIR=/models/Qwen3-0.6B \
MODEL_TORCH_DIST_DIR=/models/Qwen3-0.6B_torch_dist \
PREPARED_BUNDLE_DIR=/workspace/claude_slime/runs/training_prep/schema_failure_attribution_v1_mimo_v25pro \
TRAIN_OUTPUT_DIR=/workspace/claude_slime/runs/slime_qwen3_0p6b_pycodeagent \
bash examples/pycodeagent_offline/run_qwen3_0p6b_offline.sh
```

## Notes

- The vendored offline bridge no longer rewrites `sys.path` at import time.
  `pycodeagent` must be importable via `PYTHONPATH` or an installed package.
  The provided run scripts already do this by exporting
  `PYTHONPATH="${CODEX_REPO}:${SLIME_DIR}:${MEGATRON_DIR}"`.
- These scripts are smoke-oriented starting points, not tuned production configs.
- The offline SFT path assumes `n_samples_per_prompt=1`.
- The native-transformed RL path supports `n_samples_per_prompt>=1`, but the
  first smoke should keep it at `1`.
- `GLOBAL_BATCH_SIZE` and `ROLLOUT_BATCH_SIZE` are expected to be equal in the
  provided smoke scripts.
- The `torch_dist` conversion must be run in an environment with Megatron,
  mbridge, and CUDA available.
- Do not rely on in-repo `models/` storage for new setups; treat any such tree
  as a legacy local compatibility artifact.
