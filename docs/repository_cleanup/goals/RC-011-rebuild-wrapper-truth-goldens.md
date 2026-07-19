---
schema: repository-cleanup-goal/v1
id: RC-011
title: 重建 truth-consistent wrapper goldens
status: done
batch: A
action: repair
priority: P1
risk: high
size: M
depends_on: []
source_audit: docs/repository_asset_audit.md
source_sections: ["8.1 KEEP", "13. 测试证据", "17. 当前决策边界"]
created: 2026-07-14
updated: 2026-07-19
completed: 2026-07-19
---

# RC-011：重建 truth-consistent wrapper goldens

## 目标

让 wrapper summary、verifier、diff、reward 和 final status 对同一次运行表达一致事实。

## 范围

- 包含：审计中 truth 冲突的 wrapper fixtures/goldens 及其生成/断言路径。
- 保护：原始轨迹和 verifier 证据；在真值优先级确定前不手工“修漂亮”结果。

## 阻塞条件

- [x] 用户确认字段级 truth precedence：raw trace 负责事件，`verifier.json`
  和 `final.diff` 分别负责验证与工作区变化，状态/reward 从这些事实派生。
- [x] 用户确认重建正常 golden，并只保留一个最小冲突负例。

## 工作项与验收

- [x] 在 sidecar protocol 中建立字段级 truth matrix，并让 adapter 对正常
  sidecar summary 重建 harness-derived outcome 字段。
- [x] 重建 Claude/Kilo goldens：进程 `completed`、最终状态 `failed`、
  verifier failed、非空 diff、reward `0.0` 相互一致。
- [x] 保留单文件 synthetic conflict negative；显式伪造 verifier claim 时
  抛出 `ArtifactTruthConflictError`，禁止静默覆盖。
- [x] wrapper、canonical serializer、offline mainline、local-only acceptance
  与全量测试通过。

## 结果

sidecar 现在只负责 `raw_trace.jsonl` 事件、trace identity 与 capture metadata。
adapter 以字段为单位重建 summary：

| Field | Truth root |
| --- | --- |
| events/tool calls | `raw_trace.jsonl` |
| final diff | `final.diff` |
| verifier | `verifier.json` |
| execution status | subprocess result |
| final status | execution status，再看 verifier pass/fail |
| reward | verifier score |

sidecar 若省略派生字段，adapter 写入权威值；若显式声明，则必须精确一致，否则
硬失败。`execution_status=completed` 与 `final_status=failed` 可以合法共存。
Claude/Kilo goldens 和 canonical trace serializer 均断言 summary 与独立
diff/verifier artifacts 一致。

RC-010/011 联合专项为 `26 passed`，RC-011 协议与 wrapper 专项为
`18 passed`，offline mainline 为 `199 passed, 3 deselected`，local-only
acceptance 为 `stabilized=true`，最终全量为 `973 passed, 21 skipped`。

## 决策记录

- 2026-07-14：冲突涉及数据完整性，禁止只改快照以迎合测试。
- 2026-07-19：用户批准字段级 truth precedence、重建正常 goldens，并仅保留
  一个最小冲突负例。
- 2026-07-19：选择“省略则重建、显式声明则校验”的 sidecar 合同，使 wrapper
  不必预知 harness verifier，同时确保任何矛盾声明 loud-fail。
