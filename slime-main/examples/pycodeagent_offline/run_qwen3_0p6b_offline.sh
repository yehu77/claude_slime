#!/bin/bash

set -euo pipefail

# Minimal offline training smoke script for Qwen3-0.6B using pycodeagent
# prepared bundles.
#
# Run this inside the slime Docker container after:
# 1. Mounting the whole repository
# 2. Downloading / mounting models/Qwen3-0.6B
# 3. Converting it into models/Qwen3-0.6B_torch_dist

CODEX_REPO="${CODEX_REPO:-/workspace/claude_slime}"
SLIME_DIR="${SLIME_DIR:-${CODEX_REPO}/slime-main}"
MEGATRON_DIR="${MEGATRON_DIR:-/root/Megatron-LM}"

MODEL_HF_DIR="${MODEL_HF_DIR:-${CODEX_REPO}/models/Qwen3-0.6B}"
MODEL_TORCH_DIST_DIR="${MODEL_TORCH_DIST_DIR:-${CODEX_REPO}/models/Qwen3-0.6B_torch_dist}"
PREPARED_BUNDLE_DIR="${PREPARED_BUNDLE_DIR:-${CODEX_REPO}/runs/training_prep/schema_failure_attribution_v1_mimo_v25pro}"
TRAIN_OUTPUT_DIR="${TRAIN_OUTPUT_DIR:-${CODEX_REPO}/runs/slime_qwen3_0p6b_pycodeagent}"

NUM_GPUS="${NUM_GPUS:-1}"
ROLLOUT_BATCH_SIZE="${ROLLOUT_BATCH_SIZE:-8}"
GLOBAL_BATCH_SIZE="${GLOBAL_BATCH_SIZE:-8}"
NUM_ROLLOUT="${NUM_ROLLOUT:-50}"
SAVE_INTERVAL="${SAVE_INTERVAL:-20}"
MAX_TOKENS_PER_GPU="${MAX_TOKENS_PER_GPU:-2048}"
LR="${LR:-1e-6}"

for path_var in CODEX_REPO SLIME_DIR MEGATRON_DIR MODEL_HF_DIR MODEL_TORCH_DIST_DIR PREPARED_BUNDLE_DIR; do
  path_value="${!path_var}"
  if [ ! -e "${path_value}" ]; then
    echo "Missing required path: ${path_var}=${path_value}" >&2
    exit 1
  fi
done

if [ "${GLOBAL_BATCH_SIZE}" -ne "${ROLLOUT_BATCH_SIZE}" ]; then
  echo "This offline smoke script expects GLOBAL_BATCH_SIZE == ROLLOUT_BATCH_SIZE" >&2
  exit 1
fi

export PYTHONUNBUFFERED=1

cd "${SLIME_DIR}"
source "${SLIME_DIR}/scripts/models/qwen3-0.6B.sh"

CKPT_ARGS=(
  --hf-checkpoint "${MODEL_HF_DIR}"
  --ref-load "${MODEL_TORCH_DIST_DIR}"
  --load "${TRAIN_OUTPUT_DIR}"
  --save "${TRAIN_OUTPUT_DIR}"
  --save-interval "${SAVE_INTERVAL}"
)

OFFLINE_ARGS=(
  --data-source-path slime.rollout.pycodeagent_offline.PyCodeAgentPreparedDataSource
  --rollout-function-path slime.rollout.pycodeagent_offline.generate_rollout
  --prompt-data "${PREPARED_BUNDLE_DIR}"
  --n-samples-per-prompt 1
  --rollout-shuffle
  --num-rollout "${NUM_ROLLOUT}"
  --rollout-batch-size "${ROLLOUT_BATCH_SIZE}"
  --num-steps-per-rollout 1
  --global-batch-size "${GLOBAL_BATCH_SIZE}"
  --loss-type sft_loss
  --calculate-per-token-loss
  --disable-compute-advantages-and-returns
  --debug-train-only
)

PERF_ARGS=(
  --tensor-model-parallel-size 1
  --sequence-parallel
  --pipeline-model-parallel-size 1
  --context-parallel-size 1
  --expert-model-parallel-size 1
  --expert-tensor-parallel-size 1
  --recompute-granularity full
  --recompute-method uniform
  --recompute-num-layers 1
  --use-dynamic-batch-size
  --max-tokens-per-gpu "${MAX_TOKENS_PER_GPU}"
  --micro-batch-size 1
)

OPTIMIZER_ARGS=(
  --optimizer adam
  --lr "${LR}"
  --lr-decay-style constant
  --weight-decay 0.1
  --adam-beta1 0.9
  --adam-beta2 0.95
)

MISC_ARGS=(
  --attention-dropout 0.0
  --hidden-dropout 0.0
  --accumulate-allreduce-grads-in-fp32
  --attention-softmax-in-fp32
  --attention-backend flash
)

MASTER_ADDR="${MASTER_ADDR:-127.0.0.1}"
export no_proxy="127.0.0.1,${MASTER_ADDR}"

ray stop --force >/dev/null 2>&1 || true
ray start --head \
  --node-ip-address "${MASTER_ADDR}" \
  --num-gpus "${NUM_GPUS}" \
  --disable-usage-stats \
  --dashboard-host=0.0.0.0 \
  --dashboard-port=8265

RUNTIME_ENV_JSON="$(cat <<EOF
{
  "env_vars": {
    "PYTHONPATH": "${CODEX_REPO}:${SLIME_DIR}:${MEGATRON_DIR}",
    "CUDA_DEVICE_MAX_CONNECTIONS": "1",
    "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"
  }
}
EOF
)"

ray job submit --address="http://127.0.0.1:8265" \
  --runtime-env-json="${RUNTIME_ENV_JSON}" \
  -- python3 train_async.py \
  --actor-num-nodes 1 \
  --actor-num-gpus-per-node "${NUM_GPUS}" \
  "${MODEL_ARGS[@]}" \
  "${CKPT_ARGS[@]}" \
  "${OFFLINE_ARGS[@]}" \
  "${OPTIMIZER_ARGS[@]}" \
  "${PERF_ARGS[@]}" \
  "${MISC_ARGS[@]}"
