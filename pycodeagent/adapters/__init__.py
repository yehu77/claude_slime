"""Scaffold adapters."""

from pycodeagent.adapters.base import AgentAdapter, AgentRunContext, ToolCatalogProvider
from pycodeagent.adapters.catalog_providers import (
    ClaudeCodeCatalogProvider,
    CodexCatalogProvider,
    StaticManifestCatalogProvider,
)
from pycodeagent.adapters.claude_code_adapter import ClaudeCodeAdapter
from pycodeagent.adapters.codex_cli_adapter import CodexCliAdapter
from pycodeagent.adapters.external_cli_adapter import ExternalCliArtifactAdapter
from pycodeagent.adapters.kilo_code_adapter import KiloCodeAdapter
from pycodeagent.adapters.mock_adapter import (
    MockAdapter,
    MockToolCatalogProvider,
    MockTraceNormalizer,
    build_mock_tool_catalog,
    generate_synthetic_raw_trace,
)

__all__ = [
    "AgentAdapter",
    "AgentRunContext",
    "ClaudeCodeAdapter",
    "ClaudeCodeCatalogProvider",
    "CodexCatalogProvider",
    "CodexCliAdapter",
    "ExternalCliArtifactAdapter",
    "KiloCodeAdapter",
    "MockAdapter",
    "MockToolCatalogProvider",
    "MockTraceNormalizer",
    "StaticManifestCatalogProvider",
    "ToolCatalogProvider",
    "build_mock_tool_catalog",
    "generate_synthetic_raw_trace",
]
