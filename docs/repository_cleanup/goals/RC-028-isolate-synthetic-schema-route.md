---
schema: repository-cleanup-goal/v1
id: RC-028
title: 隔离 synthetic/trajectory baseline
status: done
batch: B
action: archive
priority: P2
risk: medium
size: M
depends_on: [RC-013]
source_audit: docs/repository_asset_audit.md
source_sections: ["6.3 Synthetic/trajectory-derived 路线", "3. 当前唯一主线"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-028：隔离 synthetic/trajectory baseline

## 目标

把 synthetic/trajectory-derived 路线明确降级为受控 baseline，而非 runtime-observed 主线的平行真源。

## 范围

- 包含：synthetic generators、专属 entrypoints/tests/docs 的命名空间和导航。
- 保护：schema mutation 的可复现实验价值以及 synthetic-first phase-one mock 合同。

## 工作项与验收

- [x] 标注哪些 synthetic 产物仅用于 baseline、unit test 或 augmentation。
- [x] 活动导航和 package API 不再暗示其为首选 source runtime。
- [x] runtime-observed 路径不反向依赖 archive namespace。
- [x] 相关定向测试、mainline、全量测试与 `git diff --check` 通过。

## 结果

- 新建 [`pycodeagent.baselines`](../../../pycodeagent/baselines/__init__.py) 作为
  synthetic canonical-intent、trajectory-derived extraction 和 synthetic
  split/profile planning 的唯一公共 route namespace。
- 从宽泛的 `pycodeagent.rl` aggregate API 删除 9 个 baseline exports；当前仓库
  没有该聚合路径的调用方。底层 `pycodeagent.rl.schema_following_*` 文件暂作为
  compatibility implementation 保留，避免把路线隔离扩大成无关的物理搬迁。
- `generate_schema_following_data.py` 和专属 synthetic eval/SFT tests 改从
  `pycodeagent.baselines` import；CLI description/help 明确称其为 controlled
  baseline，不再暗示它是通用或首选 source-data 入口。
- synthetic 与 trajectory-derived `dataset_manifest.json` 增加
  `route_role = controlled_baseline` 和 `artifact_owner = pycodeagent.baselines`；
  trajectory `source_manifest.json` 同步记录所有权。
- route boundary 文档明确允许用途：deterministic unit/contract tests、受控对照、
  显式标注的 augmentation，以及受保护的 phase-one synthetic mock contract；明确
  禁止把它们当作 runtime realism、model-visible request capture 或 provider 证据。
- architecture gate 实际生成 synthetic bundle 和空 trajectory-derived bundle，
  校验 manifest ownership；同时 AST 检查 runtime-observed mainline 不 import
  `pycodeagent.baselines` 或 `pycodeagent.auxiliary`。
- 与 RC-029 联合验收：路线专项 `34 passed, 1 skipped`；docs/route 门禁
  `15 passed`；mainline `57 passed, 3 deselected`；全量
  `968 passed, 77 skipped`；native-family acceptance `stabilized=True`；
  taxonomy `91 documents, 36 inventory entries, 247 local links`；
  `git diff --check` 通过。

## 决策记录

- 2026-07-14：隔离而非删除，以保留对照实验和 phase-one 合同价值。
- 2026-07-17：这里的 `archive` action 表示从主线暴露面隔离，不表示删除代码或
  把 phase-one mock 文档移入历史 archive；后者仍是当前 synthetic-first 合同。
- 2026-07-17：保留原模块路径作为 implementation compatibility，但新调用方和
  文档只使用 `pycodeagent.baselines`；未来机械移动不应改变生成确定性。
- 2026-07-17：runtime-observed exporter 不接受 controlled-baseline manifest 作为
  source runtime 证据，依赖方向由 mainline architecture gate 持续约束。
