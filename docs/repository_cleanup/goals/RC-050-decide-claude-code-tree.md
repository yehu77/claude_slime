---
schema: repository-cleanup-goal/v1
id: RC-050
title: 决定 claude_code 本地树去向
status: done
batch: E
action: decide
priority: P2
risk: medium
size: S
depends_on: []
source_audit: docs/repository_asset_audit.md
source_sections: ["12.3 `claude_code/`", "12.4 本地 ignored 资产", "17. 当前决策边界"]
created: 2026-07-14
updated: 2026-07-19
completed: 2026-07-19
---

# RC-050：决定 claude_code 本地树去向

## 目标

确定 ignored `claude_code/` 本地树是否仍是必要研究参考，以及应留在工作树外何处。

## 范围

- 包含：用途、来源、大小、敏感性、仓内引用和替代获取方式的只读审计。
- 保护：用户未明确同意前不删除、不移动、不公开该本地树内容。

## 阻塞条件

- [x] 选择保留在工作树、外移到本地参考目录，或确认可删除。
- [x] 若外移/删除，确认是否需要来源 lock 或备份。

## 工作项与验收

- [x] 记录最终决定及 RC-051 是否适用。
- [x] 更新 ignored-assets 文档，使其他开发者不会误以为它是必需 tracked 依赖。

## 结果

Done。选择 `externalize_to_local_reference_store`：保留这份研究证据，但不继续
把它放在项目工作树内；RC-051 负责将完整树验证后外移到本机持久 reference
store。本目标没有移动、删除、上传或公开任何文件。

只读审计确认：

- 当前树是 ignored/untracked 的 `@anthropic-ai/claude-code` 2.1.88；
- 共有 1,927 个文件、323 个目录、文件内容总计 133,151,295 bytes；
- 主要体积来自约 58 MB source map、35 MB 提取源码、29 MB vendor 和
  13 MB packaged CLI；
- Git tracked 文件为零，仓库没有该目录的路径消费者；
- `ClaudeCodeAdapter` 解析 PATH 中的 `claude`，`claude_code` agent ID 和
  catalog 名称不是路径依赖；
- 未发现 `.env`、credential database、private-key container、用户 session
  artifact 或用户配置；auth/token/key/secret 文件名来自实现源码，原始树仍按
  restricted local reference 处理；
- bundled legal terms 不支持把本地提取树默认为可发布资产。

RC-051 的目标位置冻结为
`${XDG_DATA_HOME:-$HOME/.local/share}/pycodeagent/references/claude-code/2.1.88/research-tree`。
它只能位于本机、Git 工作树之外，不允许 NAS、云或对象存储。执行必须
copy→full-tree digest/entry-count verify→remove source，任一失败保留源目录。
package version 和选定 checksum 只是 identity evidence，不声称可逐字重建
source-map-derived 研究布局；因此不授权直接删除。

机器决策与 sanitized audit 在
[`claude_code_tree_decision.json`](../claude_code_tree_decision.json)，ignored
资产边界见 [`local_ignored_assets.md`](../../local_ignored_assets.md)。

ignored-asset/docs/ledger 专项为 `25 passed`；offline mainline 为
`198 passed, 3 deselected`；全量为 `970 passed, 21 skipped`；文档链接和
`git diff --check` 通过。RC-050 是只读审计与治理决策，没有修改 runtime、
provider、ToolView 或本地 ignored 树，因此 local/real-provider acceptance
均记为 N/A；外移行为验收由 RC-051 负责。

## 决策记录

- 2026-07-14：ignored 不等于无价值或已授权删除。
- 2026-07-19：仓库零路径依赖，但本地提取研究树可能无法仅凭 package version
  逐字重建；选择验证外移而不是保留在工作树或直接删除。
- 2026-07-19：RC-050 只授权 RC-051 的保留式本机外移路线，不授权永久删除、
  外部存储或发布。
- 2026-07-19：RC-051 已按该路线完成，工作树源路径已移除，验证外部副本保留。
