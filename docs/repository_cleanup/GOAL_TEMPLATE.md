---
schema: repository-cleanup-goal/v1
id: RC-XXX
title: 简短、可观察的目标名称
status: backlog
batch: A
action: decide
priority: P1
risk: low
size: S
depends_on: []
source_audit: docs/repository_asset_audit.md
source_sections: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
completed: null
---

# RC-XXX：目标名称

## 目标

用一句话描述完成后可以直接观察和验证的状态。

## 范围

包含：

- 明确的文件、目录、入口或合同边界。

不包含：

- 必须保护的相邻资产和非目标。

## 前置条件

- [ ] 依赖目标已经完成。
- [ ] 静态引用、动态发现和仓外风险已经复核。
- [ ] 删除、归档或迁移边界已经冻结。

## 工作项

- [ ] 执行一个可独立审查和回滚的修改。

## 验收

- [ ] 目标状态与预期一致，受保护资产未变化。
- [ ] 活动引用为零，或全部迁移到新边界。
- [ ] 相关定向测试通过。
- [ ] mainline gates 与 local acceptance 通过。
- [ ] 必要时全量 `tests/` 回归通过。
- [ ] `git diff --check` 通过。

不适用的验收项必须写成 `[x] N/A — 原因`，不能直接省略。

## 结果

Pending.

## 决策记录

- YYYY-MM-DD：记录范围、状态或依赖变化及理由。
