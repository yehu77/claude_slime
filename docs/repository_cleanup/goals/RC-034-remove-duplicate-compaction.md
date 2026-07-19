---
schema: repository-cleanup-goal/v1
id: RC-034
title: 删除 turn_state 重复 compaction
status: done
batch: C
action: delete
priority: P1
risk: high
size: L
depends_on: [RC-033]
source_audit: docs/repository_asset_audit.md
source_sections: ["5.1 `turn_state.py` 中重复的 compaction 实现", "14. 建议的安全清理顺序"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-034：删除 turn_state 重复 compaction

## 目标

将所有 runtime 调用迁到 RC-033 选定的唯一 compaction 实现并删除重复路径。

## 范围

- 包含：`turn_state.py` 重复逻辑、call sites、imports、结果类型和专属 tests。
- 保护：RC-033 冻结的事件序列、摘要内容、token budget 和恢复语义。

## 工作项与验收

- [x] 建立旧到新行为映射并逐调用方迁移。
- [x] 删除重复实现后 repository search 只剩 canonical owner。
- [x] contract/golden 覆盖同步、模型失败与 continuation。
- [x] compaction slow tests、mainline、local acceptance、全量测试和 `git diff --check` 通过。

## 结果

已删除 `pycodeagent.agent.turn_state` 中三个 selector 和其 compaction 专属
辅助函数副本。旧到新映射为：

| 旧 `turn_state.py` 私有路径 | 唯一保留路径 |
| --- | --- |
| `_select_full_history` | `compaction._select_full_history` |
| `_select_tail_window` | `compaction._select_tail_window` |
| `_select_deterministic_compaction` | `compaction._select_deterministic_compaction` |
| selection、turn-range、summary、budget 私有 helpers | `compaction.py` 同名实现 |

生产调用在 RC-033 前已使用 `compaction.plan_request_context`；本次保留
`turn_state.select_request_messages` 作为向 canonical owner 的兼容委托，以保护
现有调用方。状态/result models 与 provider-agnostic token estimator 继续由
`turn_state.py` 持有，不属于重复实现。

`tests/test_compaction_contract.py` 已从临时的新旧副本比较改为 canonical-owner
静态门禁，并继续覆盖委托、model-backed 成功、五类失败降级、跨度验证和失败后
continuation。本次从 `turn_state.py` 净删除 750 行重复代码。验收结果：compaction
定向套件 `47 passed`；mainline `77 passed, 3 deselected`；local-only
native-family acceptance `stabilized=True`；全量 `1001 passed, 77 skipped`；
`git diff --check` 通过。

## 决策记录

- 2026-07-14：高风险合并必须以行为合同而非代码相似度验收。
- 2026-07-17：保留 `turn_state.select_request_messages` 兼容入口，避免把内部去重
  扩大为无关公共 API 迁移；新增行为只能进入 `pycodeagent.agent.compaction`。
