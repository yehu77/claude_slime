---
schema: repository-cleanup-goal/v1
id: RC-015
title: 归档旧 local-runtime/P3 文档
status: done
batch: A
action: archive
priority: P1
risk: medium
size: M
depends_on: [RC-013, RC-014]
source_audit: docs/repository_asset_audit.md
source_sections: ["7.3 ARCHIVE", "14. 建议的安全清理顺序"]
created: 2026-07-14
updated: 2026-07-16
completed: 2026-07-16
---

# RC-015：归档旧 local-runtime/P3 文档

## 目标

把已完成或被当前 codex-rs driver 取代的 local-runtime/P3 计划移出活动文档命名空间。

## 范围

- 包含：审计列出的旧 local-runtime/P3 规划、阶段报告及其入口链接。
- 保护：当前 codex-rs implementation plan、工业 gap acceptance framework 和仍有效合同。

## 工作项与验收

- [x] 逐文档记录完成度、替代文档和保留理由。
- [x] 移入带日期的 archive，或删除完全重复且无证据价值的副本。
- [x] 活动导航不再把 archive 当作当前任务驱动。
- [x] 链接完整性和 `git diff --check` 通过；N/A — 纯文档移动不要求运行回归。

## 结果

六份旧 local-runtime/P3 文档已从活动 `docs/` 根目录移动到
[`docs/archive/2026-07-16-local-runtime/`](../../archive/2026-07-16-local-runtime/README.md)。
archive manifest 逐份记录原路径、归档时完成度、当前替代文档与保留理由；每份正文
顶部也有 RC-015/date 注记，避免历史文案被误读成当前 construction schedule。

当前替代关系收敛到 ADR-0001、codex-rs subsystem driver、industrial gap roadmap、
native-family acceptance；P3 compaction 尚未冻结的决策另指向 RC-033。docs taxonomy
已把六份记录标成 `archive-complete: RC-015`，活动 Reading Order 没有 archive 路径，
审计快照仍保留原路径作为 2026-07-14 的历史证据。

新增 docs gate 断言旧活动路径不存在、六份归档文件和 manifest 完整。验收：docs
定向 `5 passed`；mainline `21 passed, 3 deselected`；全量分片合计
`931 passed, 77 skipped`；taxonomy
`documents=89, inventory_entries=34, local_links=187`；`git diff --check` 通过。
N/A — 纯文档移动不需要 native local acceptance。

## 决策记录

- 2026-07-14：要求 ADR 先落盘，避免归档时丢失仍有效决策。
- 2026-07-16：保留全部六份记录；它们包含阶段完成证据、subsystem mapping 或
  acceptance rationale，删除会损失比磁盘收益更大的历史上下文。
- 2026-07-16：不保留旧路径 redirect 文件，确保 archive 真正退出活动命名空间；
  迁移映射由 docs taxonomy 和 archive manifest 提供。
