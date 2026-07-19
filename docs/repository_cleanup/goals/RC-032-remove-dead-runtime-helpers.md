---
schema: repository-cleanup-goal/v1
id: RC-032
title: 删除失活 runtime helpers
status: done
batch: C
action: delete
priority: P1
risk: low
size: S
depends_on: [RC-001]
source_audit: docs/repository_asset_audit.md
source_sections: ["5.2 `runner.py` 内失活 helper", "10. DELETE?：代码级高置信候选"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-032：删除失活 runtime helpers

## 目标

删除无调用方、无动态注册且无合同价值的 runtime 辅助函数。

## 范围

- 包含：runner 中 `_meaningful_progress_observed`、`_active_recent_failure_kind`、`_sync_session_pending_issue`，prompt 的 `format_history_for_prompt`，mock adapter 的 `read_mock_raw_trace`。
- 保护：`pycodeagent/testing/runtime_observed.py` 和当前 E2E helper；它们已有活动消费者。

## 工作项与验收

- [x] 用静态引用、属性访问和测试 monkeypatch 搜索逐个确认零消费者。
- [x] 删除函数及专属死 imports/comments，不顺带重构相邻逻辑。
- [x] runtime、prompt、mock adapter 定向测试和 mainline 通过。
- [x] local acceptance、全量测试与 `git diff --check` 通过。

## 结果

静态符号、属性访问和测试 monkeypatch 搜索确认五个目标 helper 均为零消费者。
已删除 runner 的 `_meaningful_progress_observed`、
`_active_recent_failure_kind`、`_sync_session_pending_issue`，prompt 的
`format_history_for_prompt`，以及 mock adapter 的 `read_mock_raw_trace`；同时
删除仅由后者使用的 `read_raw_trace` import。没有改动相邻 runtime 状态机、
prompt 构造或 `pycodeagent/testing/runtime_observed.py` 的活动 E2E helper。

`tests/test_route_boundaries.py` 增加符号不存在门禁，防止这些无合同 helper 被
重新引入。联合 runtime/prompt/mock、hash、mutation 定向回归 `66 passed`；
mainline `60 passed, 3 deselected`；local native-family acceptance
`stabilized=True`；全量 `983 passed, 77 skipped`；`git diff --check` 通过。

## 决策记录

- 2026-07-14：依据最新调用图纠正范围，明确保留新主线测试 helper。
- 2026-07-17：五个 helper 的零消费者证据及全部门禁通过，状态置为 `done`。
