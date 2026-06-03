"""Tool catalog contracts and JSON persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class CatalogToolEntry(BaseModel):
    """One native tool exposed by an agent."""

    raw_tool_name: str
    description: str
    input_schema: dict[str, Any]
    output_format_hint: str | None = None
    availability_conditions: dict[str, Any] = Field(default_factory=dict)
    tool_family: str | None = None
    canonical_name: str | None = None
    version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentToolCatalog(BaseModel):
    """Catalog of tools available to one agent/session configuration."""

    schema_version: int = SCHEMA_VERSION
    catalog_id: str
    agent_name: str
    agent_version: str
    capture_mode: str
    source_kind: str
    captured_at: str | None = None
    tools: list[CatalogToolEntry] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def write_tool_catalog(catalog: AgentToolCatalog, path: str | Path) -> Path:
    """Write a tool catalog as JSON."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(catalog.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return target


def read_tool_catalog(path: str | Path) -> AgentToolCatalog:
    """Load a tool catalog from JSON."""
    source = Path(path)
    with open(source, encoding="utf-8") as handle:
        data = json.load(handle)
    return AgentToolCatalog.model_validate(data)
