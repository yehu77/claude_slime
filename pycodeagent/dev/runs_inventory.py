"""Build and verify a deterministic, content-redacted inventory of local runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


RUNS_INVENTORY_SCHEMA = "pycodeagent-runs-inventory/v1"
RUNS_INVENTORY_RECORD_SCHEMA = "pycodeagent-runs-inventory-record/v1"
DEFAULT_RUNS_ROOT = Path("runs")
DEFAULT_SUMMARY_PATH = Path("references/runs-inventory.summary.json")
DEFAULT_INVENTORY_PATH = Path("references/runs-inventory.jsonl")

_METADATA_KEYS = {
    "run_id": ("run_id",),
    "task_id": ("task_id",),
    "profile_id": ("tool_profile_id", "profile_id"),
    "family": (
        "tool_stack_kind",
        "tool_family",
        "native_family",
        "family",
    ),
    "status": ("final_status", "status"),
    "schema_version": ("schema_version", "version"),
}
_METADATA_SOURCE_KEYS = {
    source_key: canonical_key
    for canonical_key, source_keys in _METADATA_KEYS.items()
    for source_key in source_keys
}
_SAFE_METADATA_RE = re.compile(r"^[A-Za-z0-9_.:/+-]{1,160}$")
_SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "potential_authorization_material",
        re.compile(
            rb"(?i)(authorization|api[_-]?key|access[_-]?token|"
            rb"secret[_-]?key|bearer[ \t]+[A-Za-z0-9])"
        ),
    ),
    (
        "private_key_material",
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "personal_email",
        re.compile(
            rb"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
        ),
    ),
    (
        "absolute_user_path",
        re.compile(rb"(?:/home/|/Users/)[A-Za-z0-9._-]+/"),
    ),
)
_KNOWN_MANIFEST_REFERENCES: Mapping[str, tuple[str, ...]] = {
    "runtime_trace_manifest.json": ("event_log_path", "payload_dir"),
    "request_context_manifest.json": ("entry_log_path",),
    "retained_history_manifest.json": ("entry_log_path",),
}


class RunsInventoryError(ValueError):
    """Raised when inventory inputs, output records, or verification drift."""


@dataclass(frozen=True)
class _ScannedArtifact:
    record: dict[str, Any]
    content_digest: str | None
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class RunsInventory:
    """Deterministic in-memory inventory ready for redacted serialization."""

    summary: dict[str, Any]
    groups: tuple[dict[str, Any], ...]
    artifacts: tuple[dict[str, Any], ...]

    def records(self) -> Iterable[dict[str, Any]]:
        yield {
            "schema": RUNS_INVENTORY_RECORD_SCHEMA,
            "record_type": "inventory",
            **self.summary,
        }
        yield from self.groups
        yield from self.artifacts


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def scan_runs(
    repo_root: str | Path,
    *,
    runs_root: str | Path = DEFAULT_RUNS_ROOT,
) -> RunsInventory:
    """Scan runs read-only and return only paths, metadata, hashes, and labels."""
    root = Path(repo_root).resolve()
    resolved_runs = _resolve_under_root(root, runs_root)
    if not resolved_runs.is_dir():
        raise RunsInventoryError(f"Runs root is missing: {resolved_runs}")
    runs_root_label = resolved_runs.relative_to(root).as_posix()

    scanned: list[_ScannedArtifact] = []
    for artifact_path in _iter_artifacts(resolved_runs):
        scanned.append(
            _scan_artifact(
                artifact_path,
                repo_root=root,
                runs_root=resolved_runs,
            )
        )

    duplicate_ids, duplicate_group_count, duplicate_file_count, duplicate_bytes = (
        _duplicate_assignments(scanned)
    )
    artifact_records: list[dict[str, Any]] = []
    for item in scanned:
        record = dict(item.record)
        record["duplicate_group_id"] = duplicate_ids.get(record["path"])
        artifact_records.append(record)
    artifact_records.sort(key=lambda record: record["path"])
    group_records = _build_group_records(artifact_records)

    classification_counts = Counter(
        record["artifact_class"] for record in artifact_records
    )
    parse_counts = Counter(record["parse_status"] for record in artifact_records)
    manifest_counts = Counter(
        record["manifest_status"] for record in artifact_records
    )
    risk_counts = Counter(
        risk
        for record in artifact_records
        for risk in record["sensitive_risk_labels"]
    )
    group_classification_counts = Counter(
        record["group_class"] for record in group_records
    )
    total_bytes = sum(record["size_bytes"] for record in artifact_records)
    state_fingerprint = _state_fingerprint(scanned)
    summary = {
        "inventory_schema": RUNS_INVENTORY_SCHEMA,
        "runs_root": runs_root_label,
        "state_fingerprint": state_fingerprint,
        "artifact_count": len(artifact_records),
        "artifact_group_count": len(group_records),
        "total_bytes": total_bytes,
        "classification_status": "complete",
        "classified_artifact_count": len(artifact_records),
        "classified_group_count": len(group_records),
        "artifact_class_counts": dict(sorted(classification_counts.items())),
        "group_class_counts": dict(sorted(group_classification_counts.items())),
        "parse_status_counts": dict(sorted(parse_counts.items())),
        "manifest_status_counts": dict(sorted(manifest_counts.items())),
        "sensitive_risk_label_counts": dict(sorted(risk_counts.items())),
        "duplicate_group_count": duplicate_group_count,
        "duplicate_file_count": duplicate_file_count,
        "duplicate_redundant_bytes": duplicate_bytes,
        "inventory_file": DEFAULT_INVENTORY_PATH.as_posix(),
        "content_policy": (
            "No payload text, tool arguments/results, secret matches, or "
            "workspace file contents are serialized."
        ),
    }
    return RunsInventory(
        summary=summary,
        groups=tuple(group_records),
        artifacts=tuple(artifact_records),
    )


def write_inventory(
    inventory: RunsInventory,
    *,
    summary_path: str | Path,
    inventory_path: str | Path,
) -> None:
    """Write deterministic JSON/JSONL outputs after an explicit caller request."""
    summary_target = Path(summary_path)
    records_target = Path(inventory_path)
    summary_target.parent.mkdir(parents=True, exist_ok=True)
    records_target.parent.mkdir(parents=True, exist_ok=True)
    summary_target.write_text(
        json.dumps(inventory.summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with records_target.open("w", encoding="utf-8", newline="\n") as handle:
        for record in inventory.records():
            handle.write(
                json.dumps(
                    record,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            handle.write("\n")


def load_and_validate_inventory(
    *,
    summary_path: str | Path,
    inventory_path: str | Path,
) -> RunsInventory:
    """Load tracked outputs and enforce redaction/completeness invariants."""
    summary_target = Path(summary_path)
    records_target = Path(inventory_path)
    try:
        summary = json.loads(summary_target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunsInventoryError(
            f"Runs inventory summary is missing: {summary_target}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RunsInventoryError(
            f"Runs inventory summary is invalid JSON: {summary_target}"
        ) from exc
    if not isinstance(summary, dict):
        raise RunsInventoryError("Runs inventory summary must be an object")
    if summary.get("inventory_schema") != RUNS_INVENTORY_SCHEMA:
        raise RunsInventoryError("Unsupported runs inventory summary schema")

    groups: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    inventory_headers: list[dict[str, Any]] = []
    try:
        lines = records_target.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise RunsInventoryError(
            f"Runs inventory records are missing: {records_target}"
        ) from exc
    for line_number, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RunsInventoryError(
                f"Invalid inventory JSONL at line {line_number}"
            ) from exc
        _validate_record(record, line_number=line_number)
        record_type = record["record_type"]
        if record_type == "inventory":
            inventory_headers.append(record)
        elif record_type == "artifact_group":
            groups.append(record)
        else:
            artifacts.append(record)

    expected_header = {
        "schema": RUNS_INVENTORY_RECORD_SCHEMA,
        "record_type": "inventory",
        **summary,
    }
    if (
        len(inventory_headers) != 1
        or not lines
        or json.loads(lines[0]).get("record_type") != "inventory"
        or inventory_headers[0] != expected_header
    ):
        raise RunsInventoryError(
            "Inventory JSONL must begin with exactly the tracked summary record"
        )
    if len(artifacts) != summary.get("artifact_count"):
        raise RunsInventoryError("Artifact count does not match inventory summary")
    if len(groups) != summary.get("artifact_group_count"):
        raise RunsInventoryError("Artifact-group count does not match summary")
    if len({record["path"] for record in artifacts}) != len(artifacts):
        raise RunsInventoryError("Artifact paths must be unique")
    if len({record["path"] for record in groups}) != len(groups):
        raise RunsInventoryError("Artifact-group paths must be unique")
    if summary.get("classified_artifact_count") != len(artifacts):
        raise RunsInventoryError("Inventory is not 100% artifact-classified")
    if summary.get("classified_group_count") != len(groups):
        raise RunsInventoryError("Inventory is not 100% group-classified")
    if summary.get("classification_status") != "complete":
        raise RunsInventoryError("Inventory classification_status is not complete")
    return RunsInventory(
        summary=summary,
        groups=tuple(groups),
        artifacts=tuple(artifacts),
    )


def verify_inventory_against_runs(
    repo_root: str | Path,
    *,
    runs_root: str | Path = DEFAULT_RUNS_ROOT,
    summary_path: str | Path = DEFAULT_SUMMARY_PATH,
    inventory_path: str | Path = DEFAULT_INVENTORY_PATH,
) -> RunsInventory:
    """Rescan without writes and require exact deterministic output equality."""
    root = Path(repo_root).resolve()
    tracked = load_and_validate_inventory(
        summary_path=_resolve_under_root(root, summary_path),
        inventory_path=_resolve_under_root(root, inventory_path),
    )
    actual = scan_runs(root, runs_root=runs_root)
    if tracked.summary != actual.summary:
        raise RunsInventoryError(
            "Runs inventory summary drift; rerun the explicit scan command"
        )
    if tracked.groups != actual.groups or tracked.artifacts != actual.artifacts:
        raise RunsInventoryError(
            "Runs inventory record drift; rerun the explicit scan command"
        )
    return tracked


def _iter_artifacts(runs_root: Path) -> Iterable[Path]:
    for directory, dirnames, filenames in os.walk(runs_root, followlinks=False):
        directory_path = Path(directory)
        symlink_dirs = [
            name for name in dirnames if (directory_path / name).is_symlink()
        ]
        dirnames[:] = sorted(name for name in dirnames if name not in symlink_dirs)
        for name in sorted(symlink_dirs):
            yield directory_path / name
        for name in sorted(filenames):
            yield directory_path / name


def _scan_artifact(
    path: Path,
    *,
    repo_root: Path,
    runs_root: Path,
) -> _ScannedArtifact:
    relative_repo_path = path.relative_to(repo_root).as_posix()
    relative_runs_path = path.relative_to(runs_root).as_posix()
    file_stat = path.lstat()
    file_kind = _file_kind(file_stat.st_mode)
    content: bytes | None = None
    digest: str | None = None
    read_status = "ok"
    if file_kind == "regular":
        try:
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
        except OSError:
            read_status = "read_error"
    elif file_kind == "symlink":
        try:
            target = os.readlink(path)
            digest = hashlib.sha256(target.encode("utf-8")).hexdigest()
        except OSError:
            read_status = "read_error"

    artifact_class = _classify_artifact(
        PurePosixPath(relative_runs_path),
        file_kind=file_kind,
    )
    metadata, parse_status, manifest_status, manifest_reference_status = (
        _structured_metadata(
            path,
            content=content,
            artifact_class=artifact_class,
            repo_root=repo_root,
        )
    )
    if read_status != "ok":
        parse_status = read_status
        if artifact_class == "manifest":
            manifest_status = "read_error"
    risks = _risk_labels(
        PurePosixPath(relative_runs_path),
        artifact_class=artifact_class,
        file_kind=file_kind,
        content=content,
    )
    record = {
        "schema": RUNS_INVENTORY_RECORD_SCHEMA,
        "record_type": "artifact",
        "path": relative_repo_path,
        "parent_group": path.parent.relative_to(repo_root).as_posix(),
        "campaign": PurePosixPath(relative_runs_path).parts[0],
        "size_bytes": file_stat.st_size,
        "mtime_ns": file_stat.st_mtime_ns,
        "mtime_utc": _mtime_utc(file_stat.st_mtime_ns),
        "file_kind": file_kind,
        "artifact_class": artifact_class,
        "classification_status": "classified",
        "parse_status": parse_status,
        "manifest_status": manifest_status,
        "manifest_reference_status": manifest_reference_status,
        "metadata": metadata,
        "sensitive_risk_labels": risks,
        "duplicate_group_id": None,
    }
    return _ScannedArtifact(record=record, content_digest=digest, metadata=metadata)


def _file_kind(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "regular"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "special"


def _classify_artifact(path: PurePosixPath, *, file_kind: str) -> str:
    if file_kind == "symlink":
        return "symlink"
    if file_kind == "special":
        return "special"
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    suffix = path.suffix.lower()
    if "manifest" in name and suffix == ".json":
        return "manifest"
    if "payloads" in parts or "claude_gateway_traces" in parts:
        return "raw_provider_payload"
    if "workspace" in parts or "w" in parts:
        return "workspace_snapshot"
    if suffix in {".pyc", ".pyo"} or "__pycache__" in parts:
        return "compiled_artifact"
    if suffix in {".patch", ".diff"}:
        return "patch"
    if suffix == ".log":
        return "log"
    if any(
        marker in name
        for marker in (
            "runtime_trace",
            "request_context",
            "retained_history",
            "trajectory",
        )
    ):
        return "trace"
    if suffix == ".jsonl" and any(
        marker in name for marker in ("samples", "tokenized", "train")
    ):
        return "dataset"
    if any(marker in name for marker in ("report", "summary", "metrics", "acceptance")):
        return "report"
    if suffix in {".yaml", ".yml", ".toml"} or "config" in name:
        return "config"
    if suffix == ".json":
        return "structured_artifact"
    if suffix == ".jsonl":
        return "event_log"
    if suffix in {".py", ".sh", ".md", ".txt"}:
        return "source_or_text_snapshot"
    return "other"


def _structured_metadata(
    path: Path,
    *,
    content: bytes | None,
    artifact_class: str,
    repo_root: Path,
) -> tuple[dict[str, Any], str, str, str]:
    empty_metadata = {key: None for key in _METADATA_KEYS}
    if content is None or path.suffix.lower() not in {".json", ".jsonl"}:
        manifest_status = "not_manifest"
        if artifact_class == "manifest":
            manifest_status = "read_error"
        return empty_metadata, "not_structured", manifest_status, "not_applicable"

    objects: list[Any] = []
    try:
        if path.suffix.lower() == ".json":
            objects.append(json.loads(content.decode("utf-8")))
        else:
            for raw_line in content.splitlines()[:16]:
                if raw_line.strip():
                    objects.append(json.loads(raw_line.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        manifest_status = (
            "invalid_json" if artifact_class == "manifest" else "not_manifest"
        )
        return empty_metadata, "invalid_json", manifest_status, "not_applicable"

    metadata = dict(empty_metadata)
    for obj in objects:
        _collect_metadata(obj, metadata, remaining_nodes=[5000])
    manifest_status = "not_manifest"
    reference_status = "not_applicable"
    if artifact_class == "manifest":
        if not objects or not isinstance(objects[0], dict):
            manifest_status = "invalid_shape"
        else:
            manifest_status = "valid"
            reference_status = _manifest_reference_status(
                path,
                objects[0],
                repo_root=repo_root,
            )
            if reference_status == "missing_reference":
                manifest_status = "missing_references"
    return metadata, "parsed", manifest_status, reference_status


def _collect_metadata(
    value: Any,
    output: dict[str, Any],
    *,
    remaining_nodes: list[int],
) -> None:
    if remaining_nodes[0] <= 0:
        return
    remaining_nodes[0] -= 1
    if isinstance(value, dict):
        for key, child in value.items():
            canonical = _METADATA_SOURCE_KEYS.get(str(key))
            if canonical is not None and output[canonical] is None:
                output[canonical] = _sanitize_metadata_value(child)
            if any(item is None for item in output.values()):
                _collect_metadata(child, output, remaining_nodes=remaining_nodes)
    elif isinstance(value, list):
        for child in value[:100]:
            if not any(item is None for item in output.values()):
                break
            _collect_metadata(child, output, remaining_nodes=remaining_nodes)


def _sanitize_metadata_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        if _SAFE_METADATA_RE.fullmatch(value) and not any(
            pattern.search(encoded) for _label, pattern in _SENSITIVE_PATTERNS
        ):
            return value
        return {
            "redacted": True,
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    return {
        "redacted": True,
        "type": type(value).__name__,
    }


def _manifest_reference_status(
    manifest_path: Path,
    payload: Mapping[str, Any],
    *,
    repo_root: Path,
) -> str:
    reference_keys = _KNOWN_MANIFEST_REFERENCES.get(manifest_path.name)
    if reference_keys is None:
        return "not_defined"
    for key in reference_keys:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            return "missing_reference"
        candidate = Path(value)
        if candidate.is_absolute():
            if not candidate.exists():
                return "missing_reference"
            continue
        local_candidate = manifest_path.parent / candidate
        root_candidate = repo_root / candidate
        if not local_candidate.exists() and not root_candidate.exists():
            return "missing_reference"
    return "complete"


def _risk_labels(
    path: PurePosixPath,
    *,
    artifact_class: str,
    file_kind: str,
    content: bytes | None,
) -> list[str]:
    risks: set[str] = set()
    if artifact_class == "raw_provider_payload":
        risks.add("raw_provider_content")
    if artifact_class in {"trace", "event_log"}:
        risks.add("raw_trace_content")
    if artifact_class == "workspace_snapshot":
        risks.add("workspace_snapshot_content")
    if artifact_class == "compiled_artifact":
        risks.add("compiled_or_binary_content")
    if artifact_class == "log":
        risks.add("log_content")
    if file_kind == "symlink":
        risks.add("symlink_boundary")
    if path.name.startswith(".env"):
        risks.add("environment_secret_file")
    if content is not None:
        for label, pattern in _SENSITIVE_PATTERNS:
            if pattern.search(content):
                risks.add(label)
    return sorted(risks)


def _duplicate_assignments(
    scanned: Sequence[_ScannedArtifact],
) -> tuple[dict[str, str], int, int, int]:
    by_digest: dict[tuple[int, str], list[str]] = defaultdict(list)
    for item in scanned:
        digest = item.content_digest
        if digest is None:
            continue
        by_digest[(item.record["size_bytes"], digest)].append(item.record["path"])
    groups = [
        (key, sorted(paths))
        for key, paths in by_digest.items()
        if len(paths) > 1
    ]
    groups.sort(key=lambda item: item[1])
    assignments: dict[str, str] = {}
    duplicate_file_count = 0
    redundant_bytes = 0
    for index, ((size_bytes, _digest), paths) in enumerate(groups, start=1):
        group_id = f"dup-{index:05d}"
        for path in paths:
            assignments[path] = group_id
        duplicate_file_count += len(paths)
        redundant_bytes += size_bytes * (len(paths) - 1)
    return assignments, len(groups), duplicate_file_count, redundant_bytes


def _build_group_records(
    artifacts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_parent: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in artifacts:
        by_parent[str(record["parent_group"])].append(record)
    groups: list[dict[str, Any]] = []
    for parent, members in sorted(by_parent.items()):
        metadata = {key: None for key in _METADATA_KEYS}
        for member in members:
            for key, value in member["metadata"].items():
                if metadata[key] is None and value is not None:
                    metadata[key] = value
        manifest_members = [
            member for member in members if member["artifact_class"] == "manifest"
        ]
        if not manifest_members:
            manifest_status = "absent"
        elif all(member["manifest_status"] == "valid" for member in manifest_members):
            manifest_status = "present_valid"
        else:
            manifest_status = "present_with_issues"
        group_class = _classify_group(members)
        risk_labels = sorted(
            {
                risk
                for member in members
                for risk in member["sensitive_risk_labels"]
            }
        )
        groups.append(
            {
                "schema": RUNS_INVENTORY_RECORD_SCHEMA,
                "record_type": "artifact_group",
                "path": parent,
                "campaign": (
                    PurePosixPath(parent).parts[1]
                    if len(PurePosixPath(parent).parts) > 1
                    else "__root__"
                ),
                "artifact_count": len(members),
                "total_bytes": sum(
                    int(member["size_bytes"]) for member in members
                ),
                "group_class": group_class,
                "classification_status": "classified",
                "manifest_status": manifest_status,
                "metadata": metadata,
                "sensitive_risk_labels": risk_labels,
            }
        )
    return groups


def _classify_group(members: Sequence[Mapping[str, Any]]) -> str:
    classes = {str(member["artifact_class"]) for member in members}
    names = {PurePosixPath(str(member["path"])).name for member in members}
    if "runtime_trace_manifest.json" in names or "trajectory.json" in names:
        return "runtime_run"
    if "dataset_manifest.json" in names or "training_prep.json" in names:
        return "dataset_or_training_bundle"
    if "raw_provider_payload" in classes:
        return "provider_payload_group"
    if "workspace_snapshot" in classes:
        return "workspace_snapshot_group"
    if "manifest" in classes:
        return "manifested_artifact_group"
    if classes <= {"compiled_artifact"}:
        return "compiled_cache_group"
    if "log" in classes:
        return "log_group"
    return "unmanifested_artifact_group"


def _state_fingerprint(scanned: Sequence[_ScannedArtifact]) -> str:
    digest = hashlib.sha256()
    for item in sorted(scanned, key=lambda entry: entry.record["path"]):
        record = item.record
        digest.update(str(record["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record["size_bytes"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(record["mtime_ns"]).encode("ascii"))
        digest.update(b"\0")
        digest.update((item.content_digest or "unreadable").encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _mtime_utc(mtime_ns: int) -> str:
    return datetime.fromtimestamp(
        mtime_ns / 1_000_000_000,
        tz=timezone.utc,
    ).isoformat(timespec="microseconds")


def _validate_record(record: Any, *, line_number: int) -> None:
    if not isinstance(record, dict):
        raise RunsInventoryError(
            f"Inventory record at line {line_number} must be an object"
        )
    if record.get("schema") != RUNS_INVENTORY_RECORD_SCHEMA:
        raise RunsInventoryError(
            f"Inventory record schema drift at line {line_number}"
        )
    record_type = record.get("record_type")
    if record_type not in {"inventory", "artifact_group", "artifact"}:
        raise RunsInventoryError(
            f"Unsupported inventory record type at line {line_number}"
        )
    serialized = json.dumps(record, sort_keys=True)
    forbidden_keys = (
        '"content"',
        '"tool_arguments"',
        '"tool_results"',
        '"secret_value"',
        '"payload_text"',
    )
    if any(forbidden in serialized for forbidden in forbidden_keys):
        raise RunsInventoryError(
            f"Forbidden content-bearing field at line {line_number}"
        )
    if record_type in {"artifact_group", "artifact"}:
        if record.get("classification_status") != "classified":
            raise RunsInventoryError(
                f"Unclassified inventory record at line {line_number}"
            )
        if not isinstance(record.get("path"), str):
            raise RunsInventoryError(
                f"Inventory path missing at line {line_number}"
            )


def _resolve_under_root(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (root / candidate).resolve()
    )
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RunsInventoryError(f"Path escapes repository root: {path}") from exc
    return resolved


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("scan", "validate", "verify"))
    parser.add_argument("--repo-root", type=Path, default=project_root())
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = args.repo_root.resolve()
    try:
        summary_path = _resolve_under_root(root, args.summary)
        inventory_path = _resolve_under_root(root, args.inventory)
        if args.command == "scan":
            inventory = scan_runs(root, runs_root=args.runs_root)
            write_inventory(
                inventory,
                summary_path=summary_path,
                inventory_path=inventory_path,
            )
            print(
                f"runs-inventory: wrote {inventory.summary['artifact_count']} "
                f"artifacts and {inventory.summary['artifact_group_count']} groups; "
                f"state={inventory.summary['state_fingerprint']}"
            )
        elif args.command == "validate":
            inventory = load_and_validate_inventory(
                summary_path=summary_path,
                inventory_path=inventory_path,
            )
            print(
                f"runs-inventory: valid tracked report with "
                f"{inventory.summary['artifact_count']} artifacts"
            )
        else:
            inventory = verify_inventory_against_runs(
                root,
                runs_root=args.runs_root,
                summary_path=summary_path,
                inventory_path=inventory_path,
            )
            print(
                f"runs-inventory: tracked report matches "
                f"{inventory.summary['state_fingerprint']}"
            )
    except (RunsInventoryError, OSError) as exc:
        print(f"runs-inventory: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
