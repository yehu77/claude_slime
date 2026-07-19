---
schema: repository-cleanup-goal/v1
id: RC-021
title: 定义 family-neutral task metadata
status: done
batch: B
action: govern
priority: P0
risk: medium
size: M
depends_on: [RC-014]
source_audit: docs/repository_asset_audit.md
source_sections: ["3. 当前唯一主线", "9.4 TASK PACKS", "17. 当前决策边界"]
created: 2026-07-14
updated: 2026-07-16
completed: 2026-07-16
---

# RC-021：定义 family-neutral task metadata

## 目标

冻结 task 描述与 runtime family 选择之间的边界，使一个任务可被多个 native family 显式复用。

## 范围

- 包含：task identity/workspace/verifier 与 family/profile/adapter 参数的字段归属和 schema 校验。
- 保护：任务不能通过默认值静默绑定到某个 backend family；现有 task ID 保持稳定。

## 工作项与验收

- [x] 写出 versioned metadata schema 和向后迁移规则。
- [x] 明确 family-neutral 字段、run-time required 参数和非法组合。
- [x] 用正负样本测试缺失、未知和冲突字段。
- [x] task loader、mainline、local acceptance 与 `git diff --check` 通过。

## 结果

- 在 [`pycodeagent/env/task.py`](../../../pycodeagent/env/task.py) 增加严格的
  `TaskMetadataContractV1`，由 `metadata.task_contract` 承载：
  `schema_version: 1`、非空且去重的 `required_capabilities`、可选的
  `behavioral_requirements` 和 validation-evidence 开关。
- v1 capability 是 family-neutral 行为能力：`workspace_read`、
  `workspace_write`、`command_execution`、`validation`、
  `failure_recovery`；不包含 Claude/Codex 暴露工具名。
- `CodingTask` 现在拒绝 metadata 中的 family/profile/adapter/provider runtime
  selector；`tool_stack_kind` 仍由 `run_coding_task` 调用者必填，task 不提供默认
  family，也不从 tool-name hint 推断 family。
- 定义向后迁移：没有 `task_contract` 的任务作为 legacy v0 继续可读，旧
  `require_runtime_validation_evidence` 保持行为；一旦声明 v1，就拒绝缺失/未知
  版本、未知字段或 capability、空值、重复值，以及与 `primary_tools` /
  `expected_pattern` 混用。
- [`ADR-0001`](../../adr/0001-native-family-runtime-boundary.md) 已补充字段表、
  字段归属、运行时必填参数、非法组合和 legacy v0 → v1 迁移规则。
- 移除 native-family acceptance 中两处 `CodingTask.metadata.family` 违规；实际
  Claude/Codex 选择仍分别通过显式 `tool_stack_kind` 完成，task identity 未变。
- 正负样本覆盖 v1 JSON round-trip、缺失/未知版本、未知字段/capability、空列表、
  重复值、runtime selector、legacy/v1 冲突和 legacy v0 读取。
- 验收：合同专项 `66 passed`；task/docs 联合门禁 `38 passed`；mainline
  `42 passed, 3 deselected`；全量 `952 passed, 77 skipped`；taxonomy
  `90 documents, 35 inventory entries, 229 local links`；`git diff --check`
  通过。
- native-family local acceptance：`stabilized=True`，2 个 regression commands、
  3 个 native Codex tasks 和 2 个 family generation smokes 均通过。

## 决策记录

- 2026-07-14：作为 realistic task 修复的合同前置目标。
- 2026-07-16：采用嵌套 `task_contract`，避免把严格 schema 强加给历史上允许
  任意扩展的整个 metadata 字典；外围描述性 metadata 仍可增量迁移。
- 2026-07-16：legacy v0 只获得读取兼容，不获得 runtime-selection 例外；即使
  没有 v1 contract，family/profile/adapter/provider selector 也立即拒绝。
- 2026-07-16：RC-021 只冻结合同和兼容层，不提前修改 realistic task pack；
  其确定性字段迁移由 RC-022 独立完成。
