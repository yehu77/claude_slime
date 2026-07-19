"""Tests for vendored native-transformed RL slime bridge boundaries."""

from __future__ import annotations

import asyncio
import builtins
import importlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SLIME_MAIN = _REPO_ROOT / "slime-main"
_VENDOR_MODULES = [
    "slime.rollout.pycodeagent_native_rl",
    "slime.rollout",
    "slime.utils.types",
    "slime.utils",
    "slime",
]
_PYCODEAGENT_MODULES = [
    "pycodeagent.auxiliary.native_transformed.reward",
    "pycodeagent.auxiliary.native_transformed.rl_dataset",
]
_TEST_NAMESPACE = "slime_native_rl_vendor_bridge"


def _install_torch_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    torch_stub = types.ModuleType("torch")
    torch_stub.Tensor = object
    torch_stub.Size = tuple
    torch_stub.dtype = object
    torch_stub.save = lambda *args, **kwargs: None
    torch_stub.load = lambda *args, **kwargs: {}
    monkeypatch.setitem(sys.modules, "torch", torch_stub)


def _clear_modules() -> None:
    for module_name in _VENDOR_MODULES:
        sys.modules.pop(module_name, None)


def _import_vendor_module(monkeypatch: pytest.MonkeyPatch, *, stub_torch: bool = True):
    _clear_modules()
    for module_name in _PYCODEAGENT_MODULES:
        sys.modules.pop(module_name, None)
    if stub_torch:
        _install_torch_stub(monkeypatch)
    else:
        pytest.importorskip("torch")
    monkeypatch.syspath_prepend(str(_SLIME_MAIN))
    baseline = list(sys.path)
    module = importlib.import_module("slime.rollout.pycodeagent_native_rl")
    return module, baseline


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _rl_sample_payload(
    sample_id: str,
    *,
    tool_name: str = "InspectFile",
    path: str = "README.md",
) -> dict:
    return {
        "sample_id": sample_id,
        "sample_type": "native_transformed_rl_prompt",
        "source_type": "native_transformed_claude_api_sft",
        "task_id": f"task_{sample_id}",
        "tool_profile_id": "profile_name_only",
        "messages": [
            {"role": "system", "content": "You are a coding agent.", "metadata": {}},
            {"role": "user", "content": f"Inspect {path}.", "metadata": {}},
        ],
        "tool_specs": [
            {
                "name": tool_name,
                "description": "Read a file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            }
        ],
        "reward_reference": {
            "reference_type": "tool_call_exact",
            "expected_tool_calls": [
                {
                    "call_id": f"call_{sample_id}",
                    "name": tool_name,
                    "arguments": {"file_path": path},
                    "metadata": {},
                }
            ],
            "target_block_count": 1,
            "target_text_block_count": 0,
            "metadata": {},
        },
        "metadata": {
            "transformation_mode": "name_only",
            "source_sample_id": sample_id,
        },
    }


def _write_rl_prompts(path: Path, samples: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _tool_text(name: str, arguments: dict) -> str:
    return (
        "<|tool|>\n"
        + json.dumps(
            {"id": "predicted", "name": name, "arguments": arguments},
            sort_keys=True,
        )
        + "\n<|end|>\n"
    )


class TestVendoredNativeRLBridge:
    def test_import_does_not_mutate_sys_path_or_eager_import_pycodeagent(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module, baseline = _import_vendor_module(monkeypatch)

        assert sys.path == baseline
        assert module.__name__ == "slime.rollout.pycodeagent_native_rl"
        assert "pycodeagent.auxiliary.native_transformed.reward" not in sys.modules
        assert "pycodeagent.auxiliary.native_transformed.rl_dataset" not in sys.modules

    def test_missing_pycodeagent_dependency_raises_clear_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module, _ = _import_vendor_module(monkeypatch, stub_torch=False)
        module._load_pycodeagent_dependencies.cache_clear()

        original_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in _PYCODEAGENT_MODULES:
                raise ModuleNotFoundError("No module named 'pycodeagent'")
            return original_import(name, globals, locals, fromlist, level)

        for module_name in _PYCODEAGENT_MODULES:
            sys.modules.pop(module_name, None)

        monkeypatch.setattr(builtins, "__import__", guarded_import)

        with pytest.raises(ModuleNotFoundError, match="requires the pycodeagent package"):
            module._load_pycodeagent_dependencies()

    def test_data_source_reads_rl_prompts_and_groups_samples(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module, _ = _import_vendor_module(monkeypatch, stub_torch=False)
        module._load_pycodeagent_dependencies.cache_clear()
        tmp = _get_test_dir()
        try:
            dataset_dir = tmp / "dataset"
            prompt_path = dataset_dir / "train" / "rl_prompts.jsonl"
            _write_rl_prompts(
                prompt_path,
                [
                    _rl_sample_payload("sample_1"),
                    _rl_sample_payload("sample_2", path="pyproject.toml"),
                ],
            )
            args = SimpleNamespace(
                n_samples_per_prompt=2,
                prompt_data=str(dataset_dir),
                rollout_shuffle=False,
                rollout_seed=0,
                save=None,
                load=None,
            )

            data_source = module.PyCodeAgentNativeRLDataSource(args)
            groups = data_source.get_samples(1)

            assert len(data_source) == 2
            assert len(groups) == 1
            assert len(groups[0]) == 2
            first, second = groups[0]
            assert first.prompt == second.prompt
            assert first.reward is None
            assert first.group_index == 0
            assert second.group_index == 0
            assert first.index == 0
            assert second.index == 1
            assert first.metadata["sample_id"] == "sample_1"
            assert first.metadata["reward_reference"]["expected_tool_calls"][0]["name"] == "InspectFile"
            assert "native_transformed_rl_sample" in first.metadata
        finally:
            _cleanup(tmp)

    def test_data_source_shuffle_is_seeded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module, _ = _import_vendor_module(monkeypatch, stub_torch=False)
        module._load_pycodeagent_dependencies.cache_clear()
        tmp = _get_test_dir()
        try:
            prompt_path = tmp / "rl_prompts.jsonl"
            _write_rl_prompts(
                prompt_path,
                [
                    _rl_sample_payload("sample_a"),
                    _rl_sample_payload("sample_b"),
                    _rl_sample_payload("sample_c"),
                ],
            )
            args = SimpleNamespace(
                n_samples_per_prompt=1,
                prompt_data=str(prompt_path),
                rollout_shuffle=True,
                rollout_seed=123,
                save=None,
                load=None,
            )

            first = module.PyCodeAgentNativeRLDataSource(args)
            second = module.PyCodeAgentNativeRLDataSource(args)

            assert [
                sample.metadata["sample_id"] for sample in first.templates
            ] == [
                sample.metadata["sample_id"] for sample in second.templates
            ]
        finally:
            _cleanup(tmp)

    def test_reward_func_scores_single_and_batch_samples(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module, _ = _import_vendor_module(monkeypatch, stub_torch=False)
        module._load_pycodeagent_dependencies.cache_clear()
        tmp = _get_test_dir()
        try:
            prompt_path = tmp / "rl_prompts.jsonl"
            _write_rl_prompts(prompt_path, [_rl_sample_payload("sample_1")])
            args = SimpleNamespace(
                n_samples_per_prompt=1,
                prompt_data=str(prompt_path),
                rollout_shuffle=False,
                rollout_seed=0,
                save=None,
                load=None,
            )
            data_source = module.PyCodeAgentNativeRLDataSource(args)
            sample = data_source.get_samples(1)[0][0]
            sample.response = _tool_text("InspectFile", {"file_path": "README.md"})

            single_reward = asyncio.run(module.reward_func(args, sample))
            batch_reward = asyncio.run(module.reward_func(args, [sample]))

            assert single_reward == 1.0
            assert batch_reward == [1.0]
            assert sample.metadata["native_transformed_reward"]["parse_ok"] is True
            assert sample.metadata["native_transformed_reward"]["tool_name_ok"] is True
        finally:
            _cleanup(tmp)

    def test_reward_func_requires_native_rl_metadata(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module, _ = _import_vendor_module(monkeypatch)
        module._load_pycodeagent_dependencies.cache_clear()
        sample = module.Sample(prompt="prompt", response="response", metadata={})

        with pytest.raises(ValueError, match="missing native_transformed_rl_sample"):
            module.sample_to_native_rl_reward_case(sample)
