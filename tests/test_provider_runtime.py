from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent import (
    MimoNativeToolClient,
    OpenAINativeToolClient,
    RuntimeClientCapabilities,
    RuntimeProviderConfig,
    build_llm_client,
    build_llm_client_factory_from_path,
    load_runtime_provider_env,
    load_runtime_provider_config,
    resolve_runtime_provider_config,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


def _write_provider_config(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _disable_repo_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pycodeagent.agent.provider_runtime._dotenv_candidates",
        lambda env_path=None: [],
    )


def test_load_runtime_provider_config_rejects_inline_api_key():
    tmp = make_unique_test_dir("provider_runtime")
    try:
        config_path = _write_provider_config(
            tmp / "provider.local.json",
            {
                "client_mode": "mimo_native_tools",
                "model": "mimo-v2.5-pro",
                "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                "api_key_env": "PYCODEAGENT_API_KEY",
                "api_key": "should-not-be-here",
            },
        )

        with pytest.raises(ValueError, match="Inline api_key is not allowed"):
            load_runtime_provider_config(config_path)
    finally:
        cleanup_test_path(tmp)


def test_build_llm_client_uses_mimo_native_tools_mode():
    config = RuntimeProviderConfig(
        client_mode="mimo_native_tools",
        model="mimo-v2.5-pro",
        base_url="https://token-plan-cn.xiaomimimo.com/v1",
        api_key_env="PYCODEAGENT_API_KEY",
    )

    client = build_llm_client(config)

    assert isinstance(client, MimoNativeToolClient)
    assert client.runtime_provenance()["client_mode"] == "mimo_native_tools"
    assert client.runtime_provenance()["provider_kind"] == "mimo"
    assert client.runtime_capabilities() == RuntimeClientCapabilities(
        protocol_mode="native_tool_calling",
        supports_native_tools=True,
        text_fallback_allowed=False,
        structured_finish_mode="finish_tool_call",
        supports_structured_output=True,
        supports_model_backed_compaction=True,
        provider_family="openai_chat_completions",
        provider_name="mimo",
    )


def test_build_llm_client_uses_openai_native_tools_mode():
    config = RuntimeProviderConfig(
        client_mode="openai_native_tools",
        model="gpt-4o-mini",
        base_url="https://example.com/v1",
        api_key_env="PYCODEAGENT_API_KEY",
    )

    client = build_llm_client(config)

    assert isinstance(client, OpenAINativeToolClient)
    assert client.runtime_provenance()["client_mode"] == "openai_native_tools"
    assert client.runtime_provenance()["provider_kind"] == "openai_compatible"
    assert client.runtime_capabilities() == RuntimeClientCapabilities(
        protocol_mode="native_tool_calling",
        supports_native_tools=True,
        text_fallback_allowed=False,
        structured_finish_mode="finish_tool_call",
        supports_structured_output=True,
        supports_model_backed_compaction=True,
        provider_family="openai_chat_completions",
        provider_name="openai_compatible",
    )


def test_build_llm_client_factory_from_path(monkeypatch: pytest.MonkeyPatch):
    tmp = make_unique_test_dir("provider_runtime")
    try:
        _disable_repo_dotenv(monkeypatch)
        monkeypatch.setenv("PYCODEAGENT_API_KEY", "tp-test")
        monkeypatch.delenv("PYCODEAGENT_CLIENT_MODE", raising=False)
        config_path = _write_provider_config(
            tmp / "provider.local.json",
            {
                "client_mode": "mimo_native_tools",
                "model": "mimo-v2.5-pro",
                "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                "api_key_env": "PYCODEAGENT_API_KEY",
                "timeout_seconds": 45,
                "max_retries": 5,
            },
        )

        factory = build_llm_client_factory_from_path(config_path)
        client = factory()

        assert isinstance(client, MimoNativeToolClient)
        assert client.runtime_provenance() == {
            "provider_kind": "mimo",
            "client_mode": "mimo_native_tools",
            "model": "mimo-v2.5-pro",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "api_key_env": "PYCODEAGENT_API_KEY",
            "timeout_seconds": 45.0,
            "max_retries": 5,
            "temperature": None,
            "max_output_tokens": None,
        }
    finally:
        cleanup_test_path(tmp)


def test_resolve_runtime_provider_config_from_env_only(monkeypatch: pytest.MonkeyPatch):
    _disable_repo_dotenv(monkeypatch)
    monkeypatch.setenv("PYCODEAGENT_API_KEY", "tp-env")
    monkeypatch.setenv("PYCODEAGENT_MODEL", "mimo-v2.5-pro")
    monkeypatch.delenv("PYCODEAGENT_CLIENT_MODE", raising=False)
    monkeypatch.delenv("PYCODEAGENT_BASE_URL", raising=False)

    config = resolve_runtime_provider_config()

    assert config.client_mode == "mimo_native_tools"
    assert config.model == "mimo-v2.5-pro"
    assert config.base_url == "https://token-plan-cn.xiaomimimo.com/v1"
    assert config.api_key_env == "PYCODEAGENT_API_KEY"


def test_resolve_runtime_provider_config_env_overrides_local_json(monkeypatch: pytest.MonkeyPatch):
    tmp = make_unique_test_dir("provider_runtime")
    try:
        _disable_repo_dotenv(monkeypatch)
        monkeypatch.setenv("PYCODEAGENT_API_KEY", "tp-env")
        monkeypatch.setenv("PYCODEAGENT_MODEL", "env-model")
        monkeypatch.setenv("PYCODEAGENT_BASE_URL", "https://env.example.com/v1")
        monkeypatch.delenv("PYCODEAGENT_CLIENT_MODE", raising=False)
        config_path = _write_provider_config(
            tmp / "provider.local.json",
            {
                "client_mode": "mimo_native_tools",
                "model": "json-model",
                "base_url": "https://json.example.com/v1",
                "api_key_env": "PYCODEAGENT_API_KEY",
            },
        )

        config = resolve_runtime_provider_config(config_path)

        assert config.client_mode == "mimo_native_tools"
        assert config.model == "env-model"
        assert config.base_url == "https://env.example.com/v1"
    finally:
        cleanup_test_path(tmp)


def test_resolve_runtime_provider_config_rejects_unknown_client_mode(
    monkeypatch: pytest.MonkeyPatch,
):
    tmp = make_unique_test_dir("provider_runtime")
    try:
        _disable_repo_dotenv(monkeypatch)
        monkeypatch.setenv("PYCODEAGENT_API_KEY", "tp-env")
        monkeypatch.setenv("PYCODEAGENT_MODEL", "legacy-model")
        monkeypatch.delenv("PYCODEAGENT_CLIENT_MODE", raising=False)
        config_path = _write_provider_config(
            tmp / "provider.local.json",
            {
                "client_mode": "unsupported_client_mode",
                "model": "legacy-model",
                "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                "api_key_env": "PYCODEAGENT_API_KEY",
            },
        )

        with pytest.raises(ValueError, match="Unable to resolve runtime provider config"):
            resolve_runtime_provider_config(config_path)
    finally:
        cleanup_test_path(tmp)


def test_resolve_runtime_provider_config_loads_dotenv_file(monkeypatch: pytest.MonkeyPatch):
    tmp = make_unique_test_dir("provider_runtime")
    try:
        dotenv_path = tmp / ".env"
        dotenv_path.write_text(
            "\n".join(
                [
                    "PYCODEAGENT_API_KEY=tp-dotenv",
                    "PYCODEAGENT_MODEL=mimo-from-dotenv",
                    "PYCODEAGENT_BASE_URL=https://dotenv.example.com/v1",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.delenv("PYCODEAGENT_API_KEY", raising=False)
        monkeypatch.delenv("PYCODEAGENT_MODEL", raising=False)
        monkeypatch.delenv("PYCODEAGENT_BASE_URL", raising=False)

        loaded_path = load_runtime_provider_env(dotenv_path)
        config = resolve_runtime_provider_config(env_path=dotenv_path)

        assert loaded_path == dotenv_path
        assert config.model == "mimo-from-dotenv"
        assert config.base_url == "https://dotenv.example.com/v1"
        assert config.api_key_env == "PYCODEAGENT_API_KEY"
    finally:
        import os

        os.environ.pop("PYCODEAGENT_API_KEY", None)
        os.environ.pop("PYCODEAGENT_MODEL", None)
        os.environ.pop("PYCODEAGENT_BASE_URL", None)
        cleanup_test_path(tmp)


def test_shell_env_overrides_dotenv(monkeypatch: pytest.MonkeyPatch):
    tmp = make_unique_test_dir("provider_runtime")
    try:
        dotenv_path = tmp / ".env"
        dotenv_path.write_text(
            "\n".join(
                [
                    "PYCODEAGENT_API_KEY=tp-dotenv",
                    "PYCODEAGENT_MODEL=dotenv-model",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("PYCODEAGENT_API_KEY", "tp-shell")
        monkeypatch.setenv("PYCODEAGENT_MODEL", "shell-model")

        config = resolve_runtime_provider_config(env_path=dotenv_path)

        assert config.model == "shell-model"
        assert config.api_key_env == "PYCODEAGENT_API_KEY"
    finally:
        cleanup_test_path(tmp)
