"""Validate the installed read-only legacy-study archive boundary."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


BOUNDARY_SCHEMA = "repository-cleanup-legacy-study-archive-boundary/v1"
ARCHIVE_MANIFEST_SCHEMA = (
    "repository-cleanup-legacy-study-archive-manifest/v1"
)
DEFAULT_BOUNDARY_PATH = Path(
    "docs/repository_cleanup/legacy_study_archive_boundary.json"
)
_ARCHIVE_DISPOSITIONS = {"archive_rc026", "archive_rc027"}
_ALLOWED_SOURCE_DISPOSITIONS = {
    "archive_rc026",
    "archive_rc027",
    "edit_rc026",
    "edit_rc027",
    "retired_rc057",
}
_GOAL_BY_DISPOSITION = {
    "archive_rc026": "RC-026",
    "archive_rc027": "RC-027",
    "edit_rc026": "RC-026",
    "edit_rc027": "RC-027",
    "retired_rc057": "RC-057",
}
_SCANNED_ROOTS = ("pycodeagent", "tests")
_IGNORED_EDGE_SOURCES = {
    "pycodeagent/dev/legacy_study_boundary.py",
    "tests/test_docs_taxonomy.py",
    "tests/test_legacy_study_boundary.py",
    "tests/test_repository_cleanup_decisions.py",
}


class LegacyStudyBoundaryError(ValueError):
    """Raised when the archive contract or repository state drifts."""


@dataclass(frozen=True)
class BoundaryVerification:
    asset_count: int
    archive_asset_count: int
    archive_manifest_entry_count: int
    frozen_edge_count: int
    edge_count: int
    active_reverse_dependency_count: int
    implementation_state: str


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_boundary(path: str | Path) -> Mapping[str, Any]:
    boundary_path = Path(path)
    try:
        payload = json.loads(boundary_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LegacyStudyBoundaryError(
            f"Legacy study boundary is missing: {boundary_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise LegacyStudyBoundaryError(
            f"Legacy study boundary is invalid JSON: {boundary_path}"
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema") != BOUNDARY_SCHEMA:
        raise LegacyStudyBoundaryError("Unsupported legacy study boundary schema")
    return payload


def verify_boundary(
    repo_root: str | Path,
    *,
    boundary_path: str | Path = DEFAULT_BOUNDARY_PATH,
) -> BoundaryVerification:
    root = Path(repo_root).resolve()
    boundary = load_boundary(_rooted(root, boundary_path))
    if boundary.get("goal_id") != "RC-025":
        raise LegacyStudyBoundaryError("Legacy study boundary goal_id drift")
    if boundary.get("decision_ref") != (
        "docs/repository_cleanup/legacy_study_route_decision.json"
    ):
        raise LegacyStudyBoundaryError("Legacy study decision reference drift")

    _validate_archive_contract(boundary)
    assets = _validate_assets(root, boundary)
    _validate_protected_dependencies(root, boundary, assets)
    frozen_edges = _validate_frozen_edges(boundary)
    _validate_cross_goal_constraints(boundary, frozen_edges)
    manifest_count = _validate_archive_manifest(root, boundary, assets)
    _validate_pytest_exclusion(root)

    observed_edges = build_edges(root, boundary)
    if boundary.get("post_archive_edges") != observed_edges:
        raise LegacyStudyBoundaryError(
            "Legacy study post-archive dependency edges drift"
        )

    disposition_by_path = {
        str(asset["path"]): str(asset["disposition"]) for asset in assets
    }
    archive_targets = {
        str(asset["path"])
        for asset in assets
        if asset["disposition"] in _ARCHIVE_DISPOSITIONS
    }
    active_reverse_edges = [
        edge
        for edge in observed_edges
        if edge["target"] in archive_targets
        and disposition_by_path.get(edge["source"])
        not in _ALLOWED_SOURCE_DISPOSITIONS
    ]
    if active_reverse_edges:
        first = active_reverse_edges[0]
        raise LegacyStudyBoundaryError(
            "Active source depends on legacy archive target: "
            f"{first['source']} -> {first['target']}"
        )

    expected_reverse_summary = {
        "status": "none",
        "count": 0,
        "policy": (
            "Every source edge into an archive target is itself archived, "
            "edited at the owning migration boundary, a negative guard, "
            "or separately retired."
        ),
    }
    if boundary.get("active_reverse_dependencies") != expected_reverse_summary:
        raise LegacyStudyBoundaryError(
            "Active reverse-dependency summary is not fail-closed"
        )

    archive_count = sum(
        asset["disposition"] in _ARCHIVE_DISPOSITIONS for asset in assets
    )
    return BoundaryVerification(
        asset_count=len(assets),
        archive_asset_count=archive_count,
        archive_manifest_entry_count=manifest_count,
        frozen_edge_count=len(frozen_edges),
        edge_count=len(observed_edges),
        active_reverse_dependency_count=0,
        implementation_state="archived",
    )


def build_edges(
    repo_root: str | Path,
    boundary: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Rebuild active-tree references into logical archived source paths."""

    root = Path(repo_root).resolve()
    assets = boundary.get("assets")
    if not isinstance(assets, list):
        raise LegacyStudyBoundaryError("Boundary assets must be a list")
    asset_paths = {
        str(asset.get("path"))
        for asset in assets
        if (
            isinstance(asset, dict)
            and isinstance(asset.get("path"), str)
            and asset.get("disposition") in _ARCHIVE_DISPOSITIONS
        )
    }
    module_targets: dict[str, str] = {}
    path_targets: dict[str, str] = {}
    for path_text in asset_paths:
        path = Path(path_text)
        if path.suffix == ".py":
            module_targets[_module_name(path)] = path_text
        path_targets[path_text] = path_text

    edges: set[tuple[str, str, str]] = set()
    for source_path in _python_sources(root):
        source = source_path.relative_to(root).as_posix()
        if source in _IGNORED_EDGE_SOURCES:
            continue
        try:
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            raise LegacyStudyBoundaryError(
                f"Cannot parse Python dependency source: {source}"
            ) from exc
        for target in _import_targets(tree, module_targets):
            if target != source:
                edges.add((source, target, "python_import"))
        for value in _string_values(tree):
            for target in _matching_path_targets(value, path_targets):
                if target != source:
                    edges.add((source, target, "path_reference"))

    for source_path in sorted((root / "configs").rglob("*.json")):
        source = source_path.relative_to(root).as_posix()
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LegacyStudyBoundaryError(
                f"Cannot parse JSON dependency source: {source}"
            ) from exc
        for value in _json_strings(payload):
            for target in _matching_path_targets(value, path_targets):
                if target != source:
                    edges.add((source, target, "path_reference"))

    for source_path in _active_markdown_sources(root):
        source = source_path.relative_to(root).as_posix()
        text = source_path.read_text(encoding="utf-8")
        for target in path_targets:
            if target in text or Path(target).name in text:
                edges.add((source, target, "path_reference"))

    return [
        {"source": source, "target": target, "kind": kind}
        for source, target, kind in sorted(edges)
    ]


def _validate_archive_contract(boundary: Mapping[str, Any]) -> None:
    expected = {
        "archive_id": "legacy-study-readonly-v1",
        "archive_root": "archive/legacy-study-v1",
        "layout": "preserve_repository_relative_paths",
        "execution_status": "historical_reference_only",
        "python_importable": False,
        "pytest_collectable": False,
        "checksum_algorithm": "sha256",
        "move_installation": "copy_verify_then_remove_source_in_same_reviewed_diff",
        "compatibility_shims": "forbidden_without_separate_contract",
        "manifest_path": "archive/legacy-study-v1/archive_manifest.json",
    }
    if boundary.get("archive_contract") != expected:
        raise LegacyStudyBoundaryError("Legacy study archive contract drift")


def _validate_assets(
    root: Path,
    boundary: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    assets = boundary.get("assets")
    if not isinstance(assets, list) or not assets:
        raise LegacyStudyBoundaryError("Boundary assets must be non-empty")
    allowed_keys = {
        "path",
        "kind",
        "owner",
        "disposition",
        "implementation_goal",
        "archive_path",
        "reason",
    }
    paths: set[str] = set()
    archive_paths: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict) or set(asset) != allowed_keys:
            raise LegacyStudyBoundaryError("Boundary asset fields drift")
        path = _required_string(asset, "path")
        pure_path = Path(path)
        if (
            pure_path.is_absolute()
            or ".." in pure_path.parts
            or any(character in path for character in "*?[]")
        ):
            raise LegacyStudyBoundaryError(
                f"Boundary asset path must be exact and relative: {path}"
            )
        if path in paths:
            raise LegacyStudyBoundaryError(f"Duplicate boundary asset: {path}")
        paths.add(path)
        _required_string(asset, "kind")
        _required_string(asset, "owner")
        disposition = _required_string(asset, "disposition")
        goal = _required_string(asset, "implementation_goal")
        if _GOAL_BY_DISPOSITION.get(disposition) != goal:
            raise LegacyStudyBoundaryError(
                f"Boundary asset {path} has invalid disposition/goal ownership"
            )
        _required_string(asset, "reason")
        archive_path = asset.get("archive_path")
        source_exists = (root / path).is_file()
        if disposition in _ARCHIVE_DISPOSITIONS:
            expected_archive_path = f"archive/legacy-study-v1/{path}"
            if archive_path != expected_archive_path:
                raise LegacyStudyBoundaryError(
                    f"Archive path must preserve source path: {path}"
                )
            if archive_path in archive_paths:
                raise LegacyStudyBoundaryError(
                    f"Duplicate archive destination: {archive_path}"
                )
            archive_paths.add(str(archive_path))
            archived_exists = (root / str(archive_path)).is_file()
            if source_exists or not archived_exists:
                raise LegacyStudyBoundaryError(
                    f"Archive installation incomplete for {path}: "
                    "source must be absent and destination present"
                )
        else:
            if archive_path is not None:
                raise LegacyStudyBoundaryError(
                    f"Non-archive asset cannot have archive_path: {path}"
                )
            if disposition == "retired_rc057":
                if source_exists:
                    raise LegacyStudyBoundaryError(
                        f"Retired boundary asset reappeared: {path}"
                    )
            elif not source_exists:
                raise LegacyStudyBoundaryError(
                    f"Boundary asset is missing: {path}"
                )
    return assets


def _validate_archive_manifest(
    root: Path,
    boundary: Mapping[str, Any],
    assets: Sequence[Mapping[str, Any]],
) -> int:
    contract = boundary["archive_contract"]
    manifest_path = root / str(contract["manifest_path"])
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise LegacyStudyBoundaryError(
            "Legacy study archive manifest is missing or invalid"
        ) from exc
    expected_header = {
        "schema": ARCHIVE_MANIFEST_SCHEMA,
        "archive_id": contract["archive_id"],
        "created": "2026-07-18",
        "goals": ["RC-026", "RC-027"],
        "boundary_ref": DEFAULT_BOUNDARY_PATH.as_posix(),
        "execution_status": contract["execution_status"],
        "checksum_algorithm": "sha256",
        "source_count": 29,
    }
    for key, value in expected_header.items():
        if manifest.get(key) != value:
            raise LegacyStudyBoundaryError(
                f"Legacy study archive manifest {key} drift"
            )
    entries = manifest.get("entries")
    if not isinstance(entries, list) or len(entries) != 29:
        raise LegacyStudyBoundaryError(
            "Legacy study archive manifest entry count drift"
        )
    expected_assets = {
        str(asset["path"]): asset
        for asset in assets
        if asset["disposition"] in _ARCHIVE_DISPOSITIONS
    }
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "source",
            "archive_path",
            "implementation_goal",
            "sha256",
        }:
            raise LegacyStudyBoundaryError(
                "Legacy study archive manifest entry fields drift"
            )
        source = _required_string(entry, "source")
        if source in seen or source not in expected_assets:
            raise LegacyStudyBoundaryError(
                f"Unexpected or duplicate archive manifest source: {source}"
            )
        seen.add(source)
        asset = expected_assets[source]
        if (
            entry["archive_path"] != asset["archive_path"]
            or entry["implementation_goal"] != asset["implementation_goal"]
        ):
            raise LegacyStudyBoundaryError(
                f"Archive manifest ownership/path drift: {source}"
            )
        archived_path = root / str(entry["archive_path"])
        checksum = hashlib.sha256(archived_path.read_bytes()).hexdigest()
        if entry["sha256"] != checksum:
            raise LegacyStudyBoundaryError(
                f"Archive checksum mismatch: {source}"
            )
    if seen != set(expected_assets):
        raise LegacyStudyBoundaryError("Archive manifest coverage drift")
    return len(entries)


def _validate_frozen_edges(
    boundary: Mapping[str, Any],
) -> list[Mapping[str, str]]:
    edges = boundary.get("edges")
    if not isinstance(edges, list):
        raise LegacyStudyBoundaryError("Historical dependency edges are missing")
    expected_count = boundary.get("historical_edge_count")
    if expected_count != len(edges):
        raise LegacyStudyBoundaryError("Historical dependency edges drift")
    canonical = json.dumps(
        edges, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    checksum = hashlib.sha256(canonical).hexdigest()
    if boundary.get("historical_edges_sha256") != checksum:
        raise LegacyStudyBoundaryError("Historical dependency edges drift")
    identities = {
        (edge.get("source"), edge.get("target"), edge.get("kind"))
        for edge in edges
        if isinstance(edge, dict)
    }
    if len(identities) != len(edges):
        raise LegacyStudyBoundaryError(
            "Historical dependency edges contain duplicates or invalid records"
        )
    return edges


def _validate_protected_dependencies(
    root: Path,
    boundary: Mapping[str, Any],
    assets: Sequence[Mapping[str, Any]],
) -> None:
    protected = boundary.get("protected_shared_dependencies")
    if not isinstance(protected, list) or not protected:
        raise LegacyStudyBoundaryError(
            "Protected shared dependencies must be non-empty"
        )
    asset_paths = {str(asset["path"]) for asset in assets}
    protected_paths: set[str] = set()
    for item in protected:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "owner",
            "reason",
        }:
            raise LegacyStudyBoundaryError(
                "Protected shared dependency fields drift"
            )
        path = _required_string(item, "path")
        _required_string(item, "owner")
        _required_string(item, "reason")
        if path in asset_paths or path in protected_paths:
            raise LegacyStudyBoundaryError(
                f"Protected dependency overlaps or duplicates boundary asset: {path}"
            )
        if not (root / path).is_file():
            raise LegacyStudyBoundaryError(
                f"Protected shared dependency is missing: {path}"
            )
        protected_paths.add(path)


def _validate_cross_goal_constraints(
    boundary: Mapping[str, Any],
    frozen_edges: Sequence[Mapping[str, str]],
) -> None:
    constraints = boundary.get("cross_goal_constraints")
    if not isinstance(constraints, list) or not constraints:
        raise LegacyStudyBoundaryError(
            "Cross-goal constraints must be non-empty"
        )
    frozen_pairs = {
        (edge["source"], edge["target"]) for edge in frozen_edges
    }
    seen: set[tuple[str, str]] = set()
    for item in constraints:
        if not isinstance(item, dict) or set(item) != {
            "source",
            "target",
            "constraint",
        }:
            raise LegacyStudyBoundaryError("Cross-goal constraint fields drift")
        source = _required_string(item, "source")
        target = _required_string(item, "target")
        _required_string(item, "constraint")
        pair = (source, target)
        if pair in seen or pair not in frozen_pairs:
            raise LegacyStudyBoundaryError(
                f"Cross-goal constraint does not bind one frozen edge: {pair}"
            )
        seen.add(pair)


def _validate_pytest_exclusion(root: Path) -> None:
    pytest_config = (root / "pytest.ini").read_text(encoding="utf-8")
    if "norecursedirs" not in pytest_config or "\n    archive\n" not in pytest_config:
        raise LegacyStudyBoundaryError(
            "archive must be excluded from pytest collection"
        )
    if (root / "archive" / "__init__.py").exists():
        raise LegacyStudyBoundaryError("archive must not be a Python package")


def _python_sources(root: Path) -> Iterable[Path]:
    for relative_root in _SCANNED_ROOTS:
        yield from sorted((root / relative_root).rglob("*.py"))
    yield from sorted(root.glob("*.py"))


def _active_markdown_sources(root: Path) -> Iterable[Path]:
    yield from sorted(root.glob("*.md"))
    yield from sorted((root / "configs").rglob("*.md"))


def _module_name(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_targets(
    tree: ast.AST,
    module_targets: Mapping[str, str],
) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        for module in modules:
            target = module_targets.get(module)
            if target is not None:
                targets.add(target)
    return targets


def _string_values(tree: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _json_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _json_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _json_strings(item)


def _matching_path_targets(
    value: str,
    targets: Mapping[str, str],
) -> set[str]:
    normalized = value.replace("\\", "/")
    matches: set[str] = set()
    for target in targets:
        if normalized == target or normalized.endswith(f"/{target}"):
            matches.add(target)
            continue
        if "/" not in normalized and normalized == Path(target).name:
            matches.add(target)
    return matches


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise LegacyStudyBoundaryError(f"{key} must be a non-empty string")
    return value


def _rooted(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the installed legacy-study read-only archive."
    )
    parser.add_argument("--repo-root", default=str(project_root()))
    parser.add_argument("--boundary", default=str(DEFAULT_BOUNDARY_PATH))
    args = parser.parse_args(argv)
    try:
        result = verify_boundary(
            args.repo_root,
            boundary_path=args.boundary,
        )
    except LegacyStudyBoundaryError as exc:
        print(f"legacy study boundary error: {exc}", file=sys.stderr)
        return 1
    print(
        "legacy study archive verified: "
        f"state={result.implementation_state}, "
        f"assets={result.asset_count}, "
        f"archive_assets={result.archive_asset_count}, "
        f"manifest_entries={result.archive_manifest_entry_count}, "
        f"frozen_edges={result.frozen_edge_count}, "
        f"post_archive_edges={result.edge_count}, "
        "active_reverse_dependencies=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
