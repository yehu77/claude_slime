---
schema: repository-cleanup-goal/v1
id: RC-013
title: 建立 docs 分类与导航
status: done
batch: A
action: govern
priority: P1
risk: low
size: M
depends_on: [RC-000]
source_audit: docs/repository_asset_audit.md
source_sections: ["7. 文档资产结论", "14. 建议的安全清理顺序"]
created: 2026-07-14
updated: 2026-07-15
completed: 2026-07-15
---

# RC-013：建立 docs 分类与导航

## 目标

把 docs 明确分为 current driver、contract/reference、runbook 和 archive，并提供唯一导航页。

## 范围

- 包含：分类规则、目录/索引、每份文档 owner/status/superseded-by 标记。
- 保护：`codex_rs_subsystem_implementation_plan.md` 是当前 construction driver；工业 gap roadmap 是成熟度/验收框架。

## 工作项与验收

- [x] 完成 docs inventory，所有 tracked 文档 100% 归类。
- [x] 首页明确当前阅读顺序和 canonical 文档。
- [x] archived 文档仍保留来源、日期和替代关系。
- [x] 所有相对链接通过检查，`git diff --check` 通过。

## 结果

`docs/README.md` 现在是唯一 docs 导航页和 taxonomy 真源。它用四个稳定分类
（current-driver、contract-reference、runbook、archive）覆盖当前工作树中的 87 份
`docs/**/*.md`；cleanup goals 通过一条 self-indexed glob 规则覆盖，避免复制其自身
frontmatter 状态。

首页明确 `codex_rs_subsystem_implementation_plan.md` 是唯一 current driver，工业
gap roadmap 是 maturity/acceptance framework；根 README 已不再将 archive-pending
计划列为当前阅读入口。archive-pending 行在实际移动前已记录审计来源、日期与当前
替代关系，物理归档仍由 RC-015/RC-016 负责。

新增 `pycodeagent.dev.docs_taxonomy` 与 mainline
`tests/test_docs_taxonomy.py`：它验证 inventory 覆盖、唯一 current driver、archive
元数据、阅读顺序边界，以及 root/docs/configs/examples repo-owned Markdown 的相对
链接。四个指向已删除 builtin tool 文件的历史断链已修正为保留历史语义的有效引用。

验收：taxonomy CLI 报告 `documents=87, inventory_entries=32, local_links=135`；
mainline `19 passed, 3 deselected`；全量 `929 passed, 77 skipped`；
`git diff --check` 通过。N/A — 文档治理不需要 native local acceptance。

## 决策记录

- 2026-07-14：先建立分类规则，再批量移动旧规划文档。
- 2026-07-15：只建立逻辑 archive-pending 边界，不提前移动或重写历史正文；物理
  归档和 ADR 映射仍由 RC-014/RC-015/RC-016 负责。
