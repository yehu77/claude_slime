---
schema: repository-cleanup-goal/v1
id: RC-057
title: 退出无消费者的 legacy eval tables
status: done
batch: C
action: delete
priority: P2
risk: medium
size: S
depends_on: [RC-039, RC-031]
source_audit: docs/repository_asset_audit.md
source_sections: ["10. DELETE?：代码级高置信候选"]
created: 2026-07-17
updated: 2026-07-18
completed: 2026-07-18
---

# RC-057：退出无消费者的 legacy eval tables

## 目标

在公共导出边界收窄后，删除没有活动 report、CLI 或测试消费者的 legacy table
builders。

## 范围

- 包含：`pycodeagent/eval/tables.py` 及 `pycodeagent.eval` 对应 re-export。
- 保护：当前 behavior/credibility/runtime-observed reports 和 RC-043 将建立的
  campaign report 合同。

## 前置条件

- [x] RC-039 已确认仓内唯一消费者是 package re-export。
- [x] RC-031 已冻结公共 API 和兼容策略。
- [x] 删除前再次复核已知仓外 import 风险。

## 工作项与验收

- [x] 删除 module 和 package re-export，或按 RC-031 决策提供有期限的 shim。
- [x] eval/report 定向测试、import smoke、mainline、全量和
  `git diff --check` 通过。

## 结果

Done；`pycodeagent/eval/tables.py` 已删除，没有 compatibility shim。

删除前复核确认：

- 活动 runtime、report、CLI、docs 和 tests 没有行为消费者；
- RC-031 已从 `pycodeagent.eval` facade 移除全部 table exports；
- 模块唯一 import 指向 RC-026 已归档的 `eval/analysis.py`；
- 仓库没有 packaging entrypoint、动态 import、已知外部 integration 或稳定发行
  合同证据。

`orphan_support_modules.json` 已更新为 `retired` 且消费者为空。legacy-study
boundary 保留 65 条历史依赖边作为决策证据，但安装态
`post_archive_edges` 从 1 降为 0；验证器会拒绝模块重新出现或 stale edge
回流。public API mainline 也增加六个 table symbol 永不泄漏的负向断言。

验收结果：

- cleanup/public-API/archive/docs 专项：`42 passed`；
- 活动 eval/runtime/report 扩展回归：`36 passed, 1 skipped`；
- legacy archive verifier：`post_archive_edges=0`、
  `active_reverse_dependencies=0`；
- offline mainline：`161 passed, 3 deselected`；
- local-only native-family acceptance：`stabilized=True`、
  `native_codex_tasks=3`、`generation_smokes=2`；
- 全量测试：`938 passed, 21 skipped`；
- `git diff --check`：通过。

real-provider acceptance 记为 N/A：删除的模块没有 provider/runtime consumer，
本目标未改变 transport、请求、campaign 执行或训练数据合同。

## 决策记录

- 2026-07-17：RC-039 判定该模块没有仓内行为消费者，但 package-level export
  构成兼容风险，因此实际删除排在 RC-031 之后。
- 2026-07-18：RC-031 完成最小 public API contract，本目标全部前置条件满足。
- 2026-07-18：删除模块且不提供 shim；历史依赖证据保留，活动依赖归零。
