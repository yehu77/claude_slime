---
schema: repository-cleanup-goal/v1
id: RC-027
title: 归档阶段性根入口
status: done
batch: B
action: archive
priority: P1
risk: medium
size: M
depends_on: [RC-025]
source_audit: docs/repository_asset_audit.md
source_sections: ["6.2 阶段性根入口", "11.3 ARCHIVE"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-027：归档阶段性根入口

## 目标

将只服务旧 study 阶段的根级脚本与其路线一起退出活动入口集合。

## 范围

- 包含：RC-025 确认的阶段性 wrappers、调用文档和专属测试。
- 保护：仍被 current runtime、acceptance 或正式 CLI 迁移计划使用的入口。

## 工作项与验收

- [x] 每个入口标注唯一消费者、替代入口和处置。
- [x] 归档/删除后根目录帮助文档与调用示例无悬空路径。
- [x] 活动入口 smoke tests、mainline 与 local acceptance 通过。
- [x] 全量测试和 `git diff --check` 通过。

## 结果

Done；六个阶段性根入口与 `tests/test_mimo_entrypoints.py` 已随旧路线移入
只读 archive。`tests/test_root_cli.py` 仅移除旧 schema-following wrapper
用例；Mimo example 保留连接字段但去掉 study/output 默认值；local config
README 删除两个旧命令并指向活动 provider smoke、behavior baseline、
credibility bundle 与 ToolView generation 入口。

底层 compaction verifier、auxiliary schema-following SFT module、共享 Mimo
client 和所有活动 native-family/provider 入口均保留。归档条目纳入 RC-026
共用的 29 文件 SHA-256 manifest，活动树没有未分类反向依赖或悬空调用示例。

验收结果：

- archive/cleanup/task-pack/CLI/docs 专项：`69 passed`；
- offline mainline：`153 passed, 3 deselected`；
- local-only native-family acceptance：`stabilized=True`、
  `native_codex_tasks=3`、`generation_smokes=2`；
- 全量测试：`930 passed, 21 skipped`；
- 活动旧入口引用扫描仅剩 governance/negative guards；RC-057 随后删除
  `eval/tables.py`，安装态 legacy-study 依赖边现为 0；
- `git diff --check`：通过。

real-provider acceptance 记为 N/A：未调用真实 provider，且保留的活动 provider
入口和底层连接合同未发生行为变更。

## 决策记录

- 2026-07-14：入口必须随依赖闭包处置，不能只删 wrapper 留隐式路线。
- 2026-07-18：RC-024 决定入口随旧路线归档，不删除底层共享 Mimo client。
- 2026-07-18：RC-025 完成，精确入口消费者和共享编辑边界已冻结，本目标解锁。
- 2026-07-18：与 RC-026 原子完成归档；补录并清理
  `configs/local/README.md` 中两个此前漏记的旧入口引用。
