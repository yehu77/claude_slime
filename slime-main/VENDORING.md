# Vendoring Strategy

`slime-main/` is a vendored upstream tree, not a submodule and not a fully
owned first-class package inside this repo.

## Frozen Upstream Baseline

The authoritative upstream is
[`THUDM/slime`](https://github.com/THUDM/slime.git), frozen at the full
immutable commit:

```text
16924b697e86adab96eded3a3d0bf6098a943bb4
```

The machine-readable provenance source is
[`references/slime-upstream.lock.json`](../references/slime-upstream.lock.json).
It records the official archive URL, Apache-2.0 license path and checksum,
acquisition evidence, and the canonical 465-entry upstream tree checksum. The
first repository commit containing this vendor tree is
`c92d21a72dd86dae8838fffa4ec6a7c4d8e8d5f2`, dated
`2026-06-03T16:36:43+08:00`; the original download transport was not recorded
and therefore remains explicitly `unknown`.

Verify the upstream-only projection without changing files:

```bash
python -B -m pycodeagent.dev.slime_vendor verify
```

The comparison evidence is stored in
[`references/slime-vendor-baseline-report.json`](../references/slime-vendor-baseline-report.json).
It shows that all 465 upstream entries match after normalizing the copied
`.agents/skills` symlink placeholder, with no modified, missing, or
unknown-source upstream paths. The nine local-only paths are governed by
[`references/slime-overlay.manifest.json`](../references/slime-overlay.manifest.json),
completed by RC-048, which records an owner, reason, file mode, and SHA-256 for
every overlay file.

## Why It Exists Here

This repo needs a thin offline-training bridge from pycodeagent rollout bundles
into `slime`. Keeping that bridge in-tree makes it possible to validate the
rollout -> dataset -> training-bundle contract without depending on a separate
checkout.

## Owned Local Surface

Changes owned by this repo should stay narrowly scoped to pycodeagent
integration. The manifest above is the exact path source of truth; the owned
surface groups are:

- `slime/rollout/pycodeagent_offline.py`
- `slime/rollout/pycodeagent_native_rl.py`
- `examples/pycodeagent_offline/`
- `VENDORING.md`

Everything else in `slime-main/` should be treated as upstream code unless a
pycodeagent integration requirement forces a change.

## Hard Rules

- Do not add import-time `sys.path` mutation to vendored bridge code.
- Vendored bridge code must assume `pycodeagent` is importable through
  `PYTHONPATH` or an installed package.
- Do not quietly spread pycodeagent-specific edits across unrelated upstream
  `slime` modules.
- If a change is generic to `slime`, prefer keeping it clearly isolated so it
  can be upstreamed or re-applied during the next sync.

## Validation Boundary

The default green path for this repo is still:

```powershell
python -B -m pytest tests -q
```

Owned vendored-bridge coverage lives in the repo-owned suite, especially:

```powershell
python -B -m pytest tests/test_slime_bridge.py tests/test_slime_vendor_bridge.py -q
```

`slime-main/tests` is not currently part of the default required loop in this
repo. If you edit broader vendored `slime` code, you are responsible for
running the relevant upstream tests in a provisioned environment.

## Update Workflow

When syncing `slime-main/` from upstream:

1. Do not overwrite the current tree or its local changes in place.
2. Fetch the exact commit in the tracked source lock into a temporary path.
3. Verify the pristine upstream checksum before applying any local files.
4. Re-apply only the checksum-verified files in the overlay manifest.
5. Re-run the full vendor verifier and repo-owned bridge tests.
6. Update the source lock only when deliberately moving to another full
   upstream commit.

## Verify And Rebuild

The normal read-only check validates the upstream projection, every overlay
file and mode, and the complete expected 474-entry tree:

```bash
python -B -m pycodeagent.dev.slime_vendor verify
```

To prove reconstruction from an already downloaded official archive without
writing a destination:

```bash
python -B -m pycodeagent.dev.slime_vendor rebuild \
  --archive /path/to/slime-16924b697.tar.gz
```

Omit `--archive` to download the exact full-commit archive in the source lock.
Pass `--destination /new/absent/path` only when a materialized comparison tree
is needed. Rebuild verifies the pristine upstream tree first, copies only
manifest-listed overlay files, validates the final tree checksum, and refuses
to replace an existing destination.

An upstream, overlay, mode, missing-file, or unknown-file drift is a hard
failure. Ignored `__pycache__/*.pyc` artifacts are excluded from the contract
and should be removed through normal repository hygiene.
