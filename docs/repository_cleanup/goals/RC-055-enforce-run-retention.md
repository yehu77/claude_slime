---
schema: repository-cleanup-goal/v1
id: RC-055
title: 在新 run writer 中执行 retention 规则
status: done
batch: E
action: govern
priority: P2
risk: high
size: L
depends_on: [RC-053]
source_audit: docs/repository_asset_audit.md
source_sections: ["12.4 本地 ignored 资产", "16. 目标仓库形态"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-055：在新 run writer 中执行 retention 规则

## 目标

让新产生的 runtime/campaign artifacts 从创建时就带 retention class、敏感标签、checksum 和可审计生命周期。

## 范围

- 包含：run manifest 字段、writer defaults、retained index 更新、dry-run cleanup 和 policy verifier。
- 保护：append-only raw trace 和完整 trajectory；自动化不得在默认路径静默删除研究证据。

## 工作项与验收

- [x] 所有新 run 必须显式/确定性得到 retention class，未知值 loud-fail。
- [x] cleanup 默认 dry-run，实际删除需要 policy 和授权条件同时满足。
- [x] writer crash/resume 不产生无索引或被错误过期的 artifacts。
- [x] retention integration tests、mainline、local acceptance、全量测试和 `git diff --check` 通过。

## 结果

新 run 的 retention 合同已接入真实 writer：

- `RuntimeTraceWriter`、`run_coding_task` 和 `AgentHarness.run_task` 都在
  artifact 写入前建立 retention 元数据；默认明确落为无限期、不可删除的
  `unclassified_hold`，未知 class 在创建 artifact 前 hard-fail。
- 每个 run 自带 `run_retention_manifest.json`、RC-053 兼容的
  `retained-run.index.jsonl` 和 append-only
  `run_retention_events.jsonl`；local runtime manifest 同步保存 policy、
  class、风险标签、期限、处置和 checksum 引用。
- 完整 run 落盘后生成 `sha256-tree-manifest-v1` 摘要。runtime trace、
  payload、trajectory、verifier、diff、日志和 workspace 都在保护集合中；
  自引用的治理文件明确排除。
- resume 必须匹配原 run/task/policy/class/owner/risk labels，保留原始
  retention/quarantine 时间，并恢复 event/payload ordinal。测试覆盖普通
  crash resume 和“trace 已完成但 retention 尚未封存”的中断窗口。
- `pycodeagent.dev.runs_lifecycle` 提供 policy/index/checksum verifier 和
  dry-run cleanup plan。cleanup 没有删除实现，`--execute` 明确拒绝；任何
  后续 destructive batch 仍须另行通过 RC-053 的精确资产授权和全部前置条件。
- [`docs/run_writer_retention.md`](../../run_writer_retention.md) 记录 writer、
  checksum、恢复和 cleanup 合同，并已纳入 docs taxonomy 与 offline
  mainline。

验收结果：

- retention enforcement + runtime writer 专项：`10 passed`；
- 相关 retention/runtime/docs 集成：`45 passed`；
- offline mainline：`146 passed, 3 deselected`；
- local-only native-family acceptance：`stabilized=True`，
  `native_codex_tasks=3`，`generation_smokes=2`；
- 全量测试：`1041 passed, 77 skipped`；
- `git diff --check`：通过。

real-provider acceptance 记为 N/A：本目标只改变 artifact lifecycle
metadata 和本地 writer，不改变 provider transport、模型行为或 ToolView。

## 决策记录

- 2026-07-14：先定义 policy，再自动执行；保守默认是保留并报告。
