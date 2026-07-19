---
schema: repository-cleanup-goal/v1
id: RC-052
title: 生成 runs 只读 inventory
status: done
batch: E
action: govern
priority: P1
risk: low
size: M
depends_on: []
source_audit: docs/repository_asset_audit.md
source_sections: ["12.4 本地 ignored 资产", "17. 当前决策边界"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-052：生成 runs 只读 inventory

## 目标

在任何归档/删除前，对本地 runs 生成不泄露内容的完整元数据清单。

## 范围

- 包含：路径、大小、mtime、run/task/profile/family/status、schema version、manifest 完整性和敏感风险标签。
- 保护：不上传、不修改、不删除 raw traces、workspace snapshots 或可能含凭据的数据。

## 工作项与验收

- [x] 定义只读 scanner 和去敏 inventory schema。
- [x] 所有发现的 run/artifact 100% 有分类状态，解析失败也作为显式记录。
- [x] 报告重复、损坏、无 manifest 和可能敏感资产，但不展示秘密内容。
- [x] 重复扫描在无文件变化时确定一致；`git diff --check` 通过。

## 结果

新增 `pycodeagent.dev.runs_inventory` 作为 repo-owned scanner，并冻结
`pycodeagent-runs-inventory/v1` summary 与
`pycodeagent-runs-inventory-record/v1` JSONL record 合同。scanner 不跟随目录
symlink；只在内存中读取内容以做去重摘要、结构化元数据提取、已知 manifest
引用检查和敏感模式标记。输出不包含 payload/workspace 原文、秘密命中值、
tool arguments/results、原始文件 checksum 或 symlink target；可疑元数据值
只保留不可逆摘要。

当前 2026-07-18 快照落在：

- [`references/runs-inventory.summary.json`](../../../references/runs-inventory.summary.json)；
- [`references/runs-inventory.jsonl`](../../../references/runs-inventory.jsonl)；
- [`references/runs-inventory.schema.json`](../../../references/runs-inventory.schema.json)；
- [`docs/runs_inventory.md`](../../runs_inventory.md)。

清单覆盖 8,855 个文件、741 个 file-bearing artifact groups 和
59,472,914 logical bytes，artifact/group 分类率均为 100%。437 个 manifest
中 431 个有效、6 个存在已知引用缺失；当前结构化文件没有 JSON parse
failure，非结构化文件以 `not_structured` 显式记录。共识别 494 个重复组、
3,641 个重复文件和 6,619,151 redundant bytes；这些数字不构成删除授权。

风险标签只报告类别与计数：6,035 个 raw-provider content、517 个 raw trace、
754 个 workspace snapshot、28 个 log、205 个 potential authorization
material 和 936 个 absolute user path。标签是保守风险信号，不证明存在可用
凭据；匹配原文从未落盘。

验收：

- scanner 合成/静态报告专项 `4 passed`；
- docs taxonomy `9 passed`；
- offline mainline `119 passed, 3 deselected`；
- 全量 `1014 passed, 77 skipped`；
- 生成后 `validate` 与只读 `verify` 均通过；
- 连续两次生成的 summary 与 JSONL SHA-256 分别保持
  `94860b50...e662` 和 `135521d5...85dc`；
- source state fingerprint 两次均为
  `fea8f4f5...8089`，且测试验证 scan 前后源文件 size/mtime/content hash
  不变；
- `git diff --check` 通过。

local/real-provider acceptance 为 N/A：本目标只治理 ignored `runs/` 的只读
元数据快照，没有改变 runtime、provider 或任务执行行为。RC-053 仍需用户确认
保留期限、外部存储边界和不可逆删除规则；RC-052 不上传、不归档、不 scrub、
不删除任何 run。

## 决策记录

- 2026-07-14：retention 决策必须建立在完整且只读的 inventory 上。
- 2026-07-18：duplicate 和 sensitive labels 只作为 RC-053 的决策输入，不能
  被自动解释为删除候选。
- 2026-07-18：tracked report 保留路径和 allowlisted IDs 以支持治理，但文档
  明确要求在仓库外分享前再次审查这些元数据。
