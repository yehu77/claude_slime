"""Repository artifact hygiene checks and cleanup."""

from __future__ import annotations

import argparse
import json
import stat
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HygieneFinding:
    path: Path
    category: str
    detail: str | None = None


def repo_root_from(module_path: Path | None = None) -> Path:
    base = module_path or Path(__file__).resolve()
    return base.parents[2]


def _within_repo(path: Path, repo_root: Path) -> bool:
    try:
        path.resolve().relative_to(repo_root.resolve())
        return True
    except ValueError:
        return False


def _iter_recursive_matches(repo_root: Path, pattern: str, *, category: str) -> list[HygieneFinding]:
    findings: list[HygieneFinding] = []
    for path in repo_root.rglob(pattern):
        if _within_repo(path, repo_root):
            findings.append(HygieneFinding(path=path, category=category))
    return findings


_MODEL_WEIGHT_SUFFIXES = (
    ".safetensors",
    ".safetensors.index.json",
    ".bin",
    ".pt",
    ".pth",
    ".ckpt",
    ".distcp",
)


def discover_hygiene_findings(repo_root: Path) -> list[HygieneFinding]:
    repo_root = repo_root.resolve()
    findings: list[HygieneFinding] = []

    root_exact = (
        (repo_root / ".pytest_cache", "pytest_cache"),
        (repo_root / "__pycache__", "python_cache_dir"),
        (repo_root / "runs", "run_artifacts"),
    )
    for path, category in root_exact:
        if path.exists():
            findings.append(HygieneFinding(path=path, category=category))

    for path in repo_root.iterdir():
        if path.name.startswith("tmp"):
            findings.append(HygieneFinding(path=path, category="temp_root"))

    tests_dir = repo_root / "tests"
    if tests_dir.exists():
        for child in tests_dir.iterdir():
            if child.name.startswith("_"):
                findings.append(HygieneFinding(path=child, category="test_artifact"))
            elif child.name.startswith("tmp"):
                findings.append(HygieneFinding(path=child, category="test_temp"))

    findings.extend(_iter_recursive_matches(repo_root, "__pycache__", category="python_cache_dir"))
    findings.extend(_iter_recursive_matches(repo_root, "*.pyc", category="python_cache_file"))
    findings.extend(
        _iter_recursive_matches(repo_root, "pytest-cache-files-*", category="pytest_cache_files")
    )

    unique_findings: dict[Path, HygieneFinding] = {}
    for finding in findings:
        resolved = finding.path.resolve()
        if _within_repo(resolved, repo_root):
            unique_findings.setdefault(resolved, HygieneFinding(path=resolved, category=finding.category))

    return sorted(unique_findings.values(), key=lambda finding: str(finding.path))


def discover_local_resource_findings(repo_root: Path) -> list[HygieneFinding]:
    """Detect machine-local configs, model weights, and cache roots inside the repo."""
    repo_root = repo_root.resolve()
    findings: list[HygieneFinding] = []

    local_config_dir = repo_root / "configs" / "local"
    if local_config_dir.exists():
        for path in sorted(local_config_dir.glob("*.local.json")):
            findings.append(
                HygieneFinding(
                    path=path.resolve(),
                    category="repo_local_config",
                    detail="machine-local config should live outside the source tree",
                )
            )
            findings.extend(_discover_inline_secret_findings(path.resolve()))

    models_dir = repo_root / "models"
    if models_dir.exists():
        for path in sorted(models_dir.rglob("*")):
            if not path.is_file():
                continue
            if _is_model_weight_file(path):
                findings.append(
                    HygieneFinding(
                        path=path.resolve(),
                        category="repo_model_weight",
                        detail="model weights should live in a machine-local model directory",
                    )
                )

    for path in _discover_hf_cache_roots(repo_root):
        findings.append(
            HygieneFinding(
                path=path.resolve(),
                category="repo_hf_cache",
                detail="Hugging Face caches should live in a machine-local cache directory",
            )
        )

    unique_findings: dict[tuple[Path, str], HygieneFinding] = {}
    for finding in findings:
        resolved = finding.path.resolve()
        if _within_repo(resolved, repo_root):
            unique_findings.setdefault(
                (resolved, finding.category),
                HygieneFinding(path=resolved, category=finding.category, detail=finding.detail),
            )

    return sorted(unique_findings.values(), key=lambda finding: str(finding.path))


def _is_model_weight_file(path: Path) -> bool:
    lower_name = path.name.lower()
    return any(lower_name.endswith(suffix) for suffix in _MODEL_WEIGHT_SUFFIXES)


def _discover_hf_cache_roots(repo_root: Path) -> list[Path]:
    findings: list[Path] = []

    exact_roots = (
        repo_root / ".cache" / "huggingface",
        repo_root / ".hf-cache",
        repo_root / "hf_cache",
        repo_root / "huggingface_cache",
    )
    for path in exact_roots:
        if path.exists():
            findings.append(path)

    models_dir = repo_root / "models"
    if models_dir.exists():
        for path in models_dir.rglob("huggingface"):
            if path.is_dir() and path.parent.name == ".cache":
                findings.append(path)

    return findings


def _discover_inline_secret_findings(path: Path) -> list[HygieneFinding]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, dict):
        return []

    api_key = str(payload.get("api_key", "")).strip()
    if not api_key:
        return []

    return [
        HygieneFinding(
            path=path,
            category="inline_secret",
            detail="replace inline api_key with api_key_env and an exported environment variable",
        )
    ]


def clean_hygiene_findings(repo_root: Path) -> list[Path]:
    removed: list[Path] = []
    for finding in discover_hygiene_findings(repo_root):
        path = finding.path
        if not path.exists():
            continue
        if not _within_repo(path, repo_root):
            raise ValueError(f"Refusing to remove path outside repo root: {path}")
        if path.is_dir():
            _remove_tree(path)
        else:
            _remove_file(path)
        removed.append(path)
    return removed


def _make_writable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _remove_file(path: Path) -> None:
    _make_writable(path)
    path.unlink(missing_ok=True)


def _on_rmtree_error(func, path, excinfo) -> None:
    target = Path(path)
    _make_writable(target)
    if target.parent.exists():
        _make_writable(target.parent)
    if target.is_dir():
        target.rmdir()
    else:
        target.unlink(missing_ok=True)


def _remove_tree(path: Path) -> None:
    _make_writable(path)
    shutil.rmtree(path, ignore_errors=False, onexc=_on_rmtree_error)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("check", "clean", "audit-local"),
        default="check",
        help="check for repository artifacts, audit local-only resources, or remove artifacts",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="override the repository root for testing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve() if args.repo_root else repo_root_from()

    if args.command == "clean":
        removed = clean_hygiene_findings(repo_root)
        for path in removed:
            print(f"removed\t{path.relative_to(repo_root)}")
        return 0

    if args.command == "audit-local":
        findings = discover_local_resource_findings(repo_root)
        if not findings:
            print("repo local-resource audit passed")
            return 0
        for finding in findings:
            line = f"{finding.category}\t{finding.path.relative_to(repo_root)}"
            if finding.detail:
                line += f"\t{finding.detail}"
            print(line)
        return 1

    findings = discover_hygiene_findings(repo_root)
    if not findings:
        print("repo hygiene check passed")
        return 0

    for finding in findings:
        print(f"{finding.category}\t{finding.path.relative_to(repo_root)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
