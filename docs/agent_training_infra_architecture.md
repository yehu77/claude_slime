# Agent Training Infrastructure Architecture

> **Auxiliary architecture reference:** This document describes earlier
> Claude API/native-transformed routes, not the runtime-observed construction
> mainline. See [source route boundaries](./source_route_boundaries.md); RC-030
> owns migration of the registered auxiliary code.

本文档整理当前仓库已经建设好的 Agent 训练基础设施。它描述的是
`claude_slime` 目前能稳定表达的数据流、接口边界和验证状态，不把尚未完成的
远端训练实验说成已经闭环。

## 当前定位

这个项目的核心目标不是做一个完整 Coding Agent 产品，而是建设一套可复现的
训练数据基础设施：

- 捕获真实 Agent/Claude Code 调用时模型实际看到的 native tool schema。
- 将真实 trace 转成可审计、可验证的训练样本。
- 对 tool schema 做 surface-level transformation，验证模型能否跟随当前可见
  schema，而不是记忆固定工具名。
- 同时支持轻量 HF SFT smoke、slime offline SFT smoke 和 slime online RL
  smoke 三条下游训练入口。

当前基础设施已经覆盖数据构造、格式适配、reward 评估和 smoke 脚本；远端
Megatron/slime 真正完成 optimizer step 仍待依赖环境闭环。

## 总体数据流

```text
Claude Code / Agent run
  -> claude_gateway_proxy session JSONL
  -> native tool catalog + assistant tool_use
  -> native-transformed SFT train.jsonl
  -> validation_report.json
  -> prepared/tokenized SFT artifacts
       -> HF local SFT smoke
       -> slime offline SFT smoke

native-transformed SFT train.jsonl
  -> RL prompt exporter
  -> rl_prompts.jsonl
  -> slime online rollout with SGLang
  -> pycodeagent reward_func
  -> slime/Megatron RL train step
```

SFT 和 RL 的关键差异：

- SFT 消费已经序列化并 tokenized 的监督答案，loss mask 指定哪些 token 参与
  训练。
- RL 消费 prompt-only 样本；模型在线生成 completion 后，再由 reward function
  根据 reference tool call 打分。

## 主要模块边界

### Trace 与 native-transformed SFT

相关文档：

- [native_transformed_sft_pipeline.md](./auxiliary/native_transformed_sft_pipeline.md)
- [claude_gateway_proxy.md](./auxiliary/claude_gateway_proxy.md)

主要职责：

- `claude_gateway_proxy.py` 捕获 Claude API request/response JSONL。
- `export_native_transformed_sft_dataset.py` 从真实 request-side tools 和
  assistant `tool_use` 构造 native-transformed SFT dataset。
- `validate_native_transformed_sft_dataset.py` 验证 transformed schema 与
  tool-use target 对齐。
- `prepare_native_transformed_sft_training_data.py` 复用现有 serializer、
  tokenizer、loss-mask 逻辑生成训练输入。

当前已验证：

- Claude Code trace 到 native-transformed SFT raw dataset 的导出路径已打通。
- native-transformed SFT validation 已覆盖基本结构和 tool name 对齐。
- HF Qwen smoke 使用 trimmed tokenized 数据已验证为轻量 SFT 路径。

### slime offline SFT bridge

相关入口：

- `pycodeagent.rl.slime_bridge`
- `slime-main/slime/rollout/pycodeagent_offline.py`
- `slime-main/examples/pycodeagent_offline/run_qwen3_0p6b_native_transformed_smoke.sh`

主要职责：

- 将 `TokenizedExample(input_ids, token_train_mask, metadata)` 适配成 slime
  offline `Sample`。
- 对 tokenized native-transformed SFT 输入直接使用已有 token ids 和 mask，不
  重新 tokenizer 编码。
- 保留旧的 `rollouts.jsonl` prepared bundle 路径，兼容早期 offline rollout
  数据。

当前已验证：

- 本地单元测试覆盖 tokenized SFT sample 到 slime train sample 的适配。
- offline datasource 同时支持旧 `rollouts.jsonl` 和新
  `tokenized.jsonl`/`smoke_tokenized.jsonl` 输入。
- 远端 slime/Megatron offline SFT optimizer step 尚未完成，当前阻塞是
  `Qwen3-0.6B_torch_dist` 和 Megatron/Transformer Engine 环境。

### native-transformed RL data 与 reward

相关文档：

- [native_transformed_rl_pipeline.md](./auxiliary/native_transformed_rl_pipeline.md)

主要职责：

- `export_native_transformed_rl_dataset.py` 从 native-transformed SFT dataset
  生成 prompt-only `rl_prompts.jsonl`。
- `pycodeagent.auxiliary.native_transformed.rl_dataset` 定义 RL prompt sample 和 reward
  reference 数据结构。
- `pycodeagent.auxiliary.native_transformed.reward` 解析模型 completion 中的
  `<|tool|> ... <|end|>` JSON block，并根据 expected tool call 打分。
- `slime-main/slime/rollout/pycodeagent_native_rl.py` 提供 slime datasource 和
  `reward_func`，把 prompt 数据接入 slime online RL。

当前已验证：

- 本地已生成 full RL prompt dataset 和 tiny smoke dataset。
- 本地测试覆盖 RL prompt datasource、reward reference 转换和 reward_func。
- 远端在线 RL smoke 脚本已准备好，但尚未完成真实 Ray/SGLang/Megatron 训练
  step。

## 产物清单

常见数据产物：

```text
runs/claude_gateway_traces/<session_id>.jsonl
outputs/native_transformed_sft/<run>/train.jsonl
outputs/native_transformed_sft/<run>/validation_report.json
outputs/native_transformed_sft/<run>/train/tokenized.jsonl
outputs/native_transformed_sft/<run>/train/smoke_tokenized.jsonl
outputs/native_transformed_rl/<run>/train/rl_prompts.jsonl
```

当前 smoke 重点产物：

```text
outputs/native_transformed_sft/qwen_smoke_run_trim/train/smoke_tokenized.jsonl
outputs/native_transformed_rl/qwen_smoke_tiny/train/rl_prompts.jsonl
```

远端训练依赖产物：

```text
Qwen3-0.6B
Qwen3-0.6B_torch_dist
Megatron-LM
transformer_engine
```

## 当前状态

可以认为已经完成：

- 真实 Claude trace 到 native-transformed SFT dataset 的基础链路。
- native-transformed SFT 到 HF smoke 的轻量验证链路。
- tokenized SFT sample 到 slime offline SFT sample 的适配层。
- native-transformed SFT 到 RL prompt dataset 的导出层。
- tool-call reward evaluator 和 slime online RL datasource。
- offline SFT smoke 和 online RL smoke 的启动脚本。

还不能宣称已经完成：

- 远端 A800 环境里 slime offline SFT optimizer step 已跑通。
- 远端 A800 环境里 slime online RL optimizer step 已跑通。
- reward function 已经能代表真实 coding task 成败。
- 训练后模型能力提升已经被评估。

下一步基础设施验证应聚焦在：

1. 在远端环境安装正确的 Megatron/Transformer Engine 依赖。
2. 将 Qwen3-0.6B HF 权重转换为 Megatron `torch_dist`。
3. 跑一次 native-transformed offline SFT smoke，确认至少 1 个 optimizer step。
4. 跑一次 native-transformed online RL smoke，确认 rollout、reward、train step
   三段都能连起来。
