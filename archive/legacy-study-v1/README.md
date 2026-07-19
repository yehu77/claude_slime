# Legacy Study Archive v1

This directory is a read-only historical reference created by RC-026 and
RC-027. It preserves the repository-relative layout of the retired study,
toy-task, and stage-wrapper route.

The files here are not an active Python package, are excluded from pytest
discovery, and must not be imported or invoked by current repository code.
They are retained for source archaeology only; executable reproducibility and
compatibility shims are explicitly out of scope.

Governance:

- Route decision:
  [`legacy_study_route_decision.json`](../../docs/repository_cleanup/legacy_study_route_decision.json)
- Frozen boundary:
  [`legacy_study_archive_boundary.json`](../../docs/repository_cleanup/legacy_study_archive_boundary.json)
- Integrity record: [`archive_manifest.json`](./archive_manifest.json)

Current runtime campaigns, provider acceptance, ToolView data generation, and
training-data preparation remain in the active repository tree. Any reuse of
an archived implementation requires a new reviewed contract; archived files
must not be copied back as implicit compatibility shims.
