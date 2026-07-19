---
schema: repository-cleanup-goal/v1
id: RC-002
title: 删除孤立 buggy_reverser
status: done
batch: A
action: delete
priority: P1
risk: low
size: S
depends_on: [RC-001]
source_audit: docs/repository_asset_audit.md
source_sections: ["9.2 DELETE?", "15. 第一批高置信候选"]
created: 2026-07-14
updated: 2026-07-14
completed: 2026-07-14
---

# RC-002：删除孤立 buggy_reverser

## 目标

删除与主线、测试发现和文档均无关联的示例目录。

## 范围

- 包含：`examples/buggy_reverser/reverser.py` 与其局部测试。
- 保护：其他 task workspace、task pack 和 acceptance 示例。

## 工作项与验收

- [x] 静态引用与测试发现复核为零。
- [x] 两个 tracked 文件已删除，忽略缓存不作为仓库资产保留。
- [x] mainline、toy、local acceptance 与全量测试均通过。
- [x] `git diff --check` 通过。

## 结果

孤立示例已从活动工作树删除，不影响可执行研究路径。

## 决策记录

- 2026-07-14：按高置信删除候选实施并标记完成。
