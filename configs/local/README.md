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
