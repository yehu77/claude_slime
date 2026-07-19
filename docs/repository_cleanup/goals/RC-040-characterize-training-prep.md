---
schema: repository-cleanup-goal/v1
id: RC-040
title: 建立 training-prep 行为矩阵与 golden
status: done
batch: D
action: guardrail
priority: P0
risk: medium
size: L
depends_on: [RC-001]
source_audit: docs/repository_asset_audit.md
source_sections: ["5.4 Training prep 四套重复编排", "4.3 训练数据合同内核"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-040：建立 training-prep 行为矩阵与 golden

## 目标

在统一四条 training-prep 路径前，完整刻画它们对同一输入的字段、序列化、mask、packing 和失败行为。

## 范围

- 包含：runtime-observed、multi-agent/transformed、native-transformed 与现有 rollout/prep 入口的对照 corpus。
- 保护：serialized text、segment/char/token masks、reward/status/verifier/task/profile/split 元数据不得静默变化。

## 工作项与验收

- [x] 建立路径×输入类型×输出字段×失败条件的行为矩阵。
- [x] 生成小型 deterministic goldens，包含 transformed ToolView 和失败样本。
- [x] 明确哪些差异是合同、兼容包袱或 bug。
- [x] 四路径 characterization tests、mainline、全量测试与 `git diff --check` 通过。

## 结果

已冻结 [`training_prep_behavior_contract.md`](../../training_prep_behavior_contract.md)
和机器可执行
[`training_prep_characterization.json`](../training_prep_characterization.json)。
同一语义 corpus 通过四种 source envelope 覆盖 transformed `inspect_file → Read`
ToolView、一个失败 run 和一个 corrected hard-negative。

| Path | 当前训练 mask | outcome/provenance | contract + packing | 分类 |
| --- | --- | --- | --- | --- |
| rollout | assistant text + tool call | 保留 reward/status/verifier/task/profile | 有 | compatibility debt |
| schema-following | tool call only | 保留 task/profile/split/source/mutation；源格式没有 run outcome | 有 | target contract |
| runtime-observed | tool call only | 额外保留 observed family/profile/provenance | nested prepared report 有 | source-adapter contract |
| native-transformed | selected assistant text + tool use | 保留 auxiliary trace/transformation identity；没有 run outcome | 只有 raw validation，无 shared prepared report/packing | auxiliary compatibility gap |

Golden tests 同时冻结 serialized text/segments/character mask、token/label mask 对齐、
配置 round-trip、输出文件布局和四类失败边界。测试明确证明 packing 当前只在
contract verifier 中内存验证，不物化 packed JSONL。

本次还修复 RC-056 后遗留的 recommendation 文案：`tokenized.jsonl` 现在描述为
downstream training consumer 输入，不再指向已删除的“current training loop”。
没有在本目标合并 recommendation 类型、mask policy 或 bundle builder。

验收结果：四路径 golden `6 passed`；training-prep 扩展定向
`56 passed`；mainline `88 passed, 3 deselected`；local-only native-family
acceptance `stabilized=True`；全量 `983 passed, 77 skipped`；
`git diff --check` 通过。

## 决策记录

- 2026-07-14：先测清差异再合并，防止统一入口静默丢训练字段。
- 2026-07-17：把 schema-following/runtime-observed 的
  `assistant_tool_call_only` 视为目标合同；rollout 宽 assistant mask 必须作为
  显式兼容策略迁移，不能在 RC-041/042 中静默改变。
- 2026-07-17：native-transformed 保持 auxiliary source adapter 身份；其 shared
  prepared-contract/packing 缺口交由后续统一 builder 显式处理。
- 2026-07-17：RC-041 以 PreparedSample v1 显式迁移 rollout/native 的宽 mask；
  本文表格保留 RC-040 完成时的历史基线，当前可执行矩阵升级为 v2。
- 2026-07-17：RC-042 将当前可执行矩阵升级为 v3；四路径统一生成 checksummed
  bundle，并新增 materialized `packed.jsonl`，本文结果表仍保留 RC-040 原始快照。
