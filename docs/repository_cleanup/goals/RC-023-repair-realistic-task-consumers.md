---
schema: repository-cleanup-goal/v1
id: RC-023
title: 修复 realistic consumers 的 family 选择
status: done
batch: B
action: repair
priority: P0
risk: medium
size: M
depends_on: [RC-022]
source_audit: docs/repository_asset_audit.md
source_sections: ["9.4 TASK PACKS", "11.1 KEEP，但当前需要修复或并入统一 CLI", "13.3 Native-family acceptance"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-023：修复 realistic consumers 的 family 选择

## 目标

让所有 realistic task 消费者显式传递并记录 native family/tool-stack 选择。

## 范围

- 包含：behavior baseline 内部 `run_coding_task`、根 runtime smoke、根 credibility/mutation wrappers 的缺参路径。
- 保护：内部 credibility/mutation 函数已有的 family 参数；不做无依据的全模块重写。

## 工作项与验收

- [x] 枚举所有 realistic dataset consumers 和调用签名。
- [x] 消除缺失 `tool_stack_kind`/required-family 参数或静默默认。
- [x] manifest/trace 中可观察到最终 family 选择。
- [x] 每个入口有定向测试，mainline、local acceptance、全量测试和 `git diff --check` 通过。

## 结果

### 最新 consumer 调用图

| 入口 | realistic loader | 内部调用 | 修复结果 | family 证据 |
| --- | --- | --- | --- | --- |
| `run_real_provider_behavior_baseline.py` | `load_realistic_runtime_tasks()` | `run_real_provider_behavior_baseline()` → `run_behavior_baseline()` → `run_coding_task()` | 三层 API 均要求并传递 `tool_stack_kind`；根入口显式选择 `native_claude` | result、behavior summary、每个 run 的 `tool_profile.json` |
| `run_toolview_mutation_data_generation.py` | 同上 | `run_real_provider_toolview_mutation_data_generation()` → source-run materializer | 内部 API 原已必填并记录；补齐根 wrapper 的显式 `native_claude` 参数 | result、generation summary/manifest、source-run profile/trace |
| `run_real_provider_credibility_bundle.py` | 同上 | `run_real_provider_credibility_bundle()` → source-run materializer | 内部 API 原已必填并记录；补齐根 wrapper，并把 stack 加入 result | result、credibility summary/manifest、source-run profile/trace |
| `run_runtime_smoke_real_provider.py` | 不加载 pack；属于同组 real-provider runtime 入口 | 直接 `run_coding_task()` | 补齐显式 `native_claude` 参数并打印选择 | stdout、trajectory profile ID、`tool_profile.json` |

### 落盘结果

- [`real_provider_behavior_baseline.py`](../../../pycodeagent/eval/real_provider_behavior_baseline.py)
  的 `run_behavior_baseline()`、`run_real_provider_behavior_baseline()` 和 summary
  builder 现在都把 `ToolStackKind` 作为 keyword-only 必填参数；不存在 provider、
  task metadata 或 tool-name 推断默认。
- behavior result/summary、mutation result、credibility result 均显式携带
  `tool_stack_kind`。mutation/credibility 的 summary 和 manifest 原有字段继续保留。
- 四个根 wrapper 以类型化常量
  `_TOOL_STACK_KIND: ToolStackKind = "native_claude"` 显式声明当前
  real-provider transport 路线；内部 API 仍允许调用者
  明确选择 `native_codex`，没有将 provider family 等同于 tool family。
- 新增 [`test_realistic_task_consumers.py`](../../../tests/test_realistic_task_consumers.py)：
  实际运行最小 behavior/credibility source run，核对结果、summary/manifest 和
  `tool_profile.json`；同时对四个根 wrapper 做参数捕获。
- native-family generation smoke 补查 Claude/Codex mutation summary 和 manifest，
  分别固定 `native_claude` / `native_codex` provenance。
- consumer gate 已加入 GitHub mainline workflow、cleanup 标准命令、native-family
  acceptance regression 路径和当前 acceptance runbook，避免未来再次成为旁路测试。
- 验收：consumer 专项 `13 passed, 1 skipped`；mainline
  `50 passed, 3 deselected`；全量 `961 passed, 77 skipped`；`git diff --check`
  通过；taxonomy `90 documents, 35 inventory entries, 233 local links`。
- native-family local acceptance：`stabilized=True`，更新后的 2 个 regression
  commands、3 个 native Codex tasks 和 2 个 family generation smokes 均通过。

## 决策记录

- 2026-07-14：按最新调用图收窄问题，不沿用审计中已过时的“全部 broken”判断。
- 2026-07-17：mutation/credibility 内部 materializer 已正确要求、传递并在 manifest
  记录 family，本目标不重写它们；只补根 wrapper 和 result provenance。
- 2026-07-17：当前 OpenAI-compatible real-provider 正式入口选择
  `native_claude`；Codex freeform transport 限制仍由 ADR/acceptance 明示，不做静默
  替代或自动降级。
- 2026-07-17：不把根 wrapper 改造成完整 argparse CLI；统一 CLI 属于后续 RC-045，
  本目标只关闭实际缺参和不可观测 family 的合同缺口。
