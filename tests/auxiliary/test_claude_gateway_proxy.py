"""Tests for the API-trace-only Claude gateway proxy."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

pytest.importorskip("starlette")

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from claude_gateway_proxy import AppConfig, build_app
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir

_TEST_NAMESPACE = "claude_gateway_proxy"


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _build_messages_upstream(
    *,
    status_code: int = 200,
    streaming_chunks: list[str] | None = None,
    fail_on_messages: bool = False,
):
    seen: list[dict] = []

    async def messages(request: Request):
        if fail_on_messages:
            return Response("upstream broken", status_code=502)
        body = await request.body()
        seen.append(
            {
                "path": request.url.path,
                "headers": dict(request.headers),
                "body": json.loads(body),
            }
        )
        if streaming_chunks is not None:
            async def _gen():
                for chunk in streaming_chunks:
                    yield chunk.encode("utf-8")

            return StreamingResponse(
                _gen(),
                status_code=status_code,
                media_type="text/event-stream",
                headers={"x-upstream": "messages"},
            )
        return JSONResponse(
            {"type": "message", "content": [{"type": "text", "text": "ok"}]},
            status_code=status_code,
            headers={"x-upstream": "messages"},
        )

    async def count_tokens(request: Request):
        body = await request.body()
        seen.append(
            {
                "path": request.url.path,
                "headers": dict(request.headers),
                "body": json.loads(body),
            }
        )
        return JSONResponse({"input_tokens": 42}, headers={"x-upstream": "count_tokens"})

    app = Starlette(
        routes=[
            Route("/v1/messages", messages, methods=["POST"]),
            Route("/v1/messages/count_tokens", count_tokens, methods=["POST"]),
        ]
    )
    return app, seen


def _build_client(tmp_path: Path, upstream_app: Starlette) -> TestClient:
    config = AppConfig(
        upstream_base_url="https://upstream.example",
        trace_dir=tmp_path / "traces",
        request_timeout_seconds=30.0,
        upstream_transport=httpx.ASGITransport(app=upstream_app),
    )
    return TestClient(build_app(config))


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


class TestClaudeGatewayProxy:
    def test_messages_non_streaming_forward_and_redaction(self) -> None:
        tmp_path = _get_test_dir()
        upstream_app, seen = _build_messages_upstream()
        try:
            with _build_client(tmp_path, upstream_app) as client:
                response = client.post(
                    "/v1/messages",
                    headers={
                        "anthropic-version": "2023-06-01",
                        "anthropic-beta": "prompt-caching-2024-07-31",
                        "x-api-key": "secret-key",
                        "authorization": "Bearer secret-token",
                        "x-claude-code-session-id": "session_alpha",
                        "x-claude-code-agent-id": "agent_1",
                    },
                    json={"model": "claude-sonnet", "messages": [{"role": "user", "content": "hi"}]},
                )

            assert response.status_code == 200
            assert response.json()["type"] == "message"
            assert seen[0]["headers"]["anthropic-version"] == "2023-06-01"
            assert seen[0]["headers"]["anthropic-beta"] == "prompt-caching-2024-07-31"
            assert seen[0]["headers"]["x-api-key"] == "secret-key"
            assert seen[0]["headers"]["authorization"] == "Bearer secret-token"

            events = _load_jsonl(tmp_path / "traces" / "session_alpha.jsonl")
            assert [event["event_type"] for event in events] == [
                "messages_request",
                "messages_response_headers",
                "messages_stream_chunk",
                "messages_stream_end",
            ]
            request_headers = events[0]["data"]["headers"]
            assert request_headers["anthropic-version"] == "2023-06-01"
            assert request_headers["anthropic-beta"] == "prompt-caching-2024-07-31"
            assert request_headers["x-api-key"] == {"present": True, "redacted": True}
            assert request_headers["authorization"] == {"present": True, "redacted": True}
        finally:
            cleanup_test_path(tmp_path)

    def test_messages_streaming_forward_and_session_aggregation(self) -> None:
        tmp_path = _get_test_dir()
        upstream_app, _seen = _build_messages_upstream(streaming_chunks=["chunk-a", "chunk-b"])
        try:
            with _build_client(tmp_path, upstream_app) as client:
                with client.stream(
                    "POST",
                    "/v1/messages",
                    headers={"x-claude-code-session-id": "session_stream"},
                    json={"messages": [{"role": "user", "content": "first"}]},
                ) as response:
                    body = b"".join(response.iter_bytes()).decode("utf-8")
                with client.stream(
                    "POST",
                    "/v1/messages",
                    headers={"x-claude-code-session-id": "session_stream"},
                    json={"messages": [{"role": "user", "content": "second"}]},
                ) as response:
                    body += b"".join(response.iter_bytes()).decode("utf-8")

            assert "chunk-a" in body and "chunk-b" in body
            events = _load_jsonl(tmp_path / "traces" / "session_stream.jsonl")
            assert len(events) == 8
            assert {event["request_id"] for event in events if event["event_type"] == "messages_request"}
            chunk_events = [event for event in events if event["event_type"] == "messages_stream_chunk"]
            assert len(chunk_events) >= 2
            chunk_text = "".join(str(event["data"]["text"]) for event in chunk_events)
            assert "chunk-a" in chunk_text
            assert "chunk-b" in chunk_text
        finally:
            cleanup_test_path(tmp_path)

    def test_count_tokens_forward_and_response(self) -> None:
        tmp_path = _get_test_dir()
        upstream_app, seen = _build_messages_upstream()
        try:
            with _build_client(tmp_path, upstream_app) as client:
                response = client.post(
                    "/v1/messages/count_tokens",
                    headers={"x-claude-code-session-id": "session_tokens"},
                    json={"model": "claude-sonnet", "messages": [{"role": "user", "content": "hi"}]},
                )

            assert response.status_code == 200
            assert response.json()["input_tokens"] == 42
            assert seen[0]["path"] == "/v1/messages/count_tokens"
            events = _load_jsonl(tmp_path / "traces" / "session_tokens.jsonl")
            assert [event["event_type"] for event in events] == [
                "count_tokens_request",
                "count_tokens_response",
            ]
        finally:
            cleanup_test_path(tmp_path)

    def test_missing_session_id_uses_fallback_file(self) -> None:
        tmp_path = _get_test_dir()
        upstream_app, _seen = _build_messages_upstream()
        try:
            with _build_client(tmp_path, upstream_app) as client:
                response = client.post(
                    "/v1/messages",
                    json={"model": "claude-sonnet", "messages": [{"role": "user", "content": "hi"}]},
                )

            assert response.status_code == 200
            files = list((tmp_path / "traces").glob("unknown_session_*.jsonl"))
            assert len(files) == 1
            events = _load_jsonl(files[0])
            assert all(event["session_id"].startswith("unknown_session_") for event in events)
        finally:
            cleanup_test_path(tmp_path)

    def test_messages_non_2xx_writes_error_event(self) -> None:
        tmp_path = _get_test_dir()
        upstream_app, _seen = _build_messages_upstream(status_code=503)
        try:
            with _build_client(tmp_path, upstream_app) as client:
                response = client.post(
                    "/v1/messages",
                    headers={"x-claude-code-session-id": "session_error"},
                    json={"messages": [{"role": "user", "content": "hi"}]},
                )

            assert response.status_code == 503
            events = _load_jsonl(tmp_path / "traces" / "session_error.jsonl")
            assert any(event["event_type"] == "messages_error" for event in events)
        finally:
            cleanup_test_path(tmp_path)

    def test_count_tokens_non_2xx_writes_error_event(self) -> None:
        tmp_path = _get_test_dir()
        async def count_tokens_error(_request: Request):
            return JSONResponse({"error": "bad"}, status_code=429)

        async def messages_ok(_request: Request):
            return JSONResponse({"type": "message"})

        upstream = Starlette(
            routes=[
                Route("/v1/messages", messages_ok, methods=["POST"]),
                Route("/v1/messages/count_tokens", count_tokens_error, methods=["POST"]),
            ]
        )
        try:
            with _build_client(tmp_path, upstream) as client:
                response = client.post(
                    "/v1/messages/count_tokens",
                    headers={"x-claude-code-session-id": "session_count_error"},
                    json={"messages": [{"role": "user", "content": "hi"}]},
                )

            assert response.status_code == 429
            events = _load_jsonl(tmp_path / "traces" / "session_count_error.jsonl")
            assert [event["event_type"] for event in events] == [
                "count_tokens_request",
                "count_tokens_response",
                "count_tokens_error",
            ]
        finally:
            cleanup_test_path(tmp_path)

    def test_upstream_connect_error_writes_error_event(self) -> None:
        tmp_path = _get_test_dir()
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=_request)

        transport = httpx.MockTransport(handler)
        config = AppConfig(
            upstream_base_url="https://upstream.example",
            trace_dir=tmp_path / "traces",
            request_timeout_seconds=30.0,
            upstream_transport=transport,
        )
        try:
            with TestClient(build_app(config)) as client:
                response = client.post(
                    "/v1/messages",
                    headers={"x-claude-code-session-id": "session_connect_error"},
                    json={"messages": [{"role": "user", "content": "hi"}]},
                )

            assert response.status_code == 502
            events = _load_jsonl(tmp_path / "traces" / "session_connect_error.jsonl")
            assert [event["event_type"] for event in events] == [
                "messages_request",
                "messages_error",
            ]
        finally:
            cleanup_test_path(tmp_path)
