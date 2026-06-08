# Native Transformed RL Pipeline

本文档说明 native-transformed 数据如何进入在线 RL 训练链路。这里的 RL 指
slime 在线 rollout + 自定义 reward function + Megatron 训练 step 的基础设施
路径，不代表已经完成真实 coding task 级别的强化学习闭环。

## 目标

SFT 路径已经能把 native-transformed tool-use 样本变成 tokenized 监督数据。
RL 路径要验证另一件事：

```text
同一批 native-transformed 样本
  -> 去掉监督答案，只保留 prompt 和 reward reference
  -> 让模型在线生成 tool call
  -> 用 pycodeagent reward function 打分
  -> 交给 slime 做 RL 训练 step
```

第一版只验证基础设施：

- prompt 数据能被 slime datasource 加载。
- SGLang rollout 能拿到 prompt 并生成 completion。
- `reward_func` 能把 completion 转成标量 reward。
- slime/Megatron 能消费 reward 并完成训练 step。

第一版不验证：

- reward 是否足够表达真实 coding task 成败。
- RL 训练是否带来模型能力提升。
- 多轮 tool execution 或真实工具调用结果。

## 数据格式

RL prompt 数据由 `export_native_transformed_rl_dataset.py` 从
native-transformed SFT dataset 导出：

```powershell
python export_native_transformed_rl_dataset.py ^
  outputs/native_transformed_sft/qwen_smoke_dataset ^
  outputs/native_transformed_rl/qwen_smoke_dataset
```

输出目录：

```text
outputs/native_transformed_rl/<run>/
  dataset_manifest.json
  split_metrics.json
  train/
    rl_prompts.jsonl
```

`rl_prompts.jsonl` 是 prompt-only 数据。每行主要包含：

- `messages`: 发送给模型的 system/user prompt。
- `tools`: 当前样本可见的 transformed native tool schema。
- `reward_reference`: 期望模型生成的 tool call。
- `metadata`: 原始 request、transformation mode、tool profile、source sample 等审计信息。

它和 SFT `tokenized.jsonl` 的区别：

- `tokenized.jsonl` 已经包含监督答案 token 和 loss mask。
- `rl_prompts.jsonl` 不包含 trainable answer token，只提供在线 rollout 的输入和
  reward 参考答案。

## Reward 语义

当前 reward evaluator 在 `pycodeagent.rl.native_transformed_reward` 中实现。

模型 completion 期望包含一个工具调用块：

```text
<|tool|>{"name":"tool_name","arguments":{...}}<|end|>
```

v1 reward 主要评分：

- 是否能解析出 tool block。
- JSON 是否合法。
- tool name 是否匹配 expected tool call。
- arguments 是否匹配 expected arguments。
- arguments 是否符合目标 schema 的基本结构。

这个 reward 是 infrastructure smoke 级别的 rule-based reward。它适合验证
slime 的 online RL 接入，不应被解释为完整任务级 reward model。

## slime 在线 RL 接入

slime 侧入口：

- datasource: `slime.rollout.pycodeagent_native_rl.PyCodeAgentNativeRLDataSource`
- rollout: `slime.rollout.sglang_rollout.generate_rollout`
- reward: `slime.rollout.pycodeagent_native_rl.reward_func`
- smoke script:
  `slime-main/examples/pycodeagent_offline/run_qwen3_0p6b_native_transformed_rl_smoke.sh`

推荐 smoke 输入：

```text
outputs/native_transformed_rl/qwen_smoke_tiny/train/rl_prompts.jsonl
```

tiny 数据集只保留少量短 prompt，目的是降低首次远端验证成本。full 数据集保留
完整 tool specs，prompt 会明显更长，更适合在 smoke 通过后再使用。

## 运行方式

在远端 slime 环境中，先确认依赖路径存在：

```bash
ls -ld /home/kas/claude_slime/Qwen3-0.6B
ls -ld /home/kas/claude_slime/Qwen3-0.6B_torch_dist
ls -ld /home/kas/claude_slime/outputs/native_transformed_rl/qwen_smoke_tiny
ls -ld /home/kas/claude_slime/Megatron-LM
```

如果 `Qwen3-0.6B_torch_dist` 不存在，需要先完成 HF -> Megatron torch_dist
转换。转换脚本依赖 Megatron 和 `transformer_engine`：

```bash
cd /home/kas/claude_slime/slime-main

CODEX_REPO=/home/kas/claude_slime \
MEGATRON_DIR=/home/kas/claude_slime/Megatron-LM \
MODEL_HF_DIR=/home/kas/claude_slime/Qwen3-0.6B \
MODEL_TORCH_DIST_DIR=/home/kas/claude_slime/Qwen3-0.6B_torch_dist \
bash examples/pycodeagent_offline/convert_qwen3_0p6b_to_torch_dist.sh
```

启动 online RL smoke：

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

## 成功标准

一次合格的 online RL smoke 应该证明：

- Ray job 正常提交并退出。
- datasource 成功加载 `rl_prompts.jsonl`。
- SGLang rollout server 成功启动并生成 completion。
- `reward_func` 被调用并返回 reward。
- Megatron actor 至少完成 1 个训练 step。
- `TRAIN_OUTPUT_DIR` 中出现日志、metrics 或 checkpoint。
- 没有 OOM、路径缺失、依赖缺失或 import error。

如果只完成了 datasource/reward 的本地测试，不能说 online RL 训练已经跑通。

## 常见阻塞

- `MEGATRON_DIR` 默认是 `/root/Megatron-LM`，远端如果放在
  `/home/kas/claude_slime/Megatron-LM` 需要显式覆盖。
- `MODEL_TORCH_DIST_DIR` 不存在时，必须先跑转换脚本。
- `transformer-engine` 安装成 `0.0.0` placeholder 不等于可用的
  `transformer_engine` PyTorch 扩展。
- full `rl_prompts.jsonl` prompt 可能很长，首次 smoke 应使用
  `qwen_smoke_tiny`。
- `GLOBAL_BATCH_SIZE` 和 `ROLLOUT_BATCH_SIZE` 在 smoke 脚本中应保持相等。

## 当前状态

已完成：

- RL prompt exporter。
- RL prompt sample / reward reference schema。
- rule-based tool-call reward evaluator。
- slime native RL datasource。
- slime `reward_func` bridge。
- tiny/full RL prompt 数据产物。
- online RL smoke 启动脚本。
- 本地 datasource/reward 单元测试。

未完成：

- 远端 `Qwen3-0.6B_torch_dist` 权重转换验证。
- 远端 Ray/SGLang/Megatron online RL smoke 真实训练 step。
- 任务级 reward、真实工具执行、多轮交互和训练收益评估。
