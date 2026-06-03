"""MiMo-specific text-mode client.

Wraps the OpenAI-compatible Chat Completions API with the extra history
adaptation required by MiMo reasoning models:
- replay assistant `reasoning_content` on subsequent turns
- flatten structured tool-call history into assistant text blocks
- convert tool observations into plain user messages
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from pycodeagent.agent.llm_client import GenerateRequest, GenerateResponse
from pycodeagent.agent.openai_client import EmptyResponseError, OpenAITextClient


class MimoTextClient(OpenAITextClient):
    """MiMo-compatible text client with reasoning-history replay."""

    def __init__(self, config) -> None:
        super().__init__(config)
        self._assistant_reasoning_history: list[str | None] = []
        self._http_client: httpx.Client | None = None

    @staticmethod
    def _assistant_message_count(messages: list[dict[str, Any]]) -> int:
        """Count assistant messages present in the current request history."""
        return sum(1 for message in messages if message.get("role") == "assistant")

    def _make_request(
        self,
        api_key: str,
        request: GenerateRequest,
    ) -> GenerateResponse:
        if self._assistant_message_count(request.messages) == 0:
            self._assistant_reasoning_history.clear()

        url = f"{self._base_url}/chat/completions"
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": self._sanitize_messages(request.messages),
        }
        if self._config.temperature is not None:
            body["temperature"] = self._config.temperature
        if self._config.max_output_tokens is not None:
            body["max_tokens"] = self._config.max_output_tokens

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self._config.extra_headers)

        self._call_count += 1
        try:
            response = self._get_http_client().post(url, json=body, headers=headers)
        except httpx.HTTPError:
            # Drop the connection pool and let the caller's retry loop retry
            # with a fresh client on the next attempt.
            self.close()
            raise

        if response.status_code != 200:
            self._raise_api_error(response)
        return self._parse_response(response)

    def _get_http_client(self) -> httpx.Client:
        """Return a persistent HTTP client for the lifetime of this LLM client."""
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=self._config.timeout_seconds)
        return self._http_client

    def _sanitize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert agent-internal history into MiMo-compatible messages."""
        sanitized: list[dict[str, Any]] = []
        assistant_count = self._assistant_message_count(messages)
        replay_history = (
            self._assistant_reasoning_history[-assistant_count:]
            if assistant_count
            else []
        )
        assistant_idx = 0

        for message in messages:
            role = message.get("role")
            content = str(message.get("content", ""))

            if role in {"system", "user"}:
                sanitized.append({"role": role, "content": content})
                continue

            if role == "assistant":
                tool_calls = message.get("tool_calls") or []
                if tool_calls:
                    blocks = []
                    for call in tool_calls:
                        blocks.append(
                            "<|tool|>\n"
                            + json.dumps(
                                {
                                    "id": call.get("id"),
                                    "name": call.get("name"),
                                    "arguments": call.get("arguments", {}),
                                },
                                ensure_ascii=False,
                            )
                            + "\n<|end|>"
                        )
                    content = f"{content}\n{chr(10).join(blocks)}".strip()

                assistant_message: dict[str, Any] = {"role": "assistant", "content": content}
                if assistant_idx < len(replay_history):
                    reasoning = replay_history[assistant_idx]
                    if reasoning:
                        assistant_message["reasoning_content"] = reasoning
                assistant_idx += 1
                sanitized.append(assistant_message)
                continue

            if role == "tool":
                tool_name = message.get("tool_name", "tool")
                call_id = message.get("tool_call_id", "")
                sanitized.append(
                    {
                        "role": "user",
                        "content": (
                            f'<tool_result name="{tool_name}" call_id="{call_id}">\n'
                            f"{content}\n"
                            "</tool_result>"
                        ),
                    }
                )
                continue

            sanitized.append({"role": str(role), "content": content})

        return sanitized

    def _parse_response(self, response: httpx.Response) -> GenerateResponse:
        """Parse a successful MiMo response and capture reasoning history."""
        try:
            data = response.json()
        except Exception as e:
            raise EmptyResponseError(f"Failed to parse response JSON: {e}") from e

        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise EmptyResponseError("Response missing 'choices' array")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise EmptyResponseError(f"Invalid choice: {first_choice}")

        message = first_choice.get("message")
        if not message or not isinstance(message, dict):
            raise EmptyResponseError("Choice missing 'message' object")

        content = message.get("content")
        if content is None:
            raise EmptyResponseError("Model returned empty content (possibly filtered)")

        self._assistant_reasoning_history.append(message.get("reasoning_content"))
        return GenerateResponse(text=str(content))

    def close(self) -> None:
        """Close the persistent HTTP client if it exists."""
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
