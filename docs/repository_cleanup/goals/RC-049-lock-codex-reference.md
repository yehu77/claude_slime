---
schema: repository-cleanup-goal/v1
id: RC-049
title: 增加 codex-rs reference lock/bootstrap
status: done
batch: E
action: govern
priority: P0
risk: medium
size: M
depends_on: []
source_audit: docs/repository_asset_audit.md
source_sections: ["12.2 `codex-rs/`", "3. 当前唯一主线"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-049：增加 codex-rs reference lock/bootstrap

## 目标

让实现驱动所依赖的 ignored `codex-rs/` 参考树具有明确来源、精确 ref、checksum 和可选 bootstrap。

## 范围

- 包含：source URL、commit/ref、license、subtree checksum、获取/校验脚本或文档。
- 保护：`codex-rs` 仅作 subsystem mapping/reference，不作为仓库运行时隐式依赖或被复制进产品代码。

## 工作项与验收

- [x] 确认参考树的权威来源和不可变 ref。
- [x] tracked lock 能在树缺失时解释如何获取，在树存在时验证版本/checksum。
- [x] codex-rs implementation plan 链接 lock，而非假设每个开发环境都有同一 ignored tree。
- [x] 在“树存在/缺失/版本错误”三种状态验证诊断；`git diff --check` 通过。

## 结果

权威来源已锁定为官方 `https://github.com/openai/codex.git` 的 `codex-rs`
subtree，精确提交为
`0beb5c7f32cf5459a51e3f6bc01e6509d7951854`，license 为 Apache-2.0。
[`references/codex-rs.lock.json`](../../../references/codex-rs.lock.json)
记录 source URL、full commit、archive/license URL、subtree、4477 个条目和
`sha256-tree-manifest-v1` 摘要
`26842e6859cb892c4872e9fa838585ba1696b90283d35574df0610b5e864ea81`。

新增 `pycodeagent.dev.codex_reference`：

- `verify` 在 tree 正确、缺失、checksum/entry-count 漂移时分别返回
  `ok`/`missing`/`mismatch` 和退出码 0/2/1；
- `bootstrap` 只从 full-commit archive 提取 `codex-rs/`，先在 staging
  校验 checksum，再安装到缺失目标，并拒绝覆盖已有路径；
- digest 忽略时间戳和 mode，但保留 path、文件 bytes、size 和 symlink target；
  当前 source-copy 将上游 `vendor/bubblewrap/LICENSE -> COPYING` 落成精确
  link-target placeholder 的情况由 lock 显式声明和报告，不会放宽其他内容。

[`docs/codex_rs_reference.md`](../../codex_rs_reference.md) 是操作与边界说明；
current implementation plan、README、docs taxonomy 和 CI mainline 均已链接或
纳入该门禁。`codex-rs/` 继续被 ignore，只允许作为 implementation reference，
其缺失不会阻断 runtime 或普通测试。

验收：reference/docs 专项 `15 passed`；offline mainline
`105 passed, 3 deselected`；全量 `1000 passed, 77 skipped`；
`git diff --check` 通过。local real-provider acceptance 为 N/A：本目标没有修改
runtime/provider 行为，且明确禁止把 reference tree 变成运行依赖。

## 决策记录

- 2026-07-14：这是当前 runtime build order 的 P0 可复现性缺口。
- 2026-07-18：不能使用 `git -C codex-rs rev-parse HEAD` 推断 ref；本地目录没有
  nested `.git`，该命令会越界解析到当前仓库 HEAD。
- 2026-07-18：逐文件比对确认本地 tree 对应官方 `0beb5c7f...`；其下一提交
  `08cb633c...` 恰好修改先前观察到差异的五个 Rust 文件。唯一物料化差异是
  已在 lock 中声明的 portable symlink placeholder。
- 2026-07-18：reference lock 只治理实现证据，不授权 runtime dependency、
  源码复制或产品功能扩张。
