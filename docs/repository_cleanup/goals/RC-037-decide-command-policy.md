---
schema: repository-cleanup-goal/v1
id: RC-037
title: 决定旧 command policy 去向
status: done
batch: C
action: decide
priority: P1
risk: medium
size: S
depends_on: []
source_audit: docs/repository_asset_audit.md
source_sections: ["5.3 `command_safety.py` 大部分失活", "17. 当前决策边界"]
created: 2026-07-14
updated: 2026-07-19
completed: 2026-07-19
---

# RC-037：决定旧 command policy 去向

## 目标

确定旧 command-safety policy 应作为未来 S5 权限策略的基础，还是作为失活路线删除。

## 范围

- 包含：policy 类型、parser/checker、调用现状和未来 sandbox/approval 合同的适配评估。
- 保护：当前实际命令执行安全边界；不得因删除死代码而放宽 runtime 权限。

## 阻塞条件

- [x] 决定 S5 权限子系统是否采用当前 policy 数据模型/语义。
- [x] 若不采用，明确当前活动调用方为零并授权后续移除。

## 工作项与验收

- [x] 形成 keep-and-activate 或 delete 的短决策记录。
- [x] 将选择同步到 RC-038 的实施范围和验收。

## 结果

Done。决定采用 `delete_legacy_implementation`：RC-038 删除旧
`pycodeagent/tools/command_safety.py`，S5 不复用其数据模型、allowlist 或
subprocess 实现。

审计确认模块中只有 `normalize_workdir` 仍被 `shell_runtimes.py` 调用，而且它
只是 `path_policy.validate_cwd` 的薄转发。旧 executable allow/deny lists、
`CommandPolicyDecision`、`classify_command_argv`、旧
`CommandExecutionResult`、metadata builder、subprocess executor 和 renderer
均无活动调用方，也没有直接测试。RC-038 将先把该唯一调用改为直接使用
`validate_cwd`，再删除整个模块。

不选择 keep-and-activate 的原因不是“当前没人调用”，而是旧语义与 S5 不兼容：
它只有 `allow/deny` 两态、面向 argv、无法解释当前 runtime 执行的 shell string
与复合命令、没有 matched-rule/provenance，也无法区分 model 请求的
sandbox/permission 字段和真正生效的策略决定。直接激活还会拒绝当前真实任务
常见的 Python/npm 等命令，造成未声明的 source-run 行为变化。

未来 S5 应参考锁定的 `codex-rs/execpolicy` 与
`codex-rs/shell-command` 分解重新建立三态、规则证据和 trace-visible 合同，
但不建设 approval UX 或 production sandbox。完整机器决策见
[`command_policy_decision.json`](../command_policy_decision.json)。

决策/docs/codex-reference 专项为 `30 passed`；锁定的 codex-rs reference 为
`status=ok`、4477 个条目且 checksum 一致；offline mainline 为
`188 passed, 3 deselected`；全量为 `960 passed, 21 skipped`；
`git diff --check` 通过。RC-037 不改 runtime、provider、tool schema 或执行
行为，因此 local/real-provider acceptance 记为 N/A；行为实施验收由 RC-038
负责。

## 决策记录

- 2026-07-14：安全相关代码不以“当前没调用”作为唯一删除依据。
- 2026-07-19：对照锁定的 codex-rs reference 后确认旧两态 argv allowlist 不是
  S5 可接受的基础；S5 保留设计目标，不保留错误实现。
- 2026-07-19：workspace cwd、protected write、process execution 和 execution
  metadata 的当前 owner 分别保持为 `path_policy.py`、`path_policy.py`、
  `process_exec.py + shell_runtimes.py` 和 `execution_contract.py`。
