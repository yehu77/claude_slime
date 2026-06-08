#!/bin/bash

set -euo pipefail

# Native-transformed online RL smoke for Qwen3-0.6B.
#
# This consumes prompt-only rl_prompts.jsonl, uses slime's default SGLang
# rollout path for generation, and scores completions through pycodeagent's
# native-transformed tool-call reward function.

CODEX_REPO="${CODEX_REPO:-/home/kas/claude_slime}"
SLIME_DIR="${SLIME_DIR:-${CODEX_REPO}/slime-main}"
MEGATRON_DIR="${MEGATRON_DIR:-/root/Megatron-LM}"

MODEL_HF_DIR="${MODEL_HF_DIR:-${CODEX_REPO}/Qwen3-0.6B}"
MODEL_TORCH_DIST_DIR="${MODEL_TORCH_DIST_DIR:-${CODEX_REPO}/Qwen3-0.6B_torch_dist}"
RL_PROMPT_DATA_DIR="${RL_PROMPT_DATA_DIR:-${CODEX_REPO}/outputs/native_transformed_rl/qwen_smoke_tiny}"
TRAIN_OUTPUT_DIR="${TRAIN_OUTPUT_DIR:-${CODEX_REPO}/runs/slime_native_transformed_qwen3_0p6b_rl_smoke}"

NUM_GPUS="${NUM_GPUS:-1}"
ROLLOUT_NUM_GPUS="${ROLLOUT_NUM_GPUS:-${NUM_GPUS}}"
ROLLOUT_NUM_GPUS_PER_ENGINE="${ROLLOUT_NUM_GPUS_PER_ENGINE:-1}"
ROLLOUT_BATCH_SIZE="${ROLLOUT_BATCH_SIZE:-1}"
GLOBAL_BATCH_SIZE="${GLOBAL_BATCH_SIZE:-1}"
N_SAMPLES_PER_PROMPT="${N_SAMPLES_PER_PROMPT:-1}"
NUM_ROLLOUT="${NUM_ROLLOUT:-1}"
SAVE_INTERVAL="${SAVE_INTERVAL:-1}"
MAX_TOKENS_PER_GPU="${MAX_TOKENS_PER_GPU:-4096}"
ROLLOUT_MAX_PROMPT_LEN="${ROLLOUT_MAX_PROMPT_LEN:-3072}"
ROLLOUT_MAX_RESPONSE_LEN="${ROLLOUT_MAX_RESPONSE_LEN:-256}"
ROLLOUT_TEMPERATURE="${ROLLOUT_TEMPERATURE:-0.7}"
ROLLOUT_TOP_P="${ROLLOUT_TOP_P:-0.95}"
LR="${LR:-1e-6}"
KL_COEF="${KL_COEF:-0.0}"

for path_var in CODEX_REPO SLIME_DIR MEGATRON_DIR MODEL_HF_DIR RL_PROMPT_DATA_DIR; do
  path_value="${!path_var}"
  if [ ! -e "${path_value}" ]; then
    echo "Missing required path: ${path_var}=${path_value}" >&2
    exit 1
  fi
done

if [ ! -e "${MODEL_TORCH_DIST_DIR}" ]; then
  echo "Missing required path: MODEL_TORCH_DIST_DIR=${MODEL_TORCH_DIST_DIR}" >&2
  echo "Run examples/pycodeagent_offline/convert_qwen3_0p6b_to_torch_dist.sh first." >&2
  exit 1
fi

if [ ! -e "${RL_PROMPT_DATA_DIR}/train/rl_prompts.jsonl" ] && [ ! -e "${RL_PROMPT_DATA_DIR}/rl_prompts.jsonl" ]; then
  echo "Missing rl_prompts.jsonl under RL_PROMPT_DATA_DIR=${RL_PROMPT_DATA_DIR}" >&2
  echo "Run export_native_transformed_rl_dataset.py first." >&2
  exit 1
fi

if [ "${GLOBAL_BATCH_SIZE}" -ne "${ROLLOUT_BATCH_SIZE}" ]; then
  echo "This smoke script expects GLOBAL_BATCH_SIZE == ROLLOUT_BATCH_SIZE" >&2
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

ROLLOUT_ARGS=(
  --data-source-path slime.rollout.pycodeagent_native_rl.PyCodeAgentNativeRLDataSource
  --rollout-function-path slime.rollout.sglang_rollout.generate_rollout
  --custom-rm-path slime.rollout.pycodeagent_native_rl.reward_func
  --prompt-data "${RL_PROMPT_DATA_DIR}"
  --n-samples-per-prompt "${N_SAMPLES_PER_PROMPT}"
  --rollout-shuffle
  --num-rollout "${NUM_ROLLOUT}"
  --rollout-batch-size "${ROLLOUT_BATCH_SIZE}"
  --num-steps-per-rollout 1
  --global-batch-size "${GLOBAL_BATCH_SIZE}"
  --rollout-max-prompt-len "${ROLLOUT_MAX_PROMPT_LEN}"
  --rollout-max-response-len "${ROLLOUT_MAX_RESPONSE_LEN}"
  --rollout-temperature "${ROLLOUT_TEMPERATURE}"
  --rollout-top-p "${ROLLOUT_TOP_P}"
  --rollout-stop "<|end|>"
)

GRPO_ARGS=(
  --advantage-estimator grpo
  --kl-loss-type low_var_kl
  --kl-coef "${KL_COEF}"
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

SGLANG_ARGS=(
  --rollout-num-gpus "${ROLLOUT_NUM_GPUS}"
  --rollout-num-gpus-per-engine "${ROLLOUT_NUM_GPUS_PER_ENGINE}"
  --sglang-mem-fraction-static 0.45
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
  --colocate \
  "${MODEL_ARGS[@]}" \
  "${CKPT_ARGS[@]}" \
  "${ROLLOUT_ARGS[@]}" \
  "${GRPO_ARGS[@]}" \
  "${OPTIMIZER_ARGS[@]}" \
  "${PERF_ARGS[@]}" \
  "${SGLANG_ARGS[@]}" \
  "${MISC_ARGS[@]}"
