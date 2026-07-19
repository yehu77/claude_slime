---
schema: repository-cleanup-goal/v1
id: RC-007
title: 删除伪 native trace fixture
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
updated: 2026-07-15
completed: 2026-07-15
---

# RC-007：删除伪 native trace fixture

## 目标

移除名称暗示 native、实际不符合当前 native trace 合同的误导性 fixture。

## 范围

- 包含：审计定位的 pseudo-native fixture 和专属断言。
- 保护：真实 native tool catalog、RawAgentTrace 和 native-transformed 辅助路线的合同样本。

## 工作项与验收

- [x] 确认 28 个文件没有显式消费者、fixture 根目录扫描或 pytest 隐式发现。
- [x] 确认 envelope 仍可读，但 `tool_profile_id=base` 和 generic legacy 九工具不符合当前 Claude/Codex strict native-family 语义。
- [x] 删除 `local_runtime_trace_bundle_native/` 的 22 个 payload、3 个 JSONL 和 3 个 manifest，共 116,552 bytes；无需迁移专属断言。
- [x] trace/native 定向测试 `55 passed, 3 skipped`；mainline `14 passed`；local-only acceptance `stabilized=True`。
- [x] 全量 `923 passed, 77 skipped`；活动引用为零，`git diff --check` 通过。

## 结果

已删除名称误导且无活动消费者的旧 bundle。它记录的是 `native_tool_calling` 传输模式下的 legacy `base` ToolView，并不是当前 `native_claude` 或 `native_codex` family trace；删除依据不是 JSON 或 runtime-trace envelope 损坏。

当前 native-family 合同继续由动态 runtime/mainline、strict family、profile transform 和 acceptance 测试覆盖。Claude API、external CLI、RawAgentTrace/tool catalog、model-backed compaction 以及 RC-008 的 runtime-observed fixtures 均保持不变。

## 决策记录

- 2026-07-14：登记为防止错误研究语义继续传播的独立目标。
- 2026-07-15：确认唯一历史消费者已经删除，当前活动消费者和隐式 fixture discovery 均为零。
- 2026-07-15：确认该 bundle 的 envelope 仍有效，但 generic `base` ToolView 不代表当前 strict native family；完成精确删除和全部门禁后置为 `done`。
