---
schema: repository-cleanup-goal/v1
id: RC-016
title: 归档 Tool Runtime 实施计划簇
status: done
batch: A
action: archive
priority: P1
risk: medium
size: M
depends_on: [RC-014]
source_audit: docs/repository_asset_audit.md
source_sections: ["7.3 ARCHIVE", "3. 当前唯一主线"]
created: 2026-07-14
updated: 2026-07-16
completed: 2026-07-16
---

# RC-016：归档 Tool Runtime 实施计划簇

## 目标

将已被 native-family ADR 和 codex-rs driver 覆盖的 Tool Runtime 计划簇转为历史证据。

## 范围

- 包含：旧 Tool Runtime spec/implementation/status 文档及重复导航链接。
- 保护：仍被代码或测试直接引用的合同说明，迁移后必须有稳定新链接。

## 工作项与验收

- [x] 建立旧计划到 ADR/current driver 的映射。
- [x] 归档时保留日期、状态与 superseded-by 元数据。
- [x] 活动 docs 中不存在相互冲突的 construction schedule。
- [x] 链接完整性和 `git diff --check` 通过；N/A — 纯文档治理不改运行行为。

## 结果

- 将 family split、legacy demotion、Steps A–F 和 ToolView mutation 共 10 份
  历史计划整体迁入
  [`docs/archive/2026-07-16-tool-runtime/`](../../archive/2026-07-16-tool-runtime/README.md)。
- 归档 manifest 逐项记录原路径、归档时状态、替代文档和保留理由；原簇内部链接
  与代码证据链接均随新目录修正。
- [`ADR-0001`](../../adr/0001-native-family-runtime-boundary.md) 现在是
  native-family 术语与选择边界入口；当前建设顺序和验收分别由 codex-rs driver
  与 native-family acceptance 文档承接。
- 活动 `docs/` 根目录不再存在这组阶段性 construction schedule；文档分类门禁
  同时验证旧路径消失、归档文件齐全及 manifest 覆盖。
- 验收：文档门禁 `6 passed`；mainline 门禁与全量测试通过；
  `pycodeagent.dev.docs_taxonomy` 和 `git diff --check` 通过。
- N/A：本目标只移动和重分类历史文档，不修改 runtime、ToolView 或数据合同，
  因此不重复执行 native-family local acceptance。

## 决策记录

- 2026-07-14：作为 docs 去重独立目标，避免和代码架构迁移混做。
- 2026-07-16：保留全部 10 份计划作为实现演进证据；不在旧路径放 redirect，
  统一由 taxonomy、ADR 和归档 manifest 提供稳定映射。
- 2026-07-16：Tool Runtime 计划簇与 RC-015 的 local-runtime/P3 计划簇分目录
  归档，避免把两个建设世代混成一个历史边界。
