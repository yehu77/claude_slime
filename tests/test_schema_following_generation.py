"""Tests for synthetic schema-following dataset generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.rl.schema_following_dataset import read_schema_following_jsonl
from pycodeagent.rl.schema_following_generate import (
    generate_synthetic_schema_following_data,
)
from pycodeagent.rl.schema_following_splits import (
    SCHEMA_FOLLOWING_SPLIT_ORDER,
    build_default_synthetic_profile_specs,
)
from pycodeagent.testing.temp_artifacts import make_request_test_dir
from pycodeagent.tools.bootstrap import build_base_tool_profile, build_builtin_registry


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_profile(profile_entry: dict):
    if profile_entry["mode"] == "base":
        return build_base_tool_profile(profile_id=profile_entry["profile_id"])
    return ToolProfileSampler(seed=profile_entry["seed"]).sample(profile_entry["mode"])


class TestSyntheticSchemaFollowingGeneration:
    def test_writes_expected_files(self, request):
        output_dir = make_request_test_dir("schema_following_generation", request)
        result = generate_synthetic_schema_following_data(
            output_dir,
            num_intents=18,
            seed=42,
        )

        assert result.sample_count > 0
        assert (output_dir / "dataset_manifest.json").exists()
        assert (output_dir / "profile_manifest.json").exists()
        assert (output_dir / "split_metrics.json").exists()
        for split_name in SCHEMA_FOLLOWING_SPLIT_ORDER:
            assert (output_dir / f"{split_name}.jsonl").exists()

    def test_generation_is_deterministic(self, request):
        output_a = make_request_test_dir("schema_following_generation_a", request)
        output_b = make_request_test_dir("schema_following_generation_b", request)

        result_a = generate_synthetic_schema_following_data(output_a, num_intents=12, seed=7)
        result_b = generate_synthetic_schema_following_data(output_b, num_intents=12, seed=7)

        assert result_a.model_dump(mode="json")["split_counts"] == result_b.model_dump(mode="json")["split_counts"]
        for split_name in SCHEMA_FOLLOWING_SPLIT_ORDER:
            assert (
                (output_a / f"{split_name}.jsonl").read_text(encoding="utf-8")
                == (output_b / f"{split_name}.jsonl").read_text(encoding="utf-8")
            )

    def test_samples_validate_and_roundtrip_to_canonical(self, request):
        output_dir = make_request_test_dir("schema_following_generation_roundtrip", request)
        generate_synthetic_schema_following_data(output_dir, num_intents=18, seed=42)

        profile_manifest = _read_json(output_dir / "profile_manifest.json")
        profiles = {
            entry["profile_id"]: _load_profile(entry)
            for entry in profile_manifest["profiles"]
        }
        registry = build_builtin_registry()

        for split_name in SCHEMA_FOLLOWING_SPLIT_ORDER:
            for sample in read_schema_following_jsonl(output_dir / f"{split_name}.jsonl"):
                profile = profiles[sample.tool_profile_id]
                canonical_tool = registry.get(sample.canonical_intent.tool)
                _, roundtrip = profile.map_call_arguments(
                    sample.target_tool_call.name,
                    sample.target_tool_call.arguments,
                    canonical_tool=canonical_tool,
                )
                assert roundtrip == sample.canonical_intent.arguments

    def test_split_metrics_are_written(self, request):
        output_dir = make_request_test_dir("schema_following_generation_metrics", request)
        result = generate_synthetic_schema_following_data(output_dir, num_intents=18, seed=42)

        metrics = _read_json(output_dir / "split_metrics.json")
        manifest = _read_json(output_dir / "dataset_manifest.json")

        assert metrics["split_counts"] == result.split_counts
        assert manifest["sample_count"] == result.sample_count
        assert set(manifest["implemented_categories"]) == {
            "base",
            "description_paraphrase",
            "mixed_hard",
            "rename_light",
            "schema_flat_to_nested",
        }

    def test_default_profile_specs_cover_required_roles(self):
        specs = build_default_synthetic_profile_specs(seed=42)
        roles = {spec.split_role for spec in specs}
        assert "train_seen" in roles
        assert "eval_unseen_name" in roles
        assert "eval_unseen_description" in roles
        assert "eval_unseen_schema" in roles
