"""Synthetic schema-following dataset generation.

This path intentionally remains text-rendered because the training target is a
serialized tool-call block, not a live runtime provider exchange. It is not a
runtime-mainline transport contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.rl.schema_following import (
    CanonicalToolIntent,
    SchemaFollowingMessage,
    SchemaFollowingSample,
)
from pycodeagent.rl.schema_following_dataset import write_schema_following_jsonl
from pycodeagent.rl.schema_following_splits import (
    SCHEMA_FOLLOWING_SPLIT_ORDER,
    SyntheticProfileSpec,
    assign_synthetic_split,
    build_default_synthetic_profile_specs,
)
from pycodeagent.tools.families import (
    build_claude_canonical_registry,
    build_codex_canonical_registry,
)
from pycodeagent.tools.profile_factory import (
    build_native_claude_profile,
    build_native_codex_profile,
)
from pycodeagent.tools.spec import ToolProfile

NativeSchemaFamily = Literal["claude", "codex"]


class SyntheticProfileManifestEntry(BaseModel):
    """One profile entry used during synthetic dataset generation."""

    profile_id: str
    category: str
    mode: str
    seed: int
    split_role: str
    family: str
    native_profile_kind: str
    tools: list[dict[str, Any]]


class SyntheticSchemaFollowingGenerationResult(BaseModel):
    """Summary of one synthetic generation run."""

    output_dir: str
    sample_count: int
    num_intents: int
    seed: int
    implemented_categories: list[str] = Field(default_factory=list)
    split_counts: dict[str, int] = Field(default_factory=dict)
    profile_ids: list[str] = Field(default_factory=list)
    profile_manifest_path: str
    dataset_manifest_path: str
    split_metrics_path: str
    present_splits: list[str] = Field(default_factory=list)


def _canonical_intent_variants(
    family: NativeSchemaFamily,
) -> dict[str, list[tuple[CanonicalToolIntent, str]]]:
    """Return deterministic canonical intent templates for one native family."""
    if family == "claude":
        return {
            "Read": [
                (
                    CanonicalToolIntent(
                        tool="Read",
                        arguments={"file_path": "/workspace/src/calculator.py", "offset": 1, "limit": 80},
                    ),
                    "Read the first 80 lines of /workspace/src/calculator.py.",
                ),
                (
                    CanonicalToolIntent(
                        tool="Read",
                        arguments={"file_path": "/workspace/README.md"},
                    ),
                    "Inspect /workspace/README.md.",
                ),
            ],
            "Grep": [
                (
                    CanonicalToolIntent(
                        tool="Grep",
                        arguments={"pattern": "def add", "path": "/workspace/src", "glob": "*.py"},
                    ),
                    "Search /workspace/src for the add function definition.",
                ),
                (
                    CanonicalToolIntent(
                        tool="Grep",
                        arguments={"pattern": "pytest", "path": "/workspace/tests"},
                    ),
                    "Search /workspace/tests for pytest usage.",
                ),
            ],
            "Bash": [
                (
                    CanonicalToolIntent(
                        tool="Bash",
                        arguments={"command": "pytest -q", "timeout": 30000},
                    ),
                    "Run the test suite with pytest.",
                ),
                (
                    CanonicalToolIntent(
                        tool="Bash",
                        arguments={"command": "ruff check .", "timeout": 30000},
                    ),
                    "Run ruff against the repository root.",
                ),
            ],
            "Edit": [
                (
                    CanonicalToolIntent(
                        tool="Edit",
                        arguments={
                            "file_path": "/workspace/src/calculator.py",
                            "old_string": "return a - b",
                            "new_string": "return a + b",
                            "replace_all": False,
                        },
                    ),
                    "Fix the add implementation in /workspace/src/calculator.py.",
                ),
            ],
            "Write": [
                (
                    CanonicalToolIntent(
                        tool="Write",
                        arguments={
                            "file_path": "/workspace/notes.txt",
                            "content": "Validation complete.\n",
                        },
                    ),
                    "Write a short validation note to /workspace/notes.txt.",
                ),
            ],
            "Glob": [
                (
                    CanonicalToolIntent(
                        tool="Glob",
                        arguments={"pattern": "**/*.py", "path": "/workspace"},
                    ),
                    "List Python files under /workspace.",
                ),
            ],
        }

    return {
        "exec_command": [
            (
                CanonicalToolIntent(
                    tool="exec_command",
                    arguments={"cmd": "git status", "workdir": ".", "shell": "bash", "login": True},
                ),
                "Run git status from the workspace root.",
            ),
            (
                CanonicalToolIntent(
                    tool="exec_command",
                    arguments={"cmd": "pytest -q", "workdir": ".", "shell": "bash", "login": True},
                ),
                "Run pytest in the workspace root.",
            ),
        ],
        "write_stdin": [
            (
                CanonicalToolIntent(
                    tool="write_stdin",
                    arguments={"session_id": 1, "chars": "q\n", "yield_time_ms": 1000, "max_output_tokens": 4000},
                ),
                "Send input to an existing shell session.",
            ),
        ],
        "apply_patch": [
            (
                CanonicalToolIntent(
                    tool="apply_patch",
                    input_text=(
                        "*** Begin Patch\n"
                        "*** Update File: src/calculator.py\n"
                        "@@\n"
                        "-def add(a, b):\n"
                        "-    return a - b\n"
                        "+def add(a, b):\n"
                        "+    return a + b\n"
                        "*** End Patch\n"
                    ),
                ),
                "Apply a strict patch that fixes add() in src/calculator.py.",
            ),
        ],
    }


def _iter_generated_intents(
    *,
    num_intents: int,
    seed: int,
    family: NativeSchemaFamily,
) -> list[tuple[str, CanonicalToolIntent, str]]:
    """Generate deterministic synthetic canonical intents."""
    variants_by_tool = _canonical_intent_variants(family)
    ordered_tools = list(variants_by_tool)
    results: list[tuple[str, CanonicalToolIntent, str]] = []

    for intent_index in range(num_intents):
        tool_name = ordered_tools[intent_index % len(ordered_tools)]
        variants = variants_by_tool[tool_name]
        variant_index = (intent_index + seed) % len(variants)
        intent, task_prompt = variants[variant_index]
        task_id = f"synthetic_{tool_name}_{intent_index:04d}"
        results.append(
            (
                task_id,
                intent,
                task_prompt,
            )
        )

    return results


def _profile_from_spec(
    spec: SyntheticProfileSpec,
    *,
    family: NativeSchemaFamily,
) -> ToolProfile:
    """Build one ToolProfile from a synthetic profile spec."""
    if spec.mode == "base":
        if family == "claude":
            return build_native_claude_profile(
                profile_id=f"schema_following_claude_base_{spec.seed}"
            )
        return build_native_codex_profile(
            profile_id=f"schema_following_codex_base_{spec.seed}"
        )
    return ToolProfileSampler(seed=spec.seed, family=family).sample(spec.mode)


def _tool_manifest_entry(profile: ToolProfile) -> list[dict[str, Any]]:
    """Return manifest-friendly tool metadata for one profile."""
    items: list[dict[str, Any]] = []
    for tool in profile.tools:
        adapter = profile.adapters.get(tool.exposed_name)
        items.append(
            {
                "canonical_name": tool.canonical_name,
                "exposed_name": tool.exposed_name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "adapter": (
                    adapter.model_dump(mode="json")
                    if adapter is not None
                    else {"exposed_to_canonical": {}, "defaults": {}}
                ),
            }
        )
    return items


def _messages_from_prompt(task_prompt: str, profile: ToolProfile) -> list[SchemaFollowingMessage]:
    """Build text-rendered schema-following prompt messages.

    This stays isolated from the runtime prompt module so runtime cleanup can
    remove text-mode prompt branches without breaking synthetic dataset export.
    """
    tool_section = _build_legacy_text_tool_specs_section(profile.get_exposed_specs())
    raw_messages = [
        {
            "role": "system",
            "content": (
                "You are a coding agent working inside a repository workspace.\n\n"
                "The available tools are listed in the user message inside a <tools> block.\n"
                "Use only the exact tool names and argument shapes shown there.\n\n"
                "When calling a tool, emit canonical <|tool|> JSON blocks only.\n"
                "Do not output <tool_result> blocks.\n"
            ),
        },
        {
            "role": "user",
            "content": (
                f"{task_prompt}\n\n"
                "Use only the exact tool names and argument shapes listed below.\n"
                "When calling a tool, use canonical <|tool|> ... <|end|> blocks only.\n\n"
                f"{tool_section}"
            ),
        },
    ]
    return [
        SchemaFollowingMessage(role=message["role"], content=message["content"])
        for message in raw_messages
    ]


def _build_legacy_text_tool_specs_section(tool_specs: list[dict[str, Any]]) -> str:
    lines = ["<tools>"]
    for spec in tool_specs:
        name = spec.get("name", "unknown")
        desc = spec.get("description", "")
        schema = spec.get("input_schema", {})
        lines.append(f"  {name}: {desc}")
        if schema.get("properties"):
            props = schema["properties"]
            required = set(schema.get("required", []))
            for prop_name, prop_spec in props.items():
                prop_type = prop_spec.get("type", "any")
                prop_desc = prop_spec.get("description", "")
                req_marker = " (required)" if prop_name in required else ""
                lines.append(f"    - {prop_name}: {prop_type}{req_marker} - {prop_desc}")
    lines.append("</tools>")
    return "\n".join(lines)


def _has_nested_values(value: Any) -> bool:
    """Return True when the projected argument object contains nested objects."""
    if isinstance(value, dict):
        return any(
            isinstance(child, dict) or _has_nested_values(child)
            for child in value.values()
        )
    if isinstance(value, list):
        return any(_has_nested_values(child) for child in value)
    return False


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def _group_profile_ids_by_split_role(
    profile_specs: list[SyntheticProfileSpec],
    profile_manifest: list[SyntheticProfileManifestEntry],
) -> dict[str, list[str]]:
    """Group generated profile IDs by synthetic split role."""
    grouped: dict[str, list[str]] = {}
    for spec, entry in zip(profile_specs, profile_manifest, strict=True):
        grouped.setdefault(spec.split_role, []).append(entry.profile_id)
    return grouped


def generate_synthetic_schema_following_data(
    output_dir: str | Path,
    *,
    family: NativeSchemaFamily,
    num_intents: int = 120,
    seed: int = 42,
    profile_specs: list[SyntheticProfileSpec] | None = None,
) -> SyntheticSchemaFollowingGenerationResult:
    """Generate deterministic synthetic schema-following datasets."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    profile_specs = profile_specs or build_default_synthetic_profile_specs(
        seed=seed,
        family=family,
    )
    registry = (
        build_claude_canonical_registry()
        if family == "claude"
        else build_codex_canonical_registry()
    )
    intents = _iter_generated_intents(num_intents=num_intents, seed=seed, family=family)
    split_samples: dict[str, list[SchemaFollowingSample]] = {
        split: [] for split in SCHEMA_FOLLOWING_SPLIT_ORDER
    }
    profile_manifest: list[SyntheticProfileManifestEntry] = []
    category_counts: dict[str, int] = {}

    for spec in profile_specs:
        profile = _profile_from_spec(spec, family=family)
        profile_manifest.append(
            SyntheticProfileManifestEntry(
                profile_id=profile.profile_id,
                category=spec.category,
                mode=spec.mode,
                seed=spec.seed,
                split_role=spec.split_role,
                family=family,
                native_profile_kind=f"native_{family}",
                tools=_tool_manifest_entry(profile),
            )
        )

        for intent_index, (task_id, canonical_intent, task_prompt) in enumerate(intents):
            canonical_tool = registry.get(canonical_intent.tool)
            if canonical_intent.input_text is not None:
                target_call = profile.project_canonical_payload(
                    canonical_intent.tool,
                    canonical_input_text=canonical_intent.input_text,
                    call_id="call_1",
                    canonical_tool=canonical_tool,
                )
                _, roundtrip_payload = profile.map_call_payload(
                    target_call.name,
                    input_text=target_call.input_text,
                    canonical_tool=canonical_tool,
                )
                if roundtrip_payload != canonical_intent.input_text:
                    raise ValueError(
                        "Projection roundtrip mismatch for "
                        f"{profile.profile_id}/{canonical_intent.tool}: "
                        f"{roundtrip_payload!r} != {canonical_intent.input_text!r}"
                    )
            else:
                target_call = profile.project_canonical_call(
                    canonical_intent.tool,
                    canonical_intent.arguments,
                    call_id="call_1",
                    canonical_tool=canonical_tool,
                )
                _, roundtrip_args = profile.map_call_arguments(
                    target_call.name,
                    target_call.arguments,
                    canonical_tool=canonical_tool,
                )
                if roundtrip_args != canonical_intent.arguments:
                    raise ValueError(
                        "Projection roundtrip mismatch for "
                        f"{profile.profile_id}/{canonical_intent.tool}: "
                        f"{roundtrip_args!r} != {canonical_intent.arguments!r}"
                    )

            requires_nested_args = _has_nested_values(target_call.arguments)
            sample_id = (
                f"sf__synthetic__seed{seed}__{profile.profile_id}__intent{intent_index:04d}"
            )
            split = assign_synthetic_split(
                spec,
                split_key=f"{task_id}:{profile.profile_id}",
                requires_nested_args=requires_nested_args,
            )

            sample = SchemaFollowingSample(
                sample_id=sample_id,
                sample_type="schema_following",
                source_type="synthetic",
                split=split,
                task_id=task_id,
                tool_profile_id=profile.profile_id,
                mutation_category=spec.category,
                messages=_messages_from_prompt(task_prompt, profile),
                canonical_intent=canonical_intent,
                target_tool_call=target_call,
                target_text=target_call.render_text(),
                loss_mask_policy="assistant_tool_call_only",
                metadata={
                    "canonical_tool_name": canonical_intent.tool,
                    "family": family,
                    "profile_mode": spec.mode,
                    "profile_seed": spec.seed,
                    "profile_split_role": spec.split_role,
                    "requires_nested_args": requires_nested_args,
                    "has_distractor_tools": False,
                    "tool_order_seed": 0,
                    "intent_index": intent_index,
                },
            )
            split_samples[split].append(sample)
            category_counts[spec.category] = category_counts.get(spec.category, 0) + 1

    for split_name, samples in split_samples.items():
        write_schema_following_jsonl(samples, output_dir / f"{split_name}.jsonl")

    split_counts = {
        split_name: len(samples) for split_name, samples in split_samples.items()
    }
    present_splits = [name for name, count in split_counts.items() if count > 0]
    profile_manifest_path = output_dir / "profile_manifest.json"
    dataset_manifest_path = output_dir / "dataset_manifest.json"
    split_metrics_path = output_dir / "split_metrics.json"

    _write_json(
        profile_manifest_path,
        {
            "version": 1,
            "seed": seed,
            "family": family,
            "profiles": [
                entry.model_dump(mode="json") for entry in profile_manifest
            ],
        },
    )
    _write_json(
        dataset_manifest_path,
        {
            "dataset_type": "schema_following_synthetic",
            "version": 1,
            "seed": seed,
            "family": family,
            "num_intents": num_intents,
            "sample_count": sum(split_counts.values()),
            "loss_mask_policy": "assistant_tool_call_only",
            "implemented_categories": sorted({spec.category for spec in profile_specs}),
            "implemented_splits": list(SCHEMA_FOLLOWING_SPLIT_ORDER),
            "present_splits": present_splits,
            "profile_ids": [entry.profile_id for entry in profile_manifest],
            "profile_manifest_path": profile_manifest_path.name,
            "split_metrics_path": split_metrics_path.name,
        },
    )
    _write_json(
        split_metrics_path,
        {
            "version": 1,
            "seed": seed,
            "split_counts": split_counts,
            "category_counts": category_counts,
            "profiles_by_split_role": _group_profile_ids_by_split_role(
                profile_specs,
                profile_manifest,
            ),
        },
    )

    return SyntheticSchemaFollowingGenerationResult(
        output_dir=str(output_dir),
        sample_count=sum(split_counts.values()),
        num_intents=num_intents,
        seed=seed,
        implemented_categories=sorted({spec.category for spec in profile_specs}),
        split_counts=split_counts,
        profile_ids=[entry.profile_id for entry in profile_manifest],
        profile_manifest_path=str(profile_manifest_path),
        dataset_manifest_path=str(dataset_manifest_path),
        split_metrics_path=str(split_metrics_path),
        present_splits=present_splits,
    )
