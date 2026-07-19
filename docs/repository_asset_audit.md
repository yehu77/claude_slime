# Repository Asset Audit

> 本文保留为 2026-07-14 的审计证据快照，不随每次清理持续改写。
> 实时目标、依赖和量化进度见
> [`repository_cleanup/README.md`](./repository_cleanup/README.md)。

## 文档状态

- 审计日期：2026-07-14
- 审计范围：仓库架构、Python 调用关系、根目录入口、测试与 fixture、
  examples、任务包、文档代际，以及外部源码树边界
- 审计方式：只读检查、静态引用分析、默认测试、定向 slow 测试和本地
  native-family acceptance
- 本文性质：清理决策依据，不是已经执行的删除清单

本文使用以下分类：

- `KEEP`：当前主线或明确契约，应继续保留
- `MERGE`：功能仍有价值，但存在重复实现或重复入口
- `ARCHIVE`：有历史或研究价值，但不应继续占据当前主命名空间
- `DELETE?`：高置信删除候选，仍需在实际删除前确认
- `REDUCE`：保留用途，但应缩小体积或减少重复内容
- `VENDOR`：外部源码或参考树，不应与 repo-owned 代码混为一体

---

## 1. 执行结论

当前仓库确实存在显著的资产混杂问题。混乱的主要来源不是核心 local
runtime 本身，而是以下几代路线同时留在活动目录中：

1. native-family 切换前的 generic-tool runtime、study 和 task-pack 资产
2. 当前 repo-owned native-family local runtime 主线
3. generic trajectory、schema-following、Claude API SFT、native-transformed
   SFT/RL 等多套训练入口
4. 尚未真正闭环的 multi-agent raw-trace scaffold
5. 已经完成或 superseded 的大量实施计划和阶段说明
6. `slime-main`、`codex-rs`、`claude_code` 三种边界不同的外部源码树

因此，当前最合理的策略不是继续添加功能，也不是立即进行大规模代码重构，
而是先完成：

1. 当前主线冻结
2. 历史资产归档
3. orphan fixture/example 清理
4. 重复实现合并
5. vendor/reference 边界显式化

---

## 2. 仓库规模快照

审计时的仓库规模如下：

| 项目 | 数量或体积 |
| --- | ---: |
| Git tracked 文件 | 1,028 |
| `slime-main/` tracked 文件 | 474 |
| 根目录 Python 入口 | 23 |
| `pycodeagent/` Python 代码 | 约 45,700 行 |
| `agent + rl + eval` Python 代码 | 约 32,000 行 |
| `docs/` 文档 | 27 份，10,473 行 |
| tracked fixture | 200 个文件，约 5.06 MB |
| 本地 ignored `claude_code/` | 约 133 MB |
| 本地 ignored `codex-rs/` | 约 54 MB |
| 本地 ignored `runs/` | 约 84 MB |
| 本地 ignored `.venv-regression/` | 约 16 MB |

`slime-main/` 单独占全部 tracked 文件的约 46%。这部分体积属于 vendor
边界问题，而不是 `pycodeagent` 自身代码规模。

---

## 3. 当前唯一主线

依据 `AGENTS.md`、README、当前实现和数据合同，当前唯一应被视为主线的链路是：

```text
CodingTask / workspace
  -> repo-owned local runtime
  -> CanonicalTool / ToolView / ToolRuntime
  -> Trajectory + RuntimeTrace + ToolProfile
  -> runtime-observed schema-following exporter
  -> serializer / loss mask / tokenizer / contract verification
  -> slime-compatible consumer
```

主要代码边界：

- [`pycodeagent/env/coding_env.py`](../pycodeagent/env/coding_env.py)
- [`pycodeagent/agent/runner.py`](../pycodeagent/agent/runner.py)
- [`pycodeagent/tools/spec.py`](../pycodeagent/tools/spec.py)
- [`pycodeagent/tools/runtime.py`](../pycodeagent/tools/runtime.py)
- [`pycodeagent/tools/families/`](../pycodeagent/tools/families/)
- [`pycodeagent/trajectory/`](../pycodeagent/trajectory/)
- [`pycodeagent/runtime_trace/`](../pycodeagent/runtime_trace/)
- [`pycodeagent/rl/schema_following_from_runtime.py`](../pycodeagent/rl/schema_following_from_runtime.py)
- [`pycodeagent/rl/training_prep.py`](../pycodeagent/rl/training_prep.py)
- [`pycodeagent/rl/contract.py`](../pycodeagent/rl/contract.py)

multi-agent contracts、adapters 和 harness 仍符合长期项目目标，但当前更适合标记为
experimental/integration，而不是和 local runtime 主线并列宣称已经闭环。

---

## 4. KEEP：应继续保留的资产

### 4.1 Local runtime 与工具控制面

- `pycodeagent/env/`
- `pycodeagent/agent/runner.py`
- `pycodeagent/agent/turn_context.py`
- `pycodeagent/agent/history_manager.py`
- `pycodeagent/agent/compaction.py`
- `pycodeagent/agent/recovery.py`
- `pycodeagent/agent/stopping.py`
- `pycodeagent/tools/spec.py`
- `pycodeagent/tools/runtime.py`
- `pycodeagent/tools/registry.py`
- `pycodeagent/tools/bootstrap.py`
- `pycodeagent/tools/profile_factory.py`
- `pycodeagent/tools/contracts.py`
- `pycodeagent/tools/process_exec.py`
- `pycodeagent/tools/shell_runtimes.py`
- `pycodeagent/tools/patch_apply.py`
- `pycodeagent/tools/patch_runtime.py`
- `pycodeagent/tools/families/claude.py`
- `pycodeagent/tools/families/codex.py`

### 4.2 运行与审计合同

- `pycodeagent/trajectory/`
- `pycodeagent/runtime_trace/`
- `pycodeagent/agent/history_verify.py`
- `pycodeagent/eval/runtime_behavior_audit.py`
- `pycodeagent/eval/runtime_execution_reconciliation.py`
- `pycodeagent/eval/runtime_observed_postrun.py`

`history_verify.py` 虽然当前主要由测试调用，但它验证 retained history 与 request
context 的一致性，符合项目的数据完整性目标，应并入正式 contract verification，
而不是直接删除。

### 4.3 训练数据合同内核

- `pycodeagent/rl/serializer.py`
- `pycodeagent/rl/loss_mask.py`
- `pycodeagent/rl/mask_alignment.py`
- `pycodeagent/rl/tokenizer.py`
- `pycodeagent/rl/tokenizer_config.py`
- `pycodeagent/rl/tensorize.py`
- `pycodeagent/rl/packing.py`
- `pycodeagent/rl/train_dataset.py`
- `pycodeagent/rl/dataset_manifest.py`
- `pycodeagent/rl/contract.py`
- `pycodeagent/rl/schema_following.py`
- `pycodeagent/rl/schema_following_dataset.py`
- `pycodeagent/rl/schema_following_from_runtime.py`
- `pycodeagent/rl/sample_builder.py`
- `pycodeagent/rl/dataset_builder.py`
- `pycodeagent/rl/slime_rollout.py`
- `pycodeagent/rl/slime_bridge.py`

`packing.py` 当前主要用于 contract roundtrip 验证，而不是最终 packed 训练文件。
这属于实现边界未完成，不代表该模块没有价值。

`native_transformed_reward.py` 在 `pycodeagent` 内部看起来调用较少，但实际由
`slime-main/slime/rollout/pycodeagent_native_rl.py` 动态消费，不能删除。

### 4.4 Multi-agent 长期合同

建议保留但隔离：

- `pycodeagent/adapters/`
- `pycodeagent/harness/`
- `pycodeagent/traces/raw_trace.py`
- `pycodeagent/traces/tool_catalog.py`
- `pycodeagent/traces/canonical_trace.py`

这些资产对应长期 raw-agent trace scaffold。当前问题是尚未闭环，而不是方向错误。

---

## 5. MERGE：重复实现与过渡实现

### 5.1 `turn_state.py` 中重复的 compaction 实现

[`turn_state.py`](../pycodeagent/agent/turn_state.py) 的
`select_request_messages()` 已经直接委托给
[`compaction.py`](../pycodeagent/agent/compaction.py)，但
`turn_state.py:1172-1913` 仍保留：

- `_select_full_history`
- `_select_tail_window`
- `_select_deterministic_compaction`
- `_build_context_selection`
- turn range、summary、token-budget 等整组 helper

这约 740 行代码与 `compaction.py` 中的活动实现高度重复，属于当前最高置信的
可移除重复代码。

应保留 `turn_state.py` 中的状态模型和 token estimator，将 request selection
实现只保留在 `compaction.py`。

### 5.2 `runner.py` 内失活 helper

以下内部函数没有调用方：

- `_meaningful_progress_observed`
- `_active_recent_failure_kind`
- `_sync_session_pending_issue`

前两个已有 `turn_state.py` 中的活动实现，第三个已经被
`sync_pending_issue_record()` 替代。

### 5.3 `command_safety.py` 大部分失活

审计时的 `pycodeagent/tools/command_safety.py` 约 297 行，但当时只有
`normalize_workdir` 仍被 `shell_runtimes.py` 使用。

旧的以下内容没有活动调用方或测试：

- executable allowlist/denylist
- `classify_command_argv`
- 旧 `CommandPolicyDecision`
- 旧 `CommandExecutionResult`
- `run_subprocess`

当前执行底座已经转为 `process_exec.py + shell_runtimes.py`。建议先明确 S5 权限
策略是否会复用这些规则；如果不会，将 `normalize_workdir` 移到 path policy 后
删除旧模块。

后续状态：RC-037 决定不复用旧两态 argv policy，RC-038 已将唯一转发迁移到
`path_policy.validate_cwd` 并删除该模块。本节保留为 2026-07-14 审计证据。

### 5.4 Training prep 四套重复编排

[`training_prep.py`](../pycodeagent/rl/training_prep.py) 中存在四个相近入口：

- `prepare_slime_training_input`
- `prepare_native_transformed_sft_training_input`
- `prepare_schema_following_training_input`
- `prepare_runtime_observed_schema_following_training_input`

它们重复执行：

```text
resolve tokenizer
  -> write prepared samples
  -> tensorize
  -> write tokenized.jsonl
  -> write tokenizer/train config
  -> contract/recommendation
```

建议收敛为：

```text
source adapter
  -> PreparedSample
  -> one serialize/mask/tokenize/verify bundle builder
  -> consumer
```

`schema_following_training.py` 与 `claude_api_sft_training.py` 的 prepared sample、
serialize、mask 和 IO 也高度同构，应共享一个 prepared-text contract。

### 5.5 Eval/campaign 重复

以下组件重复实现 task × profile × seed/repeat 运行矩阵：

- `BatchRunner`
- `ExperimentRunner`
- `MutationStudyRunner`
- behavior baseline
- credibility bundle
- ToolView mutation generation
- native-family acceptance

建议最终只保留一个 `RunCampaign` 或 `RunMatrix`，报告、gates 和 postprocessors
作为可插拔组件。

### 5.6 根目录 CLI 重复

仓库根目录有 23 个 Python 入口，绝大多数只是薄 wrapper，并重复：

- provider config 解析
- tokenizer 参数解析
- output root 规则
- JSON summary 打印
- acceptance/smoke 参数

仓库根部又没有 `pyproject.toml` 或正式 console entrypoint。

建议最终收敛为一个带 subcommand 的 CLI，例如：

```text
pycodeagent runtime ...
pycodeagent trace ...
pycodeagent dataset ...
pycodeagent train-prep ...
pycodeagent acceptance ...
```

### 5.7 包级全量 re-export

[`pycodeagent/rl/__init__.py`](../pycodeagent/rl/__init__.py) 有约 476 行、191 个导出，
一次 import 会加载约 106 个 `pycodeagent` 模块。

问题包括：

- 掩盖真实 reachability
- 辅助路线看起来像稳定公共 API
- `__all__` 包含未实际 import 的 `CanonicalIntentBaselinePredictor`
- `from pycodeagent.rl import *` 会因此触发 `AttributeError`

`pycodeagent/eval/__init__.py` 也把新旧两代 eval eager import 到同一命名空间。
应收窄为少量稳定合同导出。

### 5.8 其他重复

- `external_cli_adapter.py` 与 `mock_adapter.py` 各有一份相同的
  `hash_workspace()`
- `profile_loader.py` 与 `profile_sampler.py` 各有一套 mutation config loader
- `examples/multi_agent_mock_run/` 与
  `tests/fixtures/multi_agent_mock_bundle/` 的 5 个数据文件 SHA-256 完全相同
- `AGENTS.md` 与 `CLAUDE.MD` 均为 371 行，仅少量 agent-specific 文字不同

---

## 6. ARCHIVE：应退出活动主命名空间的路线

### 6.1 旧 study/eval 编排簇

以下模块合计约 3,020 行：

- `pycodeagent/eval/analysis.py`
- `pycodeagent/eval/batch_runner.py`
- `pycodeagent/eval/experiment_config.py`
- `pycodeagent/eval/experiment_runner.py`
- `pycodeagent/eval/metrics.py`
- `pycodeagent/eval/report.py`
- `pycodeagent/eval/run_study.py`
- `pycodeagent/eval/study_config.py`
- `pycodeagent/eval/study_report.py`
- `pycodeagent/eval/study_runner.py`
- `pycodeagent/eval/tables.py`

它们不是“可能过时”，而是已经确认存在 native-family cutover 后的调用断裂：

- `run_batch()` 未传新增的 `tool_stack_kind`
- `run_experiment()` 未传新增的 `tool_stack_kind`
- `MutationStudyRunner` 创建 `ExperimentRunner` 时未传该参数
- behavior baseline 调 `run_coding_task()` 时也未传该参数
- slow tests 仍构造 `<|tool|>` 文本协议以及旧 `finish/python_run/write_file`
  工具调用

如果 study 仍是近期产品面，应整体迁移到显式 native-family campaign；否则应把
代码、测试、configs 和 toy task pack 一起归档，不能继续依靠默认 skip 维持绿色。

### 6.2 阶段性根入口

建议归档：

- `run_first_study_mimo.py`
- `run_first_study_real_provider.py`
- `run_schema_attribution_mimo.py`
- `run_p3b_real_provider_compaction_acceptance.py`
- `verify_p3b_real_provider_compaction_acceptance.py`
- `run_schema_following_sft.py`

`MimoNativeToolClient` 本身仍被通用 provider runtime 使用，应保留；需要归档的是
Mimo 专用旧 study helper 和配置，而不是 native client。

### 6.3 Synthetic/trajectory-derived 路线

建议作为 research baseline 隔离，而不是继续和 observed-data 主线并列：

- `generate_schema_following_data.py`
- `pycodeagent/rl/schema_following_generate.py`
- `pycodeagent/rl/schema_following_from_trajectories.py`
- `pycodeagent/rl/schema_following_splits.py`
- `pycodeagent/rl/schema_following_eval.py`
- `pycodeagent/rl/schema_following_sft.py`

`schema_following_from_runtime.py` 已包含 execution provenance 和 native-family
contract，是 trajectory-derived exporter 的更强主线版本。

### 6.4 Claude API/native-transformed 路线

以下路径有文档、测试和 slime 侧消费者，不能直接删除：

- `claude_gateway_proxy.py`
- `export_claude_api_sft_dataset.py`
- `export_native_transformed_sft_dataset.py`
- `validate_native_transformed_sft_dataset.py`
- `prepare_native_transformed_sft_training_data.py`
- `export_native_transformed_rl_dataset.py`
- `run_native_transformed_sft_smoke.py`

但 `AGENTS.md` 已将它们定义为辅助 source path。建议整体移动到明确的
`auxiliary/native_transformed/` 或 `scripts/native_transformed/`，避免继续影响仓库
主线认知。

---

## 7. 文档资产结论

### 7.1 KEEP

- [`codex_rs_subsystem_implementation_plan.md`](./codex_rs_subsystem_implementation_plan.md)
- [`local_runtime_industrial_gap_roadmap.md`](./local_runtime_industrial_gap_roadmap.md)
- [`claude_gateway_proxy.md`](./auxiliary/claude_gateway_proxy.md)
- [`native_transformed_sft_pipeline.md`](./auxiliary/native_transformed_sft_pipeline.md)
- [`native_transformed_rl_pipeline.md`](./auxiliary/native_transformed_rl_pipeline.md)
- [`external_agent_sidecar_protocol.md`](./external_agent_sidecar_protocol.md)
- [`external_cli_capability_matrix.md`](./external_cli_capability_matrix.md)

### 7.2 KEEP，但必须重写

- `tool_runtime_native_family_acceptance_and_regression_plan.md`
  - 自称 active，但 17 个测试引用中有 8 个文件不存在
  - 列出的 5 组 runtime-observed fixture 实际都是 `family=legacy`
- `real_provider_runtime_usage.md`
  - 仍描述 `read_file -> finish`
  - 程序化示例漏传必填 `tool_stack_kind`
  - study 示例进入已断裂的 `MutationStudyRunner`
- `scaffold_phase1.md`
  - 契约目标仍有价值，但 golden 已无测试消费，并与当前 native MockAdapter 和
    renderer 不一致

### 7.3 ARCHIVE

建议移出活动 `docs/` 根目录：

- `P3plan.md`
- `agent_training_infra_architecture.md`，或改放 auxiliary 文档区
- `local_runtime_85_maturity_execution_plan.md`
- `local_runtime_maturation_plan.md`
- `local_runtime_realism_mainline_plan.md`
- `runtime_r1_implementation_note.md`
- `runtime_r3_implementation_note.md`
- `tool_runtime_family_split_implementation_plan.md`
- `tool_runtime_step_a_shared_process_primitives_plan.md`
- `tool_runtime_step_b_shell_runtime_integration_plan.md`
- `tool_runtime_step_c0_native_tool_contract_expansion_plan.md`
- `tool_runtime_step_c_canonical_tool_definitions_plan.md`
- `tool_runtime_step_d_native_family_profiles_plan.md`
- `tool_runtime_step_e_bootstrap_registry_selection_plan.md`
- `tool_runtime_step_f_native_family_mutation_data_integration_plan.md`
- `toolview_mutation_data_generation_plan.md`

其中 P3、多代 local-runtime 计划、R1/R3 note 和 Step A-F 中最明确的历史文档
合计约 7,089 行。

建议将 family split 的长期架构理由浓缩为一份 ADR。详细实施过程已经由 Git
历史保存，不必继续作为活动指导文档。

### 7.4 DELETE?

- `tool_runtime_legacy_demotion_followup_plan.md`
  - 只有 33 行
  - 文件本身已经明确标记 superseded/archive-only
- `runtime_r1_implementation_note.md`
- `runtime_r3_implementation_note.md`
- Step A-F 详细计划

如果不准备维护单独的 docs archive，上述文件可以在提炼 ADR 后直接从当前树
删除，依靠 Git 历史承担考古用途。

---

## 8. Fixture 资产结论

### 8.1 KEEP

- `tests/fixtures/external_cli_claude_real_smoke/`
- `tests/fixtures/external_cli_claude_wrapper_bundle/`
- `tests/fixtures/external_cli_kilo_wrapper_bundle/`
- `tests/fixtures/claude_api_tool_use_session.jsonl`

前三组有当前测试消费。但 Claude/Kilo wrapper bundle 仍存在 truth conflict：

```text
raw_trace_summary.json: completed / verifier passed / empty diff
verifier.json: verifier failed
final.diff: non-empty
```

当前 golden 固定的是 artifact handoff，而不是 truth integrity，需要在 sidecar
reconciliation 合同确定后重建。

### 8.2 REDUCE

`tests/fixtures/claude_api_tool_use_session.jsonl` 当前：

- 3,933,704 bytes
- 569 个事件
- 27 个 request
- 重复保存完整 system prompt、29 个 tool schema 和 session/device metadata

当前测试实际只要求：

- 至少一个 request-side tool catalog
- 一个 `tool_use`
- 后续 request 中匹配的 `tool_result`
- 至少四个 transformation mode

可以用一份脱敏的两请求 mini trace 代替。完整真实 trace 如需研究留存，应进入
repo 外 artifact storage。

`tests/fixtures/local_runtime_trace_bundle_model_backed_compaction/` 有 57 个文件，
但当前测试只读取：

- `request_context.jsonl`
- `retained_history.jsonl`

其余 55 个 manifest、runtime trace 和 payload 文件没有 active-test 消费者。

### 8.3 ARCHIVE/DELETE?

以下目录没有当前测试消费者，而且属于旧 generic/legacy 工具代际：

```text
tests/fixtures/deterministic_runtime_task_pack/
tests/fixtures/realistic_runtime_task_pack/
tests/fixtures/local_runtime_trace_bundle_compaction/
tests/fixtures/local_runtime_trace_bundle_native/
tests/fixtures/multi_agent_mock_bundle/
tests/fixtures/runtime_observed_dataset_bundle/
tests/fixtures/runtime_observed_dataset_bundle_mutated/
tests/fixtures/runtime_observed_dataset_bundle_tool_reorder/
tests/fixtures/runtime_observed_study_bundle/
tests/fixtures/runtime_observed_training_prep_bundle/
```

其中：

- deterministic/realistic smoke responses 仍是 `<|tool|>` 文本协议以及
  `create_file/read_file/python_run/finish`
- 名为 `local_runtime_trace_bundle_native` 的 fixture 实际工具名仍是
  `list_files/read_file/.../finish`
- 5 组 runtime-observed profile manifest 均为
  `family=legacy, native_profile_kind=legacy`
- mutated runtime-observed bundle 与 training-prep bundle 的 raw dataset 还存在
  逐字节重复文件

综合统计，约 185 个 fixture 文件没有 active-test 消费，或属于被读取目录中的
未读衍生产物。

---

## 9. Examples 与 task packs

### 9.1 KEEP

- `examples/external_wrappers/`
- `examples/buggy_counter/`
- `examples/runtime_realistic_patch_calculator/`
- `examples/runtime_realistic_revise_add_one/`
- `examples/runtime_realistic_subdir_formatter/`
- `examples/runtime_rewrite_greeter/`

`runtime_rewrite_greeter` 仍被 smoke/compaction 入口引用，不能在入口决策之前单独
删除。

### 9.2 DELETE?

- `examples/buggy_reverser/`
  - 不在任何 task dataset 中
  - 没有测试、脚本或文档引用
- `examples/runtime_create_add_one/`
- `examples/runtime_subdir_formatter/`
  - 只由无人消费的 deterministic task pack 指向

### 9.3 CONSOLIDATE

`examples/multi_agent_mock_run/` 和
`tests/fixtures/multi_agent_mock_bundle/` 保存同一份快照。

应只保留一个可执行 golden 真源：

- fixture 为真源，文档直接链接 fixture；或
- example 为真源，测试直接消费 example

当前两份都没有测试消费者，因此只是重复且已经过时的快照。

### 9.4 TASK PACKS

`datasets/tasks/deterministic_runtime_tasks.jsonl`：

- 全仓没有当前消费者
- metadata 与 expected pattern 都是旧 generic tools
- 可以与相应 examples 和 smoke fixture 一起归档或删除

`datasets/tasks/toy_tasks.jsonl`：

- 仍被旧 study configs 引用
- study 主链当前断裂
- 12 个 task 的 `primary_tools` 均为旧
  `read_file/apply_patch/run_command/finish`
- 如果 study 暂停，应整组移动到 `legacy_toy_study/`

`datasets/tasks/realistic_runtime_tasks.jsonl`：

- 被多个 real-provider 路径引用，应保留
- metadata/expected pattern 仍使用旧
  `create_file/read_file/write_file/python_run/finish`
- 应改成 family-neutral 行为要求，或分别定义 Claude/Codex expectations

---

## 10. DELETE?：代码级高置信候选

下列项目没有当前生产调用方：

- `pycodeagent/testing/runtime_observed.py`
  - 最新 native-family commit 删除了消费它的 runtime-observed golden tests
  - 当前只由 `testing/__init__.py` 重导出
- `pycodeagent/rl/train_loop.py`
  - 只有测试和 `rl/__init__.py` 消费
  - 实现的是 ToyModel/minimal loop
  - 实际训练出口已经是 slime
- `pycodeagent/adapters/mock_adapter.py` 中的 `read_mock_raw_trace`
- `pycodeagent/agent/compaction.py` 中的 `ModelBackedCompactionResult`
- `pycodeagent/agent/prompt.py` 中的 `format_history_for_prompt`
- `pycodeagent/mutations/profile_loader.py` 中的 `load_mutation_config`

需要先确认是否存在个人 notebook 或外部 import 的候选：

- `pycodeagent/rl/export.py`
  - 当前只有测试和 `rl/__init__.py` 使用
  - production dataset builder 已有自己的 JSONL 写出逻辑
- `pycodeagent/eval/tables.py`
  - 没有生产调用、根入口或测试
  - 只由 `eval/__init__.py` 暴露
- `pycodeagent/traces/render.py`
  - 当前无调用方和测试
  - 但属于 multi-agent 长期设计，应该隔离，不建议直接删除

---

## 11. 根目录入口结论

### 11.1 KEEP，但当前需要修复或并入统一 CLI

- `run_native_family_acceptance.py`
- `run_runtime_smoke_real_provider.py`
- `run_toolview_mutation_data_generation.py`
- `run_real_provider_credibility_bundle.py`

已知断裂：

- runtime smoke 漏传 `tool_stack_kind`
- mutation generation 漏传 `tool_stack_kind`
- credibility bundle 漏传 `tool_stack_kind`
- native acceptance 的 regression 清单引用 8 个已删除测试

### 11.2 MERGE

建议统一到 runtime/campaign/acceptance subcommands：

- `run_real_provider_behavior_baseline.py`
- `run_real_provider_credibility_bundle.py`
- `run_toolview_mutation_data_generation.py`
- `run_native_family_acceptance.py`
- `run_runtime_smoke_real_provider.py`

### 11.3 ARCHIVE

- `run_first_study_mimo.py`
- `run_first_study_real_provider.py`
- `run_schema_attribution_mimo.py`
- `run_p3b_real_provider_compaction_acceptance.py`
- `verify_p3b_real_provider_compaction_acceptance.py`
- `run_schema_following_sft.py`

### 11.4 AUXILIARY

以下入口应整体隔离，而不是散落在仓库根目录：

- `claude_gateway_proxy.py`
- `export_claude_api_sft_dataset.py`
- `export_native_transformed_sft_dataset.py`
- `validate_native_transformed_sft_dataset.py`
- `prepare_native_transformed_sft_training_data.py`
- `export_native_transformed_rl_dataset.py`
- `run_native_transformed_sft_smoke.py`

---

## 12. VENDOR 与本地外部树

### 12.1 `slime-main/`

分类：`VENDOR`

- 约 11 MB
- 474 个 tracked 文件
- 无 nested `.git`
- 无 `.gitmodules`
- 只在一个历史 commit 中整体加入
- [`VENDORING.md`](../slime-main/VENDORING.md) 明确说明它是 vendored upstream
- 当前没有记录 upstream URL + commit/tag
- VENDORING 的 owned surface 清单遗漏了实际存在并被测试消费的
  `pycodeagent_native_rl.py`

应补充：

- upstream URL
- 精确 commit/tag
- license/provenance
- repo-owned patch/overlay manifest
- 两个 bridge 文件和 examples 的明确所有权

长期可考虑用 pinned dependency/submodule 加独立 integration overlay，减少主仓库导航
噪音。

### 12.2 `codex-rs/`

分类：`VENDOR/REFERENCE`

- 约 54 MB、4,477 个本地文件
- Git tracked 文件为 0
- 被 `.gitignore` 忽略
- 无 nested Git 和 provenance
- 多份 runtime 文档按具体源码路径引用它

它应该继续是可重建的外部 reference，而不是直接加入主仓库。需要一份
`references.lock` 或 bootstrap 说明，记录 URL、commit 和校验信息。

### 12.3 `claude_code/`

分类：`DELETE? / MOVE OUT OF TREE`

- 约 133 MB、1,927 个本地文件
- Git tracked 文件为 0
- 被 `.gitignore` 忽略
- 无 nested Git
- package version 为 2.1.88
- 仓库没有任何对该目录的路径依赖
- Claude adapter 实际只调用 PATH 中的 `claude`

如果仍需逆向研究，应移到 repo 外缓存并记录版本；否则可以在明确确认后清理。

后续状态：RC-050 已选择保留式本机外移，目标为工作树外的持久 reference
store；RC-051 已完成 copy、完整树摘要校验和工作树源目录移除，外部验证副本
继续保留。本节保留为 2026-07-14 审计证据。

### 12.4 本地 ignored 资产

- `.env`：包含本地配置，不能纳入通用清理
- `configs/local/*.local.json`：机器本地配置，不能自动删除
- `runs/`：可能包含有价值的研究结果，先制定 retention/archive 策略
- `.venv-regression/`：可重建环境，可以清理但不属于 Git 仓库资产
- `__pycache__/`：纯缓存，可以安全清理
- 空 `.agents/`、`.codex/`、`tmpmutationdata/`：本地空目录，可清理

---

## 13. 测试证据

### 13.1 默认测试

运行：

```bash
python -B -m pytest tests -q -rs
```

结果：

```text
907 passed, 77 skipped
```

其中 63 个 slow 测试由 `tests/conftest.py` 默认跳过。

### 13.2 定向 slow 测试

运行：

```bash
python -B -m pytest \
  tests/test_run_study.py \
  tests/test_study_report.py \
  tests/test_study_runner.py \
  tests/test_toy_dataset.py \
  tests/test_verifier.py \
  --runslow -q
```

结果：

```text
49 failed, 32 passed
```

失败分类：

- `test_run_study.py`：14 失败
  - 13 个由缺失 `tool_stack_kind` 导致
  - 1 个由 package export 与 module name 冲突导致 monkeypatch 失败
- `test_study_report.py`：14 失败
- `test_study_runner.py`：9 失败
  - 同样进入缺失 `tool_stack_kind` 的旧 study 路径
- `test_toy_dataset.py`：12 失败
  - 使用 `shutil.copytree`，但测试文件未 import `shutil`
- `test_verifier.py`：7 通过

结论：旧 study/toy 资产不是“慢但健康”，而是“默认不执行且已经断裂”。

### 13.3 Native-family acceptance

运行：

```bash
python -B run_native_family_acceptance.py \
  --local-only \
  --output-root /tmp/pycodeagent-asset-audit-acceptance
```

结果：

```text
stabilized=False
```

acceptance runner 仍引用以下已删除测试：

```text
tests/test_tools_bootstrap.py
tests/test_schema_following_from_runtime.py
tests/test_schema_following_from_runtime_golden.py
tests/test_runtime_observed_postrun.py
tests/test_runtime_observed_postrun_golden.py
tests/test_runtime_observed_training_prep_golden.py
tests/test_toolview_mutation_data_generation.py
tests/test_runtime_execution_reconciliation.py
```

`tests/test_native_family_acceptance.py` mock 了真实 pytest runner，所以默认单测没有
验证这些路径是否存在。

---

## 14. 建议的安全清理顺序

### Batch A：纯资产清理

不改变核心 runtime 行为：

1. 将 docs 分成 `current / contracts / auxiliary / archive`
2. 只保留一份当前 runtime driver 和一份 maturity framework
3. 合并 `AGENTS.md` 与 `CLAUDE.MD` 的重复真源
4. 处理没有测试消费者的 legacy fixtures
5. 合并重复 multi-agent example/fixture
6. 删除 `examples/buggy_reverser/`
7. 缩减 Claude API trace 和 model-backed compaction fixture

### Batch B：旧路线隔离

1. 决定 study/toy 路径是迁移还是整组归档
2. 将 P3/Mimo/study 根入口移出活动入口面
3. 将 Claude API/native-transformed 路线放入 auxiliary namespace
4. 收窄 `rl/__init__.py` 和 `eval/__init__.py`

### Batch C：内部重复代码清理

1. 删除 `turn_state.py` 中重复的 compaction 实现
2. 删除 runner 和 prompt 中无调用方 helper
3. 处理旧 `command_safety.py`
4. 合并 workspace hash 与 mutation config loader

### Batch D：编排统一

1. 一个 training bundle builder
2. 一个 `RunCampaign/RunMatrix`
3. 一个带 subcommands 的正式 CLI
4. 恢复 current native-family E2E golden 和默认 contract tests

### Batch E：外部树治理

1. 为 slime 添加 upstream pin 和 owned patch manifest
2. 为 codex-rs 添加 reference lock/bootstrap
3. 将 claude_code 移出仓库工作树
4. 为 runs 建立 retention/archive 规则

---

## 15. 第一批高置信候选

如果开始实际清理，建议第一批只触及以下内容：

```text
docs 历史实施计划归档/浓缩
AGENTS.md / CLAUDE.MD 去重
examples/buggy_reverser/
tests/fixtures/deterministic_runtime_task_pack/
tests/fixtures/realistic_runtime_task_pack/
tests/fixtures/local_runtime_trace_bundle_compaction/
tests/fixtures/local_runtime_trace_bundle_native/
五组 legacy runtime-observed fixture
重复的 multi-agent example/fixture
```

在这一批中不修改：

- runtime loop
- ToolView/ToolAdapter
- trajectory/runtime trace contracts
- serializer/mask/tokenizer/contract
- current real-provider runtime code
- multi-agent contract类型
- slime bridge

---

## 16. 目标仓库形态

长期建议收敛为：

```text
source adapters
  - runtime observed
  - raw external agent
  - auxiliary API trace
        |
        v
one model-visible request / trace contract
        |
        v
one PreparedSample contract
        |
        v
one serialize / mask / tokenize / verify builder
        |
        v
consumers
  - slime offline
  - slime online RL
  - HF acceptance smoke
```

eval workload 应只共享一个 RunCampaign，差异通过 task packs、gates、reports 和
postprocessors 表达，而不是继续复制整套运行循环。

---

## 17. 当前决策边界

本文没有授权或执行任何删除。实际清理前仍需明确：

1. 旧 study/toy 路径是否仍有个人实验价值
2. 完整 Claude API trace 是否已有 repo 外备份
3. `runs/` 中哪些结果需要长期留存
4. 是否有人在仓库外 import `pycodeagent.rl.export` 或 `eval.tables`
5. multi-agent mock golden 是修复后重建，还是暂时整体归档

在这些问题确认之前，`DELETE?` 只表示高置信候选，不表示可以无条件删除。
