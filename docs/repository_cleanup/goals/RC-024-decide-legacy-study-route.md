---
schema: repository-cleanup-goal/v1
id: RC-024
title: 决定旧 study/toy 路线去向
status: done
batch: B
action: decide
priority: P0
risk: medium
size: S
depends_on: []
source_audit: docs/repository_asset_audit.md
source_sections: ["6.1 旧 study/eval 编排簇", "17. 当前决策边界"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-024：决定旧 study/toy 路线去向

## 目标

确定旧 study/eval/toy 路线应归档保留、外移，还是在证据备份后删除。

## 范围

- 包含：审计列出的 study modules、toy configs、专属 tests、fixtures 和根入口的研究价值判断。
- 保护：任何可能仍有个人实验价值的结果或配置，在用户决定前不删除。

## 阻塞条件

- [x] 用户确认该路线仅需历史参考，不再作为活动主线或兼容当前 runtime。
- [x] 选择完整只读归档，不授权删除，因此不触发外部备份删除门槛。

## 工作项与验收

- [x] 记录选项、理由、候选资产闭包和后续目标状态。
- [x] 决策同步到 RC-025、RC-026、RC-027、RC-043。

## 结果

项目所有者已选择 `archive_read_only_historical_reference`：

- 旧 study/eval/toy 路线只保留历史研究参考，不再是活动 mainline。
- 不要求它继续兼容当前 native-family runtime，也不把旧的 generic tool、
  `<|tool|>` 文本协议或偶然 resume/report 行为迁入新 campaign 合同。
- 保留完整代码、配置、task、测试和入口证据，但归档后必须退出活动 package、
  默认 pytest discovery、CLI 帮助和当前文档操作路径。
- 本目标不授权删除。RC-025 负责冻结精确依赖闭包并选择仓库内、活动命名空间
  之外的只读归档位置；在此之前不移动任何候选资产。

机器可读的候选边界和保护清单记录在
[`legacy_study_route_decision.json`](../legacy_study_route_decision.json)。
它覆盖：

- 10 个旧 `pycodeagent.eval` 编排/分析/report 模块；
- 2 个 study configs 和 `datasets/tasks/toy_tasks.jsonl`；
- 9 个 study 专属测试；
- 6 个阶段性根入口及 4 个已知入口测试；
- `eval/tables.py` 的单独 RC-057 所有权；
- Mimo client、realistic task pack、runtime-observed 主线、共享
  serializer/loss-mask/training-prep 和活动 acceptance/provider 入口的保护边界。

RC-025 与 RC-043 已解锁为 `ready`；RC-026、RC-027 继续等待 RC-025 的精确
闭包。RC-025 随后已完成并将 RC-026、RC-027 解锁为 `ready`，精确闭包见
[`legacy_study_archive_boundary.json`](../legacy_study_archive_boundary.json)。
决策清单、cleanup ledger 与文档链接专项 `18 passed`；offline mainline
`150 passed, 3 deselected`；`git diff --check` 通过。本目标不改 runtime
代码或活动资产，因此 local/real-provider acceptance 和全量行为回归记为 N/A。

## 决策记录

- 2026-07-14：审计证据不足以替用户判断历史实验价值。
- 2026-07-18：用户接受“只读归档、退出主线”的建议；不授权删除，也不要求
  旧路线在当前环境中保持可执行。
