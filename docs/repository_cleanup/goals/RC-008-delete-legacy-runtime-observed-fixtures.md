---
schema: repository-cleanup-goal/v1
id: RC-008
title: 删除 legacy runtime-observed fixtures
status: done
batch: A
action: delete
priority: P1
risk: medium
size: M
depends_on: [RC-001, RC-018]
source_audit: docs/repository_asset_audit.md
source_sections: ["8.3 ARCHIVE/DELETE?", "13. 测试证据"]
created: 2026-07-14
updated: 2026-07-15
completed: 2026-07-15
---

# RC-008：删除 legacy runtime-observed fixtures

## 目标

清除不再代表当前 observed dataset 合同的旧 fixture，同时保持主线 E2E 的真实生成路径。

## 范围

- 包含：经复核已被在线构造或新 golden 取代的 runtime-observed fixture。
- 保护：`pycodeagent/testing/runtime_observed.py`、新 runtime-observed mainline E2E 和活动合同样本。

## 工作项与验收

- [x] 五组 fixture 均完成“消费者—替代证据—处置”复核；代码、测试、CI 和隐式目录发现消费者为零。
- [x] RC-018 先行修正活动 acceptance 文档，移除错误 fixture ownership 和失效测试引用。
- [x] 新增在线 native Claude/Codex study E2E，覆盖 postrun、training-prep、trace coverage 和 execution reconciliation。
- [x] 删除 43 个 legacy fixture 文件，共 463,777 bytes；没有静态断言需要迁移。
- [x] runtime-observed/acceptance 定向测试 `49 passed, 1 skipped`；mainline `15 passed`；local-only acceptance `stabilized=True`。
- [x] 全量 `924 passed, 77 skipped`；活动路径引用为零，`git diff --check` 通过。

## 结果

| Fixture | 消费者 | 当前替代证据 | 处置 |
| --- | --- | --- | --- |
| `runtime_observed_dataset_bundle/`（5 files / 26,945 B） | 无 | 在线 exporter/profile provenance mainline | 删除 |
| `runtime_observed_dataset_bundle_mutated/`（5 / 32,387 B） | 无 | native profile mutation + 在线 training-prep | 删除 |
| `runtime_observed_dataset_bundle_tool_reorder/`（5 / 28,922 B） | 无 | acceptance 两 family mutation smokes | 删除 |
| `runtime_observed_study_bundle/`（16 / 301,714 B） | 无 | 新增两 family 在线 study/postrun E2E | 删除 |
| `runtime_observed_training_prep_bundle/`（12 / 73,809 B） | 无 | mainline serializer、assistant-only mask 和 tokenization 断言 | 删除 |

五组 profile 全部是 `family=legacy`、`native_profile_kind=legacy`；其中 training-prep 的 raw dataset 与 mutated bundle 五个文件逐字节重复。当前动态覆盖保留 strict native family、ToolView/canonical 边界和训练合同，不再维护静态 legacy golden。

## 决策记录

- 2026-07-14：纠正初审误判，明确测试 helper 与新 E2E 必须保留。
- 2026-07-15：确认五组目录共 43 个 tracked 文件、463,777 bytes，且没有显式或隐式消费者。
- 2026-07-15：先完成 RC-018，并以在线两 family study E2E 补齐 postrun 覆盖后执行精确删除。
- 2026-07-15：所有门禁通过，状态置为 `done`。
