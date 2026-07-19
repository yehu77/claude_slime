---
schema: repository-cleanup-goal/v1
id: RC-041
title: 定义唯一 PreparedSample 合同
status: done
batch: D
action: merge
priority: P0
risk: high
size: M
depends_on: [RC-040]
source_audit: docs/repository_asset_audit.md
source_sections: ["5.4 Training prep 四套重复编排", "4.3 训练数据合同内核"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-041：定义唯一 PreparedSample 合同

## 目标

定义各 trace source 进入 tokenization/packing 前必须满足的唯一 versioned `PreparedSample` 合同。

## 范围

- 包含：必需字段、可选 source metadata、schema version、validation 和 loss-mask policy。
- 保护：训练目标固定为 assistant tool-call tokens only；source-specific 证据不能被便利转换吞掉。

## 工作项与验收

- [x] 从 RC-040 行为矩阵提炼最小无损字段集合。
- [x] 明确 raw/canonical/transformed schema 和 prepared sample 的转换边界。
- [x] 增加字段缺失、mask 不对齐、未知版本的 loud-failure 测试。
- [x] golden round-trip、serializer/mask、mainline 和 `git diff --check` 通过。

## 结果

新增唯一的 `pycodeagent.rl.prepared_sample.PreparedSample` v1。原
`TrainingSample`、`SchemaFollowingPreparedSample` 和
`ClaudeApiSFTPreparedSample` 名称保留为同一 class 的兼容别名，不再拥有三套
独立字段定义。统一模型冻结 sample/source/split/task/profile identity、序列化
segments、character mask/spans、可选 mutation、source metadata 和全有或全无的
run outcome 组；额外顶层字段、部分 outcome、未知 version 和结构不一致都会在
构造或 JSONL 加载时直接失败。

所有 source-specific prepared JSONL helper 已委托同一个 deterministic
writer/validated reader，所有 prepared tensorization 已汇入
`tensorize_prepared_sample`。auxiliary source 仍保留原始 loss-mask policy 和
transformation provenance，但不会伪造不存在的 reward/status/verifier。

PreparedSample v1 唯一允许的训练目标为 `assistant_tool_call_only`。rollout 与
native-transformed 的 RC-040 宽 mask 已作为显式版本迁移收敛到该策略，RC-040
历史表格保留旧行为证据，可执行 characterization 升级为 v2。详细边界和 loud
validation 见
[`prepared_sample_contract.md`](../../prepared_sample_contract.md)。

新增 7 个 RC-041 mainline 测试，覆盖唯一类型、source evidence round-trip、
字段缺失、未知 version、mask 错位、非 tool-call 训练段和带行号的 JSONL
失败。验收结果：training-prep/serializer/contract 扩展定向
`192 passed, 2 skipped`；mainline `95 passed, 3 deselected`；local-only
native-family acceptance `stabilized=True`；全量 `990 passed, 77 skipped`；
`git diff --check` 通过。

## 决策记录

- 2026-07-14：合同先于 builder 实现，禁止以某条现有路径偶然结构作默认真源。
- 2026-07-17：PreparedSample v1 只训练 model-visible assistant tool call；
  natural-language assistant text 是上下文。
- 2026-07-17：run outcome 使用全有或全无的可选字段组，不为缺少这些证据的
  schema/native source 填充假值。
- 2026-07-17：RC-041 只统一 sample/tensorization 边界；recommendation、
  output layout、contract report 和 bundle packing 编排留给 RC-042。
- 2026-07-17：RC-042 已完成上述 bundle 编排，并保持本目标的 PreparedSample v1
  与 `assistant_tool_call_only` 语义不变。
