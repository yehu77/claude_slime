---
schema: repository-cleanup-goal/v1
id: RC-005
title: 退出 deterministic runtime pack
status: done
batch: A
action: delete
priority: P1
risk: low
size: S
depends_on: [RC-001, RC-003, RC-004]
source_audit: docs/repository_asset_audit.md
source_sections: ["9.4 TASK PACKS", "14. 建议的安全清理顺序"]
created: 2026-07-14
updated: 2026-07-14
completed: 2026-07-14
---

# RC-005：退出 deterministic runtime pack

## 目标

删除已无消费者的 deterministic dataset 及其仅由该 dataset 使用的 workspace。

## 范围

- 包含：deterministic task dataset、`runtime_create_add_one`、`runtime_subdir_formatter`。
- 保护：`runtime_rewrite_greeter`；它仍被 smoke、compaction 和 acceptance 路径使用。

## 前置证据

- [x] 仓库级引用复核未发现 deterministic dataset 消费者。
- [x] 两个待删 workspace 是该 pack 独占资产。
- [x] `runtime_rewrite_greeter` 已从删除边界中排除。

## 工作项与验收

- [x] 删除 1 个 dataset 与 2 个独占 workspace，并清理 ignored cache 和空目录。
- [x] 排除审计/goal 证据后活动引用为零；`runtime_rewrite_greeter` 两个 tracked 文件无 diff，仍有 7 处活动引用。
- [x] 删除后 inventory 为 2 个 pack、15 个全局唯一任务、15 个有效 workspace 和 2 个 study config。
- [x] task-pack 定向测试 `12 passed`；mainline `14 passed`；local-only acceptance `stabilized=True`。
- [x] 全量 `923 passed, 77 skipped`；`git diff --check` 通过。

## 结果

已删除 `datasets/tasks/deterministic_runtime_tasks.jsonl`、`examples/runtime_create_add_one/` 和 `examples/runtime_subdir_formatter/`。动态完整性门禁自动收敛到剩余 realistic/toy packs，受保护 greeter workspace 保持完整。

## 决策记录

- 2026-07-14：关联资产与下游引用审计完成；为避免后续引用回归，增加 RC-004 依赖并保持 `backlog`。
- 2026-07-14：RC-004 已完成，全部依赖满足，状态置为 `ready`。
- 2026-07-14：删除边界、保护资产和全部门禁验收通过，状态置为 `done`。
