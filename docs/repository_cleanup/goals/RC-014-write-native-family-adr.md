---
schema: repository-cleanup-goal/v1
id: RC-014
title: 提炼 native-family ADR
status: done
batch: A
action: merge
priority: P1
risk: medium
size: M
depends_on: [RC-013]
source_audit: docs/repository_asset_audit.md
source_sections: ["7.1 KEEP", "7.2 KEEP，但必须重写", "3. 当前唯一主线"]
created: 2026-07-14
updated: 2026-07-16
completed: 2026-07-16
---

# RC-014：提炼 native-family ADR

## 目标

用一份短 ADR 固化 native-family 的术语、family 选择、fallback、artifact 和 acceptance 边界。

## 范围

- 包含：现行设计决策、被替代文档清单和不可破坏合同。
- 保护：不把阶段性实施日志搬进 ADR，也不改变 `CanonicalTool -> ToolView -> ToolAdapter`。

## 工作项与验收

- [x] 从活动文档和代码提取已实现事实，区分现状与未来计划。
- [x] 记录 family-neutral task contract、显式选择和禁止静默 fallback 的原则。
- [x] 所有相关 runbook/plan 链接到 ADR，而非各自重新定义术语。
- [x] 文档链接检查和 `git diff --check` 通过。

## 结果

[ADR-0001](../../adr/0001-native-family-runtime-boundary.md) 现在是
native-family 术语、显式 stack 选择、禁止静默 family/contract fallback、artifact
provenance 和 acceptance 层级的唯一决策记录。它以当前代码为事实源，同时明确旧
task metadata 中的 tool-name hints 是 RC-021/RC-022 的迁移债务，不能反向决定
`tool_stack_kind`。

docs 首页和根 README 已把 ADR 放入当前阅读顺序。codex-rs construction driver、
industrial gap framework、native acceptance、real-provider runbook，以及 family
split、legacy demotion、Step A-F 和 ToolView mutation 历史计划均链接 ADR；历史文档
只保留实施证据，不再定义当前 family 规则。taxonomy 中的替代关系也已指向 ADR，
为 RC-015/RC-016 的物理归档提供映射。

验收：ADR/taxonomy 与 family-selection/provider 定向测试 `34 passed`；mainline
`20 passed, 3 deselected`；全量分片合计 `930 passed, 77 skipped`；taxonomy
`documents=88, inventory_entries=33, local_links=164`；`git diff --check` 通过。
N/A — 文档决策未改变 runtime，实现事实由定向和 mainline tests 验证。

## 决策记录

- 2026-07-14：将 ADR 设为旧 runtime 文档归档前置条件。
- 2026-07-16：provider transport 与 tool family 作为不同维度；transport 不支持
  freeform contract 时必须显式拒绝或标注限制，不能跨 family 或改写 contract。
- 2026-07-16：task contract 以行为和 workspace 约束为核心；family 由 runtime
  invocation 显式选择，遗留工具名 metadata 的治理留给 RC-021/RC-022。
