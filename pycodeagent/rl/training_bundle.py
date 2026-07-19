"""Single deterministic PreparedSample-to-training-bundle orchestration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pycodeagent.rl.contract import (
    ContractIssue,
    ContractVerificationResult,
    verify_prepared_bundle,
)
from pycodeagent.rl.packing import PackedBatch, pack_examples
from pycodeagent.rl.prepared_sample import (
    PREPARED_SAMPLE_SCHEMA_VERSION,
    PreparedSample,
    write_prepared_samples,
)
from pycodeagent.rl.tensorize import tensorize_prepared_sample
from pycodeagent.rl.tokenizer import BaseTokenizerAdapter, resolve_tokenizer_adapter
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig
from pycodeagent.rl.train_config import TrainConfig
from pycodeagent.rl.train_dataset import TrainDataset


TRAINING_BUNDLE_SCHEMA = "pycodeagent-training-bundle/v1"
TRAINING_BUNDLE_VERSION = 1
TRAINING_BUNDLE_ORDERING = (
    "split,task_id,tool_profile_id,sample_id,source_type,sample_type"
)


class TrainingBundleArtifact(BaseModel):
    """Digest and size for one builder-owned artifact."""

    model_config = ConfigDict(extra="forbid")

    sha256: str
    size_bytes: int


class TrainingBundleManifest(BaseModel):
    """Versioned, deterministic manifest for one prepared training bundle."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["pycodeagent-training-bundle/v1"] = TRAINING_BUNDLE_SCHEMA
    version: Literal[1] = TRAINING_BUNDLE_VERSION
    prepared_sample_schema_version: Literal[1] = PREPARED_SAMPLE_SCHEMA_VERSION
    source_type: str
    source_path: str
    sample_count: int
    tokenized_count: int
    packed_sequence_count: int
    max_length: int
    ordering: str = TRAINING_BUNDLE_ORDERING
    contract_ok: bool
    source_artifacts: list[str] = Field(default_factory=list)
    artifacts: dict[str, TrainingBundleArtifact]
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrainingBundleBuildResult(BaseModel):
    """Paths and validated models returned by the shared builder."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    output_dir: Path
    samples_path: Path
    tokenized_path: Path
    packed_path: Path
    tokenizer_config_path: Path
    train_config_path: Path
    contract_report_path: Path
    manifest_path: Path
    manifest: TrainingBundleManifest
    contract_result: ContractVerificationResult


class TrainingBundleBuilder:
    """Build every training bundle through one deterministic orchestration."""

    def build(
        self,
        samples: list[PreparedSample],
        output_dir: str | Path,
        *,
        source_type: str,
        source_path: str | Path,
        run_id: str,
        max_length: int = 2048,
        batch_size: int = 8,
        learning_rate: float = 1e-4,
        max_steps: int = 1000,
        seed: int = 42,
        tokenizer: BaseTokenizerAdapter | None = None,
        tokenizer_config: TokenizerConfig | None = None,
        fake_tokenizer_config: FakeTokenizerConfig | None = None,
        tokenizer_metadata: dict[str, Any] | None = None,
        train_metadata: dict[str, Any] | None = None,
        bundle_metadata: dict[str, Any] | None = None,
        source_artifacts: list[str] | None = None,
        source_issues: list[ContractIssue] | None = None,
        rollout_count: int = 0,
        allow_empty: bool = False,
    ) -> TrainingBundleBuildResult:
        """Serialize, tokenize, pack, verify, and manifest PreparedSample v1."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "bundle_manifest.json"
        if manifest_path.exists():
            manifest_path.unlink()
        ordered_samples = sorted(samples, key=_sample_sort_key)

        tokenizer, resolved_config = resolve_tokenizer_adapter(
            tokenizer=tokenizer,
            tokenizer_config=tokenizer_config,
            fake_tokenizer_config=fake_tokenizer_config,
            default_max_length=max_length,
        )
        resolved_metadata = dict(resolved_config.metadata)
        resolved_metadata.update(tokenizer_metadata or {})
        resolved_config = resolved_config.model_copy(
            update={
                "max_length": max_length,
                "truncation": True,
                "padding": "do_not_pad",
                "metadata": resolved_metadata,
            }
        )

        samples_path = output_dir / "samples.jsonl"
        write_prepared_samples(ordered_samples, samples_path)

        tokenized_examples = [
            tensorize_prepared_sample(sample, tokenizer, resolved_config)
            for sample in ordered_samples
        ]
        tokenized_path = output_dir / "tokenized.jsonl"
        TrainDataset.from_examples(tokenized_examples).save_jsonl(tokenized_path)

        packed = pack_examples(tokenized_examples, max_length=max_length)
        packed_path = output_dir / "packed.jsonl"
        _write_packed_jsonl(packed, packed_path)

        tokenizer_config_path = output_dir / "tokenizer_config.yaml"
        resolved_config.save(tokenizer_config_path)

        train_config = TrainConfig(
            run_id=run_id,
            dataset_path=str(tokenized_path),
            output_dir=str(output_dir / "training_outputs"),
            max_steps=max_steps,
            batch_size=batch_size,
            learning_rate=learning_rate,
            seed=seed,
            allow_empty_dataset=allow_empty,
            metadata=dict(train_metadata or {}),
        )
        train_config_path = output_dir / "train_config.json"
        train_config.save(train_config_path)

        contract_result = verify_prepared_bundle(
            ordered_samples,
            tokenized_examples,
            packed,
            source_type=source_type,
            source_path=str(source_path),
            dataset_dir=output_dir,
            rollout_count=rollout_count,
            initial_issues=source_issues,
            allow_empty=allow_empty,
        )
        contract_report_path = output_dir / "contract_report.json"
        contract_report_path.write_text(
            json.dumps(
                contract_result.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        if not contract_result.ok:
            raise ValueError(
                "Training bundle failed contract verification. "
                f"See {contract_report_path}"
            )

        artifact_paths = (
            samples_path,
            tokenized_path,
            packed_path,
            tokenizer_config_path,
            train_config_path,
            contract_report_path,
        )
        manifest = TrainingBundleManifest(
            source_type=source_type,
            source_path=str(source_path),
            sample_count=len(ordered_samples),
            tokenized_count=len(tokenized_examples),
            packed_sequence_count=len(packed.sequences),
            max_length=max_length,
            contract_ok=contract_result.ok,
            source_artifacts=sorted(set(source_artifacts or [])),
            artifacts={
                path.name: _artifact_digest(path)
                for path in sorted(artifact_paths, key=lambda item: item.name)
            },
            metadata=dict(bundle_metadata or {}),
        )
        manifest_path.write_text(
            json.dumps(
                manifest.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        verify_training_bundle_manifest(output_dir)

        return TrainingBundleBuildResult(
            output_dir=output_dir,
            samples_path=samples_path,
            tokenized_path=tokenized_path,
            packed_path=packed_path,
            tokenizer_config_path=tokenizer_config_path,
            train_config_path=train_config_path,
            contract_report_path=contract_report_path,
            manifest_path=manifest_path,
            manifest=manifest,
            contract_result=contract_result,
        )


def _sample_sort_key(sample: PreparedSample) -> tuple[str, ...]:
    return (
        sample.split,
        sample.task_id,
        sample.tool_profile_id,
        sample.sample_id,
        sample.source_type,
        sample.sample_type,
    )


def _write_packed_jsonl(packed: PackedBatch, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for sequence in packed.sequences:
            handle.write(sequence.model_dump_json())
            handle.write("\n")


def _artifact_digest(path: Path) -> TrainingBundleArtifact:
    payload = path.read_bytes()
    return TrainingBundleArtifact(
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def verify_training_bundle_manifest(
    output_dir: str | Path,
) -> TrainingBundleManifest:
    """Load a v1 manifest and verify every builder-owned artifact checksum."""
    output_dir = Path(output_dir)
    manifest_path = output_dir / "bundle_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing training bundle manifest: {manifest_path}")
    manifest = TrainingBundleManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    for relative_path, expected in manifest.artifacts.items():
        candidate = Path(relative_path)
        if candidate.is_absolute() or len(candidate.parts) != 1:
            raise ValueError(
                f"Unsafe training bundle artifact path: {relative_path}"
            )
        artifact_path = output_dir / candidate
        if not artifact_path.is_file():
            raise ValueError(
                f"Missing training bundle artifact declared by manifest: "
                f"{relative_path}"
            )
        actual = _artifact_digest(artifact_path)
        if actual != expected:
            raise ValueError(
                f"Training bundle checksum mismatch for {relative_path}: "
                f"expected {expected.sha256}, got {actual.sha256}"
            )
    return manifest
