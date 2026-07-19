---
schema: repository-cleanup-goal/v1
id: RC-026
title: 隔离旧 study 模块、测试与配置
status: done
batch: B
action: archive
priority: P1
risk: high
size: L
depends_on: [RC-025]
source_audit: docs/repository_asset_audit.md
source_sections: ["6.1 旧 study/eval 编排簇", "14. 建议的安全清理顺序"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-026：隔离旧 study 模块、测试与配置

## 目标

把 RC-025 冻结的旧 study 闭包移出活动 package/测试发现，同时保留所选历史价值。

## 范围

- 包含：闭包清单中的 modules、tests、configs、fixtures 和文档链接。
- 保护：活动 runtime-observed、multi-agent contract 与共享 training-data kernel。

## 工作项与验收

- [x] 按选定机制归档或外移完整闭包，不留下半活动入口。
- [x] 默认 package imports、CLI 帮助和 pytest collection 不暴露 archive。
- [x] 若要求可复现，提供独立说明和版本/依赖快照。
- [x] mainline、local acceptance、全量测试和 `git diff --check` 通过。

## 结果

Done；22 个旧 study modules/configs/task/tests 已按原仓库相对路径移入
`archive/legacy-study-v1/`。活动 `pycodeagent.eval` 不再 eager-import 或
re-export 旧 API，task-pack integrity 门禁不再依赖旧 StudyConfig，canonical
scaffold design 也改指向活动 runtime evaluation surface。

归档与 RC-027 共用
[`archive_manifest.json`](../../../archive/legacy-study-v1/archive_manifest.json)：
29 个条目逐一保存 source、archive path、owner goal 与 SHA-256。archive
没有 package `__init__.py`，且由 `pytest.ini` 的 `norecursedirs` 排除。
`pycodeagent.dev.legacy_study_boundary` 验证源路径已消失、目标存在、manifest
100% 覆盖、checksum 匹配和活动反向依赖为零。`eval/tables.py` 未在本目标中
越权处置，随后已由 RC-057 独立删除。

验收结果：

- archive verifier：`assets=36`、`archive_assets=29`、
  `manifest_entries=29`、`frozen_edges=65`、`post_archive_edges=0`；
- archive/cleanup/task-pack/CLI/docs 专项：`69 passed`；
- offline mainline：`153 passed, 3 deselected`；
- local-only native-family acceptance：`stabilized=True`、
  `native_codex_tasks=3`、`generation_smokes=2`；
- 全量测试：`930 passed, 21 skipped`；
- eval import smoke：25 个活动 exports，旧 exports 泄漏为 0；
- `git diff --check`：通过。

real-provider acceptance 记为 N/A：本目标只调整静态包边界和历史资产位置，
没有修改 provider transport、provider client 或 runtime 行为。

## 决策记录

- 2026-07-14：定义为高风险整体迁移，不允许逐文件随意删除。
- 2026-07-18：RC-024 禁止删除和兼容性迁移，只允许按 RC-025 闭包整体归档。
- 2026-07-18：RC-025 完成，精确资产和依赖边已冻结，本目标解锁。
- 2026-07-18：与 RC-027 同批完成只读归档；实施中补录 canonical design
  的一条文档引用，因此冻结闭包从 34 个资产/62 条边精化为 36 个资产/65 条边。
