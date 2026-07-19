---
schema: repository-cleanup-goal/v1
id: RC-003
title: 删除旧 runtime task-pack fixtures
status: done
batch: A
action: delete
priority: P1
risk: low
size: S
depends_on: [RC-001]
source_audit: docs/repository_asset_audit.md
source_sections: ["8.3 ARCHIVE/DELETE?", "9.4 TASK PACKS", "15. 第一批高置信候选"]
created: 2026-07-14
updated: 2026-07-14
completed: 2026-07-14
---

# RC-003：删除旧 runtime task-pack fixtures

## 目标

移除已被真实 task dataset 取代、且无下游读取方的两份 smoke-case fixture。

## 范围

- 包含：`tests/fixtures/{deterministic,realistic}_runtime_task_pack/smoke_cases.json`。
- 保护：`datasets/tasks/` 中的活动任务定义及其 `examples/` workspace。

## 工作项与验收

- [x] 逐项核对下游引用，确认 fixture 文件无活动消费者。
- [x] 两份 fixture 已删除。
- [x] mainline、local acceptance 与全量测试均通过。
- [x] `git diff --check` 通过。

## 结果

测试 fixture 不再重复保存 task-pack 真源。

## 决策记录

- 2026-07-14：完成关联资产审计后删除，标记完成。
