---
schema: repository-cleanup-goal/v1
id: RC-035
title: 合并 workspace hash helper
status: done
batch: C
action: merge
priority: P2
risk: low
size: S
depends_on: [RC-001]
source_audit: docs/repository_asset_audit.md
source_sections: ["5.8 其他重复"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-035：合并 workspace hash helper

## 目标

建立唯一 workspace digest 实现，使相同树在所有 runner/verifier 路径产生相同值。

## 范围

- 包含：重复 hash helpers、排序/忽略/符号链接规则和所有调用方。
- 保护：已持久化 manifest 的算法/version 解释能力，不静默重解释历史 digest。

## 工作项与验收

- [x] 用 corpus 比较重复实现并记录任何差异。
- [x] 选择 canonical helper，必要时给算法加版本字段。
- [x] 迁移调用方并删除重复实现。
- [x] hash goldens、mainline、全量测试与 `git diff --check` 通过。

## 结果

审计确认 `mock_adapter.py` 与 `external_cli_adapter.py` 的旧实现逐字等价；missing、
empty、directory-only、嵌套二进制/文本树及不同创建顺序 corpus 未发现输出差异。
唯一实现现为 `pycodeagent.adapters.workspace_digest.compute_workspace_digest`，
合同名 `sha256-tree-v1`、version `1`。v1 明确冻结 POSIX relative path 排序、NUL
分隔、文件字节、`<dir>` 和 `<missing>` 规则及当前 symlink 语义。

两个 adapter 已迁移到 canonical helper 并删除本地 `hash_workspace` 与死
`hashlib` import。新生成的 adapter metadata 和 `RawAgentRunResult.metadata`
持久化 `workspace_digest_algorithm`/`workspace_digest_version`；历史未带字段的
digest 仍解释为旧 v1，因为本次没有改变其字节算法。Claude/Kilo wrapper
golden 仅补充这两个合同字段。

新增五组 digest golden/corpus 检查及唯一 owner 静态门禁。联合定向回归
`66 passed`，wrapper/digest 修复回归 `34 passed`；mainline
`60 passed, 3 deselected`；local acceptance `stabilized=True`；全量
`983 passed, 77 skipped`；`git diff --check` 通过。

## 决策记录

- 2026-07-14：低风险去重，但历史 artifact 兼容必须显式处理。
- 2026-07-17：选择完全保持旧输出的 `sha256-tree-v1`，并以显式 metadata
  区分后续算法演进；全部门禁通过后置为 `done`。
