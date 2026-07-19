"""Lock, verify, and optionally bootstrap the ignored codex-rs reference tree."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


REFERENCE_LOCK_SCHEMA = "pycodeagent-external-reference-lock/v1"
TREE_DIGEST_ALGORITHM = "sha256-tree-manifest-v1"
DEFAULT_LOCK_PATH = Path("references/codex-rs.lock.json")


class CodexReferenceError(ValueError):
    """Raised when the lock, reference tree, or bootstrap archive is invalid."""


@dataclass(frozen=True)
class CodexReferenceLock:
    """Validated fields from the tracked codex-rs reference lock."""

    reference_id: str
    repository_url: str
    commit: str
    subtree: str
    archive_url: str
    license_spdx: str
    materialized_path: str
    tree_sha256: str
    entry_count: int
    expected_symlinks: Mapping[str, str]
    bootstrap_command: str


@dataclass(frozen=True)
class TreeDigest:
    """Canonical digest of a materialized reference subtree."""

    sha256: str
    entry_count: int
    portable_symlink_placeholders: tuple[str, ...]


@dataclass(frozen=True)
class VerificationReport:
    """Result of comparing the local ignored tree with its tracked lock."""

    status: str
    reference_path: Path
    expected_sha256: str
    actual_sha256: str | None
    expected_entry_count: int
    actual_entry_count: int | None
    message: str
    portable_symlink_placeholders: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_reference_lock(path: str | Path) -> CodexReferenceLock:
    """Load and validate the machine-readable reference lock."""
    lock_path = Path(path)
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CodexReferenceError(f"Reference lock is missing: {lock_path}") from exc
    except json.JSONDecodeError as exc:
        raise CodexReferenceError(f"Reference lock is invalid JSON: {lock_path}") from exc

    if not isinstance(payload, dict):
        raise CodexReferenceError("Reference lock root must be an object")
    if payload.get("schema") != REFERENCE_LOCK_SCHEMA:
        raise CodexReferenceError(
            f"Unsupported reference lock schema: {payload.get('schema')!r}"
        )
    if payload.get("purpose") != "implementation_reference_only":
        raise CodexReferenceError(
            "codex-rs lock purpose must be implementation_reference_only"
        )
    if payload.get("runtime_dependency") is not False:
        raise CodexReferenceError("codex-rs must not be a runtime dependency")

    source = _object_field(payload, "source")
    license_record = _object_field(payload, "license")
    materialization = _object_field(payload, "materialization")
    bootstrap = _object_field(payload, "bootstrap")
    if materialization.get("digest_algorithm") != TREE_DIGEST_ALGORITHM:
        raise CodexReferenceError(
            "Unsupported reference tree digest algorithm: "
            f"{materialization.get('digest_algorithm')!r}"
        )

    commit = _string_field(source, "commit")
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise CodexReferenceError("source.commit must be a full lowercase Git SHA")

    expected_symlinks_payload = materialization.get("expected_symlinks", {})
    if not isinstance(expected_symlinks_payload, dict) or not all(
        isinstance(path, str) and isinstance(target, str)
        for path, target in expected_symlinks_payload.items()
    ):
        raise CodexReferenceError(
            "materialization.expected_symlinks must map paths to link targets"
        )
    expected_symlinks = dict(sorted(expected_symlinks_payload.items()))
    for relative_path, target in expected_symlinks.items():
        _validate_relative_path(relative_path, field="expected symlink path")
        _validate_symlink_target(target, field=f"target for {relative_path}")

    tree_sha256 = _string_field(materialization, "tree_sha256")
    if len(tree_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in tree_sha256
    ):
        raise CodexReferenceError("materialization.tree_sha256 must be a SHA-256")
    entry_count = materialization.get("entry_count")
    if not isinstance(entry_count, int) or isinstance(entry_count, bool) or entry_count < 1:
        raise CodexReferenceError("materialization.entry_count must be a positive integer")

    return CodexReferenceLock(
        reference_id=_string_field(payload, "reference_id"),
        repository_url=_string_field(source, "repository_url"),
        commit=commit,
        subtree=_string_field(source, "subtree"),
        archive_url=_string_field(source, "archive_url"),
        license_spdx=_string_field(license_record, "spdx"),
        materialized_path=_string_field(materialization, "path"),
        tree_sha256=tree_sha256,
        entry_count=entry_count,
        expected_symlinks=expected_symlinks,
        bootstrap_command=_string_field(bootstrap, "command"),
    )


def digest_reference_tree(
    root: str | Path,
    *,
    expected_symlinks: Mapping[str, str] | None = None,
    excluded_paths: Sequence[str] = (),
    excluded_globs: Sequence[str] = (),
) -> TreeDigest:
    """Hash paths and bytes while ignoring timestamps and executable-bit drift.

    A regular file containing exactly the expected link target is normalized as
    the corresponding symlink. This supports source-copy tools that materialize
    a Git symlink as a portable one-line placeholder instead of a filesystem
    symlink. No other file-content differences are normalized.
    """
    tree_root = Path(root)
    if not tree_root.is_dir():
        raise CodexReferenceError(f"Reference tree is not a directory: {tree_root}")
    normalized_links = dict(expected_symlinks or {})
    excluded_path_set = frozenset(excluded_paths)
    digest = hashlib.sha256()
    entry_count = 0
    portable_placeholders: list[str] = []

    for path in sorted(tree_root.rglob("*"), key=lambda item: item.as_posix()):
        relative_path = path.relative_to(tree_root).as_posix()
        if relative_path in excluded_path_set or any(
            fnmatch.fnmatchcase(relative_path, pattern)
            for pattern in excluded_globs
        ):
            continue
        if path.is_symlink():
            target = os.readlink(path)
            _update_link_digest(digest, relative_path, target)
            entry_count += 1
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            raise CodexReferenceError(
                f"Unsupported special file in reference tree: {relative_path}"
            )

        expected_target = normalized_links.get(relative_path)
        if expected_target is not None and path.read_bytes() == expected_target.encode(
            "utf-8"
        ):
            _update_link_digest(digest, relative_path, expected_target)
            portable_placeholders.append(relative_path)
        else:
            content_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            record = (
                f"file\0{relative_path}\0{path.stat().st_size}\0{content_sha256}\n"
            )
            digest.update(record.encode("utf-8"))
        entry_count += 1

    return TreeDigest(
        sha256=digest.hexdigest(),
        entry_count=entry_count,
        portable_symlink_placeholders=tuple(portable_placeholders),
    )


def verify_reference(
    repo_root: str | Path,
    *,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    reference_path: str | Path | None = None,
) -> VerificationReport:
    """Verify the optional local tree without making it a runtime dependency."""
    root = Path(repo_root).resolve()
    resolved_lock_path = _resolve_under_root(root, lock_path)
    lock = load_reference_lock(resolved_lock_path)
    tree_path = _resolve_under_root(
        root, reference_path if reference_path is not None else lock.materialized_path
    )

    if not tree_path.exists():
        return VerificationReport(
            status="missing",
            reference_path=tree_path,
            expected_sha256=lock.tree_sha256,
            actual_sha256=None,
            expected_entry_count=lock.entry_count,
            actual_entry_count=None,
            message=(
                "Optional codex-rs reference tree is absent. Repository runtime and "
                f"tests do not depend on it. To materialize the locked reference, run: "
                f"{lock.bootstrap_command}"
            ),
        )
    if not tree_path.is_dir():
        return VerificationReport(
            status="mismatch",
            reference_path=tree_path,
            expected_sha256=lock.tree_sha256,
            actual_sha256=None,
            expected_entry_count=lock.entry_count,
            actual_entry_count=None,
            message=f"Reference path exists but is not a directory: {tree_path}",
        )

    actual = digest_reference_tree(
        tree_path,
        expected_symlinks=lock.expected_symlinks,
    )
    if (
        actual.sha256 != lock.tree_sha256
        or actual.entry_count != lock.entry_count
    ):
        return VerificationReport(
            status="mismatch",
            reference_path=tree_path,
            expected_sha256=lock.tree_sha256,
            actual_sha256=actual.sha256,
            expected_entry_count=lock.entry_count,
            actual_entry_count=actual.entry_count,
            message=(
                "codex-rs reference tree does not match the locked commit "
                f"{lock.commit}. Move the local tree aside and rerun: "
                f"{lock.bootstrap_command}"
            ),
            portable_symlink_placeholders=actual.portable_symlink_placeholders,
        )

    placeholder_note = ""
    if actual.portable_symlink_placeholders:
        placeholder_note = (
            " Portable symlink placeholders normalized: "
            + ", ".join(actual.portable_symlink_placeholders)
            + "."
        )
    return VerificationReport(
        status="ok",
        reference_path=tree_path,
        expected_sha256=lock.tree_sha256,
        actual_sha256=actual.sha256,
        expected_entry_count=lock.entry_count,
        actual_entry_count=actual.entry_count,
        message=(
            f"codex-rs matches locked commit {lock.commit} "
            f"({actual.entry_count} entries).{placeholder_note}"
        ),
        portable_symlink_placeholders=actual.portable_symlink_placeholders,
    )


def bootstrap_reference(
    repo_root: str | Path,
    *,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    archive_path: str | Path | None = None,
    reference_path: str | Path | None = None,
) -> VerificationReport:
    """Materialize the locked subtree into an absent destination and verify it."""
    root = Path(repo_root).resolve()
    resolved_lock_path = _resolve_under_root(root, lock_path)
    lock = load_reference_lock(resolved_lock_path)
    destination = _resolve_under_root(
        root, reference_path if reference_path is not None else lock.materialized_path
    )
    if destination.exists() or destination.is_symlink():
        raise CodexReferenceError(
            f"Refusing to overwrite existing reference path: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary_root = Path(
        tempfile.mkdtemp(prefix=".codex-reference-", dir=destination.parent)
    )
    downloaded_archive: Path | None = None
    try:
        if archive_path is None:
            downloaded_archive = temporary_root / "source.tar.gz"
            with urllib.request.urlopen(lock.archive_url) as response:
                with downloaded_archive.open("wb") as output:
                    shutil.copyfileobj(response, output)
            source_archive = downloaded_archive
        else:
            source_archive = Path(archive_path).resolve()
            if not source_archive.is_file():
                raise CodexReferenceError(
                    f"Bootstrap archive is missing: {source_archive}"
                )

        staging = temporary_root / "tree"
        staging.mkdir()
        _extract_locked_subtree(
            source_archive,
            staging,
            subtree=lock.subtree,
        )
        digest = digest_reference_tree(
            staging,
            expected_symlinks=lock.expected_symlinks,
        )
        if digest.sha256 != lock.tree_sha256 or digest.entry_count != lock.entry_count:
            raise CodexReferenceError(
                "Downloaded archive subtree failed the tracked checksum: "
                f"expected {lock.tree_sha256}/{lock.entry_count}, "
                f"got {digest.sha256}/{digest.entry_count}"
            )
        os.replace(staging, destination)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)

    report = verify_reference(
        root,
        lock_path=resolved_lock_path,
        reference_path=destination,
    )
    if not report.ok:
        raise CodexReferenceError(report.message)
    return report


def _extract_locked_subtree(
    archive_path: Path,
    destination: Path,
    *,
    subtree: str,
) -> None:
    matched_entries = 0
    with tarfile.open(archive_path, mode="r:*") as archive:
        for member in archive.getmembers():
            parts = PurePosixPath(member.name).parts
            if len(parts) < 2 or parts[1] != subtree:
                continue
            relative_parts = parts[2:]
            if not relative_parts:
                continue
            relative = PurePosixPath(*relative_parts)
            _validate_archive_relative_path(relative)
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.isfile():
                source = archive.extractfile(member)
                if source is None:
                    raise CodexReferenceError(
                        f"Unable to read archive member: {member.name}"
                    )
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
            elif member.issym():
                _validate_symlink_target(
                    member.linkname,
                    field=f"archive symlink {member.name}",
                )
                try:
                    target.symlink_to(member.linkname)
                except OSError:
                    target.write_text(member.linkname, encoding="utf-8")
            else:
                raise CodexReferenceError(
                    f"Unsupported archive member in locked subtree: {member.name}"
                )
            matched_entries += 1
    if matched_entries == 0:
        raise CodexReferenceError(
            f"Archive does not contain the locked subtree: {subtree}"
        )


def _update_link_digest(
    digest: Any,
    relative_path: str,
    target: str,
) -> None:
    digest.update(f"symlink\0{relative_path}\0{target}\n".encode("utf-8"))


def _object_field(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise CodexReferenceError(f"{key} must be an object")
    return value


def _string_field(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CodexReferenceError(f"{key} must be a non-empty string")
    return value


def _resolve_under_root(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CodexReferenceError(f"Path escapes repository root: {path}") from exc
    return resolved


def _validate_relative_path(path: str, *, field: str) -> None:
    value = PurePosixPath(path)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise CodexReferenceError(f"Invalid {field}: {path!r}")


def _validate_archive_relative_path(path: PurePosixPath) -> None:
    if path.is_absolute() or ".." in path.parts:
        raise CodexReferenceError(f"Unsafe archive path: {path}")


def _validate_symlink_target(target: str, *, field: str) -> None:
    value = PurePosixPath(target)
    if value.is_absolute() or ".." in value.parts:
        raise CodexReferenceError(f"Unsafe {field}: {target!r}")


def _report_payload(report: VerificationReport) -> dict[str, Any]:
    return {
        "status": report.status,
        "reference_path": str(report.reference_path),
        "expected_sha256": report.expected_sha256,
        "actual_sha256": report.actual_sha256,
        "expected_entry_count": report.expected_entry_count,
        "actual_entry_count": report.actual_entry_count,
        "portable_symlink_placeholders": list(
            report.portable_symlink_placeholders
        ),
        "message": report.message,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("verify", "bootstrap"),
        help="verify the optional tree or materialize the exact locked subtree",
    )
    parser.add_argument("--repo-root", type=Path, default=project_root())
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--reference-path", type=Path)
    parser.add_argument(
        "--archive",
        type=Path,
        help="use a local source archive instead of downloading the locked URL",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "bootstrap":
            report = bootstrap_reference(
                args.repo_root,
                lock_path=args.lock,
                archive_path=args.archive,
                reference_path=args.reference_path,
            )
        else:
            if args.archive is not None:
                raise CodexReferenceError("--archive is only valid with bootstrap")
            report = verify_reference(
                args.repo_root,
                lock_path=args.lock,
                reference_path=args.reference_path,
            )
    except (CodexReferenceError, OSError, tarfile.TarError) as exc:
        print(f"codex-reference: error: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(_report_payload(report), indent=2, sort_keys=True))
    else:
        print(report.message)
    if report.status == "missing":
        return 2
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
