# Local Runtime and P3 Planning Archive

- Archived on: 2026-07-16
- Archive goal: RC-015
- Source namespace: `docs/`
- Owner: historical-records
- Status: read-only historical evidence

This directory preserves the local-runtime and P3 planning generation that was
replaced by the current codex-rs subsystem driver, industrial-gap acceptance
framework, and native-family ADR. The files remain useful for reconstructing
why trace, recovery, context, compaction, and result-fidelity work was added,
but none is a current construction schedule.

Current work should start from:

1. [ADR-0001](../../adr/0001-native-family-runtime-boundary.md) for the
   native-family boundary;
2. [the codex-rs subsystem implementation plan](../../codex_rs_subsystem_implementation_plan.md)
   for construction order;
3. [the industrial gap roadmap](../../local_runtime_industrial_gap_roadmap.md)
   for maturity and acceptance.

## Retained Records

| Archived file | Original path | Completion at archive time | Replacement | Why retained |
| --- | --- | --- | --- | --- |
| [P3plan.md](./P3plan.md) | `docs/P3plan.md` | Partially implemented and superseded: retained-history/request-context and model-backed compaction machinery exist, while final compaction policy is still governed separately. | [codex-rs driver](../../codex_rs_subsystem_implementation_plan.md), [industrial gap roadmap](../../local_runtime_industrial_gap_roadmap.md), and [RC-033](../../repository_cleanup/goals/RC-033-freeze-compaction-contract.md) | Preserves the P3-A/P3-B split and original compaction acceptance reasoning. |
| [local_runtime_85_maturity_execution_plan.md](./local_runtime_85_maturity_execution_plan.md) | `docs/local_runtime_85_maturity_execution_plan.md` | Mixed implementation blueprint; several runtime-core capabilities landed, but the percentage target was never a release or product claim. | [codex-rs driver](../../codex_rs_subsystem_implementation_plan.md) and [industrial gap roadmap](../../local_runtime_industrial_gap_roadmap.md) | Preserves source-subsystem mapping and historical maturity criteria. |
| [local_runtime_maturation_plan.md](./local_runtime_maturation_plan.md) | `docs/local_runtime_maturation_plan.md` | Partially implemented, then superseded; trace-first artifacts landed while generic text-mode and builtin-tool assumptions were removed. | [ADR-0001](../../adr/0001-native-family-runtime-boundary.md), [codex-rs driver](../../codex_rs_subsystem_implementation_plan.md), and [industrial gap roadmap](../../local_runtime_industrial_gap_roadmap.md) | Preserves the earliest trace-first runtime rationale and milestone shape. |
| [local_runtime_realism_mainline_plan.md](./local_runtime_realism_mainline_plan.md) | `docs/local_runtime_realism_mainline_plan.md` | Substantially implemented as a generation of work and then superseded as a schedule; its R1-R6 labels are no longer current ordering. | [codex-rs driver](../../codex_rs_subsystem_implementation_plan.md) and [industrial gap roadmap](../../local_runtime_industrial_gap_roadmap.md) | Preserves the decision to prioritize source-runtime realism and observed-data fidelity. |
| [runtime_r1_implementation_note.md](./runtime_r1_implementation_note.md) | `docs/runtime_r1_implementation_note.md` | Implemented historical milestone. | [codex-rs driver](../../codex_rs_subsystem_implementation_plan.md) | Preserves the exact recovery/continuation milestone and its original verification surface. |
| [runtime_r3_implementation_note.md](./runtime_r3_implementation_note.md) | `docs/runtime_r3_implementation_note.md` | Implemented for the former generic tool surface, then superseded by the native-only family cutover. | [ADR-0001](../../adr/0001-native-family-runtime-boundary.md) and [native-family acceptance](../../tool_runtime_native_family_acceptance_and_regression_plan.md) | Preserves result-fidelity decisions without presenting removed generic tools as current. |

## Archive Rules

- Do not update these records to describe current interfaces; corrections
  should be limited to broken links or an explicit archival annotation.
- Do not link these files from the active reading order as implementation
  drivers.
- When a historical decision remains current, restate it in an ADR, contract,
  or active driver and link that current source from this manifest.
- Git history remains the source for line-level evolution before this archive
  date.
