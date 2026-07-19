---
schema: repository-cleanup-goal/v1
id: RC-038
title: 删除旧 command_safety
status: done
batch: C
action: delete
priority: P1
risk: high
size: M
depends_on: [RC-037]
source_audit: docs/repository_asset_audit.md
source_sections: ["5.3 `command_safety.py` 大部分失活", "10. DELETE?：代码级高置信候选"]
created: 2026-07-14
updated: 2026-07-19
completed: 2026-07-19
---

# RC-038：删除旧 command_safety

## 目标

执行 RC-037 的删除决定，使旧 command policy 不再处于看似安全、实际未生效的
半活动状态，并为后续 S5 保留干净的合同边界。

## 范围

- 包含：`command_safety.py`、exports、tests、runtime integration 和文档声明。
- 保护：现行 command execution 行为只能在明确 contract/tests 下改变。

## 工作项与验收

- [x] 将 `shell_runtimes.py` 的唯一调用改为直接使用 `path_policy.validate_cwd`。
- [x] 删除 module，并证明无遗留 import、export、test 或活动文档误导。
- [x] 冻结 cwd workspace 拒绝、当前 command execution 和 execution metadata 行为。
- [x] 明确 requested sandbox/permission 字段不等于 effective policy enforcement。
- [x] mainline、local acceptance、安全定向测试、全量测试和 `git diff --check` 通过。

## 结果

Done。`shell_runtimes.py` 现在直接从 `path_policy.py` 导入并调用
`validate_cwd`，旧 `pycodeagent/tools/command_safety.py` 已完整删除。仓库内
不再存在该模块的 import 或 package export；旧 executable allow/deny lists、
两态 decision、重复 subprocess/result/renderer 和 metadata builder 均未迁入
其他模块。

新增 `tests/test_command_safety_retirement.py`，冻结以下边界：

- workspace 外 cwd 仍在 `validate_cwd` 阶段以 `workspace_escape` 拒绝；
- 当前 runtime 可继续执行 Python 等命令，不受已退役 allowlist 过滤；
- Codex `sandbox_permissions`、justification 和 prefix rule 仍只记录为
  `requested_*` metadata，不伪装成 effective sandbox enforcement；
- module 缺失和零残留 import 是持续门禁。

本目标没有新建 S5 policy engine，也没有改变 protected write owner、
process executor、ToolView schema 或 provider 行为。未来 S5 的三态与规则证据
要求继续由
[`command_policy_decision.json`](../command_policy_decision.json) 约束。

安全/runtime/docs 专项为 `58 passed`；offline mainline 为
`193 passed, 3 deselected`；正式 CLI local acceptance 返回 `exit_code=0`、
`stabilized=true`；全量为 `965 passed, 21 skipped`；零遗留 import 静态检查、
文档链接完整性和 `git diff --check` 通过。真实 provider acceptance 记为
N/A，因为本目标保持 provider transport、ToolView 和命令执行语义不变。

## 决策记录

- 2026-07-14：一个目标只允许最终存在“已删除”或“已执行”两种可观察状态。
- 2026-07-19：RC-037 选择删除；本目标 action 从 `merge` 收窄为 `delete`。
- 2026-07-19：requested permission metadata 保持为观测事实；在真正的 S5
  evaluator 存在前，不将其解释为审批或 sandbox 已生效。
