# Documentation Map

This is the single navigation page for repository-owned documentation. It
separates the documents that guide current work from contracts, runbooks, and
historical records so an older implementation plan cannot silently become a
new construction schedule.

The document inventory below is the taxonomy source of truth. It classifies
every Markdown document under `docs/`, including the self-indexed cleanup
collection. The machine check is:

```bash
python -B -m pytest -q tests/test_docs_taxonomy.py
```

## Reading Order

Read these in order for current implementation work:

1. [Project intent and decision rules](../AGENTS.md).
2. [Native-family runtime ADR](./adr/0001-native-family-runtime-boundary.md)
   — the canonical terminology, selection, fallback, artifact, and acceptance
   boundary.
3. [Codex-rs subsystem implementation plan](./codex_rs_subsystem_implementation_plan.md)
   — the sole current construction driver.
4. [Industrial gap roadmap](./local_runtime_industrial_gap_roadmap.md) — the
   maturity map and acceptance framework, not a competing build schedule.
5. [Native-family acceptance runbook](./tool_runtime_native_family_acceptance_and_regression_plan.md)
   — the current offline/local acceptance commands.
6. Consult [scaffold phase one](./scaffold_phase1.md) or the
   [external-agent sidecar protocol](./external_agent_sidecar_protocol.md) only
   when working on the long-term raw-trace integration boundary.

For the broad project direction, see
[the multi-agent scaffold design](../PYCODEAGENT_MULTI_AGENT_SCAFFOLD_DESIGN.md).
Use [source route boundaries](./source_route_boundaries.md) when changing
baseline or auxiliary ingestion/transformation code; those routes are not part
of the implementation reading order above.

## Taxonomy

| Category | Meaning | Use as a construction schedule? |
| --- | --- | --- |
| `current-driver` | The one document that orders active implementation work. | Yes. |
| `contract-reference` | A current contract, maturity framework, protocol, auxiliary reference, evidence snapshot, or governance record. | Only when its stated scope applies. |
| `runbook` | An operational procedure or acceptance guide. | Only after its prerequisites are satisfied. |
| `archive` | Historical implementation evidence. `archive-pending` records stay in place until their owning archive goal moves them. | No. |

`role` distinguishes auxiliary and governance material without creating a
second, competing category system. `owner` names a maintenance boundary rather
than an individual. `superseded by / next action` is always explicit: `—`
means the document remains authoritative within its stated scope.

## Document Inventory

| Path | Category | Role | Owner | Status | Superseded by / next action | Provenance / archive date |
| --- | --- | --- | --- | --- | --- | --- |
| `docs/README.md` | `contract-reference` | navigation | repository-governance | active | — | RC-013, 2026-07-15 |
| `docs/adr/0001-native-family-runtime-boundary.md` | `contract-reference` | architecture-decision | runtime-maintainers | accepted | — | RC-014, 2026-07-16 |
| `docs/codex_rs_subsystem_implementation_plan.md` | `current-driver` | construction | runtime-maintainers | active | — | current mainline |
| `docs/codex_rs_reference.md` | `contract-reference` | external-reference-lock-runbook | runtime-maintainers | active: locked by RC-049 | — | official `openai/codex` immutable subtree reference, 2026-07-18 |
| `docs/compaction_contract.md` | `contract-reference` | runtime-compaction-contract | runtime-maintainers | active: frozen by RC-033 | — | contract v1, 2026-07-17 |
| `docs/local_runtime_industrial_gap_roadmap.md` | `contract-reference` | maturity-and-acceptance | runtime-maintainers | active | — | current acceptance framework |
| `docs/training_prep_behavior_contract.md` | `contract-reference` | training-prep-behavior | training-data-maintainers | active: RC-040 baseline, RC-041/042 migrations | `docs/prepared_sample_contract.md`; `docs/training_bundle_contract.md` | contract v3, 2026-07-17 |
| `docs/prepared_sample_contract.md` | `contract-reference` | prepared-sample-contract | training-data-maintainers | active: defined by RC-041 | — | contract v1, 2026-07-17 |
| `docs/training_bundle_contract.md` | `contract-reference` | training-bundle-contract | training-data-maintainers | active: defined by RC-042 | — | contract v1, 2026-07-17 |
| `docs/run_campaign_contract.md` | `contract-reference` | runtime-campaign-contract | evaluation-maintainers | active: defined by RC-043, adopted by RC-044 | — | contract v1, 2026-07-18 |
| `docs/formal_cli.md` | `contract-reference` | formal-cli-contract | repository-governance | active: defined by RC-045, unique surface enforced by RC-046 | — | contract v1, 2026-07-18 |
| `docs/local_ignored_assets.md` | `contract-reference` | local-ignored-asset-boundary | repository-governance | active: RC-050 decision, RC-051 externalization complete | — | ignored asset decisions, 2026-07-19 |
| `docs/external_agent_sidecar_protocol.md` | `contract-reference` | external-trace-protocol | trace-contract-maintainers | active | — | phase-one integration boundary |
| `docs/external_cli_capability_matrix.md` | `contract-reference` | capability-reference | provider-integration-maintainers | active | — | raw-artifact adapter reference |
| `docs/scaffold_phase1.md` | `contract-reference` | synthetic-first-contract | trace-contract-maintainers | active: reconciled by RC-019 | — | phase-one contract; single golden fixed by RC-012 |
| `docs/source_route_boundaries.md` | `contract-reference` | route-ownership-and-dependency | repository-governance | active: RC-028, RC-029 | — | mainline/baseline/auxiliary boundary |
| `docs/auxiliary/native_transformed_sft_pipeline.md` | `contract-reference` | auxiliary-pipeline | training-data-maintainers | auxiliary: migrated RC-030 | `docs/source_route_boundaries.md` | non-mainline SFT route |
| `docs/auxiliary/native_transformed_rl_pipeline.md` | `contract-reference` | auxiliary-pipeline | training-data-maintainers | auxiliary: migrated RC-030 | `docs/source_route_boundaries.md` | non-mainline RL route |
| `docs/agent_training_infra_architecture.md` | `contract-reference` | auxiliary-architecture | training-data-maintainers | auxiliary: migration-pending RC-030 | `docs/source_route_boundaries.md` | earlier architecture reference |
| `docs/repository_asset_audit.md` | `contract-reference` | dated-evidence-snapshot | repository-governance | snapshot | `docs/repository_cleanup/README.md` | audit, 2026-07-14 |
| `docs/runs_inventory.md` | `contract-reference` | local-run-inventory-contract | repository-governance | active: RC-052 snapshot | `docs/runs_retention_policy.md` | inventory v1, 2026-07-18 |
| `docs/runs_retention_policy.md` | `contract-reference` | local-run-retention-contract | repository-governance | active: defined by RC-053 | `docs/runs_archive.md`; `docs/repository_cleanup/goals/RC-055-enforce-run-retention.md` | policy v1, 2026-07-18 |
| `docs/runs_archive.md` | `contract-reference` | local-run-archive-evidence | repository-governance | active evidence: RC-054 | — | archive `rc054-20260718`, 2026-07-18 |
| `docs/run_writer_retention.md` | `contract-reference` | new-run-retention-enforcement | repository-governance | active: enforced by RC-055 | — | writer contract v1, 2026-07-18 |
| `docs/repository_cleanup/README.md` | `contract-reference` | cleanup-governance | repository-governance | active | — | live goal ledger |
| `docs/repository_cleanup/GOAL_TEMPLATE.md` | `contract-reference` | cleanup-governance-template | repository-governance | active | — | live goal workflow |
| `docs/repository_cleanup/goals/*.md` | `contract-reference` | cleanup-governance-goal | repository-governance | self-indexed | — | goal frontmatter is status source of truth |
| `docs/tool_runtime_native_family_acceptance_and_regression_plan.md` | `runbook` | local-acceptance | runtime-maintainers | active | — | native-family acceptance |
| `docs/real_provider_runtime_usage.md` | `runbook` | provider-usage | provider-integration-maintainers | active: rewritten by RC-017 | — | provider-backed native-family operations |
| `docs/auxiliary/claude_gateway_proxy.md` | `runbook` | auxiliary-gateway | provider-integration-maintainers | auxiliary: migrated RC-030 | `docs/source_route_boundaries.md` | auxiliary trace capture |
| `docs/archive/2026-07-16-local-runtime/README.md` | `archive` | archive-manifest | historical-records | archive-complete: RC-015 | `docs/adr/0001-native-family-runtime-boundary.md`; `docs/codex_rs_subsystem_implementation_plan.md`; `docs/local_runtime_industrial_gap_roadmap.md` | archived 2026-07-16 from `docs/` |
| `docs/archive/2026-07-16-local-runtime/P3plan.md` | `archive` | historical-local-runtime-plan | historical-records | archive-complete: RC-015 | `docs/codex_rs_subsystem_implementation_plan.md`; `docs/local_runtime_industrial_gap_roadmap.md`; `docs/repository_cleanup/goals/RC-033-freeze-compaction-contract.md` | archived 2026-07-16 from `docs/P3plan.md` |
| `docs/archive/2026-07-16-local-runtime/local_runtime_85_maturity_execution_plan.md` | `archive` | historical-local-runtime-plan | historical-records | archive-complete: RC-015 | `docs/codex_rs_subsystem_implementation_plan.md`; `docs/local_runtime_industrial_gap_roadmap.md` | archived 2026-07-16 from `docs/local_runtime_85_maturity_execution_plan.md` |
| `docs/archive/2026-07-16-local-runtime/local_runtime_maturation_plan.md` | `archive` | historical-local-runtime-plan | historical-records | archive-complete: RC-015 | `docs/adr/0001-native-family-runtime-boundary.md`; `docs/codex_rs_subsystem_implementation_plan.md`; `docs/local_runtime_industrial_gap_roadmap.md` | archived 2026-07-16 from `docs/local_runtime_maturation_plan.md` |
| `docs/archive/2026-07-16-local-runtime/local_runtime_realism_mainline_plan.md` | `archive` | historical-local-runtime-plan | historical-records | archive-complete: RC-015 | `docs/codex_rs_subsystem_implementation_plan.md`; `docs/local_runtime_industrial_gap_roadmap.md` | archived 2026-07-16 from `docs/local_runtime_realism_mainline_plan.md` |
| `docs/archive/2026-07-16-local-runtime/runtime_r1_implementation_note.md` | `archive` | historical-runtime-note | historical-records | archive-complete: RC-015 | `docs/codex_rs_subsystem_implementation_plan.md` | archived 2026-07-16 from `docs/runtime_r1_implementation_note.md` |
| `docs/archive/2026-07-16-local-runtime/runtime_r3_implementation_note.md` | `archive` | historical-runtime-note | historical-records | archive-complete: RC-015 | `docs/adr/0001-native-family-runtime-boundary.md`; `docs/tool_runtime_native_family_acceptance_and_regression_plan.md` | archived 2026-07-16 from `docs/runtime_r3_implementation_note.md` |
| `docs/archive/2026-07-16-tool-runtime/README.md` | `archive` | archive-manifest | historical-records | archive-complete: RC-016 | `docs/adr/0001-native-family-runtime-boundary.md`; `docs/codex_rs_subsystem_implementation_plan.md`; `docs/tool_runtime_native_family_acceptance_and_regression_plan.md` | archived 2026-07-16 from `docs/` |
| `docs/archive/2026-07-16-tool-runtime/tool_runtime_family_split_implementation_plan.md` | `archive` | historical-tool-runtime-plan | historical-records | archive-complete: RC-016 | `docs/adr/0001-native-family-runtime-boundary.md`; `docs/codex_rs_subsystem_implementation_plan.md` | archived 2026-07-16 from `docs/tool_runtime_family_split_implementation_plan.md` |
| `docs/archive/2026-07-16-tool-runtime/tool_runtime_legacy_demotion_followup_plan.md` | `archive` | historical-tool-runtime-plan | historical-records | archive-complete: RC-016 | `docs/adr/0001-native-family-runtime-boundary.md`; `docs/tool_runtime_native_family_acceptance_and_regression_plan.md` | archived 2026-07-16 from `docs/tool_runtime_legacy_demotion_followup_plan.md` |
| `docs/archive/2026-07-16-tool-runtime/tool_runtime_step_a_shared_process_primitives_plan.md` | `archive` | historical-tool-runtime-plan | historical-records | archive-complete: RC-016 | `docs/adr/0001-native-family-runtime-boundary.md`; `docs/codex_rs_subsystem_implementation_plan.md` | archived 2026-07-16 from `docs/tool_runtime_step_a_shared_process_primitives_plan.md` |
| `docs/archive/2026-07-16-tool-runtime/tool_runtime_step_b_shell_runtime_integration_plan.md` | `archive` | historical-tool-runtime-plan | historical-records | archive-complete: RC-016 | `docs/adr/0001-native-family-runtime-boundary.md`; `docs/codex_rs_subsystem_implementation_plan.md` | archived 2026-07-16 from `docs/tool_runtime_step_b_shell_runtime_integration_plan.md` |
| `docs/archive/2026-07-16-tool-runtime/tool_runtime_step_c0_native_tool_contract_expansion_plan.md` | `archive` | historical-tool-runtime-plan | historical-records | archive-complete: RC-016 | `docs/adr/0001-native-family-runtime-boundary.md` | archived 2026-07-16 from `docs/tool_runtime_step_c0_native_tool_contract_expansion_plan.md` |
| `docs/archive/2026-07-16-tool-runtime/tool_runtime_step_c_canonical_tool_definitions_plan.md` | `archive` | historical-tool-runtime-plan | historical-records | archive-complete: RC-016 | `docs/adr/0001-native-family-runtime-boundary.md` | archived 2026-07-16 from `docs/tool_runtime_step_c_canonical_tool_definitions_plan.md` |
| `docs/archive/2026-07-16-tool-runtime/tool_runtime_step_d_native_family_profiles_plan.md` | `archive` | historical-tool-runtime-plan | historical-records | archive-complete: RC-016 | `docs/adr/0001-native-family-runtime-boundary.md` | archived 2026-07-16 from `docs/tool_runtime_step_d_native_family_profiles_plan.md` |
| `docs/archive/2026-07-16-tool-runtime/tool_runtime_step_e_bootstrap_registry_selection_plan.md` | `archive` | historical-tool-runtime-plan | historical-records | archive-complete: RC-016 | `docs/adr/0001-native-family-runtime-boundary.md` | archived 2026-07-16 from `docs/tool_runtime_step_e_bootstrap_registry_selection_plan.md` |
| `docs/archive/2026-07-16-tool-runtime/tool_runtime_step_f_native_family_mutation_data_integration_plan.md` | `archive` | historical-tool-runtime-plan | historical-records | archive-complete: RC-016 | `docs/adr/0001-native-family-runtime-boundary.md`; `docs/codex_rs_subsystem_implementation_plan.md`; `docs/tool_runtime_native_family_acceptance_and_regression_plan.md` | archived 2026-07-16 from `docs/tool_runtime_step_f_native_family_mutation_data_integration_plan.md` |
| `docs/archive/2026-07-16-tool-runtime/toolview_mutation_data_generation_plan.md` | `archive` | historical-toolview-plan | historical-records | archive-complete: RC-016 | `docs/adr/0001-native-family-runtime-boundary.md`; `docs/codex_rs_subsystem_implementation_plan.md` | archived 2026-07-16 from `docs/toolview_mutation_data_generation_plan.md` |

## Archive Boundary

RC-013 established the logical archive classification. RC-015 and RC-016 have
now moved the local-runtime/P3 and Tool Runtime planning generations into dated
archives with per-document manifests. Each archive row records its source,
archive date, and current replacement relationship.

Archive documents must never appear in the reading order above or be presented
as current construction drivers. When a physical archive is created, retain
the same fields alongside the moved document and leave a stable redirect or
link at the old location as required by its owning goal.

## Maintenance Rules

When adding, removing, or moving a `docs/**/*.md` file:

1. Update exactly one inventory row above, using one of the four categories.
2. Set an owner boundary, status, and explicit `superseded by / next action`.
3. For an `archive` row, retain a non-empty provenance/date and replacement.
4. Run the documentation gate and `git diff --check` before handoff.

The cleanup goal collection is intentionally represented by one glob row: its
own frontmatter and [goal ledger](./repository_cleanup/README.md) remain the
per-goal status source of truth.
