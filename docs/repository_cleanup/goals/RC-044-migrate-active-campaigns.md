---
schema: repository-cleanup-goal/v1
id: RC-044
title: 迁移 active campaigns 并删重复循环
status: done
batch: D
action: merge
priority: P1
risk: high
size: L
depends_on: [RC-043]
source_audit: docs/repository_asset_audit.md
source_sections: ["5.5 Eval/campaign 重复", "14. 建议的安全清理顺序"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-044：迁移 active campaigns 并删重复循环

## 目标

把仍服务主线的 experiments/studies 迁到 RunCampaign，并删除各自复制的循环与汇总逻辑。

## 范围

- 包含：经 RC-024/RC-043 判定为 active 的 campaign entrypoints、configs、tests 和 result manifests。
- 保护：不同研究问题的指标逻辑可作为插件/observer 保留，不塞进核心 runner。

## 工作项与验收

- [x] 建立旧 campaign 到新 spec 的逐字段迁移表。
- [x] 对固定 fake-client corpus 比较 run 数、顺序、status/reward 和 artifact paths。
- [x] 删除重复 orchestration，只保留研究特定分析层。
- [x] campaign regression、mainline、local acceptance、全量测试和 `git diff --check` 通过。

## 结果

Done。`real_provider_behavior_baseline`、`real_provider_credibility_bundle`
和 `toolview_mutation_data_generation` 三个活动入口已迁到
`execute_profile_run_campaigns()`，其每个 paired ToolView mode/seed 都由标准
version 1 `RunCampaign` 执行。这样保留原 `profile_seed_by_mode` 一一对应关系，
不会错误展开成 mode×seed 笛卡尔积。

三个模块原有的 task×mode×repeat 私有循环已删除；credibility 和 mutation 中
会先 `shutil.rmtree()` 再重跑的 source-run 编排也已删除。behavior audit、
credibility/reconciliation gates、mutation observed export 和 training prep
继续留在原 owning module，未塞入核心 runner。mutation 唯一保留的
`run_coding_task()` 调用只是研究特定 exact-profile executor。

新增确定性的 `profile_campaign_group_spec.json` 和
`profile_campaign_group_manifest.json`，并把 group contract 路径与状态写入
三个结果/manifest。batch discovery 对新布局只跟随 terminal
`campaign_run_record.json` 的 artifact path，排除部分中断 attempt，同时继续
只读兼容历史 direct-run 输入。若输出根已有 legacy direct runs，则硬失败并要求
使用新根，不删除或混合旧证据。

逐字段映射、顺序变化和 artifact path 映射见
[`docs/run_campaign_contract.md`](../../run_campaign_contract.md)。固定 fake-client
回归覆盖 paired mode/seed、run 数、canonical 顺序、status/reward、artifact
存在性和零 client 调用续跑；静态门禁防止三个模块恢复私有循环或 destructive
`rmtree`。

专项回归为 `50 passed`；offline mainline 为
`173 passed, 3 deselected`；local native-family acceptance 为
`stabilized=True`；全量为 `950 passed, 21 skipped`；`py_compile` 和
`git diff --check` 通过。

## 决策记录

- 2026-07-14：只迁移活动 campaigns，archive 路线不作为新核心的兼容负担。
- 2026-07-18：RC-043 完成并通过仓库门禁，本目标解除依赖、转为 ready。
- 2026-07-18：mode-specific seed 用一组标准 child campaigns 表达，不修改
  RC-043 的单矩阵笛卡尔积语义。
- 2026-07-18：新 campaign 布局通过 terminal record 接入既有 audit/export；
  partial attempt 不成为训练或评估输入，legacy direct-run 仅保留只读发现能力。
- 2026-07-18：三个活动入口完成迁移，RC-045 可在统一编排层之上建立正式 CLI。
