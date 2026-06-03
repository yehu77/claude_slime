#!/bin/bash

set -euo pipefail

# Convert Qwen3-0.6B HF weights into Megatron torch_dist format for slime.
#
# Run this inside the slime Docker container after mounting the whole repo.

CODEX_REPO="${CODEX_REPO:-/workspace/claude_slime}"
SLIME_DIR="${SLIME_DIR:-${CODEX_REPO}/slime-main}"
MEGATRON_DIR="${MEGATRON_DIR:-/root/Megatron-LM}"

MODEL_HF_DIR="${MODEL_HF_DIR:-${CODEX_REPO}/models/Qwen3-0.6B}"
MODEL_TORCH_DIST_DIR="${MODEL_TORCH_DIST_DIR:-${CODEX_REPO}/models/Qwen3-0.6B_torch_dist}"

for path_var in CODEX_REPO SLIME_DIR MEGATRON_DIR MODEL_HF_DIR; do
  path_value="${!path_var}"
  if [ ! -e "${path_value}" ]; then
    echo "Missing required path: ${path_var}=${path_value}" >&2
    exit 1
  fi
done

cd "${SLIME_DIR}"
source "${SLIME_DIR}/scripts/models/qwen3-0.6B.sh"

export PYTHONPATH="${SLIME_DIR}:${MEGATRON_DIR}:${PYTHONPATH:-}"

torchrun --nproc_per_node=1 tools/convert_hf_to_torch_dist.py \
  "${MODEL_ARGS[@]}" \
  --hf-checkpoint "${MODEL_HF_DIR}" \
  --save "${MODEL_TORCH_DIST_DIR}"
