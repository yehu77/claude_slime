---
schema: repository-cleanup-goal/v1
id: RC-020
title: 去重 AGENTS.md 与 CLAUDE.md
status: done
batch: A
action: merge
priority: P1
risk: medium
size: M
depends_on: [RC-013]
source_audit: docs/repository_asset_audit.md
source_sections: ["14. 建议的安全清理顺序", "17. 当前决策边界"]
created: 2026-07-14
updated: 2026-07-16
completed: 2026-07-16
---

# RC-020：去重 AGENTS.md 与 CLAUDE.md

## 目标

建立一个工具中立的项目目标真源，并把 agent-specific 指令缩成必要差异。

## 范围

- 包含：根级 agent 指令的共同目标、优先级、非目标和文档链接。
- 保护：不同 agent 运行环境确实需要的格式/工具差异；不擅自改变安全权限。

## 工作项与验收

- [x] 做段落级重复/冲突矩阵，指定共同内容真源。
- [x] 每个 agent 文件只保留适配差异并链接共同文档。
- [x] 人工复核当前主线、build order 和非目标未丢失。
- [x] 链接检查与 `git diff --check` 通过；N/A — 指令文档不改产品代码。

## 结果

### 段落级重复/冲突矩阵

| 内容区域 | 合并前证据 | 处理结果 |
| --- | --- | --- |
| Project Goal / 仓库定位 | 两文件逐段相同 | 仅保留在 [`AGENTS.md`](../../../AGENTS.md) |
| Current Primary Objective / Core Research Question | 两文件逐段相同 | 仅保留在 `AGENTS.md` |
| Success Criteria / Existing Foundation | 两文件逐段相同 | 仅保留在 `AGENTS.md` |
| Immediate Next Milestones / build order | 两文件逐段相同 | 仅保留在 `AGENTS.md` |
| Runtime / Training Data Contract | 两文件逐段相同 | 仅保留在 `AGENTS.md` |
| Non-Goals / Decision Rule / agent summary | 两文件逐段相同 | 仅保留在 `AGENTS.md` |
| Claude/Codex 名词 | 4 处词语不同，Claude 版本已落后于当前 Codex API 辅助路径 | 采用 `AGENTS.md` 中的当前项目事实，不视为 agent override |
| Claude Code 适配差异 | 没有仓库级特例 | [`CLAUDE.md`](../../../CLAUDE.md) 仅保留真源链接及“不覆盖工具、安全、权限规则”的说明 |

### 落盘结果

- `AGENTS.md` 明确声明为工具中立的项目目标、优先级、合同与决策规则真源。
- 将非标准大小写的 `CLAUDE.MD` 改为 Claude Code 可发现的 `CLAUDE.md`，并从
  371 行重复正文缩为 9 行兼容入口。
- 根 README 先列共同真源，再说明 Claude 入口的适配职责；文档 taxonomy 的
  Markdown source 发现规则同步采用标准文件名。
- 移除 `Trajectory.to_dict()` docstring 中“轨迹格式由 CLAUDE.md 定义”的失效
  归属；实际序列化行为未改变。
- 新增 mainline 门禁，验证旧大小写入口消失、Claude 入口保持精简并链接真源、
  核心章节不会重新复制进 agent-specific 文件。
- 人工复核确认当前 runtime-centered 主线、codex-rs subsystem-first build order、
  Runtime/Training Data Contract 和 Non-Goals 均完整保留在 `AGENTS.md`。
- 验收：文档专项 `7 passed`；mainline `23 passed, 3 deselected`；全量
  `933 passed, 77 skipped`；taxonomy `90 documents, 35 inventory entries,
  223 local links`；`git diff --check` 通过。
- N/A：只调整指令文档、导航、文档发现和一个无行为影响的 docstring，不修改
  runtime 或训练数据合同，因此不重复执行 native-family local acceptance。

## 决策记录

- 2026-07-14：登记为 merge，而非简单删除任一 agent 指令文件。
- 2026-07-16：选择 `AGENTS.md` 作为工具中立真源；它已经是 docs reading order
  的第一入口，也被仓库级 agent 发现机制使用。
- 2026-07-16：保留精简 `CLAUDE.md` 而非删除 Claude 入口，确保 Claude Code
  能发现共同规则，同时不维护第二份会漂移的项目说明。
- 2026-07-16：不在仓库指令中复制或弱化 agent runtime 自带的权限与安全规则。
