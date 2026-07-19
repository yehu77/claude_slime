---
schema: repository-cleanup-goal/v1
id: RC-056
title: 退出 toy minimal train loop
status: done
batch: C
action: delete
priority: P2
risk: medium
size: M
depends_on: [RC-039]
source_audit: docs/repository_asset_audit.md
source_sections: ["10. DELETE?：代码级高置信候选"]
created: 2026-07-17
updated: 2026-07-17
completed: 2026-07-17
---

# RC-056：退出 toy minimal train loop

## 目标

删除与实际 slime 训练边界无关的 ToyModel/minimal supervised loop，使仓库不再把
测试模型表现成正式训练入口。

## 范围

- 包含：`pycodeagent/rl/train_loop.py`、`tests/test_train_loop.py` 及
  `pycodeagent.rl` 对应 re-export。
- 保护：`TrainConfig`、`TrainDataset`、serializer/loss-mask/training-prep 和
  slime bridge 合同。

## 前置条件

- [x] RC-039 已冻结 disposition 和替代路径。
- [x] 仓内消费者仅为专属测试和 package re-export。
- [x] 删除前再次复核已知仓外 import 风险。

## 工作项与验收

- [x] 删除 module、专属 tests 和 package re-export。
- [x] 文档与 CLI 不再暗示仓库自带正式 minimal training entrypoint。
- [x] training-prep/slime 定向测试、mainline、全量和 `git diff --check` 通过。

## 结果

已删除 `pycodeagent/rl/train_loop.py`（479 行）、专属
`tests/test_train_loop.py`（544 行）及 `pycodeagent.rl` 中的六个符号 re-export：
`ToyModel`、`TrainMetrics`、`TrainResult`、`EmptyTrainingDatasetError`、
`run_training` 和 `compute_masked_cross_entropy_loss`。

仓库静态/动态 import、docs、CLI 与 packaging entrypoint 复核未发现其他消费者；
`pycodeagent.rl` 的模块说明也已改为 training-bundle handoff，不再声称提供 minimal
training entrypoint。RC-039 的机器清单已升级为 v2，区分决策时消费者与当前消费
者，并将本项标记为 `retired`。

受保护的 `TrainConfig`、`TrainDataset`、serializer、loss-mask、packing、
training-prep、rollout 和 slime bridge 均保持可导入。定向验收为
`222 passed, 4 skipped`；mainline `82 passed, 3 deselected`；local-only
native-family acceptance `stabilized=True`；全量 `977 passed, 77 skipped`；
`git diff --check` 通过。

## 决策记录

- 2026-07-17：RC-039 判定其合同价值仅限 ToyModel 测试；实际训练出口是 slime，
  不应继续维持第二套训练表象。
- 2026-07-17：不提供 compatibility shim；仓库没有真实消费者，保留 shim 只会
  延续错误的正式训练 API 表象。
