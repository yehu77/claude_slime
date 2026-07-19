---
schema: repository-cleanup-goal/v1
id: RC-051
title: 将 claude_code 移出工作树
status: done
batch: E
action: delete
priority: P2
risk: medium
size: S
depends_on: [RC-050]
source_audit: docs/repository_asset_audit.md
source_sections: ["12.3 `claude_code/`", "12.4 本地 ignored 资产"]
created: 2026-07-14
updated: 2026-07-19
completed: 2026-07-19
---

# RC-051：将 claude_code 移出工作树

## 目标

仅在 RC-050 明确授权后，将 ignored `claude_code/` 从项目工作树安全外移或删除。

## 范围

- 包含：仓内引用清理、可选 source lock/外部位置说明和最终路径验证。
- 保护：未授权内容、唯一研究资料和任何凭据；不得把本地树意外纳入 git。

## 前置条件

- [x] RC-050 已记录明确处置和备份要求。
- [x] 当前选择外移而非永久删除，不适用破坏性删除授权。

## 工作项与验收

- [x] 执行授权的外移/删除，并验证工作树内路径不存在。
- [x] tracked 代码、docs、tests 对该路径引用为零或有可复现替代。
- [x] mainline、local acceptance 与 `git diff --check` 通过。

## 结果

Done。已按 RC-050 冻结的本机保留式路线完成：

1. 在源目录仍存在时计算 `sha256-tree-manifest-v1` 摘要；
2. 确认精确目标路径不存在；
3. 使用保留文件字节和相对布局的复制写入本机持久 reference store；
4. 对源和目标独立验证完整摘要、条目数、目录数、symlink 数和总字节数；
5. 全部一致后移除工作树源路径；
6. 源路径移除后再次验证外部保留副本。

前后验证结果均为：

- tree SHA-256：
  `fe875b60f7df36978d5ee06d9e10823510a3c503664f619ddbb432b74e44bccb`
- 1,927 entries / regular files；
- 323 directories（含根目录）；
- 0 symlinks；
- 133,151,295 regular-file bytes。

工作树内 `claude_code/` 现已不存在。保留副本位于
`${XDG_DATA_HOME:-$HOME/.local/share}/pycodeagent/references/claude-code/2.1.88/research-tree`，
仍受 local-machine-only、禁止外部存储和禁止发布边界约束。tracked completion
evidence 只保存去敏元数据，不含机器绝对路径、原始文件名清单或源码内容，见
[`references/claude-code-local-reference.json`](../../../references/claude-code-local-reference.json)。
恢复时必须把外部副本复制回 ignored `claude_code/` 并重新验证同一摘要；本目标
没有授权永久删除保留副本。

externalization/docs/ledger 专项为 `26 passed`；offline mainline 为
`199 passed, 3 deselected`；正式 CLI local acceptance 返回 `exit_code=0`、
`stabilized=true`；全量为 `971 passed, 21 skipped`；外部副本 post-removal
摘要复核、工作树源路径缺失、文档链接和 `git diff --check` 均通过。真实
provider acceptance 记为 N/A，因为 adapter 仍通过 PATH 解析 `claude`，本目标
不改变 provider 或 runtime 行为。

## 决策记录

- 2026-07-14：把决策和破坏性实施拆开，避免台账本身被误解为授权。
- 2026-07-19：RC-050 选择 copy→verify→remove-source 的本机外移；任一校验
  失败必须保留工作树源目录。
- 2026-07-19：目标在复制前不存在；源和目标在移除前一致，目标在移除后再次
  一致，因此完成工作树源路径移除。
