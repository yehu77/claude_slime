"""Tests for vendored slime bridge integration boundaries."""

from __future__ import annotations

import builtins
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SLIME_MAIN = _REPO_ROOT / "slime-main"
_VENDOR_MODULES = [
    "slime.rollout.pycodeagent_offline",
    "slime.rollout",
    "slime.utils.types",
    "slime.utils",
    "slime",
]
_PYCODEAGENT_MODULES = [
    "pycodeagent.rl.slime_bridge",
    "pycodeagent.rl.tokenizer",
    "pycodeagent.rl.tokenizer_config",
]


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


def _import_vendor_module(monkeypatch: pytest.MonkeyPatch):
    _clear_modules()
    for module_name in _PYCODEAGENT_MODULES:
        sys.modules.pop(module_name, None)
    _install_torch_stub(monkeypatch)
    monkeypatch.syspath_prepend(str(_SLIME_MAIN))
    baseline = list(sys.path)
    module = importlib.import_module("slime.rollout.pycodeagent_offline")
    return module, baseline


class TestVendoredPyCodeAgentOfflineBridge:
    def test_import_does_not_mutate_sys_path_or_eager_import_pycodeagent(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module, baseline = _import_vendor_module(monkeypatch)

        assert sys.path == baseline
        assert module.__name__ == "slime.rollout.pycodeagent_offline"
        assert "pycodeagent.rl.slime_bridge" not in sys.modules
        assert "pycodeagent.rl.tokenizer" not in sys.modules
        assert "pycodeagent.rl.tokenizer_config" not in sys.modules

    def test_missing_pycodeagent_dependency_raises_clear_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module, _ = _import_vendor_module(monkeypatch)
        module._load_pycodeagent_dependencies.cache_clear()

        original_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in _PYCODEAGENT_MODULES:
                raise ModuleNotFoundError("No module named 'pycodeagent'")
            return original_import(name, globals, locals, fromlist, level)

        for module_name in _PYCODEAGENT_MODULES:
            sys.modules.pop(module_name, None)

        monkeypatch.setattr(builtins, "__import__", guarded_import)

        with pytest.raises(ModuleNotFoundError, match="requires the pycodeagent package to be importable"):
            module._load_pycodeagent_dependencies()

    def test_data_source_consumes_tokenized_path_without_hf_tokenizer(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module, _ = _import_vendor_module(monkeypatch)

        converted = SimpleNamespace(
            tokens=[1, 2, 3],
            response_length=2,
            reward=0.0,
            loss_mask=[1, 1],
            status="completed",
            metadata={"sample_id": "sample_1"},
            train_metadata={"sample_id": "sample_1"},
        )
        calls: list[str] = []

        def build_rollouts(*args, **kwargs):
            calls.append("rollouts")
            return []

        def build_tokenized(path):
            calls.append(f"tokenized:{Path(path).name}")
            return [converted]

        def is_tokenized(path):
            return Path(path).name == "smoke_tokenized.jsonl"

        class HFTokenizerAdapter:
            def __init__(self, checkpoint):
                raise AssertionError("tokenized input should not construct a tokenizer")

        module._load_pycodeagent_dependencies = lambda: (
            build_rollouts,
            build_tokenized,
            is_tokenized,
            HFTokenizerAdapter,
            object,
        )
        tokenized_path = _REPO_ROOT / "tests" / "_vendor_bridge_tokenized" / "smoke_tokenized.jsonl"
        args = SimpleNamespace(
            n_samples_per_prompt=1,
            prompt_data=str(tokenized_path),
            rollout_shuffle=False,
            rollout_seed=0,
            hf_checkpoint="unused",
            save=None,
            load=None,
        )

        data_source = module.PyCodeAgentPreparedDataSource(args)
        samples = data_source.get_samples(1)

        assert calls == ["tokenized:smoke_tokenized.jsonl"]
        assert len(data_source) == 1
        assert samples[0][0].tokens == [1, 2, 3]
        assert samples[0][0].loss_mask == [1, 1]
        assert samples[0][0].metadata["sample_id"] == "sample_1"

    def test_data_source_keeps_rollouts_path_tokenizer_flow(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module, _ = _import_vendor_module(monkeypatch)

        converted = SimpleNamespace(
            tokens=[4, 5, 6],
            response_length=1,
            reward=0.5,
            loss_mask=[1],
            status="completed",
            metadata={"task_id": "task_1"},
            train_metadata={"task_id": "task_1"},
        )
        calls: list[str] = []

        def build_rollouts(path, tokenizer, *, max_length=None):
            calls.append(f"rollouts:{Path(path).name}:{tokenizer.checkpoint}:{max_length}")
            return [converted]

        def build_tokenized(path):
            calls.append("tokenized")
            return []

        def is_tokenized(path):
            return False

        class HFTokenizerAdapter:
            def __init__(self, checkpoint):
                self.checkpoint = checkpoint

        module._load_pycodeagent_dependencies = lambda: (
            build_rollouts,
            build_tokenized,
            is_tokenized,
            HFTokenizerAdapter,
            object,
        )
        rollouts_path = _REPO_ROOT / "tests" / "_vendor_bridge_rollouts" / "rollouts.jsonl"
        args = SimpleNamespace(
            n_samples_per_prompt=1,
            prompt_data=str(rollouts_path),
            rollout_shuffle=False,
            rollout_seed=0,
            hf_checkpoint="hf",
            rollout_max_context_len=2048,
            save=None,
            load=None,
        )

        data_source = module.PyCodeAgentPreparedDataSource(args)
        samples = data_source.get_samples(1)

        assert calls == ["rollouts:rollouts.jsonl:hf:2048"]
        assert samples[0][0].tokens == [4, 5, 6]
        assert samples[0][0].reward == 0.5

    def test_data_source_rejects_multiple_samples_per_prompt(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module, _ = _import_vendor_module(monkeypatch)
        args = SimpleNamespace(n_samples_per_prompt=2)

        with pytest.raises(ValueError, match="n_samples_per_prompt=1"):
            module.PyCodeAgentPreparedDataSource(args)
