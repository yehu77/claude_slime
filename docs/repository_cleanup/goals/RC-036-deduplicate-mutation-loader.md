---
schema: repository-cleanup-goal/v1
id: RC-036
title: 合并 mutation config loader
status: done
batch: C
action: merge
priority: P2
risk: low
size: S
depends_on: [RC-001]
source_audit: docs/repository_asset_audit.md
source_sections: ["5.8 其他重复", "4.1 Local runtime 与工具控制面"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-036：合并 mutation config loader

## 目标

让所有 ToolView mutation 路径使用同一个 versioned 配置 loader 和错误语义。

## 范围

- 包含：重复 YAML/JSON loader、defaults、schema validation 和 call sites。
- 保护：mutation seed、profile ID、tool order 和 exposed schema 的确定性。

## 工作项与验收

- [x] 比较重复 loader 的接受格式、默认值和错误行为。
- [x] 确立 canonical loader 并为配置 schema/version 建立测试。
- [x] 迁移调用方，删除重复 parser/default 逻辑。
- [x] mutation goldens、mainline、全量测试与 `git diff --check` 通过。

## 结果

审计确认 mutation config 在 `profile_loader.py`、sampler 私有 helper 和
`build_sampled_tool_profile` 内存在三处 YAML 解析，其中前两处格式/错误逻辑
等价，第三处还承担 profile/mutation 类型分流。现由
`profile_loader.load_config_mapping` 唯一解析 YAML/JSON mapping，
`load_mutation_config` 统一文件缺失、top-level 类型和 schema 错误语义；sampler
不再直接 import/调用 YAML parser。

mutation schema 冻结为 `mutation_config_version: 1`，两个 checked-in config 均已
声明。loader 校验 version、`profile_id_prefix`、`tool_variants`/`families` 及
family tool-variant mapping；采样 profile metadata 同步记录 config version。
新增 YAML/JSON 等价、missing/unknown version、non-mapping 和 missing-file 测试。
原 seed、profile ID、默认 mutation mode、tool order、variant selection 和
exposed schema 逻辑保持不变，现有确定性测试继续通过。

联合 mutation/tool-contract 定向回归包含在 `66 passed` 中；mainline
`60 passed, 3 deselected`；local acceptance `stabilized=True`；全量
`983 passed, 77 skipped`；`git diff --check` 通过。

## 决策记录

- 2026-07-14：将 loader 去重限定为保持 ToolView 可复现性的机械合并。
- 2026-07-17：采用 version 1 的统一 YAML/JSON mapping loader，删除 sampler
  重复解析点并通过全部门禁，状态置为 `done`。
