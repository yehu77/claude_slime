# Local Configs

Files in this directory are compatibility fallbacks for machine-local runtime
settings. New local setups should prefer an external config directory such as:

- `%LOCALAPPDATA%\pycodeagent\configs` on Windows
- `~/.cache/pycodeagent/configs` on Unix-like systems
- or an explicit `PYCODEAGENT_LOCAL_CONFIG_DIR`

Rules:

- Commit only `*.example.json`.
- Keep real `*.local.json` files untracked.
- Prefer environment variables for secrets instead of storing them inline.
- Prefer external machine-local config directories over repo-local files.

For the generic MIMO/OpenAI-compatible connection helper:

1. Copy `mimo_v25pro.local.example.json` to your machine-local config directory
2. Name it `mimo_v25pro.local.json`
3. Fill non-secret connection fields such as `base_url` and retry settings
4. Export the API key via `MIMO_API_KEY`

If you must keep a secret inline for a one-off local run, the loader still
accepts `api_key`, but it will emit a warning and that is not the recommended
path. This file is a connection example only; it does not select a study,
task pack, or output directory.

## Formal Real-Provider Runtime Mainline

The current local-runtime mainline should prefer the formal real-provider
config contract instead of the older MIMO-only helper path.

Use:

- `configs/local/real_provider_runtime.local.example.json`
- `python -B -m pycodeagent run`
- `python -B -m pycodeagent campaign`
- `python -B -m pycodeagent acceptance`
- [docs/real_provider_runtime_usage.md](../../docs/real_provider_runtime_usage.md)

Recommended secret flow:

1. Copy [.env.example](../../.env.example) to `.env`
2. Fill `PYCODEAGENT_API_KEY`
3. Fill `PYCODEAGENT_MODEL`
4. Run the formal smoke task or an active runtime campaign subcommand

The runtime will auto-load `.env` before resolving provider config. Exported
shell variables still take precedence over `.env` values.

Optional fallback:

1. Copy `real_provider_runtime.local.example.json` to a machine-local config
   directory as `real_provider_runtime.local.json`
2. Fill non-secret overrides such as `model`, `base_url`, or retry settings
3. Keep the secret itself in the environment

Unlike the older compatibility helper, the formal runtime provider config does
not allow inline `api_key`.
