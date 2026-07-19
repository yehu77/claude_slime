---
schema: repository-cleanup-goal/v1
id: RC-042
title: 实现唯一 training bundle builder
status: done
batch: D
action: merge
priority: P0
risk: high
size: L
depends_on: [RC-041]
source_audit: docs/repository_asset_audit.md
source_sections: ["5.4 Training prep 四套重复编排", "16. 目标仓库形态"]
created: 2026-07-14
updated: 2026-07-17
completed: 2026-07-17
---

# RC-042：实现唯一 training bundle builder

## 目标

让所有 source adapter 通过同一个 dataset→tokenize→mask→pack→contract-verify 编排生成 slime-compatible bundle。

## 范围

- 包含：共享 builder、source adapters、manifest/version、确定性排序和现有四入口迁移。
- 保护：source-specific raw trace/catalog 仍作为一等 artifact，不被 builder 扁平化覆盖。

## 工作项与验收

- [x] 实现以 RC-041 为输入合同的单一 builder。
- [x] 四条旧路径对 RC-040 corpus 产生合同等价输出或有版本化迁移说明。
- [x] 重复 tokenization/mask/packing orchestration 被删除。
- [x] deterministic rebuild/checksum、mainline、全量测试和 `git diff --check` 通过。

## 结果

新增唯一的
`pycodeagent.rl.training_bundle.TrainingBundleBuilder`。它接收 RC-041
`PreparedSample` v1，按 split/task/profile/sample/source/type 稳定排序，并统一
执行 tokenize、label/mask alignment、greedy packing、round-trip contract
verification、配置写盘和 SHA-256 manifest 生成。

四条现有入口均已迁移：

| Source adapter | 保留的 source-owned 证据 | 共享 bundle |
| --- | --- | --- |
| rollout | `dataset_manifest.json`、`rollouts.jsonl`、run outcome | 根目录 |
| schema-following | split、dataset manifest、split metrics | 根目录 |
| runtime-observed | 独立 `raw_dataset/` 及 profile/source manifests | `prepared/` |
| native-transformed | auxiliary raw dataset、validation report、trace/catalog provenance | 根目录 |

每个共享 bundle 现在都有 `samples.jsonl`、`tokenized.jsonl`、
`packed.jsonl`、tokenizer/train config、`contract_report.json` 和
`bundle_manifest.json`。manifest v1 记录 PreparedSample version、稳定排序规则、
sample/tokenized/packed counts、source artifact 引用和六个 builder-owned
artifact 的 SHA-256/size。`verify_training_bundle_manifest` 会拒绝未知 version、
越界路径、缺失文件和 checksum/size 变化。

rollout/schema 原始合同检查被拆成 validation-only source adapter，不再在 prep
入口重复 tokenization/packing；native 原先缺失的 shared contract report 与
packing 也已补齐。空 bundle 默认失败，但为保持已有 rollout/runtime/native
post-run 行为，兼容 adapter 必须显式设置 `allow_empty=True`，并同步写入
`TrainConfig.allow_empty_dataset`。失败构建会写 contract report 且移除旧 success
manifest，避免残留成功状态。

详细合同见
[`training_bundle_contract.md`](../../training_bundle_contract.md)。RC-040
characterization 已升级为 v3，显式记录新增 `packed.jsonl`/
`bundle_manifest.json` 和 native contract migration。

验收结果：新增 4 个 builder mainline 测试，覆盖完整 bundle、稳定排序、重复构建
字节一致、SHA-256 防篡改、duplicate ID 失败与失败时无 success manifest；
mainline `99 passed, 3 deselected`；local-only native-family acceptance
`stabilized=True`；全量 `994 passed, 77 skipped`；`git diff --check` 通过。

## 决策记录

- 2026-07-14：统一共享编排，不强迫不同 raw source 使用同一种采集 adapter。
- 2026-07-17：`packed.jsonl` 作为 builder-owned artifact 物化；下游仍可直接使用
  `tokenized.jsonl`，两者都受 manifest checksum 保护。
- 2026-07-17：source artifacts 只在 manifest 中引用，不复制或扁平化 raw
  trace/catalog/runtime dataset。
- 2026-07-17：recommendation model 和 runtime-observed nested layout 保持
  adapter compatibility；campaign/run-matrix 不属于本目标。
