# Local Ignored Assets

Status: active governance boundary, updated by RC-050 on 2026-07-19.

Ignored paths are not repository dependencies merely because they happen to
exist beside tracked code. They may contain machine configuration, external
reference source, generated evidence, caches, or credentials. Cleanup goals
must classify them by ownership and reversibility before moving or deleting
them.

## Current boundaries

| Asset | Role | Repository dependency | Handling |
| --- | --- | --- | --- |
| `.env` and `configs/local/*.local.json` | machine-local provider configuration | optional local runtime input | keep ignored; never inventory secret values |
| `runs/` | raw and derived research evidence | runtime output, not source dependency | follow the runs inventory, retention, archive, and writer contracts |
| `codex-rs/` | locked external implementation reference | optional, never imported or required by normal tests | verify or bootstrap through `references/codex-rs.lock.json` |
| former `claude_code/` | local Claude Code 2.1.88 research derivative | none; adapters resolve `claude` from PATH | externalized by RC-051; retain verified local reference |
| virtual environments, bytecode, and tool caches | rebuildable machine state | none | delete only through ordinary local hygiene, outside repository asset claims |

## Claude Code local reference

RC-050 audited the formerly ignored `claude_code/` tree as approximately 133 MB with
1,927 files. It contains the packaged CLI, source map, extracted source, and
bundled vendor assets. Git tracks none of it, and no tracked module, test, or
runbook loads that directory. The `ClaudeCodeAdapter` invokes the executable
name `claude` through PATH; occurrences of the semantic agent ID
`claude_code` are not filesystem dependencies.

RC-051 completed the selected disposition:

```text
preserve exact local evidence
  -> copy it to the durable local reference store
  -> verify a deterministic full-tree digest and entry count
  -> remove the worktree source only after verification
```

The retained destination boundary is
`${XDG_DATA_HOME:-$HOME/.local/share}/pycodeagent/references/claude-code/2.1.88/research-tree`.
It is local-machine-only, outside every Git worktree, and must not be a NAS,
cloud, object-storage, or shared publication target. Tracked files may retain
only sanitized version, count, checksum, and disposition metadata.

The verified tree digest is
`fe875b60f7df36978d5ee06d9e10823510a3c503664f619ddbb432b74e44bccb`
for 1,927 entries. The package version is useful acquisition evidence but is not treated as a
complete reproduction lock: the local tree includes a source-map-derived
research layout. RC-051 therefore performed a verified move rather than
deleting and later assuming npm can reconstruct identical bytes. The
worktree source is now absent; the external copy remains the restoration
source.

The authoritative machine-readable audit and move preconditions are in
[`claude_code_tree_decision.json`](./repository_cleanup/claude_code_tree_decision.json).
The sanitized completion evidence is
[`claude-code-local-reference.json`](../references/claude-code-local-reference.json).
Neither file contains the machine-specific absolute destination or raw source
contents.

## Decision rules

- Never interpret `.gitignore` as deletion authorization.
- Never read or record secret values while classifying local configuration.
- Do not make CI or ordinary tests depend on the presence of an ignored local
  reference.
- A local reference move must fail closed: copy, verify, then remove the
  source; retain the source on any mismatch.
- Permanent deletion requires a separate explicit authorization when the
  governing decision does not already grant it.
