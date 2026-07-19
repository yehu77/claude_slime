---
schema: repository-cleanup-goal/v1
id: RC-053
title: 定义 retention 与 retained-run index
status: done
batch: E
action: govern
priority: P1
risk: high
size: M
depends_on: [RC-052]
source_audit: docs/repository_asset_audit.md
source_sections: ["12.4 本地 ignored 资产", "17. 当前决策边界"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-053：定义 retention 与 retained-run index

## 目标

定义哪些 run 必须保留、保留多久、存在哪里，以及何时允许 scrub/archive/delete。

## 范围

- 包含：golden/evidence/debug/failed/superseded/sensitive 分类、期限、owner、checksum 和删除授权流程。
- 保护：唯一原始研究证据、合同 goldens、真实 provider traces 和可能敏感数据。

## 前置条件

- [x] RC-052 inventory 完整。
- [x] 用户确认保留期限、外部存储边界和不可逆删除规则。

## 工作项与验收

- [x] 写出 versioned retention policy 和 machine-readable retained-run index schema。
- [x] inventory 中每一类都能得到唯一处置，不允许隐式默认删除。
- [x] 定义 scrub/checksum/restore 验收与审计记录。
- [x] policy 示例、schema validation、链接检查和 `git diff --check` 通过。

## 结果

已冻结 `rc053-conservative-local-manual-v1`：

- `contract_golden`、`unique_research_evidence` 永久保留；
- `provider_raw` 最少保留 365 天，到期只进入人工复核；
- `debug`、`failed` 最少保留 90 天，再隔离 30 天；
- `superseded`、`duplicate` 必须隔离 30 天；
- 未知用途进入无限期 `unclassified_hold`，不允许默认删除。

敏感性与用途正交。RC-052 的任一风险标签都会产生 `restricted`；潜在授权材料
还必须完成 credential review。原始 payload、trace、workspace 和 log 只能
保存在同一机器、Git 工作树之外，policy v1 禁止 network share、self-managed
object storage 和 managed cloud storage。tracked 文件只允许去敏元数据。

交付物：

- [`references/runs-retention-policy.json`](../../../references/runs-retention-policy.json)
  冻结期限、存储、scrub/archive 和删除授权策略；
- [`references/retained-run-index.schema.json`](../../../references/retained-run-index.schema.json)
  定义 header、artifact-group/artifact entry 和 deletion authorization；
- [`examples/runs_retention/retained-run-index.example.jsonl`](../../../examples/runs_retention/retained-run-index.example.jsonl)
  是不可携带删除授权的 synthetic example；
- [`references/runs-retention-coverage.json`](../../../references/runs-retention-coverage.json)
  是当前 RC-052 inventory 的去敏聚合覆盖；
- [`docs/runs_retention_policy.md`](../../runs_retention_policy.md) 说明 RC-054
  的使用和安全边界；
- `pycodeagent.dev.runs_retention` 提供只读 `validate-policy`、
  `validate-index` 和 `verify-coverage`。

当前 741 个 artifact groups、33 种观察组合全部得到唯一安全处置：40 个
`failed`、125 个 `provider_raw`、576 个 `unclassified_hold`；8 个
`internal`、733 个 `restricted`；165 个本机保留、576 个人工复核保留、
0 个删除授权。RC-053 不把 campaign 名称猜测成 golden/evidence/superseded；
这类所有者级分类留给 RC-054。

索引验证器实现 artifact override 优先于 parent group，并拒绝 duplicate
targets、coverage 缺口、外部存储、通配符/越界路径、永久类删除、缺 checksum、
未完成临时恢复、未完成敏感复核、未结束 retention/quarantine、fingerprint
漂移、授权目标不精确和授权复用。scrub 必须生成 derivative 并保留 source；
任何失败统一 retain-and-report。

验收：

- retention 专项 `14 passed`；
- retention + inventory 专项 `18 passed`；
- docs taxonomy `9 passed`；
- offline mainline `133 passed, 3 deselected`；
- 全量 `1028 passed, 77 skipped`；
- 三个只读 CLI 命令、RC-052 source-state verify 和 `git diff --check` 通过。

local/real-provider acceptance 为 N/A：本目标不改变 runtime、provider、writer
或任务执行行为，也未移动、scrub、归档或删除任何 `runs/` 内容。

## 决策记录

- 2026-07-14：台账只建立治理目标，不预先授权删除现有 runs。
- 2026-07-18：用户确认保守期限、原始资产仅本机、永久删除逐批明确确认。
- 2026-07-18：到期只产生 review/quarantine eligibility，不产生删除授权；
  deletion authorization 必须绑定精确 inventory fingerprint 和目标集合。
- 2026-07-18：RC-053 只定义合同和聚合覆盖；当前 runs 的所有者级分类与实际
  生命周期执行仍属于 RC-054。
