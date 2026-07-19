# Tool Runtime Legacy Demotion Follow-Up Plan

> Archived by RC-016 on 2026-07-16. Current native-family terminology and
> policy are defined by
> [ADR-0001](../../adr/0001-native-family-runtime-boundary.md). This file is an
> archival record and cannot override that decision. See this archive's README
> for provenance and replacement mapping.

## Status

This document is **superseded as of July 1, 2026**.

The repository no longer retains a demoted-but-supported legacy builtin tool
surface. The earlier demotion plan was overtaken by the implemented
**native-only cutover**.

That cutover has already landed in code:

- legacy builtin canonical tool modules were deleted
- `build_builtin_registry()` was removed
- `build_base_tool_profile()` was removed
- `build_base_tool_runtime()` was removed
- runtime stack selection became native-only
- mutation, runtime-observed, and downstream entrypoints were migrated off the
  legacy base-profile path

## Current Meaning

This file is kept only as a short archival marker so older references still
resolve.

It should **not** be used as an active planning document.

Use these documents instead:

- [`docs/tool_runtime_family_split_implementation_plan.md`](./tool_runtime_family_split_implementation_plan.md)
  for the implementation status record
- [`docs/tool_runtime_native_family_acceptance_and_regression_plan.md`](../../tool_runtime_native_family_acceptance_and_regression_plan.md)
  for the remaining active acceptance and stabilization work
