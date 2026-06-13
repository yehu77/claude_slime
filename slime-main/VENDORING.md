# Vendoring Strategy

`slime-main/` is a vendored upstream tree, not a submodule and not a fully
owned first-class package inside this repo.

## Why It Exists Here

This repo needs a thin offline-training bridge from pycodeagent rollout bundles
into `slime`. Keeping that bridge in-tree makes it possible to validate the
rollout -> dataset -> training-bundle contract without depending on a separate
checkout.

## Owned Local Surface

Changes owned by this repo should stay narrowly scoped to pycodeagent
integration:

- `slime/rollout/pycodeagent_offline.py`
- `examples/pycodeagent_offline/`
- minimal docs that explain the pycodeagent offline path

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

1. Start from a clean upstream snapshot.
2. Re-apply only the explicit pycodeagent-owned deltas listed above.
3. Re-run the repo-owned bridge tests.
4. Update this file if the owned surface or validation boundary changes.

## Current Gap

This repo does not yet record a precise upstream commit or tag for the current
snapshot. The next full vendor refresh should add that provenance explicitly.
