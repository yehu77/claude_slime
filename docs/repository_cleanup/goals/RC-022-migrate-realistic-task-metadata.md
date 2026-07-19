---
schema: repository-cleanup-goal/v1
id: RC-022
title: 迁移 realistic task metadata
status: done
batch: B
action: repair
priority: P0
risk: medium
size: M
depends_on: [RC-021]
source_audit: docs/repository_asset_audit.md
source_sections: ["9.4 TASK PACKS", "13. 测试证据"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-022：迁移 realistic task metadata

## 目标

将 realistic runtime task pack 迁移到 RC-021 的 family-neutral versioned schema。

## 范围

- 包含：realistic dataset、loader/generator 兼容层和 metadata golden。
- 保护：workspace 内容、verifier 预期和 task identity；不在此目标修复所有调用方。

## 工作项与验收

- [x] 对每个任务给出旧字段到新字段的确定性映射。
- [x] 迁移后 round-trip 和 schema validation 通过。
- [x] 不再由 task metadata 隐式决定 tool stack family。
- [x] task-pack 定向测试、mainline、local acceptance 与 `git diff --check` 通过。

## 结果

### 确定性迁移映射

| Task | 旧 tool hints | v1 `required_capabilities` | 保留的行为顺序 |
| --- | --- | --- | --- |
| `realistic_revise_add_one_001` | `create_file`, `write_file`, `python_run`, `finish` | `workspace_write`, `command_execution`, `validation`, `failure_recovery` | 创建文件、观察首次失败、失败未恢复时延迟完成、修订后重验成功 |
| `realistic_patch_calculator_001` | `read_file`, `write_file`, `python_run`, `finish` | `workspace_read`, `workspace_write`, `command_execution`, `validation`, `failure_recovery` | 先检查、先验证失败、重写、重验成功后完成 |
| `realistic_subdir_formatter_001` | `read_file`, `write_file`, `python_run`, `finish` | `workspace_read`, `workspace_write`, `command_execution`, `validation`, `failure_recovery` | 先检查、在 `app` cwd 验证失败、修复、同 cwd 重验成功后完成 |

### 落盘结果

- [`realistic_runtime_tasks.jsonl`](../../../datasets/tasks/realistic_runtime_tasks.jsonl)
  的三个任务全部迁移到 `metadata.task_contract.schema_version = 1`。
- 删除 `primary_tools`、`expected_pattern` 和外围 legacy
  `require_runtime_validation_evidence`；validation-evidence 开关迁入 v1 contract。
- `behavioral_requirements` 只描述可观察行为与先后关系，不包含 Claude、Codex、
  generic legacy tool 名或 runtime family/profile/provider selector。
- 三个 task ID、workspace、prompt、test command、`max_turns`、allowed/forbidden
  files 均保持稳定；只将第一项 description 的 `deferred finish` 改成工具中立的
  `deferred completion`，第三项的 `cwd-sensitive python_run` 改成
  `cwd-sensitive validation`。
- task-pack mainline 门禁内置 exact migration golden，验证三项字段映射、v1 schema、
  validation evidence、旧字段清除、工具/family hint 清除和 JSON round-trip。
- 默认 `load_realistic_runtime_tasks()` 验证继续通过：三个 v1 contract 均保留，
  repo path 仍解析为绝对 workspace。当前没有独立 task-pack generator，因此无需
  新增生成兼容分支；三个上层路线继续共用该 loader。
- [`ADR-0001`](../../adr/0001-native-family-runtime-boundary.md) 已改为完成时态，
  并明确其他未迁移 legacy packs 仍按各自路线迁移或归档。
- 验收：task-pack/loader 专项 `33 passed, 1 skipped`；mainline
  `44 passed, 3 deselected`；全量 `955 passed, 77 skipped`；taxonomy
  `90 documents, 35 inventory entries, 231 local links`；`git diff --check`
  通过。
- native-family local acceptance：`stabilized=True`，2 个 regression commands、
  3 个 native Codex tasks 和 2 个 family generation smokes 均通过。

## 决策记录

- 2026-07-14：数据迁移与 consumer 修复分开，便于审查合同变化。
- 2026-07-17：能力映射按任务必须完成的行为定义，而不是逐个翻译旧工具名；例如
  validation 与 command execution 分别保留“需要验证”和“需要执行验证命令”的
  合同含义。
- 2026-07-17：`behavioral_requirements` 保留旧 expected pattern 的可观察顺序，
  但不要求任一 family 暴露特定工具名或专用 finish 工具。
- 2026-07-17：本目标不修改 behavior baseline、mutation generation 或
  credibility bundle 的 family 传递；这些 consumer 入口由 RC-023 统一修复。
