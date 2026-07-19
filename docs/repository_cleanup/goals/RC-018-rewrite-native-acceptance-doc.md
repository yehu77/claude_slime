---
schema: repository-cleanup-goal/v1
id: RC-018
title: 重写 native-family acceptance 文档
status: done
batch: A
action: repair
priority: P1
risk: low
size: S
depends_on: [RC-001]
source_audit: docs/repository_asset_audit.md
source_sections: ["7.2 KEEP，但必须重写", "13.3 Native-family acceptance"]
created: 2026-07-14
updated: 2026-07-15
completed: 2026-07-15
---

# RC-018：重写 native-family acceptance 文档

## 目标

使 acceptance 文档与当前 local-only 聚合规则、required families 和失败列表完全一致。

## 范围

- 包含：入口命令、输出字段、`stabilized` 判定和 CI/手工运行分界。
- 保护：不把网络 provider 测试伪装成默认离线保证。

## 工作项与验收

- [x] 从当前 runner、CLI 和测试重建命令、聚合组件、报告字段及网络边界，删除 8 个失效测试引用。
- [x] 文档示例与新 local-only 输出吻合：2 个 regression commands、0 个 real-provider tasks、3 个 Codex tasks、2 个 generation smokes。
- [x] 明确 runner 没有 `required-families` CLI 参数；两 family 的固定必需表面、required-tool 失败和 `stabilized` 聚合均已记录。
- [x] 移除五组 legacy fixture 的 acceptance ownership 声明，改为在线生成 artifact 边界。
- [x] acceptance 定向测试、mainline `15 passed`、local-only `stabilized=True`、全量 `924 passed, 77 skipped` 和 `git diff --check` 通过。

## 结果

活动文档现在直接描述 `run_native_family_acceptance.py` 和 `native_family_acceptance.py` 的当前行为：local-only 是离线门禁，real-provider 是显式附加层；自动化必须检查 JSON/打印出的 `stabilized`，不能只看 CLI 退出码。

文档不再把已失活的 legacy runtime-observed fixtures 当成 golden 真源，当前 acceptance artifact 均在唯一输出根下动态生成。

## 决策记录

- 2026-07-14：将剩余工作收窄为文档真值同步。
- 2026-07-15：确认实现不存在独立 required-family 参数，改为记录固定 Claude/Codex 表面和 required-tool 失败语义。
- 2026-07-15：文档、local-only 输出和当前 mainline runner 逐项对齐，全部门禁通过后置为 `done`。
