"""Anthropic-compatible Claude Code gateway for API-trace collection.

This proxy is intentionally scoped to API traces only:

- proxies only the Anthropic Messages API surface needed by Claude Code
- captures request / response events keyed by Claude Code session id
- preserves streaming behavior with async pass-through forwarding
- avoids local runtime capture such as subprocesses, diffs, or verifiers
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse

SCHEMA_VERSION = 1
DEFAULT_UPSTREAM_BASE_URL = "https://api.anthropic.com"
DEFAULT_TRACE_DIR = Path("runs/claude_gateway_traces")
SESSION_HEADER = "x-claude-code-session-id"
AGENT_HEADER = "x-claude-code-agent-id"
PARENT_AGENT_HEADER = "x-claude-code-parent-agent-id"
SENSITIVE_HEADERS = {"authorization", "x-api-key", "cookie", "proxy-authorization"}
TRACEABLE_HEADERS = {
    "anthropic-beta",
    "anthropic-version",
    "x-api-key",
    "authorization",
    "cookie",
    "content-type",
    "accept",
    "user-agent",
    SESSION_HEADER,
    AGENT_HEADER,
    PARENT_AGENT_HEADER,
}
FORWARDED_HEADERS = {
    "anthropic-beta",
    "anthropic-version",
    "x-api-key",
    "authorization",
    "content-type",
    "accept",
}
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
_SESSION_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def build_fallback_session_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    return f"unknown_session_{stamp}_{uuid.uuid4().hex[:8]}"


def sanitize_session_id(value: str) -> str:
    cleaned = _SESSION_SAFE.sub("_", value).strip("._-")
    return cleaned or build_fallback_session_id()


def ensure_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [ensure_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): ensure_jsonable(item) for key, item in value.items()}
    return str(value)


def maybe_parse_json_bytes(payload: bytes) -> Any:
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload.decode("utf-8", errors="replace")


def trace_headers(headers: httpx.Headers | dict[str, str]) -> dict[str, Any]:
    traced: dict[str, Any] = {}
    items = headers.items() if hasattr(headers, "items") else dict(headers).items()
    for key, value in items:
        lower = key.lower()
        if lower not in TRACEABLE_HEADERS:
            continue
        if lower in SENSITIVE_HEADERS:
            traced[key] = {"present": True, "redacted": True}
        else:
            traced[key] = value
    return traced


def forward_headers(request: Request) -> dict[str, str]:
    forwarded: dict[str, str] = {}
    for key, value in request.headers.items():
        lower = key.lower()
        if lower in HOP_BY_HOP_HEADERS:
            continue
        if lower in FORWARDED_HEADERS or lower.startswith("anthropic-") or lower.startswith("x-claude-code-"):
            forwarded[key] = value
            continue
        if lower not in SENSITIVE_HEADERS:
            forwarded[key] = value
    return forwarded


def response_headers_for_client(headers: httpx.Headers) -> dict[str, str]:
    forwarded: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in HOP_BY_HOP_HEADERS:
            continue
        forwarded[key] = value
    return forwarded


def warn_trace_failure(exc: Exception) -> None:
    sys.stderr.write(
        f"[claude_gateway_proxy] warning: failed to write trace event: {type(exc).__name__}: {exc}\n"
    )
    sys.stderr.flush()


@dataclass(slots=True)
class AppConfig:
    upstream_base_url: str
    trace_dir: Path
    request_timeout_seconds: float
    upstream_transport: httpx.AsyncBaseTransport | None = None


class JsonlSessionTraceWriter:
    """Append JSONL events per Claude Code session id."""

    def __init__(self, trace_dir: Path) -> None:
        self._trace_dir = trace_dir
        self._trace_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    def path_for(self, session_id: str) -> Path:
        return self._trace_dir / f"{sanitize_session_id(session_id)}.jsonl"

    async def append_event(
        self,
        *,
        event_type: str,
        request_id: str,
        session_id: str,
        agent_id: str | None,
        parent_agent_id: str | None,
        route: str,
        data: dict[str, Any],
    ) -> None:
        record = {
            "schema_version": SCHEMA_VERSION,
            "event_type": event_type,
            "request_id": request_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "parent_agent_id": parent_agent_id,
            "route": route,
            "timestamp": utc_now(),
            "data": ensure_jsonable(data),
        }
        lock = self._lock_for(session_id)
        async with lock:
            path = self.path_for(session_id)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")
                handle.flush()


def build_app(config: AppConfig) -> Starlette:
    writer = JsonlSessionTraceWriter(config.trace_dir)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        app.state.config = config
        app.state.trace_writer = writer
        app.state.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.request_timeout_seconds),
            follow_redirects=False,
            transport=config.upstream_transport,
        )
        try:
            yield
        finally:
            await app.state.http_client.aclose()

    app = Starlette(debug=False, lifespan=lifespan)

    async def healthz(_request: Request) -> Response:
        return JSONResponse(
            {
                "ok": True,
                "schema_version": SCHEMA_VERSION,
                "trace_dir": str(config.trace_dir),
                "upstream_base_url": config.upstream_base_url,
            }
        )

    async def proxy_messages(request: Request) -> Response:
        return await _proxy_messages(
            request,
            route="/v1/messages",
            config=config,
            writer=writer,
        )

    async def proxy_count_tokens(request: Request) -> Response:
        return await _proxy_count_tokens(
            request,
            route="/v1/messages/count_tokens",
            config=config,
            writer=writer,
        )

    app.add_route("/healthz", healthz, methods=["GET"])
    app.add_route("/v1/messages", proxy_messages, methods=["POST"])
    app.add_route("/v1/messages/count_tokens", proxy_count_tokens, methods=["POST"])
    return app


async def _append_event_safely(
    writer: JsonlSessionTraceWriter,
    *,
    event_type: str,
    request_id: str,
    session_id: str,
    agent_id: str | None,
    parent_agent_id: str | None,
    route: str,
    data: dict[str, Any],
) -> None:
    try:
        await writer.append_event(
            event_type=event_type,
            request_id=request_id,
            session_id=session_id,
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            route=route,
            data=data,
        )
    except Exception as exc:
        warn_trace_failure(exc)


def _extract_session_tuple(request: Request) -> tuple[str, str | None, str | None]:
    session_id = request.headers.get(SESSION_HEADER) or build_fallback_session_id()
    agent_id = request.headers.get(AGENT_HEADER)
    parent_agent_id = request.headers.get(PARENT_AGENT_HEADER)
    return session_id, agent_id, parent_agent_id


async def _proxy_messages(
    request: Request,
    *,
    route: str,
    config: AppConfig,
    writer: JsonlSessionTraceWriter,
) -> Response:
    session_id, agent_id, parent_agent_id = _extract_session_tuple(request)
    request_id = f"request_{uuid.uuid4().hex}"
    request_body = await request.body()
    request_payload = maybe_parse_json_bytes(request_body)
    request_headers = forward_headers(request)

    await _append_event_safely(
        writer,
        event_type="messages_request",
        request_id=request_id,
        session_id=session_id,
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
        route=route,
        data={
            "headers": trace_headers(request.headers),
            "body": request_payload,
        },
    )

    client: httpx.AsyncClient = request.app.state.http_client
    upstream_url = f"{config.upstream_base_url.rstrip('/')}{route}"

    try:
        upstream_stream = client.stream(
            "POST",
            upstream_url,
            headers=request_headers,
            content=request_body,
        )
        upstream_response = await upstream_stream.__aenter__()
    except Exception as exc:
        error_text = f"upstream request failed: {type(exc).__name__}: {exc}"
        await _append_event_safely(
            writer,
            event_type="messages_error",
            request_id=request_id,
            session_id=session_id,
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            route=route,
            data={"phase": "connect", "error": error_text},
        )
        return PlainTextResponse(error_text, status_code=502)

    response_headers = response_headers_for_client(upstream_response.headers)
    await _append_event_safely(
        writer,
        event_type="messages_response_headers",
        request_id=request_id,
        session_id=session_id,
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
        route=route,
        data={
            "status_code": upstream_response.status_code,
            "headers": trace_headers(upstream_response.headers),
        },
    )
    if upstream_response.status_code >= 400:
        await _append_event_safely(
            writer,
            event_type="messages_error",
            request_id=request_id,
            session_id=session_id,
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            route=route,
            data={
                "phase": "response_headers",
                "status_code": upstream_response.status_code,
            },
        )

    async def stream_response() -> Any:
        chunk_index = 0
        stream_error: str | None = None
        try:
            async for chunk in upstream_response.aiter_raw():
                if not chunk:
                    continue
                await _append_event_safely(
                    writer,
                    event_type="messages_stream_chunk",
                    request_id=request_id,
                    session_id=session_id,
                    agent_id=agent_id,
                    parent_agent_id=parent_agent_id,
                    route=route,
                    data={
                        "index": chunk_index,
                        "text": chunk.decode("utf-8", errors="replace"),
                    },
                )
                chunk_index += 1
                yield chunk
        except Exception as exc:
            stream_error = f"streaming failed: {type(exc).__name__}: {exc}"
            await _append_event_safely(
                writer,
                event_type="messages_error",
                request_id=request_id,
                session_id=session_id,
                agent_id=agent_id,
                parent_agent_id=parent_agent_id,
                route=route,
                data={"phase": "stream", "error": stream_error},
            )
            raise
        finally:
            await _append_event_safely(
                writer,
                event_type="messages_stream_end",
                request_id=request_id,
                session_id=session_id,
                agent_id=agent_id,
                parent_agent_id=parent_agent_id,
                route=route,
                data={
                    "status_code": upstream_response.status_code,
                    "chunk_count": chunk_index,
                    "error": stream_error,
                },
            )
            await upstream_stream.__aexit__(None, None, None)

    return StreamingResponse(
        stream_response(),
        status_code=upstream_response.status_code,
        headers=response_headers,
    )


async def _proxy_count_tokens(
    request: Request,
    *,
    route: str,
    config: AppConfig,
    writer: JsonlSessionTraceWriter,
) -> Response:
    session_id, agent_id, parent_agent_id = _extract_session_tuple(request)
    request_id = f"request_{uuid.uuid4().hex}"
    request_body = await request.body()
    request_payload = maybe_parse_json_bytes(request_body)
    request_headers = forward_headers(request)

    await _append_event_safely(
        writer,
        event_type="count_tokens_request",
        request_id=request_id,
        session_id=session_id,
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
        route=route,
        data={
            "headers": trace_headers(request.headers),
            "body": request_payload,
        },
    )

    client: httpx.AsyncClient = request.app.state.http_client
    upstream_url = f"{config.upstream_base_url.rstrip('/')}{route}"

    try:
        upstream_response = await client.post(
            upstream_url,
            headers=request_headers,
            content=request_body,
        )
    except Exception as exc:
        error_text = f"upstream request failed: {type(exc).__name__}: {exc}"
        await _append_event_safely(
            writer,
            event_type="count_tokens_error",
            request_id=request_id,
            session_id=session_id,
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            route=route,
            data={"phase": "connect", "error": error_text},
        )
        return PlainTextResponse(error_text, status_code=502)

    response_headers = response_headers_for_client(upstream_response.headers)
    response_payload = maybe_parse_json_bytes(upstream_response.content)
    await _append_event_safely(
        writer,
        event_type="count_tokens_response",
        request_id=request_id,
        session_id=session_id,
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
        route=route,
        data={
            "status_code": upstream_response.status_code,
            "headers": trace_headers(upstream_response.headers),
            "body": response_payload,
        },
    )
    if upstream_response.status_code >= 400:
        await _append_event_safely(
            writer,
            event_type="count_tokens_error",
            request_id=request_id,
            session_id=session_id,
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            route=route,
            data={
                "phase": "response",
                "status_code": upstream_response.status_code,
                "body": response_payload,
            },
        )

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Anthropic-compatible Claude Code gateway for API-trace collection."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4000)
    parser.add_argument(
        "--upstream-base-url",
        default=os.environ.get("ANTHROPIC_UPSTREAM_BASE_URL", DEFAULT_UPSTREAM_BASE_URL),
    )
    parser.add_argument(
        "--trace-dir",
        default=os.environ.get("CLAUDE_GATEWAY_TRACE_DIR", str(DEFAULT_TRACE_DIR)),
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=float(os.environ.get("CLAUDE_GATEWAY_REQUEST_TIMEOUT_SECONDS", "300")),
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    config = AppConfig(
        upstream_base_url=args.upstream_base_url,
        trace_dir=Path(args.trace_dir),
        request_timeout_seconds=args.request_timeout_seconds,
    )
    uvicorn.run(build_app(config), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
