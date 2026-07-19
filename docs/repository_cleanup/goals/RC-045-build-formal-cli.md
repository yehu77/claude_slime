---
schema: repository-cleanup-goal/v1
id: RC-045
title: 建立正式 subcommand CLI
status: done
batch: D
action: merge
priority: P1
risk: high
size: L
depends_on: [RC-031, RC-042, RC-044]
source_audit: docs/repository_asset_audit.md
source_sections: ["5.6 根目录 CLI 重复", "11.1 KEEP，但当前需要修复或并入统一 CLI"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-045：建立正式 subcommand CLI

## 目标

提供一个薄、稳定的正式 CLI，将 run、campaign、export/prep、verify 和 acceptance 映射到现有合同层。

## 范围

- 包含：subcommands、config/argument precedence、exit codes、machine-readable output 和兼容入口计划。
- 保护：CLI 不承载业务逻辑，不以产品化 UX 扩张为目标。

## 工作项与验收

- [x] 冻结命令树和 config→CLI override 规则。
- [x] 每个 subcommand 调用单一 application service/builder，错误码可测试。
- [x] 输出 manifest 含 task/profile/family/version/status 等必需字段。
- [x] CLI smoke/golden、mainline、local acceptance、全量测试和 `git diff --check` 通过。

## 结果

Done。新增正式入口 `python -B -m pycodeagent`，冻结六个 subcommands：
`run`、`campaign`、`export`、`prep`、`verify`、`acceptance`。解析与分派位于
`pycodeagent.cli`；六个命令各调用 `pycodeagent.application.cli_services` 中的
一个 application service。CLI 不实现 runtime loop、campaign、export、
training-prep 或 verifier 业务规则，也不导入 baseline/auxiliary/archive 路线。

新增 version 1 config 合同 `pycodeagent-cli-config/v1`，优先级固定为
`built-in defaults < config.arguments < explicit CLI options`。config command
必须匹配已选择 subcommand，未知字段、类型/枚举错误、缺少必需参数和未显式选择
tokenizer 都在 dispatch 前失败。provider config 只保存非秘密设置，凭据仍由
`api_key_env` 指向的环境变量提供。

成功和 contract failure 在 stdout 输出 `pycodeagent-cli-result/v1`；错误在
stderr 输出 `pycodeagent-cli-error/v1`。退出码冻结为：0 成功、1 contract/gate
失败、2 usage/config、3 input、4 application/provider/runtime、130 interruption。
每个 service 在实际输出根写 `pycodeagent_cli_manifest.json`
（`pycodeagent-cli-manifest/v1`），固定保存 version、status、task IDs、profile
mode/seed、family scope、result type、owned application manifest 路径和结构化
结果。

正式合同与根 wrapper 替代映射见
[`docs/formal_cli.md`](../../formal_cli.md)；示例 config 为
`configs/local/pycodeagent_cli.acceptance.example.json`。RC-045 保留旧 root
wrappers 作为兼容面，删除或 deprecation shim 处置由 RC-046 完成。

CLI/docs/route 专项为 `52 passed`；offline mainline 为
`183 passed, 3 deselected`；通过正式 CLI 运行的 local acceptance 返回
`exit_code=0`、`stabilized=true` 并生成共同 manifest；全量为
`960 passed, 21 skipped`；`py_compile` 和 `git diff --check` 通过。

## 决策记录

- 2026-07-14：正式 CLI 放在编排统一之后，避免把重复内部实现固化成公共接口。
- 2026-07-18：全部依赖完成，本目标解除依赖、转为 ready。
- 2026-07-18：正式公共树只包含六个主线合同命令；dev、vendor、runs lifecycle、
  baseline 和 auxiliary 入口不因 CLI 统一而被隐式提升为主线。
- 2026-07-18：fake tokenizer 必须显式选择；CLI 输出 manifest 指向而不替代
  trajectory/campaign/training/verification/acceptance 的 owned manifests。
- 2026-07-18：兼容 wrappers 与正式 CLI 的拆除切换分离，RC-046 解锁。
