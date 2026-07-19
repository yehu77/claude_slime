---
schema: repository-cleanup-goal/v1
id: RC-033
title: 冻结 compaction 行为与 model-backed 决策
status: done
batch: C
action: decide
priority: P1
risk: medium
size: M
depends_on: [RC-001]
source_audit: docs/repository_asset_audit.md
source_sections: ["5.1 `turn_state.py` 中重复的 compaction 实现", "13.2 定向 slow 测试"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-033：冻结 compaction 行为与 model-backed 决策

## 目标

在删除重复实现前，冻结 compaction 的输入、事件、摘要、恢复和失败降级合同。

## 范围

- 包含：当前两套实现的行为矩阵、`ModelBackedCompactionResult` 去留和 canonical owner 决策。
- 保护：append-only raw trace、post-error continuation 和可审计摘要证据。

## 工作项与验收

- [x] 对同一 corpus 跑两套实现并记录等价/差异行为。
- [x] 决定 canonical implementation 与 model-backed result 类型的必要性。
- [x] 将接受的行为写成 golden/contract tests，包括失败和 budget 边界。
- [x] compaction 定向测试、mainline 与 `git diff --check` 通过。

## 结果

已冻结 [`docs/compaction_contract.md`](../../compaction_contract.md) v1：

- `pycodeagent.agent.compaction` 是唯一 canonical owner；
  `turn_state.select_request_messages` 只保留兼容委托边界。
- full-history、tail-window 和 deterministic-compaction 在相同 corpus、消息
  预算、token 预算及有/无 session state 下与旧私有实现完全等价；旧私有实现
  仅作为 RC-034 的待删除债务，不再拥有行为。
- 删除零消费者且与 `ContextSelectionPlan` 重复的
  `ModelBackedCompactionResult`；保留 `ModelBackedCompactionOutput` 作为结构化
  模型输出、`ContextSelectionPlan` 作为统一运行结果。
- 将 `inline_model`、`deterministic_compaction` 和五类失败原因冻结为显式常量；
  未登记的 backend、fallback policy 或 failure kind 会立即失败。
- 合同测试覆盖成功替换、跨度一致性、全部失败降级、预算边界、append-only
  事件顺序和失败后继续执行，并已加入离线 mainline CI。

验收结果：compaction 定向套件 `54 passed`；mainline `75 passed,
3 deselected`；local-only native-family acceptance `stabilized=True`；全量
`999 passed, 77 skipped`；`git diff --check` 通过。

## 决策记录

- 2026-07-14：把合同冻结和代码删除拆开，避免用测试当前偶然行为替代设计决策。
- 2026-07-17：选择 `pycodeagent.agent.compaction` 为 canonical owner；RC-034
  只能删除 `turn_state.py` 的私有副本，不得同时改变合同。
- 2026-07-17：`ModelBackedCompactionResult` 无引用且信息被现有输入/输出合同
  完整覆盖，因此直接删除，不把无消费者类型冻结成长期 API。
