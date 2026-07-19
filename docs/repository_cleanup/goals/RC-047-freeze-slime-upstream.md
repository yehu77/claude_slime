---
schema: repository-cleanup-goal/v1
id: RC-047
title: 确认 slime upstream 与精确 ref
status: done
batch: E
action: govern
priority: P1
risk: medium
size: S
depends_on: []
source_audit: docs/repository_asset_audit.md
source_sections: ["12.1 `slime-main/`", "14. 建议的安全清理顺序"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-047：确认 slime upstream 与精确 ref

## 目标

为 vendored `slime-main/` 确认权威 upstream、不可变 commit/ref、许可证和本地修改基线。

## 范围

- 包含：remote URL、commit SHA、获取日期、license、原始 tree checksum 和来源说明。
- 保护：现有本地改动不在没有基线/备份时被上游文件覆盖。

## 工作项与验收

- [x] 从可信记录确认 upstream 和精确 commit，而非仅记录 branch/tag 名称。
- [x] 保存 machine-readable source lock 与许可证路径。
- [x] 对当前 vendor tree 生成差异/未知来源报告。
- [x] lock schema、checksum 和 `git diff --check` 通过；N/A — 来源治理不改 runtime 行为。

## 结果

权威来源已确认为官方 `https://github.com/THUDM/slime.git`，精确 upstream
commit 为 `16924b697e86adab96eded3a3d0bf6098a943bb4`。首次把该 vendor tree
加入本仓库的证据 commit 是
`c92d21a72dd86dae8838fffa4ec6a7c4d8e8d5f2`，时间为
`2026-06-03T16:36:43+08:00`；原始下载 transport 没有历史证据，继续明确记录为
`unknown`，没有用推测补齐。

[`references/slime-upstream.lock.json`](../../../references/slime-upstream.lock.json)
记录 official remote、full commit、archive URL、获取证据、Apache-2.0 license
路径与 checksum，以及 upstream 原始 465-entry tree checksum：
`64f378f4a0e32102fd82d6e95e07fefcd502bf1ffc4332c3365b3258a87d5835`。

[`references/slime-vendor-baseline-report.json`](../../../references/slime-vendor-baseline-report.json)
把当前 tracked vendor 分类为：

- 465 个 unchanged upstream entries；
- 9 个 local-only overlay candidates；
- 0 个 modified upstream paths；
- 0 个 missing upstream paths；
- 0 个 unknown-source paths；
- 1 个 portable materialization：上游 `.agents/skills -> ../.claude/skills`
  在 vendor 中是精确 link-target placeholder；
- 审计时 41 个未 tracked `__pycache__/*.pyc`，明确归为 ephemeral；
- 审计时已有的 `pycodeagent_native_rl.py` working-tree 修改被记录并原样保留。

RC-047 新增的 upstream projection 校验排除 lock 中的 9 个 overlay
candidate，不覆盖、恢复或同步 `slime-main/`。RC-047 本身只冻结基线，当时不
声称 overlay 已有 owner/reason/checksum 或可重建；该后续合同现已由
[RC-048](./RC-048-add-slime-overlay-lock.md) 完成。`VENDORING.md` 已补齐精确
来源、两个 bridge 文件和安全更新边界。

验收：source-lock/bridge 专项 `18 passed, 4 skipped`；offline mainline
`110 passed, 3 deselected`；全量 `1005 passed, 77 skipped`；
`git diff --check` 通过。real-provider/local acceptance 为 N/A：本目标只增加
来源治理和只读校验，没有修改 runtime/provider 行为。

## 决策记录

- 2026-07-14：overlay 治理必须先有可复现的上游基线。
- 2026-07-18：通过官方 full-commit archive 逐路径比对，而不是根据 package
  version、branch 名或本仓库提交时间猜测上游 ref；`16924b697...` 在排除 9 个
  local-only paths 并规范化一个 symlink placeholder 后与 vendor 主体完全一致。
- 2026-07-18：RC-047 source lock 中的 `overlay_candidate_paths` 只是基线差异
  边界；只有 RC-048 可以把它们晋升为带 owner/reason/checksum 的正式 overlay。
- 2026-07-18：现有 `slime-main/slime/rollout/pycodeagent_native_rl.py`
  working-tree 修改属于受保护的本地工作，来源冻结过程中未覆盖或还原。
