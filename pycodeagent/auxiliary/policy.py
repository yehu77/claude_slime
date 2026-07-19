"""Machine-readable ownership policy for auxiliary research routes."""

from __future__ import annotations

from dataclasses import dataclass


AUXILIARY_POLICY_VERSION = 2


@dataclass(frozen=True)
class AuxiliaryRoute:
    route_id: str
    status: str
    modules: tuple[str, ...]
    entrypoints: tuple[str, ...]
    tests: tuple[str, ...]
    fixtures: tuple[str, ...]
    artifact_prefixes: tuple[str, ...]
    migration_goal: str


AUXILIARY_ROUTES: tuple[AuxiliaryRoute, ...] = (
    AuxiliaryRoute(
        route_id="claude_api_ingestion",
        status="migrated",
        modules=(
            "pycodeagent.auxiliary.claude_api.gateway_proxy",
            "pycodeagent.auxiliary.claude_api.serializer",
            "pycodeagent.auxiliary.claude_api.trace",
            "pycodeagent.auxiliary.claude_api.trace_extract",
            "pycodeagent.auxiliary.claude_api.trace_loader",
            "pycodeagent.auxiliary.claude_api.sft",
            "pycodeagent.auxiliary.claude_api.sft_dataset",
            "pycodeagent.auxiliary.claude_api.sft_dataset_io",
            "pycodeagent.auxiliary.claude_api.sft_training",
            "pycodeagent.auxiliary.claude_api.tool_catalog_snapshot",
        ),
        entrypoints=(
            "claude_gateway_proxy.py",
            "export_claude_api_sft_dataset.py",
        ),
        tests=(
            "tests/auxiliary/test_claude_gateway_proxy.py",
            "tests/auxiliary/test_claude_api_trace_loader.py",
            "tests/auxiliary/test_claude_api_trace_extract.py",
            "tests/auxiliary/test_claude_api_sft.py",
            "tests/auxiliary/test_claude_api_sft_dataset.py",
            "tests/auxiliary/test_tool_catalog_snapshot.py",
        ),
        fixtures=("tests/fixtures/claude_api_tool_use_session.jsonl",),
        artifact_prefixes=("claude_api_", "claude_gateway_"),
        migration_goal="RC-030",
    ),
    AuxiliaryRoute(
        route_id="native_transformed",
        status="migrated",
        modules=(
            "pycodeagent.auxiliary.native_transformed.reward",
            "pycodeagent.auxiliary.native_transformed.rl_dataset",
            "pycodeagent.auxiliary.native_transformed.sft",
            "pycodeagent.auxiliary.native_transformed.sft_dataset",
            "pycodeagent.auxiliary.native_transformed.sft_dataset_validate",
            "pycodeagent.auxiliary.native_transformed.sft_eval",
            "pycodeagent.auxiliary.native_transformed.sft_smoke",
            "pycodeagent.auxiliary.native_transformed.training_prep",
        ),
        entrypoints=(
            "export_native_transformed_rl_dataset.py",
            "export_native_transformed_sft_dataset.py",
            "prepare_native_transformed_sft_training_data.py",
            "run_native_transformed_sft_smoke.py",
            "validate_native_transformed_sft_dataset.py",
        ),
        tests=(
            "tests/auxiliary/test_native_profile_transform.py",
            "tests/auxiliary/test_native_transformed_sft.py",
            "tests/auxiliary/test_native_transformed_sft_dataset.py",
            "tests/auxiliary/test_native_transformed_sft_dataset_validate.py",
            "tests/auxiliary/test_native_transformed_sft_smoke.py",
            "tests/auxiliary/test_native_transformed_rl_dataset.py",
            "tests/auxiliary/test_native_transformed_reward.py",
        ),
        fixtures=("tests/fixtures/claude_api_tool_use_session.jsonl",),
        artifact_prefixes=("native_transformed_",),
        migration_goal="RC-030",
    ),
)


SHARED_KERNEL_PREFIXES: tuple[str, ...] = (
    "pycodeagent.agent.prompt",
    "pycodeagent.mutations",
    "pycodeagent.rl.contract",
    "pycodeagent.rl.loss_mask",
    "pycodeagent.rl.mask_alignment",
    "pycodeagent.rl.packing",
    "pycodeagent.rl.prepared_sample",
    "pycodeagent.rl.schema_following",
    "pycodeagent.rl.schema_following_eval",
    "pycodeagent.rl.schema_following_sft",
    "pycodeagent.rl.serializer",
    "pycodeagent.rl.tensorize",
    "pycodeagent.rl.training_bundle",
    "pycodeagent.rl.tokenizer",
    "pycodeagent.rl.tokenizer_config",
    "pycodeagent.rl.train_config",
    "pycodeagent.rl.train_dataset",
    "pycodeagent.tools",
    "pycodeagent.traces.canonical_trace",
    "pycodeagent.traces.raw_trace",
    "pycodeagent.traces.native_profile_transform",
    "pycodeagent.traces.tool_catalog",
    "pycodeagent.traces.tool_catalog_snapshot",
    "pycodeagent.trajectory",
)
