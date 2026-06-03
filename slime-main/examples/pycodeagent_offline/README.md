# PyCodeAgent Offline Training

This example runs `slime` in a minimal offline-SFT style using a prepared
bundle from:

- `prepare_slime_training_data.py`

Instead of reading prompt JSONL and generating responses online, it uses:

- `slime.rollout.pycodeagent_offline.PyCodeAgentPreparedDataSource`
- `slime.rollout.pycodeagent_offline.generate_rollout`

to feed pre-built `pycodeagent` rollouts directly into the training path.

## Expected Input

Point `--prompt-data` at a prepared bundle directory, for example:

```text
runs/training_prep/schema_failure_attribution_v1_mimo_v25pro/
```

That directory should contain at least:

- `rollouts.jsonl`
- `tokenizer_config.yaml`
- `train_config.json`

## Recommended First Smoke Model

For the first end-to-end smoke run, use:

- `Qwen3-0.6B`

Keep the Hugging Face checkpoint and derived `torch_dist` checkpoint in a
machine-local model directory outside the source tree. Suggested env vars:

- `PYCODEAGENT_MODEL_DIR`
- `PYCODEAGENT_HF_CACHE_DIR`
- standard `HF_HOME`

Before training, convert the HF checkpoint into Megatron `torch_dist` format:

```bash
cd /workspace/claude_slime/slime-main
bash examples/pycodeagent_offline/convert_qwen3_0p6b_to_torch_dist.sh
```

This should produce:

- `<model-root>/Qwen3-0.6B_torch_dist`

## Run

Inside the slime Docker container:

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
- This script is a smoke-oriented starting point, not a tuned production config.
- It assumes `n_samples_per_prompt=1`.
- It uses `--debug-train-only`, so SGLang rollout servers are not started.
- `GLOBAL_BATCH_SIZE` and `ROLLOUT_BATCH_SIZE` are expected to be equal.
- The `torch_dist` conversion must be run in an environment with Megatron, mbridge, and CUDA available.
- Do not rely on in-repo `models/` storage for new setups; treat any such tree
  as a legacy local compatibility artifact.
