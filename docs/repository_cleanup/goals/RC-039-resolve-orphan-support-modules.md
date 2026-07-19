---
schema: repository-cleanup-goal/v1
id: RC-039
title: 决定 orphan support modules 去向
status: done
batch: C
action: decide
priority: P2
risk: medium
size: M
depends_on: []
source_audit: docs/repository_asset_audit.md
source_sections: ["10. DELETE?：代码级高置信候选", "17. 当前决策边界"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-039：决定 orphan support modules 去向

## 目标

逐个确认疑似孤立 support module 的真实消费者，并为后续原子处置冻结结论。

## 范围

- 包含：`rl/train_loop.py`、`rl/export.py`、`eval/tables.py`、`traces/render.py`。
- 保护：潜在仓外 imports 和未来 broader multi-agent scaffold 的明确接口价值。

## 工作项与验收

- [x] 搜索仓内静态/动态 imports、docs/CLI 使用和已知仓外依赖。
- [x] 每个 module 单独记录 owner、合同价值、替代路径和 disposition。
- [x] 需要改代码的 module 各自登记独立 child goal；无需改动的结论写明证据。
- [x] 决策矩阵覆盖率为 4/4，链接检查和 `git diff --check` 通过。

## 结果

4/4 决策已冻结在机器可校验的
[`orphan_support_modules.json`](../orphan_support_modules.json)：

| Module | Owner | 合同价值 / 替代路径 | Disposition |
| --- | --- | --- | --- |
| `rl/train_loop.py` | training-data-maintainers | 只有 ToyModel/minimal-loop 测试价值；正式训练路径为 training-prep → slime | `retired`，已由 [RC-056](./RC-056-retire-minimal-train-loop.md) 删除 |
| [`rl/export.py`](../../../pycodeagent/rl/export.py) | training-data-maintainers | 两组测试冻结 `SlimeRolloutRecord` 的确定性 JSON/JSONL I/O；无等价统一 writer | `keep`，RC-031 只复核 re-export，不删除模块 |
| `eval/tables.py` | evaluation-maintainers | 仅 package re-export，无 runtime/report/CLI/docs/test 消费；替代边界是活动 runtime reports 与未来 RC-043 | `retired`，已由 [RC-057](./RC-057-retire-legacy-eval-tables.md) 删除 |
| [`traces/render.py`](../../../pycodeagent/traces/render.py) | trace-contract-maintainers | 已被 multi-agent golden builder 消费并由 mainline golden 校验，实现长期 `AugmentationRenderer` 边界 | `keep`，审计中的 orphan 结论已失效 |

仓内扫描覆盖直接 imports、符号调用、`importlib`/`__import__` 字符串、docs、CLI
和 packaging entrypoint；未发现清单外消费者或已知仓外 integration。对 package-level
re-export 仍按兼容风险处理，未把“仓内未发现”写成“仓外绝对不存在”。

新增 mainline 清单门禁，强制覆盖精确 4 个模块、完整 owner/consumer/contract/
replacement/risk 字段，并要求每个 `retire` 决策有唯一 child goal。验收结果：
定向 `98 passed`；mainline `82 passed, 3 deselected`；local-only native-family
acceptance `stabilized=True`；全量 `1006 passed, 77 skipped`；
`git diff --check` 通过。

## 决策记录

- 2026-07-14：将多个疑似 orphan 合并为一次证据审计，但处置必须逐模块记录。
- 2026-07-17：`traces/render.py` 因 RC-012 后出现活动 golden consumer 改判
  `keep`；`rl/export.py` 因确定性 rollout artifact 合同改判 `keep`。
- 2026-07-17：`train_loop.py` 与 `eval/tables.py` 分别登记 RC-056、RC-057，
  本决策目标不混入删除实施。
- 2026-07-18：RC-057 在 RC-031 收窄公共 API 后删除 `eval/tables.py`，
  machine inventory 同步为 `retired`。
