---
schema: repository-cleanup-goal/v1
id: RC-054
title: 分类、scrub 并归档现有 runs
status: done
batch: E
action: archive
priority: P1
risk: high
size: L
depends_on: [RC-053]
source_audit: docs/repository_asset_audit.md
source_sections: ["12.4 本地 ignored 资产", "14. 建议的安全清理顺序"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-054：分类、scrub 并归档现有 runs

## 目标

按 RC-053 policy 对现有 runs 完成 100% 分类、去敏、校验和归档，并只删除明确获准的副本。

## 范围

- 包含：inventory 中所有 run、retained index、scrub report、checksums 和 restore verification。
- 保护：未分类、校验失败、唯一证据或未获删除授权的资产。

## 工作项与验收

- [x] 每个 inventory item 有 policy disposition 和执行结果。
- [x] 归档副本通过 checksum，抽样 restore 可读取完整合同字段。
- [x] scrub 规则有敏感模式测试，原始敏感数据不进入 tracked 文件。
- [x] 删除仅发生在授权、已验证备份后；最终 inventory 100% 闭环。

## 结果

用户确认 campaign 所有者级分类与
`local-archive:rc054-20260718` 本机归档边界。tracked
[`runs-archive-classification.json`](../../../references/runs-archive-classification.json)
精确覆盖 12 个 campaign：

- `native_family_acceptance_final_v4`、P3B compaction acceptance、
  behavior baseline、credibility bundle 和 ToolView mutation generation
  是 unique research evidence；
- 这些 evidence campaign 内的 provider-payload groups 单独使用 365-day
  `provider_raw`；
- real-provider smoke 是 90-day debug；
- 更早的 native-family acceptance/CLI/final-v1–v3 是 superseded，并从本次
  执行时间开始进入 30-day quarantine。

真实
[`retained-runs.index.jsonl`](../../../references/retained-runs.index.jsonl)
包含 1 个 fingerprint-locked header 和 741 个 artifact-group entries，通过
parent-group 继承覆盖 RC-052 的全部 8,855 个 artifacts。分类结果为：

- 342 `unique_research_evidence`；
- 57 `provider_raw`；
- 21 `debug`；
- 321 `superseded`；
- 8 `internal`、733 `restricted`；
- 342 `retain_active`、78 `retain_local`、321 `quarantine`；
- 0 `delete_authorized`，0 deletion authorization records。

新增 `pycodeagent.dev.runs_archive`。`archive` 只接受不存在且位于 Git 工作树
之外的 destination，在 owner-controlled staging 中生成 derivative；成功完成
scrub、全量临时 restore 和合同对比后才原子安装。它没有 delete command。
`verify` 只读复验 source fingerprint、每文件 checksum、payload digest、
retained-index checksum、scrub 幂等性、完整覆盖和 deletion count。

正式本机归档包含 8,855 个 derivative artifacts、741 个 groups 和
56,952,245 bytes，payload SHA-256 为
`cf939cdd5444be9d80f789e7d890c8ddcaf63479dccaa15da50bbae3d704bfd5`。
完整临时恢复验证了所有 8,855 个路径、artifact class 和 allowlisted contract
metadata；不是只抽样。tracked
[`runs-archive-manifest.json`](../../../references/runs-archive-manifest.json)
记录 aggregate checksum/restore evidence，物理 archive 自带完整逐文件
checksum manifest。

去敏扫描覆盖 8,855 个文件。8,194 个 derivative bytes 与 source 不同，其中
包含 JSON/JSONL 确定性规范化；显式敏感替换为 2,760 个 absolute user-home
prefix。261 个无法安全文本去敏且可再生的 `.pyc` caches 使用同路径确定性
redacted placeholder。其他非 UTF-8 输入 fail closed。tracked
[`runs-archive-scrub-report.json`](../../../references/runs-archive-scrub-report.json)
只包含计数和状态，不包含命中原文。source `runs/` 未被移动、改写或删除，
RC-052 fingerprint 仍为 `fea8f4f5...8089`。

验收：

- archive 专项 `5 passed`；
- archive + retention + inventory 专项 `23 passed`；
- docs taxonomy `9 passed`；
- offline mainline `138 passed, 3 deselected`；
- 全量 `1033 passed, 77 skipped`；
- 正式 archive 独立 `verify`、RC-052 source verify、链接检查和
  `git diff --check` 通过。

local/real-provider acceptance 为 N/A：本目标不运行 provider、不修改 runtime
或 writer 行为；它只处理已有 ignored artifacts 的本机 derivative archive。

## 决策记录

- 2026-07-14：这是高风险数据治理任务，实施时需单独确认破坏性操作。
- 2026-07-18：用户确认 campaign 分类和工作树外本机归档位置，但未授权任何
  deletion batch；因此本目标的删除数固定为 0。
- 2026-07-18：`.pyc` 可能嵌入无法可靠文本去敏的 source path，且属于可再生
  cache；归档保留同路径 redacted placeholder 和 source group checksum，不把
  binary bytes 带入 scrubbed derivative。
- 2026-07-18：JSON/JSONL scrub 保留输入 key order，避免嵌套 tool schema 的
  `schema_version` 被 scanner 误识别为顶层 run contract metadata。
- 2026-07-18：quarantine 只是一项 index lifecycle disposition；没有明确、
  fingerprint-bound 的新授权时，RC-054 archive 不能被解释为删除许可。
