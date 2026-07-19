# Tool Runtime Planning Archive

- Archived on: 2026-07-16
- Archive goal: RC-016
- Source namespace: `docs/`
- Owner: historical-records
- Status: read-only historical evidence
- Canonical decision: [ADR-0001](../../adr/0001-native-family-runtime-boundary.md)

This directory preserves the planning sequence that introduced shared process
primitives, native tool contracts, Claude/Codex families, profiles, explicit
runtime selection, mutation, and runtime-observed data integration. The
implementation sequence landed and was followed by a native-only cutover, so
these files no longer define current terminology or construction order.

Current work should use:

1. [ADR-0001](../../adr/0001-native-family-runtime-boundary.md) for family,
   selection, fallback, artifact, and acceptance rules;
2. [the codex-rs subsystem implementation plan](../../codex_rs_subsystem_implementation_plan.md)
   for current construction order;
3. [native-family acceptance](../../tool_runtime_native_family_acceptance_and_regression_plan.md)
   for executable acceptance evidence.

## Retained Records

| Archived file | Original path | Status at archive time | Superseded by | Why retained |
| --- | --- | --- | --- | --- |
| [tool_runtime_family_split_implementation_plan.md](./tool_runtime_family_split_implementation_plan.md) | `docs/tool_runtime_family_split_implementation_plan.md` | Implemented through Step F; the subsequent native-only cleanup also landed. | [ADR-0001](../../adr/0001-native-family-runtime-boundary.md) and [codex-rs driver](../../codex_rs_subsystem_implementation_plan.md) | Master sequencing record for the family split and its dependency graph. |
| [tool_runtime_legacy_demotion_followup_plan.md](./tool_runtime_legacy_demotion_followup_plan.md) | `docs/tool_runtime_legacy_demotion_followup_plan.md` | Explicitly superseded; native-only removal replaced the proposed demoted legacy surface. | [ADR-0001](../../adr/0001-native-family-runtime-boundary.md) and [native-family acceptance](../../tool_runtime_native_family_acceptance_and_regression_plan.md) | Short decision trail explaining why legacy compatibility no longer exists. |
| [tool_runtime_step_a_shared_process_primitives_plan.md](./tool_runtime_step_a_shared_process_primitives_plan.md) | `docs/tool_runtime_step_a_shared_process_primitives_plan.md` | Implemented in the shared process-execution substrate. | [ADR-0001](../../adr/0001-native-family-runtime-boundary.md) and [codex-rs driver](../../codex_rs_subsystem_implementation_plan.md) | Preserves the separation between internal process reuse and model-visible tools. |
| [tool_runtime_step_b_shell_runtime_integration_plan.md](./tool_runtime_step_b_shell_runtime_integration_plan.md) | `docs/tool_runtime_step_b_shell_runtime_integration_plan.md` | Implemented as distinct Claude shell, Codex shell, and Codex patch runtime boundaries. | [ADR-0001](../../adr/0001-native-family-runtime-boundary.md) and [codex-rs driver](../../codex_rs_subsystem_implementation_plan.md) | Preserves family-runtime behavior and shared-execution rationale. |
| [tool_runtime_step_c0_native_tool_contract_expansion_plan.md](./tool_runtime_step_c0_native_tool_contract_expansion_plan.md) | `docs/tool_runtime_step_c0_native_tool_contract_expansion_plan.md` | Implemented; function and freeform payload contracts are first-class. | [ADR-0001](../../adr/0001-native-family-runtime-boundary.md) | Preserves why Codex `apply_patch` cannot be silently wrapped as a function tool. |
| [tool_runtime_step_c_canonical_tool_definitions_plan.md](./tool_runtime_step_c_canonical_tool_definitions_plan.md) | `docs/tool_runtime_step_c_canonical_tool_definitions_plan.md` | Implemented as strict source-aligned Claude and Codex canonical families. | [ADR-0001](../../adr/0001-native-family-runtime-boundary.md) | Preserves the native-identity decision and scoped tool-family rationale. |
| [tool_runtime_step_d_native_family_profiles_plan.md](./tool_runtime_step_d_native_family_profiles_plan.md) | `docs/tool_runtime_step_d_native_family_profiles_plan.md` | Implemented as native Claude/Codex ToolProfiles with family provenance. | [ADR-0001](../../adr/0001-native-family-runtime-boundary.md) | Preserves profile-layer and exposed/canonical separation decisions. |
| [tool_runtime_step_e_bootstrap_registry_selection_plan.md](./tool_runtime_step_e_bootstrap_registry_selection_plan.md) | `docs/tool_runtime_step_e_bootstrap_registry_selection_plan.md` | Explicit selection implemented; its temporary legacy coexistence assumptions were removed later. | [ADR-0001](../../adr/0001-native-family-runtime-boundary.md) | Preserves the transition from implicit generic bootstrap to explicit native stacks. |
| [tool_runtime_step_f_native_family_mutation_data_integration_plan.md](./tool_runtime_step_f_native_family_mutation_data_integration_plan.md) | `docs/tool_runtime_step_f_native_family_mutation_data_integration_plan.md` | Implemented across mutation and runtime-observed training-data paths. | [ADR-0001](../../adr/0001-native-family-runtime-boundary.md), [codex-rs driver](../../codex_rs_subsystem_implementation_plan.md), and [native-family acceptance](../../tool_runtime_native_family_acceptance_and_regression_plan.md) | Preserves the end-to-end native-family data-integration design. |
| [toolview_mutation_data_generation_plan.md](./toolview_mutation_data_generation_plan.md) | `docs/toolview_mutation_data_generation_plan.md` | Core mutation/data-generation path implemented; the document's staged route is no longer the main construction schedule. | [ADR-0001](../../adr/0001-native-family-runtime-boundary.md) and [codex-rs driver](../../codex_rs_subsystem_implementation_plan.md) | Preserves schema-mutation research intent and observed-call fidelity requirements. |

## Archive Rules

- Do not revise these records to match current interfaces; use an explicit
  archival note when historical wording could be mistaken for current policy.
- Do not expose them from the active reading order as implementation drivers.
- Current decisions belong in ADRs/contracts, and current work ordering belongs
  in the codex-rs subsystem driver.
- Maintain internal links and links to current sources so the archived design
  evidence stays inspectable.
