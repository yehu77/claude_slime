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

For the MIMO study scripts:

1. Copy `mimo_v25pro.local.example.json` to your machine-local config directory
2. Name it `mimo_v25pro.local.json`
3. Fill non-secret fields like `base_url`, `study_config_path`, and `output_dir`
4. Export the API key via `MIMO_API_KEY`

PowerShell example:

```powershell
$env:PYCODEAGENT_LOCAL_CONFIG_DIR = "$env:LOCALAPPDATA\\pycodeagent\\configs"
$env:MIMO_API_KEY = "your-api-key"
python run_first_study_mimo.py
```

If you must keep a secret inline for a one-off local run, the loader still
accepts `api_key`, but it will emit a warning and that is not the recommended
path.

## Formal Real-Provider Runtime Mainline

The current local-runtime mainline should prefer the formal real-provider
config contract instead of the older MIMO-only helper path.

Use:

- `configs/local/real_provider_runtime.local.example.json`
- `run_runtime_smoke_real_provider.py`
- `run_first_study_real_provider.py`
- [docs/real_provider_runtime_usage.md](../../docs/real_provider_runtime_usage.md)

Recommended secret flow:

1. Copy [.env.example](../../.env.example) to `.env`
2. Fill `PYCODEAGENT_API_KEY`
3. Fill `PYCODEAGENT_MODEL`
4. Run the smoke or study entrypoint

The runtime will auto-load `.env` before resolving provider config. Exported
shell variables still take precedence over `.env` values.

Optional fallback:

1. Copy `real_provider_runtime.local.example.json` to a machine-local config
   directory as `real_provider_runtime.local.json`
2. Fill non-secret overrides such as `model`, `base_url`, or retry settings
3. Keep the secret itself in the environment

Unlike the older compatibility helper, the formal runtime provider config does
not allow inline `api_key`.
