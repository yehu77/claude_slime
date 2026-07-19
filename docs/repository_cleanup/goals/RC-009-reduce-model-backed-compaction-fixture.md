---
schema: repository-cleanup-goal/v1
id: RC-009
title: 缩减 model-backed compaction fixture
status: done
batch: A
action: reduce
priority: P1
risk: medium
size: M
depends_on: [RC-001]
source_audit: docs/repository_asset_audit.md
source_sections: ["8.2 REDUCE", "13.2 定向 slow 测试"]
created: 2026-07-14
updated: 2026-07-15
completed: 2026-07-15
---

# RC-009：缩减 model-backed compaction fixture

## 目标

把大型 compaction fixture 缩成仍能覆盖 model-backed 摘要、carry-forward
state、message-limit compaction 与 post-compaction replay 的最小代表样本。
Token-budget 边界继续由动态 context-policy 测试覆盖。

## 范围

- 包含：model-backed compaction fixture 内容及其精确 golden 断言。
- 保护：compaction 事件顺序、摘要可追溯性和 post-compaction continuation 语义。

## 工作项与验收

- [x] 复核唯一静态消费者和隐式 manifest 闭包：history verifier 需要两份 JSONL 及其相邻 manifest；runtime trace、manifest 和 51 个 payload 没有消费者。
- [x] 确认原样本由 `message_limit_exceeded` 触发，不是 token overflow；token-budget 行为由 `test_context_policy.py` 动态覆盖。
- [x] 以 `model_backed_compaction_history_mini/` 替代旧完整 trace bundle：4 个文件、10,776 bytes、可移植 `workspace` 根路径、单个 turn-4 compaction snapshot 和 11 条必要 retained entries。
- [x] 将 runtime trace 的关键顺序迁入动态 P3B acceptance：requested → completed → selection planned → applied → model request。
- [x] compaction 定向测试 `20 passed`；mainline `15 passed`；local-only acceptance `stabilized=True`。
- [x] 全量 `924 passed, 77 skipped`；旧路径活动引用为零，`git diff --check` 通过。

## 结果

| Asset | Files | Content bytes | Purpose |
| --- | ---: | ---: | --- |
| Old full trace bundle | 57 | 265,891 | runtime trace、payload 与 history artifacts 的过大闭包 |
| New `model_backed_compaction_history_mini/` | 4 | 10,776 | summary、carry-forward state、lineage 和 post-compaction replay |

缩减 255,115 bytes（95.9%）。新的静态 mini 只保留 history verifier 所需的
manifest-backed JSONL；它明确断言 `model_backed_used=true`、`inline_model`、
无 fallback、message-limit 触发、5 条 post-compaction 与 8 条 pre-compaction
消息，以及一个完整 replacement-history lineage。

旧 `local_runtime_trace_bundle_model_backed_compaction/` 及其 51 个 payload、
runtime trace 和 manifest 已删除。动态 P3B acceptance 继续生成真实运行时 trace
并断言 compaction 事件相对顺序，避免静态大 payload 承担不必要的运行时覆盖。

## 决策记录

- 2026-07-14：登记为 reduce，不在未冻结 compaction 合同前直接删除。
- 2026-07-15：发现 JSONL loader 隐式读取相邻 manifest，因此最小闭包是 4 个文件而不是初审所述的 2 个。
- 2026-07-15：确认原 fixture 只覆盖 message-limit，不覆盖 token overflow；将 token-budget 责任明确保留给动态 context-policy 测试。
- 2026-07-15：以去敏、可移植 mini 替代 57 文件 trace bundle，并将事件顺序断言迁入动态 P3B acceptance；全部门禁通过后置为 `done`。
