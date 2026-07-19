---
schema: repository-cleanup-goal/v1
id: RC-048
title: 增加 slime overlay manifest 与 verifier
status: done
batch: E
action: govern
priority: P1
risk: high
size: L
depends_on: [RC-047]
source_audit: docs/repository_asset_audit.md
source_sections: ["12.1 `slime-main/`", "16. 目标仓库形态"]
created: 2026-07-14
updated: 2026-07-18
completed: 2026-07-18
---

# RC-048：增加 slime overlay manifest 与 verifier

## 目标

把 `slime-main/` 从无法解释的 vendor snapshot 转成“锁定 upstream + 显式 overlay + 可验证重建”。

## 范围

- 包含：upstream lock、overlay patch/file manifest、checksums、bootstrap/verify 命令和 CI 检查。
- 保护：仓库需要的 slime-compatible integration；不在本目标重写 upstream 功能。

## 工作项与验收

- [x] 分类当前 tree 差异为 upstream、intentional overlay 或 unexplained。
- [x] 所有 intentional overlay 有路径、理由、owner 和 checksum/patch。
- [x] 从 locked upstream 在临时目录可确定性重建当前期望 tree。
- [x] verifier 能检测 drift/未知文件；训练 bundle compatibility、相关测试和 `git diff --check` 通过。

## 结果

[`references/slime-overlay.manifest.json`](../../../references/slime-overlay.manifest.json)
现已把 RC-047 的 9 个 candidate 全部晋升为 intentional overlay。每个 record
都包含唯一 path、`add` operation、owner、reason、repo-tracked source path、
mode、size 和 SHA-256；路径集合必须与 upstream lock 的 candidate 集合精确
相等，不能漏项或额外放行。

当前合同为：

- locked upstream：465 entries，
  `64f378f4a0e32102fd82d6e95e07fefcd502bf1ffc4332c3365b3258a87d5835`；
- intentional overlay：9 个 local-only files，全部为 upstream 不存在的
  `add`，不存在隐式 upstream patch；
- expected vendor：474 entries，
  `b953c398a881cc4e3080dd1d41f5674936c2959c32aa461eb3bf3b356325541e`；
- unexplained/unknown paths：0；
- upstream mode 不进入内容 tree digest，9 个 overlay 的 mode 单独严格校验；
- `**/__pycache__/*.pyc` 是唯一明确排除的 ephemeral pattern。

`pycodeagent.dev.slime_vendor` 现在提供：

- `verify-upstream`：只验证 RC-047 pristine projection 和 license；
- `verify`：联合验证 upstream、license、每个 overlay 的 bytes/size/mode，
  再验证完整 474-entry expected tree；overlay drift、mode drift、missing
  file、upstream drift 和 unknown file 均硬失败；
- `rebuild`：下载或读取 exact full-commit archive，在 staging 先验证
  pristine checksum，再只复制 manifest-listed overlay，最后验证完整 tree；
  默认只做临时重建证明，可显式输出到缺失 destination，永不覆盖已有路径。

已使用 RC-047 下载的官方
`16924b697e86adab96eded3a3d0bf6098a943bb4` archive 完成真实临时重建，结果与
当前 expected tree 的 474 entries/checksum 完全一致。重建没有写回
`slime-main/`，现有 bridge 内容原样保留。`VENDORING.md`、README、CI mainline
和 baseline report 已切换到正式 overlay contract。

验收：overlay/source-lock/bridge 专项 `17 passed, 4 skipped`；offline
mainline（含 training bundle compatibility）`115 passed, 3 deselected`；
全量 `1010 passed, 77 skipped`；`git diff --check` 通过。real-provider/local
acceptance 为 N/A：本目标治理 vendored source reconstruction，没有改变
runtime/provider 执行行为。

## 决策记录

- 2026-07-14：目标是可再生依赖，不把整个 vendor tree 继续当作不可审计真源。
- 2026-07-18：9 个差异路径在 locked upstream 中全部不存在，因此统一建模为
  file overlay `add`，没有伪造 upstream patch。
- 2026-07-18：overlay source 直接使用同一批 repo-tracked vendor 文件并由
  manifest checksum 锁定，避免再复制一套易漂移的 shadow source tree。
- 2026-07-18：保留当前脚本的 `0644` mode 作为已审计事实；overlay mode 独立
  校验，未来若改为 executable 必须显式更新 manifest 和验收证据。
- 2026-07-18：重建只允许 absent destination；任何 sync/refresh 都先在
  staging 验证 pristine upstream 和 final tree，不原地覆盖用户工作。
