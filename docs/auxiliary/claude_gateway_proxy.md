# Claude Gateway Proxy

> **Auxiliary route:** This capture gateway is registered by RC-029 and is not
> a source-runtime mainline entrypoint. See
> [source route boundaries](../source_route_boundaries.md); RC-030 completed
> its namespace migration.

`claude_gateway_proxy.py` is a small Anthropic-compatible gateway for one job:
capture Claude Code API traces as session-grouped JSONL without mixing in local
runtime artifacts such as subprocess logs, diffs, or verifier results.

It currently proxies only the Claude Code API surface required for trace
collection:

- `POST /v1/messages`
- `POST /v1/messages/count_tokens`

## What It Writes

By default the proxy writes traces under:

```text
runs/claude_gateway_traces/
```

Each Claude Code session is appended to a single JSONL file:

```text
runs/claude_gateway_traces/<session_id>.jsonl
```

If Claude Code does not send `X-Claude-Code-Session-Id`, the proxy falls back
to:

```text
unknown_session_<timestamp>_<short_random>.jsonl
```

Each line is one trace event. The event envelope includes:

- `schema_version`
- `event_type`
- `request_id`
- `session_id`
- `agent_id`
- `parent_agent_id`
- `route`
- `timestamp`
- `data`

Current event types:

- `messages_request`
- `messages_response_headers`
- `messages_stream_chunk`
- `messages_stream_end`
- `messages_error`
- `count_tokens_request`
- `count_tokens_response`
- `count_tokens_error`

Sensitive headers such as `authorization`, `x-api-key`, and `cookie` are
redacted in trace files.

## Start The Proxy

From the repo root:

```powershell
python claude_gateway_proxy.py --host 127.0.0.1 --port 4000
```

Optional overrides:

```powershell
python claude_gateway_proxy.py ^
  --host 127.0.0.1 ^
  --port 4000 ^
  --trace-dir runs/claude_gateway_traces ^
  --upstream-base-url https://api.anthropic.com ^
  --request-timeout-seconds 300
```

## Point Claude Code At The Proxy

In the terminal where you will launch Claude Code:

```powershell
$env:ANTHROPIC_BASE_URL = "http://127.0.0.1:4000"
```

If your setup uses an API key environment variable, keep that configured as you
normally would. The proxy forwards auth headers upstream but does not write
their raw values to disk.

Then run Claude Code normally. For example:

```powershell
claude --bare --print --output-format text "Inspect the repo and summarize the failing test."
```

The proxy will transparently forward requests to Anthropic while appending API
events to the session JSONL file.

## Minimal Workflow

1. Start `claude_gateway_proxy.py`
2. Set `ANTHROPIC_BASE_URL=http://127.0.0.1:4000`
3. Launch Claude Code
4. Inspect `runs/claude_gateway_traces/*.jsonl`

For quick inspection on Windows PowerShell:

```powershell
Get-Content runs\claude_gateway_traces\*.jsonl | Select-Object -First 20
```

## Scope And Non-Goals

This proxy intentionally does not:

- integrate with `AgentHarness`
- capture local subprocess/runtime traces
- write `final.diff`
- write `verifier.json`
- normalize raw events into canonical capabilities
- infer tool calls from stdout or patches

It is an API-trace-only collection path.
