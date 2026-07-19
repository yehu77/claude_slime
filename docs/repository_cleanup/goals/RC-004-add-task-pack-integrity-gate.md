---
schema: repository-cleanup-goal/v1
id: RC-004
title: 增加 task-pack 引用完整性门禁
status: done
batch: A
action: guardrail
priority: P1
risk: low
size: M
depends_on: [RC-001]
source_audit: docs/repository_asset_audit.md
source_sections: ["9.4 TASK PACKS", "14. 建议的安全清理顺序"]
created: 2026-07-14
updated: 2026-07-14
completed: 2026-07-14
---

# RC-004：增加 task-pack 引用完整性门禁

## 目标

让不存在或越界的 workspace、重复 task ID，以及失效或 family 错配的 study/profile 引用在测试中立即失败。

## 范围

- 包含：活动 task datasets、workspace 路径、全局 task ID，以及 study 的 task/profile 引用静态检查。
- 保护：不在此目标中重写 metadata 合同，也不删除任何 task pack。

## 工作项与验收

- [x] 动态枚举顶层 `datasets/tasks/*.jsonl` 及其 workspace，并检查 `configs/studies/*.json` 引用。
- [x] 增加 12 个确定性正负用例，覆盖缺失/越界路径、重复 ID、失效 profile/task 引用和 profile/tool family 错配。
- [x] 正常仓库状态下门禁通过；新顶层 pack 自动纳入，坏输入返回包含文件、行号和错误类别的诊断。
- [x] mainline `14 passed`；native-family acceptance tests `6 passed`；local-only acceptance `stabilized=True`。
- [x] 全量 `923 passed, 77 skipped`；`git diff --check` 通过。

## 结果

RC-004 验收时门禁覆盖 3 个活动 task pack、18 个全局唯一任务、18 个有效 workspace 和 2 个 study config。门禁使用动态发现，后续 pack 增删无需维护数量白名单；测试已加入显式 CI mainline 路径及 native-family acceptance 回归套件。

## 决策记录

- 2026-07-14：登记为后续 task-pack 删除和迁移的前置防护，状态置为 `ready`。
- 2026-07-14：不冻结 task metadata 的 family/profile 字段；该合同留给 RC-021，本目标只验证当前 study 引用生成出的 profile/tool family 一致性。
- 2026-07-14：全部验收通过，状态置为 `done`。
