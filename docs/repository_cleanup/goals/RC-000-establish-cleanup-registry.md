---
schema: repository-cleanup-goal/v1
id: RC-000
title: 建立 cleanup goal registry
status: done
batch: foundation
action: guardrail
priority: P0
risk: low
size: M
depends_on: []
source_audit: docs/repository_asset_audit.md
source_sections: ["14. 建议的安全清理顺序", "17. 当前决策边界"]
created: 2026-07-14
updated: 2026-07-14
completed: 2026-07-14
---

# RC-000：建立 cleanup goal registry

## 目标

把一次性资产审计转换成有稳定 ID、依赖关系、状态真源和验收条件的目标台账。

## 范围

- 包含：本索引、目标模板和 `RC-000` 至 `RC-055` 的独立目标文档。
- 保护：`repository_asset_audit.md` 作为带日期的证据快照，不把它改成滚动任务清单。

## 工作项与验收

- [x] 定义状态、完成口径、依赖和批次进度。
- [x] 为 v1 范围内 56 个目标分配唯一且不复用的 ID。
- [x] 索引链接、frontmatter ID、状态计数和依赖均通过机器校验。
- [x] N/A — 本目标只改变文档，不触及运行时代码，无需代码回归。

## 结果

`docs/repository_cleanup/` 成为实时进度真源；总体进度只按 `done / active goals` 计算。

## 决策记录

- 2026-07-14：锁定 v1 为 56 个可独立验收的目标，标记完成。
