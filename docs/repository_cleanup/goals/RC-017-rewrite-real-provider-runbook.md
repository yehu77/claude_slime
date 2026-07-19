---
schema: repository-cleanup-goal/v1
id: RC-017
title: 重写 real-provider runtime runbook
status: done
batch: B
action: repair
priority: P1
risk: medium
size: M
depends_on: [RC-014, RC-023]
source_audit: docs/repository_asset_audit.md
source_sections: ["7.2 KEEP，但必须重写", "13.3 Native-family acceptance"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-017：重写 real-provider runtime runbook

## 目标

让 real-provider runbook 准确描述显式 family 选择、凭据、产物、失败诊断和离线/在线边界。

## 范围

- 包含：最小可复制命令、环境要求、输出目录、敏感数据提醒和 acceptance 解释。
- 保护：真实 provider run 只作为 acceptance/regression，不重新定义架构主线。

## 工作项与验收

- [x] 在 RC-023 修复后的真实 CLI/函数签名上逐条执行文档命令。
- [x] 明确 local-only、provider-backed 和禁止提交的 artifact。
- [x] 新环境按 runbook 可得到预期 manifest 或可解释失败。
- [x] 链接检查、命令 smoke test 与 `git diff --check` 通过。

## 结果

- 将 [`real_provider_runtime_usage.md`](../../real_provider_runtime_usage.md)
  整体重写为 native-family 操作手册，明确 provider transport 与 model-visible
  tool family 是两个独立选择；四个 checked-in provider wrappers 当前都显式选择
  `native_claude`，不从 provider、model、task metadata 或工具名推断。
- 当前操作顺序收敛为五条：single-run smoke、repeated behavior baseline、ToolView
  mutation generation、repeated credibility bundle，以及小型 provider-backed
  native-family acceptance。旧 `run_first_study_real_provider.py` / generic study
  示例不再作为 realistic provider 主路径。
- 每条命令均记录前置条件、固定 family、输入 task pack、profile modes/repeats、
  输出根目录和首要检查产物；programmatic 示例补齐必填
  `tool_stack_kind="native_claude"`。
- 配置章节与当前 `RuntimeProviderConfig` 对齐：仅支持 `mimo_native_tools` 和
  `openai_native_tools`，说明 defaults → local JSON → env 的优先级、dotenv
  搜索顺序、`api_key_env` 与禁止 inline key 的规则。
- 失败诊断给出无 model、无 API key、HTTP/provider、schema/tool-call、verifier、
  reconciliation 和 bundle gate 的分层检查顺序；未知/旧 client mode 会显式失败，
  不回退到 text parser 或另一 tool family。
- 明确 local-only acceptance 不证明网络行为，provider-backed run 也不证明 provider
  parity、production sandbox、benchmark quality 或训练收益。
- 明确 `.env`、`*.local.json`、`runs/`、provider responses、tool arguments/results、
  diffs、request context 和 retained history 的敏感性与禁止提交边界。
- 文档门禁逐项核对四个 wrapper 文件、`_TOOL_STACK_KIND`、调用参数、五条命令、
  配置错误、manifest/summary 名称、敏感数据说明和非声明边界，并禁止旧 generic
  tool/study 文本回流。
- 命令验证：四个 provider wrapper 的 `main()` 通过注入式 command smoke 执行，
  provider resolver 的成功/缺 model/缺 key/非法 mode 路径由专项测试执行；未使用
  本机凭据或发真实网络请求。runbook 中的 local-only 命令按原样执行并得到
  `stabilized=True` 和预期 report。
- 验收：runbook/config/consumer 专项 `24 passed`；mainline
  `51 passed, 3 deselected`；全量 `962 passed, 77 skipped`；taxonomy
  `90 documents, 35 inventory entries, 236 local links`；`git diff --check`
  通过。

## 决策记录

- 2026-07-14：等待 consumer family 选择修复，避免文档固化错误接口。
- 2026-07-17：不为验证文档擅自消耗 provider 配额或读取本机真实凭据；在线命令
  通过同一 `main()` 的注入式 smoke 固定参数合同，真实网络运行仍由操作者按
  runbook 显式启动。
- 2026-07-17：移除旧 study 操作段，而不是宣称 study 代码已删除；legacy
  study/toy 路线的最终处置仍由 RC-024 及其依赖目标决定。
- 2026-07-17：保留内部 API 的 `native_codex` 能力，但 checked-in
  OpenAI-compatible provider wrappers 不包装或降级 freeform Codex
  `apply_patch`。
