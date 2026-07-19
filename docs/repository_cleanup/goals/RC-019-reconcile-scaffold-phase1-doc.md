---
schema: repository-cleanup-goal/v1
id: RC-019
title: 校正 scaffold phase-one golden 文档
status: done
batch: A
action: repair
priority: P2
risk: medium
size: S
depends_on: [RC-012]
source_audit: docs/repository_asset_audit.md
source_sections: ["7.2 KEEP，但必须重写", "4.4 Multi-agent 长期合同"]
created: 2026-07-14
updated: 2026-07-16
completed: 2026-07-16
---

# RC-019：校正 scaffold phase-one golden 文档

## 目标

让 phase-one 文档只指向 RC-012 确立的唯一 mock golden，并准确说明 synthetic-first 边界。

## 范围

- 包含：`docs/scaffold_phase1.md` 的路径、生成方式、schema 版本和验收命令。
- 保护：phase one 不要求先接入真实外部 coding agent 的既定规则。

## 工作项与验收

- [x] 对照唯一 golden 和当前 schema 逐项校正文档。
- [x] 示例命令可从干净临时目录复现/验证 bundle。
- [x] 不存在指向已删除副本的链接。
- [x] 链接检查与 `git diff --check` 通过；N/A — 不改运行时实现。

## 结果

- 将 [`scaffold_phase1.md`](../../scaffold_phase1.md) 中混写的产物拆成 raw、
  normalized、derived 和 golden-management 层，并逐项列出唯一 golden 的 8 个
  文件及其合同类型。
- 校正 schema 边界：manifest、summary、catalog、canonical trace 和 normalization
  report 当前为 `schema_version: 1`；RawEvent JSONL 行由 versioned summary 管理，
  `SchemaFollowingSample` 当前没有顶层 `schema_version`，不再虚构统一版本字段。
- 文档现在链接
  [`examples/multi_agent_mock_run/`](../../../examples/multi_agent_mock_run/README.md)
  唯一真源，并明确 `tests/fixtures/` 下没有第二份文件副本。
- 增加 `mktemp -d` + `--write --output-dir` + `--check --output-dir` 的干净目录
  复现流程；实际执行成功并生成 README、manifest 及 6 个结构化产物。
- 明确 synthetic-first 边界：真实 external-agent ingestion 是后续集成目标，不是
  phase-one 验收依赖；sidecar 协议仍是未来真实适配器的独立边界。
- 新增 mainline 文档门禁，直接读取真实 manifest，验证文件全集、版本说明、
  复现命令、唯一 golden 路径和旧 fixture 无文件副本。
- docs taxonomy 将该文档从 `reconciliation-pending` 更新为
  `active: reconciled by RC-019`。
- 验收：文档专项 `8 passed`；mainline `24 passed, 3 deselected`；全量
  `934 passed, 77 skipped`；taxonomy `90 documents, 35 inventory entries,
  227 local links`；干净临时目录 write/check 与 `git diff --check` 均通过。
- N/A：本目标只校正文档和文档合同门禁，不修改 adapter、normalizer、renderer
  或 runtime 行为，因此不重复执行 native-family local acceptance。

## 决策记录

- 2026-07-14：依赖 golden 真源先统一，避免反复改文档路径。
- 2026-07-16：以 RC-012 建立的 manifest 和生成器为可执行真源，文档不再维护
  一个独立、可能漂移的文件清单解释。
- 2026-07-16：不为完成文档校正而给 `SchemaFollowingSample` 追加版本字段；这会
  改变数据合同，应由独立 schema migration 目标处理。
- 2026-07-16：空的旧 fixture 目录可能作为本地目录壳存在，但门禁要求其中没有
  任何文件；Git 合同不依赖空目录的物理存在与否。
