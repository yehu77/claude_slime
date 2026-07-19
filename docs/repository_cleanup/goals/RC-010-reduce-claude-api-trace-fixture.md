---
schema: repository-cleanup-goal/v1
id: RC-010
title: 将 Claude API trace 缩成 mini trace
status: done
batch: A
action: reduce
priority: P1
risk: high
size: M
depends_on: []
source_audit: docs/repository_asset_audit.md
source_sections: ["8.2 REDUCE", "17. 当前决策边界"]
created: 2026-07-14
updated: 2026-07-19
completed: 2026-07-19
---

# RC-010：将 Claude API trace 缩成 mini trace

## 目标

用去敏、可审查的最小 trace 替代约 3.93 MB、569 事件的原始 Claude API fixture。

## 范围

- 包含：大型 trace 的备份确认、最小事件切片、去敏和 ingestion golden 更新。
- 保护：原始数据在明确外部备份前不得删除或不可逆改写；不扩大 Claude API 路线地位。

## 阻塞条件

- [x] 用户确认原始 trace 先校验备份到本机工作树外。
- [x] 用户确认允许仓库内原件被去敏 mini trace 替换。

## 工作项与验收

- [x] 原始 fixture 已逐字节备份到本机
  `~/.local/share/pycodeagent/references/claude-api-traces/`，SHA-256、字节数、
  行数和 `cmp` 均一致；仓库只记录去敏后的引用证据。
- [x] mini trace 覆盖两个 request、请求侧工具目录、assistant `tool_use`、
  后续匹配 `tool_result`、`tool_use` 与 `end_turn` stop reason。
- [x] ingestion、transformation、dataset validation 与 training-prep 测试通过。
- [x] 去敏门禁拒绝 authorization/API key/cookie/device/user/account/本机路径，
  确定性 checksum 和文件大小断言通过。

## 结果

原 3,933,704 bytes、569 行、27 request fixture 已由完全合成且去敏的
5,318 bytes、8 行、2 request mini trace 替换，缩减 3,928,386 bytes
（99.86%）。原始 SHA-256 为
`d0afd3fb0f82a1f74dff6712f0735939a44ecc723ac214f14a1769cafc148e87`，
mini trace SHA-256 为
`4174a836788162a443d1e3960f448271b2112c0b299f93618aa85d2ae5940d32`。

备份事实、存储边界与 replacement 合同记录在
`references/claude-api-trace-local-reference.json`；原始数据不进入 Git 或
外部存储。专项合并门禁为 `19 passed`（mini contract、native-transformed
ingestion/dataset/training-prep），offline mainline 为 `199 passed,
3 deselected`，local-only acceptance 为 `stabilized=true`，最终全量为
`973 passed, 21 skipped`。

## 决策记录

- 2026-07-14：因可能含唯一原始研究证据，禁止先删后补备份。
- 2026-07-19：用户批准“先做本机工作树外校验备份，再以去敏 mini trace
  替换”；备份通过 SHA-256、大小、行数和逐字节复核后实施。
- 2026-07-19：用完全合成的两请求样本保留必要 ingestion 语义，并以独立
  contract test 阻止敏感元数据和真实 provider 内容回流。
