---
schema: repository-cleanup-goal/v1
id: RC-031
title: 收窄 rl/eval 公共导出
status: done
batch: B
action: merge
priority: P1
risk: high
size: M
depends_on: [RC-026, RC-028, RC-030]
source_audit: docs/repository_asset_audit.md
source_sections: ["5.7 包级全量 re-export", "16. 目标仓库形态"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-031：收窄 rl/eval 公共导出

## 目标

让 `pycodeagent.rl`、`pycodeagent.eval` 等 package 只导出仍属于活动合同的最小 API。

## 范围

- 包含：`__init__.py` re-exports、`__all__`、仓内 imports 和兼容策略。
- 保护：serializer/loss-mask/training-prep 等明确公共合同；先复核仓外 import 风险。

## 工作项与验收

- [x] 生成当前导出与仓内/仓外已知消费者矩阵。
- [x] 删除 archive/auxiliary 的默认暴露，必要时提供定期移除的 compatibility shim。
- [x] 增加 public API contract test，禁止重新扩张。
- [x] import smoke、mainline、全量测试和 `git diff --check` 通过。

## 结果

Done。machine-readable symbol/owner/consumer matrix 已冻结在
[`package_public_api_contract.json`](../package_public_api_contract.json)。

`pycodeagent.rl` 现在只导出 25 个跨路线稳定训练数据合同，范围严格限制为：

- PreparedSample schema/read/write；
- trajectory/schema-following serializer；
- loss-mask；
- RC-042 唯一 TrainingBundleBuilder 与 manifest verifier；
- 三条 training-prep 入口和 recommendation models。

tokenizer、packing、dataset builder、slime bridge、schema-following eval/SFT
等操作性 helper 必须从 owner 子模块导入。`pycodeagent.eval` 只保留 4 个活动
runtime campaign 入口：native-family acceptance、real-provider behavior
baseline、credibility bundle 和 ToolView mutation generation。legacy study、
table builders、内部 audit/result models 均不再从 package root 暴露。

唯一 RL 聚合消费者 `tests/test_slime_bridge.py` 和两个 eval 聚合消费者
provider wrappers 已迁移到明确子模块。仓内 aggregate consumer 数量现在为 0。
未增加 compatibility shim：仓库没有可验证的仓外消费者或已声明的稳定发行
合同，owner 子模块路径仍保留，而继续保留宽 alias 会直接破坏本目标的边界。

新增 `tests/test_package_public_api.py` 并接入 CI/mainline，硬性验证：

- `__all__` 与 tracked contract 精确一致且无重复；
- 每个 symbol 只有一个存在的 owner module；
- `from package import *` 成功；
- forbidden broad/legacy symbols 不泄漏；
- facade 只能 import 声明的 owner modules；
- 活动仓内代码不得 aggregate-import package root。

验收结果：

- public API/route/slime bridge 专项：`28 passed`；
- serializer/mask/prepared/bundle/prep/eval 扩展回归：
  `137 passed, 1 skipped`；
- offline mainline：`160 passed, 3 deselected`；
- local-only native-family acceptance：`stabilized=True`、
  `native_codex_tasks=3`、`generation_smokes=2`；
- 全量测试：`937 passed, 21 skipped`；
- `git diff --check`：通过。

real-provider acceptance 记为 N/A：本目标没有修改 provider transport、模型
请求、runtime 执行或 campaign 行为，只改变 Python import facade。

## 决策记录

- 2026-07-14：等待旧路线隔离完成后再收口，避免制造循环迁移。
- 2026-07-18：RC-026/027 完成 legacy study 归档，本目标全部依赖满足。
- 2026-07-18：选择小型稳定 facade；仓内消费者全部直连 owner submodule，
  不为未知仓外消费者保留无期限 shim。
