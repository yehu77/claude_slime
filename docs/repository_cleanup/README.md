# Repository Cleanup Goal Ledger

本目录把 [`repository_asset_audit.md`](../repository_asset_audit.md) 的审计结论
转换成可执行、可依赖、可验收的目标。原审计是证据快照；本文件是唯一进度
索引；每个 goal 的 frontmatter 是状态真源。

## 当前快照

- 范围版本：`v2`，已锁定（RC-039 增补两个原子处置目标）
- 登记目标：58
- `done`：58
- `ready`：0
- `in_progress`：0
- `blocked`：0
- `backlog`：0
- `cancelled`：0
- 总完成率：`58 / 58 = 100%`
- 最近全量门禁：`973 passed, 21 skipped`
- 下一建议目标：清理台账 v2 已全部完成；后续实现回到
  `docs/codex_rs_subsystem_implementation_plan.md` 当前主线

这里的完成率衡量“已交付的独立结果”，不等价于耗时、代码行数或磁盘空间。
只有 `done` 计入完成数；`cancelled` 不进入分母。当前 v2 范围已覆盖审计中的
Batch A–E，因此可以发布总体百分比。

## 状态规则

```text
backlog -> ready -> in_progress -> done
                       |
                       v
                    blocked
```

- `backlog`：已登记，但尚未完成实施前复核。
- `ready`：依赖和实施前证据已满足，可以开始。
- `in_progress`：当前正在修改或验证。
- `blocked`：需要用户决定、外部备份或上游信息。
- `done`：目标结果已在当前工作树实现且必需验收通过；不要求已经 commit。
- `cancelled`：不再适用或被其他目标替代。

状态变化必须在同一个 diff 中同时更新 goal frontmatter 和本索引。ID 一经创建
永不复用；文件不按状态移动；完整命令日志不写入 goal。
`depends_on` 和索引中的 `Depends on` 只登记 `RC-xxx` 目标；用户决定、外部备份、
上游来源等非目标阻塞条件写在 goal 正文的“阻塞条件”中，不混入依赖图。

## 批次进度

| Batch | 范围 | Done | Total | Ready | Blocked | Progress |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Foundation | 清理安全门与进度制度 | 2 | 2 | 0 | 0 | 100% |
| A | 纯资产、fixture、docs | 18 | 18 | 0 | 0 | 100% |
| B | 路线与入口隔离 | 12 | 12 | 0 | 0 | 100% |
| C | 内部重复与死角 | 10 | 10 | 0 | 0 | 100% |
| D | 编排统一 | 7 | 7 | 0 | 0 | 100% |
| E | vendor、reference、runs | 9 | 9 | 0 | 0 | 100% |

## 目标索引

| ID | Goal | Batch | Action | Priority | Risk | Status | Depends on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [RC-000](./goals/RC-000-establish-cleanup-registry.md) | 建立 cleanup goal registry | foundation | guardrail | P0 | low | done | — |
| [RC-001](./goals/RC-001-establish-mainline-gates.md) | 建立离线 mainline 清理门禁 | foundation | guardrail | P0 | low | done | RC-000 |
| [RC-002](./goals/RC-002-delete-buggy-reverser.md) | 删除孤立 buggy_reverser | A | delete | P1 | low | done | RC-001 |
| [RC-003](./goals/RC-003-delete-runtime-task-pack-fixtures.md) | 删除旧 runtime task-pack fixtures | A | delete | P1 | low | done | RC-001 |
| [RC-004](./goals/RC-004-add-task-pack-integrity-gate.md) | 增加 task-pack 引用完整性门禁 | A | guardrail | P1 | low | done | RC-001 |
| [RC-005](./goals/RC-005-retire-deterministic-runtime-pack.md) | 退出 deterministic runtime pack | A | delete | P1 | low | done | RC-001, RC-003, RC-004 |
| [RC-006](./goals/RC-006-delete-legacy-compaction-trace-fixture.md) | 删除 legacy compaction trace fixture | A | delete | P1 | low | done | RC-001 |
| [RC-007](./goals/RC-007-delete-pseudo-native-trace-fixture.md) | 删除伪 native trace fixture | A | delete | P1 | low | done | RC-001 |
| [RC-008](./goals/RC-008-delete-legacy-runtime-observed-fixtures.md) | 删除 legacy runtime-observed fixtures | A | delete | P1 | medium | done | RC-001, RC-018 |
| [RC-009](./goals/RC-009-reduce-model-backed-compaction-fixture.md) | 缩减 model-backed compaction fixture | A | reduce | P1 | medium | done | RC-001 |
| [RC-010](./goals/RC-010-reduce-claude-api-trace-fixture.md) | 将 Claude API trace 缩成 mini trace | A | reduce | P1 | high | done | — |
| [RC-011](./goals/RC-011-rebuild-wrapper-truth-goldens.md) | 重建 truth-consistent wrapper goldens | A | repair | P1 | high | done | — |
| [RC-012](./goals/RC-012-consolidate-multi-agent-golden.md) | 统一 multi-agent mock golden 真源 | A | merge | P1 | medium | done | RC-001 |
| [RC-013](./goals/RC-013-establish-docs-taxonomy.md) | 建立 docs 分类与导航 | A | govern | P1 | low | done | RC-000 |
| [RC-014](./goals/RC-014-write-native-family-adr.md) | 提炼 native-family ADR | A | merge | P1 | medium | done | RC-013 |
| [RC-015](./goals/RC-015-archive-local-runtime-plans.md) | 归档旧 local-runtime/P3 文档 | A | archive | P1 | medium | done | RC-013, RC-014 |
| [RC-016](./goals/RC-016-archive-tool-runtime-plans.md) | 归档 Tool Runtime 实施计划簇 | A | archive | P1 | medium | done | RC-014 |
| [RC-017](./goals/RC-017-rewrite-real-provider-runbook.md) | 重写 real-provider runtime runbook | B | repair | P1 | medium | done | RC-014, RC-023 |
| [RC-018](./goals/RC-018-rewrite-native-acceptance-doc.md) | 重写 native-family acceptance 文档 | A | repair | P1 | low | done | RC-001 |
| [RC-019](./goals/RC-019-reconcile-scaffold-phase1-doc.md) | 校正 scaffold phase-one golden 文档 | A | repair | P2 | medium | done | RC-012 |
| [RC-020](./goals/RC-020-deduplicate-agent-instructions.md) | 去重 AGENTS.md 与 CLAUDE.md | A | merge | P1 | medium | done | RC-013 |
| [RC-021](./goals/RC-021-define-family-neutral-task-contract.md) | 定义 family-neutral task metadata | B | govern | P0 | medium | done | RC-014 |
| [RC-022](./goals/RC-022-migrate-realistic-task-metadata.md) | 迁移 realistic task metadata | B | repair | P0 | medium | done | RC-021 |
| [RC-023](./goals/RC-023-repair-realistic-task-consumers.md) | 修复 realistic consumers 的 family 选择 | B | repair | P0 | medium | done | RC-022 |
| [RC-024](./goals/RC-024-decide-legacy-study-route.md) | 决定旧 study/toy 路线去向 | B | decide | P0 | medium | done | — |
| [RC-025](./goals/RC-025-freeze-study-archive-boundary.md) | 冻结 study 依赖闭包与归档机制 | B | govern | P1 | medium | done | RC-024 |
| [RC-026](./goals/RC-026-isolate-legacy-study-cluster.md) | 隔离旧 study 模块、测试与配置 | B | archive | P1 | high | done | RC-025 |
| [RC-027](./goals/RC-027-archive-stage-root-entrypoints.md) | 归档阶段性根入口 | B | archive | P1 | medium | done | RC-025 |
| [RC-028](./goals/RC-028-isolate-synthetic-schema-route.md) | 隔离 synthetic/trajectory baseline | B | archive | P2 | medium | done | RC-013 |
| [RC-029](./goals/RC-029-define-auxiliary-namespace.md) | 定义 auxiliary namespace | B | govern | P1 | medium | done | RC-013 |
| [RC-030](./goals/RC-030-migrate-native-transformed-route.md) | 迁移 gateway/native-transformed 辅助路线 | B | archive | P1 | high | done | RC-029 |
| [RC-031](./goals/RC-031-narrow-package-reexports.md) | 收窄 rl/eval 公共导出 | B | merge | P1 | high | done | RC-026, RC-028, RC-030 |
| [RC-032](./goals/RC-032-remove-dead-runtime-helpers.md) | 删除失活 runtime helpers | C | delete | P1 | low | done | RC-001 |
| [RC-033](./goals/RC-033-freeze-compaction-contract.md) | 冻结 compaction 行为与 model-backed 决策 | C | decide | P1 | medium | done | RC-001 |
| [RC-034](./goals/RC-034-remove-duplicate-compaction.md) | 删除 turn_state 重复 compaction | C | delete | P1 | high | done | RC-033 |
| [RC-035](./goals/RC-035-deduplicate-workspace-hash.md) | 合并 workspace hash helper | C | merge | P2 | low | done | RC-001 |
| [RC-036](./goals/RC-036-deduplicate-mutation-loader.md) | 合并 mutation config loader | C | merge | P2 | low | done | RC-001 |
| [RC-037](./goals/RC-037-decide-command-policy.md) | 决定旧 command policy 去向 | C | decide | P1 | medium | done | — |
| [RC-038](./goals/RC-038-retire-command-safety.md) | 删除旧 command_safety | C | delete | P1 | high | done | RC-037 |
| [RC-039](./goals/RC-039-resolve-orphan-support-modules.md) | 决定 orphan support modules 去向 | C | decide | P2 | medium | done | — |
| [RC-040](./goals/RC-040-characterize-training-prep.md) | 建立 training-prep 行为矩阵与 golden | D | guardrail | P0 | medium | done | RC-001 |
| [RC-041](./goals/RC-041-define-prepared-sample-contract.md) | 定义唯一 PreparedSample 合同 | D | merge | P0 | high | done | RC-040 |
| [RC-042](./goals/RC-042-unify-training-bundle-builder.md) | 实现唯一 training bundle builder | D | merge | P0 | high | done | RC-041 |
| [RC-043](./goals/RC-043-define-run-campaign.md) | 定义并实现 RunCampaign/RunMatrix | D | merge | P1 | high | done | RC-024, RC-042 |
| [RC-044](./goals/RC-044-migrate-active-campaigns.md) | 迁移 active campaigns 并删重复循环 | D | merge | P1 | high | done | RC-043 |
| [RC-045](./goals/RC-045-build-formal-cli.md) | 建立正式 subcommand CLI | D | merge | P1 | high | done | RC-031, RC-042, RC-044 |
| [RC-046](./goals/RC-046-remove-root-wrapper-clutter.md) | 移除被正式 CLI 取代的根 wrappers | D | delete | P2 | medium | done | RC-045 |
| [RC-047](./goals/RC-047-freeze-slime-upstream.md) | 确认 slime upstream 与精确 ref | E | govern | P1 | medium | done | — |
| [RC-048](./goals/RC-048-add-slime-overlay-lock.md) | 增加 slime overlay manifest 与 verifier | E | govern | P1 | high | done | RC-047 |
| [RC-049](./goals/RC-049-lock-codex-reference.md) | 增加 codex-rs reference lock/bootstrap | E | govern | P0 | medium | done | — |
| [RC-050](./goals/RC-050-decide-claude-code-tree.md) | 决定 claude_code 本地树去向 | E | decide | P2 | medium | done | — |
| [RC-051](./goals/RC-051-externalize-claude-code-tree.md) | 将 claude_code 移出工作树 | E | delete | P2 | medium | done | RC-050 |
| [RC-052](./goals/RC-052-inventory-runs.md) | 生成 runs 只读 inventory | E | govern | P1 | low | done | — |
| [RC-053](./goals/RC-053-define-runs-retention.md) | 定义 retention 与 retained-run index | E | govern | P1 | high | done | RC-052 |
| [RC-054](./goals/RC-054-classify-and-archive-runs.md) | 分类、scrub 并归档现有 runs | E | archive | P1 | high | done | RC-053 |
| [RC-055](./goals/RC-055-enforce-run-retention.md) | 在新 run writer 中执行 retention 规则 | E | govern | P2 | high | done | RC-053 |
| [RC-056](./goals/RC-056-retire-minimal-train-loop.md) | 退出 toy minimal train loop | C | delete | P2 | medium | done | RC-039 |
| [RC-057](./goals/RC-057-retire-legacy-eval-tables.md) | 退出无消费者的 legacy eval tables | C | delete | P2 | medium | done | RC-039, RC-031 |

## 完成门槛

代码或资产目标默认需要：

```text
相关静态引用检查
相关定向测试
python -B -m pytest -q --strict-markers -m mainline \
  tests/test_native_runtime_mainline.py \
  tests/test_runtime_observed_mainline.py \
  tests/test_task_pack_integrity.py \
  tests/test_realistic_task_consumers.py \
  tests/test_route_boundaries.py \
  tests/test_package_public_api.py \
  tests/test_multi_agent_scaffold_contracts.py \
  tests/test_compaction_contract.py \
  tests/test_repository_cleanup_decisions.py \
  tests/test_command_policy_decision.py \
  tests/test_command_safety_retirement.py \
  tests/test_training_prep_characterization.py \
  tests/test_prepared_sample_contract.py \
  tests/test_training_bundle.py \
  tests/test_run_campaign.py \
  tests/test_formal_cli.py \
  tests/test_root_wrapper_disposition.py \
  tests/test_docs_taxonomy.py \
  tests/test_codex_reference_lock.py \
  tests/test_slime_upstream_lock.py \
  tests/test_slime_overlay_manifest.py \
  tests/test_runs_inventory.py \
  tests/test_runs_retention.py \
  tests/test_runs_archive.py \
  tests/test_run_retention_enforcement.py \
  tests/test_legacy_study_boundary.py \
  tests/test_local_ignored_assets.py
python -B -m pycodeagent acceptance --local-only --output-root <tmp>
python -B -m pytest tests -q --strict-markers
git diff --check
```

文档、vendor 和 runs 目标可以用链接完整性、machine-readable lock、checksum、
100% 分类率等专属验收代替不相关的测试，但必须在目标文档中明确写出 N/A 理由。
