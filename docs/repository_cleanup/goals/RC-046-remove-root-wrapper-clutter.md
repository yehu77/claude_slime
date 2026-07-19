---
schema: repository-cleanup-goal/v1
id: RC-046
title: 移除被正式 CLI 取代的根 wrappers
status: done
batch: D
action: delete
priority: P2
risk: medium
size: M
depends_on: [RC-045]
source_audit: docs/repository_asset_audit.md
source_sections: ["5.6 根目录 CLI 重复", "11.2 MERGE", "11.3 ARCHIVE"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-046：移除被正式 CLI 取代的根 wrappers

## 目标

删除或变成明确兼容 shim 的根级 Python wrappers，使正式 CLI 成为唯一活动入口面。

## 范围

- 包含：RC-045 有功能等价替代的 root wrappers、docs、tests 和 automation references。
- 保护：无正式 CLI 替代的 bootstrap/maintenance 脚本和外部调用兼容窗口。

## 工作项与验收

- [x] 为每个 wrapper 记录替代 subcommand、仓内/已知仓外消费者和处置。
- [x] 更新 automation/docs；兼容 shim 必须发出可测试 deprecation 并有移除期限。
- [x] 根目录不再出现多套同义 run/prep/verify 入口。
- [x] CLI smoke、mainline、local acceptance、全量测试和 `git diff --check` 通过。

## 结果

Done。新增
[`root_wrapper_disposition.json`](../root_wrapper_disposition.json)，逐项记录
RC-046 审计时 17 个根级 Python wrappers 的路线、仓内消费者、仓外消费者
未知状态、正式替代、处置和理由。

删除 7 个已经被正式 CLI 完整替代的入口：
`prepare_slime_training_data.py`、`verify_slime_contract.py`、
`run_native_family_acceptance.py`、`run_real_provider_behavior_baseline.py`、
`run_real_provider_credibility_bundle.py`、
`run_toolview_mutation_data_generation.py` 和
`run_runtime_smoke_real_provider.py`。其文档、tests、CI、slime bridge 使用说明
和历史保护清单均已迁移到 `python -B -m pycodeagent`。固定 provider smoke
先落为 `datasets/tasks/real_provider_smoke_tasks.jsonl` 中的具名任务，再由
正式 `run` 子命令接管，因此未丢失原任务身份。

其余 10 个入口没有等价 application service，明确保留为辅助
Claude/native-transformed 路线、受控 schema-following baseline、
compatibility gateway 或 external-agent raw-trace 路线；它们不构成主线
run/prep/verify 的第二套命令面。本目标未保留 compatibility shim，因此不存在
需要另设移除期限的 shim。

专项 wrapper/CLI/task/docs 门禁为 `75 passed`；offline mainline 为
`184 passed, 3 deselected`；slime overlay 校验为 `status=ok`、9 个 overlay、
474 个条目；正式 CLI local acceptance 返回 `exit_code=0`、
`stabilized=true`；全量为 `956 passed, 21 skipped`；`git diff --check`
通过。真实 provider acceptance 不在删除等价入口所需行为变化范围内，记为
N/A。

## 决策记录

- 2026-07-14：以正式 CLI 已验收为硬依赖，不提前删可用入口。
- 2026-07-18：RC-045 完成，本目标解除依赖、转为 ready。
- 2026-07-18：只有具备六命令正式等价面的 wrappers 才删除；无等价服务的
  辅助、baseline、gateway 和 external-agent 入口继续由路线边界保护。
- 2026-07-18：固定 provider smoke 先获得 task-pack 身份再退役 wrapper。
- 2026-07-18：仓内消费者已全部迁移；仓外消费者保持明确 `unknown`，不虚构
  兼容承诺，也不为未知消费者无限期保留重复主线入口。
