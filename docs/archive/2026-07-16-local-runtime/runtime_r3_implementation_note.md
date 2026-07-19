# Runtime R3 Implementation Note

> Archived by RC-015 on 2026-07-16. This is historical implementation
> evidence, not a current construction schedule. See this archive's README for
> provenance, completion status, and replacement documents.

R3 freezes the current local-runtime canonical tool surface as the baseline
for realistic short-horizon coding loops:

- `list_files`
- `read_file`
- `write_file`
- `create_file`
- `search_code`
- `apply_patch`
- `run_command`
- `python_run`
- `finish`

This phase does not add new canonical tools and does not change the
`ToolResult` top-level shape. The goal is to make existing tool results more
stable, richer, and easier to audit from runtime traces.

The main contract additions in R3 are:

- file tools carry stable `operation` / `requested_path` context
- `write_file` and `create_file` record `line_count_written` and
  `newline_terminated`
- `search_code` carries explicit request context on both success and failure
- `apply_patch` records per-file operations and create/modify/delete counts
- `run_command` records `requested_cwd`, `parsed_executable`, and `arg_count`
- `python_run` records `requested_cwd`, `execution_kind`, and `target_kind`

R3 deliberately stops at result fidelity. It does not broaden command policy
or protected-path behavior. Those safety-boundary changes remain part of R4.
