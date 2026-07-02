"""Tool profile config loader.

Reads YAML config files and builds ToolProfile instances with
ToolView and ToolAdapter objects.

Config structure (YAML):

    profile_id: base
    tools:
      - canonical: read_file
        exposed_name: read_file
        description: "Read a file from the workspace."
        input_schema:
          type: object
          properties:
            path: {type: string}
          required: [path]
        adapter:
          exposed_to_canonical:
            target: path
          defaults:
            start_line: 1
        version: default
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pycodeagent.tools.contracts import ToolContractKind, coerce_tool_contract_kind
from pycodeagent.tools.spec import ToolAdapter, ToolProfile, ToolView


def _validate_and_build_profile(data: dict[str, Any]) -> ToolProfile:
    """Validate config dict and build ToolProfile.

    Args:
        data: Config dict with profile_id and tools list.

    Returns:
        A ToolProfile built from the data.

    Raises:
        ValueError: If config structure is invalid.
    """
    profile_id = data.get("profile_id")
    if not profile_id or not isinstance(profile_id, str):
        raise ValueError("Config must have a string 'profile_id'")

    raw_tools = data.get("tools")
    if not isinstance(raw_tools, list):
        raise ValueError("Config must have a 'tools' list")

    tools: list[ToolView] = []
    adapters: dict[str, ToolAdapter] = {}

    for i, entry in enumerate(raw_tools):
        if not isinstance(entry, dict):
            raise ValueError(f"tools[{i}] must be a mapping")

        canonical = entry.get("canonical")
        exposed = entry.get("exposed_name")
        description = entry.get("description", "")
        contract_kind = coerce_tool_contract_kind(entry.get("kind"))
        input_schema = entry.get("input_schema", {})
        input_format = entry.get("input_format")
        version = entry.get("version", "default")
        adapter_data = entry.get("adapter", {})

        if not canonical or not isinstance(canonical, str):
            raise ValueError(f"tools[{i}] must have a string 'canonical' name")
        if not exposed or not isinstance(exposed, str):
            raise ValueError(f"tools[{i}] must have a string 'exposed_name'")
        if contract_kind == ToolContractKind.FUNCTION:
            if not isinstance(input_schema, dict):
                raise ValueError(f"tools[{i}].input_schema must be a mapping")
        else:
            if input_format is not None and not isinstance(input_format, dict):
                raise ValueError(f"tools[{i}].input_format must be a mapping")
            if input_schema is None:
                input_schema = {}
            if not isinstance(input_schema, dict):
                raise ValueError(
                    f"tools[{i}].input_schema must be a mapping when present"
                )

        view = ToolView(
            canonical_name=canonical,
            exposed_name=exposed,
            description=description,
            input_schema=input_schema,
            contract_kind=contract_kind,
            input_format=input_format if isinstance(input_format, dict) else None,
            version=version,
        )
        tools.append(view)

        # Build adapter
        exposed_to_canonical: dict[str, str] = {}
        defaults: dict[str, Any] = {}

        if isinstance(adapter_data, dict):
            exposed_to_canonical = adapter_data.get("exposed_to_canonical", {})
            defaults = adapter_data.get("defaults", {})
            if not isinstance(exposed_to_canonical, dict):
                raise ValueError(f"tools[{i}].adapter.exposed_to_canonical must be a mapping")
            if not isinstance(defaults, dict):
                raise ValueError(f"tools[{i}].adapter.defaults must be a mapping")

        adapters[exposed] = ToolAdapter(
            exposed_to_canonical=exposed_to_canonical,
            defaults=defaults,
        )

    return ToolProfile(
        profile_id=profile_id,
        tools=tools,
        adapters=adapters,
    )


def load_tool_profile(config_path: str | Path) -> ToolProfile:
    """Load a ToolProfile from a YAML config file.

    Args:
        config_path: Path to the YAML config file.

    Returns:
        A ToolProfile built from the config.

    Raises:
        FileNotFoundError: If config file does not exist.
        ValueError: If config structure is invalid.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Config must be a mapping, got {type(data).__name__}")

    return _validate_and_build_profile(data)


def load_tool_profile_from_dict(data: dict[str, Any]) -> ToolProfile:
    """Build a ToolProfile from an already-parsed config dict.

    Useful for programmatic construction and testing.

    Args:
        data: Config dict with the same structure as a YAML file.

    Returns:
        A ToolProfile built from the data.

    Raises:
        ValueError: If config structure is invalid.
    """
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a mapping, got {type(data).__name__}")

    return _validate_and_build_profile(data)


def load_mutation_config(config_path: str | Path) -> dict[str, Any]:
    """Load a mutation config file that defines variant candidates.

    Mutation config structure:

        profile_id_prefix: mutation

        # Per-tool variant candidates
        tool_variants:
          read_file:
            name_candidates:
              - open_source
              - inspect_file
            description_candidates:
              - "Inspect source code by filename."
            schema_candidates:
              - input_schema: {...}
                adapter: {}

        # Pre-defined named variants (optional)
        named_variants:
          v1:
            read_file:
              exposed_name: open_source
              description: "Inspect source code."
              input_schema: {...}
              adapter: {...}

    Args:
        config_path: Path to the mutation config YAML file.

    Returns:
        The parsed mutation config dict.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Mutation config not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Mutation config must be a mapping, got {type(data).__name__}")

    return data
