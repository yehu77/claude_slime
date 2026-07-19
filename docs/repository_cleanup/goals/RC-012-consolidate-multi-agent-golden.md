---
schema: repository-cleanup-goal/v1
id: RC-012
title: 统一 multi-agent mock golden 真源
status: done
batch: A
action: merge
priority: P1
risk: medium
size: M
depends_on: [RC-001]
source_audit: docs/repository_asset_audit.md
source_sections: ["8.3 ARCHIVE/DELETE?", "9.3 CONSOLIDATE", "4.4 Multi-agent 长期合同"]
created: 2026-07-14
updated: 2026-07-15
completed: 2026-07-15
---

# RC-012：统一 multi-agent mock golden 真源

## 目标

让 phase-one multi-agent mock bundle 只有一个可再生真源，避免 examples、fixtures 和文档副本漂移。

## 范围

- 包含：`examples/multi_agent_mock_run/`、测试 fixture 和生成/校验入口之间的所有权整理。
- 保护：`RawAgentTrace`、native tool catalog、agent identity 和 golden contract 语义。

## 工作项与验收

- [x] 指定唯一生成源、派生产物和更新命令。
- [x] 删除或由测试动态生成重复副本。
- [x] checksum/结构验证能检测人工漂移。
- [x] multi-agent、mainline、全量测试与 `git diff --check` 通过。

## 结果

`examples/multi_agent_mock_run/` 是唯一受版本控制的 phase-one golden。
`pycodeagent.testing.multi_agent_mock_golden` 以固定 `MockAdapter` 场景、strict
native Claude `mock_base` ToolView 和 `MockTraceNormalizer` 再生它；`--write`
更新快照，`--check` 同时验证 manifest、跨文件合同和一次独立再生的逐字节一致性。

旧的 `tests/fixtures/multi_agent_mock_bundle/` 五个纯重复文件已删除。新 bundle
补齐了此前缺失的 native `tool_catalog.json`，并覆盖 RawAgentTrace、catalog、agent
identity、canonical trace、normalization report 与 schema-following sample。为使该
链可再生，normalizer 现在把 agent `command_exec` 作为其父 tool call 的证据而非重复
动作，renderer 以大小写无关的方式解析 native canonical capability。

验收：multi-agent 定向测试 `9 passed`；mainline `16 passed, 3 deselected`；
local-only native acceptance `stabilized=True`；全量 `926 passed, 77 skipped`；
`git diff --check` 通过。

## 决策记录

- 2026-07-14：登记为 consolidate，不降低 phase-one golden 的合同地位。
- 2026-07-15：选择已有 AGENTS/CLAUDE 指向的 example 作为唯一快照，测试直接消费
  该目录，避免维护第二份 fixture。
- 2026-07-15：旧 generic `read_file/run_command/finish` 快照不能由当前 strict
  native-Claude mock 链 replay，因此按当前合同重建，而非机械保留旧 payload。
