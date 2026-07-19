---
schema: repository-cleanup-goal/v1
id: RC-006
title: 删除 legacy compaction trace fixture
status: done
batch: A
action: delete
priority: P1
risk: low
size: S
depends_on: [RC-001]
source_audit: docs/repository_asset_audit.md
source_sections: ["8.3 ARCHIVE/DELETE?", "15. 第一批高置信候选"]
created: 2026-07-14
updated: 2026-07-14
completed: 2026-07-14
---

# RC-006：删除 legacy compaction trace fixture

## 目标

删除与当前 compaction 合同不再关联的旧 trace fixture。

## 范围

- 包含：审计中标出的 legacy compaction fixture 及只为它存在的测试引用。
- 保护：当前 model-backed compaction golden、append-only runtime trace 合同和 RC-033 的决策空间。

## 工作项与验收

- [x] 复核测试发现、动态目录扫描、文档和生成脚本，确认 52 个文件均无活动消费者。
- [x] 删除 `local_runtime_trace_bundle_compaction/` 的 46 个 payload、3 个 JSONL 和 3 个 manifest，共 250,114 bytes。
- [x] deterministic compaction 行为仍由动态生成测试覆盖；无需迁移 fixture 断言。
- [x] compaction/history 定向测试 `42 passed`；mainline `14 passed`；local-only acceptance `stabilized=True`。
- [x] 全量 `923 passed, 77 skipped`；活动引用为零，`git diff --check` 通过。

## 结果

已删除无消费者的 deterministic predecessor golden。受保护的 `local_runtime_trace_bundle_model_backed_compaction/` 仍为 57 个文件且无 diff，`test_history_verify.py` 继续读取其中两个活动 JSONL；其后续缩减仍归 RC-009。

## 决策记录

- 2026-07-14：从高置信 fixture 候选拆成独立删除目标。
- 2026-07-14：确认待删与保留目录同属 schema v1；删除依据是零消费者和动态覆盖，而不是 schema 不可读。
- 2026-07-14：删除边界和全部门禁验收通过，状态置为 `done`。
