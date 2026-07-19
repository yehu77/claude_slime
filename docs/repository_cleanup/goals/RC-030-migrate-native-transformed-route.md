---
schema: repository-cleanup-goal/v1
id: RC-030
title: 迁移 gateway/native-transformed 辅助路线
status: done
batch: B
action: archive
priority: P1
risk: high
size: L
depends_on: [RC-029]
source_audit: docs/repository_asset_audit.md
source_sections: ["6.4 Claude API/native-transformed 路线", "7.1 KEEP"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-030：迁移 gateway/native-transformed 辅助路线

## 目标

将 Claude API/gateway/native-transformed 代码、测试和文档迁入 RC-029 的辅助边界。

## 范围

- 包含：相关 modules、entrypoints、fixtures、docs 和 package exports。
- 保护：native tool schema 保存与 conservative SFT 的有效能力；不把它们提升为 runtime 主线。

## 工作项与验收

- [x] 按依赖闭包迁移，提供受控兼容导入或明确 breaking note。
- [x] 主线 package 不再默认 re-export auxiliary APIs。
- [x] native ingestion/transform goldens 与 shared serializer/mask 合同保持一致。
- [x] mainline、相关辅助测试、全量测试和 `git diff --check` 通过。

## 结果

Claude API gateway/trace/SFT 路径现位于
`pycodeagent.auxiliary.claude_api`，native-transformed SFT/RL/reward/eval/smoke
与训练准备现位于 `pycodeagent.auxiliary.native_transformed`。Claude 专用
serializer 与 request tool-catalog snapshot 一并迁移，shared serializer、mask、
tokenizer 与 ToolView 合同继续由原共享包提供。

`pycodeagent.rl` 和 `pycodeagent.traces` 已移除所有 auxiliary 默认导出及反向
导入；旧的 `pycodeagent.rl.claude_api_*`、
`pycodeagent.rl.native_transformed_*` 和 `pycodeagent.traces.claude_api_*` 模块
路径属于明确 breaking change。七个根命令仍作为窄兼容入口，直接转发到新
namespace；其中 gateway 实现也已迁入 package，根文件只保留
`AppConfig`、`build_app`、`main` 兼容导出。

13 个专属测试已迁入 `tests/auxiliary/`，3 份路线文档已迁入
`docs/auxiliary/`。`tests/fixtures/claude_api_tool_use_session.jsonl` 因 RC-010
单独负责其 3.9 MB fixture 的缩减与保真决策而暂留统一 fixture 根目录，但已在
version 2 machine policy 中明确登记为两条 auxiliary 路由的 fixture。

验收证据：

- route/docs 边界：`16 passed`；
- auxiliary、混合 training-prep、root CLI 与边界回归：`91 passed, 7 skipped`；
- mainline：`58 passed, 3 deselected`；
- local native-family acceptance：`stabilized=True`，2 个 regression commands、
  3 个 native Codex tasks、2 个 generation smokes；
- 全量：`969 passed, 77 skipped`；
- `git diff --check`：通过。

## 决策记录

- 2026-07-14：目标是命名空间治理，不是否定辅助数据源价值。
- 2026-07-17：采用“旧 package 模块路径明确 breaking、根命令窄兼容”的迁移
  策略，避免主线 aggregate package 继续隐式暴露辅助 API。
- 2026-07-17：依赖闭包、测试、文档和 machine policy 迁移完成，全部门禁通过，
  状态置为 `done`。
