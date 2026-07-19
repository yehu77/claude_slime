---
schema: repository-cleanup-goal/v1
id: RC-001
title: 建立离线 mainline 清理门禁
status: done
batch: foundation
action: guardrail
priority: P0
risk: low
size: M
depends_on: [RC-000]
source_audit: docs/repository_asset_audit.md
source_sections: ["13. 测试证据", "14. 建议的安全清理顺序"]
created: 2026-07-14
updated: 2026-07-14
completed: 2026-07-14
---

# RC-001：建立离线 mainline 清理门禁

## 目标

为后续删除、归档和合并建立快速、离线、可在 CI 重复执行的主线门禁。

## 范围

- 包含：native runtime 与 runtime-observed 两条端到端主线、pytest marker、Ubuntu CI 和本地 acceptance。
- 保护：真实 provider 调用仍不是离线门禁的一部分。

## 工作项与验收

- [x] 两条 mainline E2E 覆盖运行、trace、dataset、tokenization/packing 与合同验证。
- [x] CI 可从仓库根目录离线执行严格 marker 测试。
- [x] local-only native-family acceptance 返回 `stabilized=True`。
- [x] 全量结果为 `911 passed, 77 skipped`，且 `git diff --check` 通过。

## 结果

清理目标现在有快速 mainline、local acceptance 和全量回归三层验证基线。

## 决策记录

- 2026-07-14：门禁已落盘并完成本地验证，标记完成。
