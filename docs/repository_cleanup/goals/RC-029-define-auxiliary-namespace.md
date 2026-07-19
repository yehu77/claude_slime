---
schema: repository-cleanup-goal/v1
id: RC-029
title: 定义 auxiliary namespace
status: done
batch: B
action: govern
priority: P1
risk: medium
size: M
depends_on: [RC-013]
source_audit: docs/repository_asset_audit.md
source_sections: ["6.4 Claude API/native-transformed 路线", "11.4 AUXILIARY"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-029：定义 auxiliary namespace

## 目标

为非主线但仍有研究价值的 ingestion/transform 路线定义稳定、低暴露的辅助命名空间。

## 范围

- 包含：namespace、import policy、CLI exposure、artifact ownership 和弃用规则。
- 保护：共享 canonical trace/serializer 合同；辅助路线不得重新定义仓库身份。

## 工作项与验收

- [x] 写出进入 auxiliary 的判据和公共 API 边界。
- [x] 定义从 auxiliary 向 mainline 复用 shared kernel 的单向依赖。
- [x] 增加 import-boundary 或 architecture test。
- [x] 文档链接、定向测试与 `git diff --check` 通过。

## 结果

- 新建低暴露 [`pycodeagent.auxiliary`](../../../pycodeagent/auxiliary/__init__.py)
  namespace；RC-029 阶段 `__all__` 为空，不提前制造稳定公共 API。
- [`auxiliary/policy.py`](../../../pycodeagent/auxiliary/policy.py) 提供 version 1
  机器可读注册表，登记 `claude_api_ingestion` 和 `native_transformed` 两条
  `migration_pending` 路线的模块、根 entrypoints、artifact prefixes 和 RC-030
  ownership。
- [`source_route_boundaries.md`](../../source_route_boundaries.md) 冻结 auxiliary
  进入判据、API/CLI 暴露、artifact ownership、弃用/晋升规则，以及
  `auxiliary -> shared kernel <- mainline` 的依赖方向。
- policy 明确列出可复用 shared-kernel prefixes；mainline 不得 import
  `pycodeagent.auxiliary`，auxiliary 不得重新定义 canonical trace、ToolView、
  serializer、mask 或 bundle 合同。
- Claude gateway、native-transformed SFT/RL 和旧 training architecture 文档增加
  auxiliary 横幅；docs taxonomy 将其更新为 `migration-pending RC-030`，不再显示
  为未决候选或主线材料。
- 新增 mainline architecture gate，验证注册资产存在、namespace 低暴露、
  auxiliary 依赖方向和当前 mainline 零反向 import；该 gate 已加入 CI、cleanup
  标准命令和 native-family acceptance regression。
- RC-029 只定义并执行治理边界，不移动现有 Claude API/native-transformed 文件；
  物理迁移由 RC-030 完成，广泛 legacy re-export 收窄由 RC-031 完成。
- 与 RC-028 联合验收：路线专项 `34 passed, 1 skipped`；docs/route 门禁
  `15 passed`；mainline `57 passed, 3 deselected`；全量
  `968 passed, 77 skipped`；native-family acceptance `stabilized=True`；
  taxonomy `91 documents, 36 inventory entries, 247 local links`；
  `git diff --check` 通过。

## 决策记录

- 2026-07-14：先定义边界，再迁移 gateway/native-transformed 代码。
- 2026-07-17：选择“空 package + machine-readable policy”作为 RC-029 落点；既让
  architecture gate 有稳定目标，又不在 RC-030 前建立半迁移 import facade。
- 2026-07-17：现有根 wrappers 标记为 transitional compatibility surfaces；不在
  RC-045 正式 CLI 前为 auxiliary 新增更多顶层命令。
- 2026-07-17：auxiliary 晋升 mainline 必须另立 ADR，并证明其改善 source-runtime
  realism、observed-data fidelity 或核心合同，历史使用量不构成晋升理由。
