---
schema: repository-cleanup-goal/v1
id: RC-043
title: 定义并实现 RunCampaign/RunMatrix
status: done
batch: D
action: merge
priority: P1
risk: high
size: L
depends_on: [RC-024, RC-042]
source_audit: docs/repository_asset_audit.md
source_sections: ["5.5 Eval/campaign 重复", "5.6 根目录 CLI 重复"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-043：定义并实现 RunCampaign/RunMatrix

## 目标

用一个 versioned campaign 合同表达 task×family×ToolView×seed×provider 的运行矩阵和恢复语义。

## 范围

- 包含：campaign spec、run identity、deterministic expansion、resume/idempotency、artifact index 和失败汇总。
- 保护：单 run 的完整 trajectory、reward/verifier/status 和 exposed/canonical tool 边界。

## 工作项与验收

- [x] 从活动 campaign/study loops 提炼共同合同，不吸收已决定归档的历史偶然行为。
- [x] 相同 spec/seed 展开顺序与 run IDs 确定一致。
- [x] interruption/resume 不重复或覆盖 append-only trace bundles。
- [x] fake-client matrix、mainline、local acceptance、全量测试与 `git diff --check` 通过。

## 结果

Done。新增 `pycodeagent.eval.run_campaign`，以 version 1 `RunCampaign` /
`RunMatrix` 表达 task×native-family×ToolView-mode×seed×provider×repeat
矩阵。所有维度去重并排序；规范 spec、展开计划和逻辑 run identity 使用 canonical
JSON SHA-256，因此等价输入顺序得到相同 spec fingerprint、展开顺序和 run ID。

执行器把输出根绑定到精确 spec/plan，按逻辑 run 建立不可覆盖的编号 attempt：
有效 terminal record 直接跳过；完整但未落 terminal record 的 attempt 无 provider
调用恢复；部分 attempt 原样保留并使用下一编号；单 run provider/executor 异常被
结构化汇总且不阻断矩阵。恢复时重新核验 attempt、trajectory、tool profile 和
runtime trace manifest 身份，拒绝路径逃逸、spec 漂移和不完整产物。

新增确定性的 campaign spec、artifact index、failure summary 和 manifest，
索引保留完整 case、trajectory status、reward、verifier、ToolView profile 及相对
artifact paths。默认单 run 继续委托 `run_coding_task`，不改写已有
exposed/canonical tool 边界和 append-only runtime trace 合同。活动 campaign
入口的迁移与重复循环删除明确留给 RC-044。

合同见 [`docs/run_campaign_contract.md`](../../run_campaign_contract.md)。专项与
API/docs gate 为 `26 passed`；offline mainline 为 `170 passed, 3 deselected`；
local native-family acceptance 为 `stabilized=True`；全量为
`947 passed, 21 skipped`；`py_compile` 和 `git diff --check` 通过。

## 决策记录

- 2026-07-14：等待旧 study 路线决定和统一 bundle builder，防止新抽象同时背两套历史合同。
- 2026-07-18：两个依赖均已完成，本目标解锁；legacy study 仅作为负边界证据。
- 2026-07-18：campaign 核心只承担确定性编排、恢复和索引；研究特定指标留在
  observer/analysis 层，活动入口迁移由 RC-044 完成。
- 2026-07-18：attempt 作为 append-only 恢复边界；版本 1 不支持同一输出根的
  并发 writer，也不提供 delete/archive/cleanup 操作。
