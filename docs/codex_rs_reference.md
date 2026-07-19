# Codex-rs Reference Lock

The ignored `codex-rs/` tree is an optional implementation reference for local
runtime subsystem mapping. Its provenance is tracked in
[`references/codex-rs.lock.json`](../references/codex-rs.lock.json); the tree
itself remains ignored and is never a repository runtime or test dependency.

## Locked Source

The authoritative source is the `codex-rs` subtree of
[`openai/codex`](https://github.com/openai/codex) at the immutable commit:

```text
0beb5c7f32cf5459a51e3f6bc01e6509d7951854
```

The upstream repository is licensed under Apache-2.0. The lock records the
repository URL, full commit, archive URL, upstream license path, materialized
subtree path, entry count, and canonical tree checksum.

This reference may guide decomposition and behavior analysis. Do not import
from it, copy it into `pycodeagent`, invoke it at runtime, or make ordinary
tests require its presence.

## Verify

From the repository root:

```bash
python -B -m pycodeagent.dev.codex_reference verify
```

For machine-readable output:

```bash
python -B -m pycodeagent.dev.codex_reference verify --json
```

The command has three outcomes:

| State | Exit | Meaning |
| --- | ---: | --- |
| `ok` | 0 | The local tree has the locked entry count and checksum. |
| `mismatch` | 1 | A path, file byte sequence, symlink target, or entry count differs. Move the local tree aside before bootstrapping; the tool never overwrites it. |
| `missing` | 2 | The optional tree is absent. Runtime and normal tests remain valid; the diagnostic prints the bootstrap command. |

The checksum is `sha256-tree-manifest-v1`: it hashes sorted relative paths,
regular-file sizes and content hashes, and symlink targets. Timestamps and
permission bits are intentionally excluded because archive extraction can
change them without changing source. The lock declares the one upstream
symlink, `vendor/bubblewrap/LICENSE -> COPYING`. A source-copy tool may
materialize that link as a regular file containing exactly `COPYING`; the
verifier normalizes only this declared portable placeholder form and reports
when it was observed.

## Bootstrap

To materialize a missing tree from the exact locked commit:

```bash
python -B -m pycodeagent.dev.codex_reference bootstrap
```

The bootstrapper downloads the commit archive, extracts only `codex-rs/` into
a staging directory, validates the tracked checksum, and then installs the
tree at `codex-rs/`. It refuses to replace an existing path. A local archive
can be used for offline validation:

```bash
python -B -m pycodeagent.dev.codex_reference bootstrap \
  --archive /path/to/openai-codex-commit.tar.gz
```

If verification reports a mismatch, retain or move the existing tree as
needed, bootstrap a clean copy, and compare the two explicitly. Do not update
the lock merely to accept unexplained local drift.

## Updating the Reference

A future lock update must be deliberate:

1. choose a full immutable commit from the official repository;
2. confirm the repository license at that commit;
3. materialize the official `codex-rs` subtree outside the active reference;
4. compute and review its canonical digest and declared symlinks;
5. update the lock, implementation-plan evidence, and tests together;
6. run the verifier, offline mainline gates, full tests, and
   `git diff --check`.

Changing this lock does not authorize a product dependency or source-code copy.
