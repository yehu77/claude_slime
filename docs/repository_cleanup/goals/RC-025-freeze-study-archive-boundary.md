---
schema: repository-cleanup-goal/v1
id: RC-025
title: 冻结 study 依赖闭包与归档机制
status: done
batch: B
action: govern
priority: P1
risk: medium
size: M
depends_on: [RC-024]
source_audit: docs/repository_asset_audit.md
source_sections: ["6.1 旧 study/eval 编排簇", "6.2 阶段性根入口"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-025：冻结 study 依赖闭包与归档机制

## 目标

在移动旧 study 代码前，得到包含代码、配置、fixture、测试、文档和入口的完整闭包。

## 范围

- 包含：静态 imports、动态注册、文件路径、CLI 调用和仓外使用风险。
- 保护：共享 serializer、mask、packing 和 runtime 合同不得随旧路线一起归档。

## 工作项与验收

- [x] 输出 machine-readable asset/edge inventory，所有候选均有 owner/disposition。
- [x] 选定 archive 机制和可复现/只读边界。
- [x] 证明活动主线没有反向依赖 archive。
- [x] inventory 完整性、链接检查与 `git diff --check` 通过。

## 结果

精确闭包已冻结在
[`legacy_study_archive_boundary.json`](../legacy_study_archive_boundary.json)：

- 36 个资产都有唯一 owner、disposition、implementation goal 和理由。
- 29 个目标进入只读 archive：RC-026 拥有 22 个 modules/configs/task/tests，
  RC-027 拥有 6 个阶段性根入口和 `tests/test_mimo_entrypoints.py`。
- 6 个共享边界只编辑不归档：`pycodeagent.eval.__init__`、task-pack integrity、
  canonical scaffold design、root CLI 测试、Mimo local-config example 和
  local-config README，分别由 RC-026/027 维护。
- `pycodeagent/eval/tables.py` 由 RC-057 单独删除；其原先对
  `eval/analysis.py` 的 import 继续作为历史跨目标顺序证据。
- 9 个 current runtime、runtime-observed、training-prep、compaction 和
  auxiliary baseline 资产被明确保护。

归档机制冻结为 `archive/legacy-study-v1/`：

1. 保持原仓库相对路径，避免同名碰撞和失去来源；
2. 归档只用于历史阅读，不是 Python package，也不进入 pytest collection；
3. `archive_manifest.json` 记录每个源/目标路径和 SHA-256；
4. 实施时先复制、校验 checksum，再在同一个 reviewed diff 中移除源；
5. 默认禁止 compatibility shim，除非另有独立合同和移除期限。

`pycodeagent.dev.legacy_study_boundary` 使用 AST import 和 JSON/Python path
reference 扫描重建 65 条进入归档目标的依赖边，并与 tracked inventory
逐项比较。所有来源要么随闭包归档、在拥有目标中编辑，或由 RC-057 单独处置；
活动主线反向依赖为 `0`。边漂移、未分类 reverse dependency、目标路径碰撞、
保护清单重叠都会 hard-fail。

验收结果：

- boundary、cleanup decision 与 docs 专项：`23 passed`；
- 独立 verifier 的安装态结果：`assets=36`、`archive_assets=29`、
  `manifest_entries=29`、`frozen_edges=65`、`post_archive_edges=0`、
  `active_reverse_dependencies=0`；
- offline mainline：`155 passed, 3 deselected`；
- local-only native-family acceptance：`stabilized=True`，
  `native_codex_tasks=3`，`generation_smokes=2`；
- 全量测试：`1050 passed, 77 skipped`；
- `git diff --check`：通过。

real-provider acceptance 记为 N/A：本目标只冻结静态边界和归档机制，未修改
provider transport、runtime 行为或任何活动资产。

## 决策记录

- 2026-07-14：将“先知依赖闭包”设为批量移动的硬门槛。
- 2026-07-18：RC-024 选择只读历史归档，本目标解锁。
- 2026-07-18：归档不追求在当前环境中可执行；保留源码、配置、测试和
  checksum provenance 即满足 RC-024 的历史参考要求。
- 2026-07-18：RC-026/027 实施前复核补录两个文档资产和三条文档边；
  boundary 精化为 36 个资产/65 条边，并增加历史边指纹与 post-archive edges。
- 2026-07-18：RC-026 与 RC-027 应同批实施或先完成 RC-027，避免先移动
  package 后短暂留下必然失败的根 wrappers。
