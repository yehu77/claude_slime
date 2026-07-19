"""Validate the upstream-only projection of the vendored slime tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from pycodeagent.dev.codex_reference import (
    TREE_DIGEST_ALGORITHM,
    CodexReferenceError,
    digest_reference_tree,
)


SLIME_UPSTREAM_LOCK_SCHEMA = "pycodeagent-vendor-upstream-lock/v1"
SLIME_OVERLAY_MANIFEST_SCHEMA = "pycodeagent-vendor-overlay-manifest/v1"
DEFAULT_LOCK_PATH = Path("references/slime-upstream.lock.json")
DEFAULT_OVERLAY_MANIFEST_PATH = Path("references/slime-overlay.manifest.json")


class SlimeVendorError(ValueError):
    """Raised when slime provenance or its upstream projection is invalid."""


@dataclass(frozen=True)
class SlimeUpstreamLock:
    """Validated upstream provenance and projection fields."""

    vendor_id: str
    vendor_path: str
    repository_url: str
    commit: str
    archive_url: str
    acquired_at: str
    acquisition_evidence_commit: str
    license_spdx: str
    license_path: str
    license_sha256: str
    tree_sha256: str
    entry_count: int
    expected_symlinks: Mapping[str, str]
    overlay_candidate_paths: tuple[str, ...]
    ignored_ephemeral_globs: tuple[str, ...]
    baseline_report_path: str


@dataclass(frozen=True)
class SlimeProjectionReport:
    """Checksum result for the upstream-only view of the vendor tree."""

    status: str
    vendor_path: Path
    expected_sha256: str
    actual_sha256: str | None
    expected_entry_count: int
    actual_entry_count: int | None
    message: str
    portable_symlink_placeholders: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class SlimeOverlayFile:
    """One checksum-locked repo-owned file added over pristine upstream."""

    path: str
    operation: str
    owner: str
    reason: str
    source_path: str
    mode: int
    size: int
    sha256: str


@dataclass(frozen=True)
class SlimeOverlayManifest:
    """Validated final-tree contract for the slime integration overlay."""

    vendor_id: str
    vendor_path: str
    upstream_lock_path: str
    upstream_commit: str
    files: tuple[SlimeOverlayFile, ...]
    tree_sha256: str
    entry_count: int
    ignored_ephemeral_globs: tuple[str, ...]
    rebuild_command: str


@dataclass(frozen=True)
class SlimeVendorReport:
    """Complete upstream, overlay, and final-tree verification result."""

    status: str
    vendor_path: Path
    upstream_status: str
    expected_sha256: str
    actual_sha256: str | None
    expected_entry_count: int
    actual_entry_count: int | None
    overlay_file_count: int
    issues: tuple[str, ...]
    message: str

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class SlimeRebuildReport:
    """Result of rebuilding the expected vendor tree from upstream + overlay."""

    status: str
    tree_sha256: str
    entry_count: int
    destination: Path | None
    message: str

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_slime_upstream_lock(path: str | Path) -> SlimeUpstreamLock:
    """Load and validate the machine-readable slime upstream lock."""
    lock_path = Path(path)
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SlimeVendorError(f"Slime upstream lock is missing: {lock_path}") from exc
    except json.JSONDecodeError as exc:
        raise SlimeVendorError(
            f"Slime upstream lock is invalid JSON: {lock_path}"
        ) from exc
    if not isinstance(payload, dict):
        raise SlimeVendorError("Slime upstream lock root must be an object")
    if payload.get("schema") != SLIME_UPSTREAM_LOCK_SCHEMA:
        raise SlimeVendorError(
            f"Unsupported slime upstream lock schema: {payload.get('schema')!r}"
        )
    if payload.get("purpose") != "vendored_upstream_baseline":
        raise SlimeVendorError("Slime lock purpose must be vendored_upstream_baseline")

    source = _object_field(payload, "source")
    acquisition = _object_field(payload, "acquisition")
    license_record = _object_field(payload, "license")
    upstream_tree = _object_field(payload, "upstream_tree")
    local_projection = _object_field(payload, "local_projection")
    evidence = _object_field(payload, "evidence")
    if upstream_tree.get("digest_algorithm") != TREE_DIGEST_ALGORITHM:
        raise SlimeVendorError(
            "Unsupported upstream tree digest algorithm: "
            f"{upstream_tree.get('digest_algorithm')!r}"
        )

    commit = _full_git_sha(source, "commit")
    evidence_commit = _full_git_sha(acquisition, "repository_import_commit")
    tree_sha256 = _sha256(upstream_tree, "tree_sha256")
    license_sha256 = _sha256(license_record, "sha256")
    expected_symlinks = _string_map(upstream_tree, "expected_symlinks")
    overlay_paths = _string_list(local_projection, "overlay_candidate_paths")
    ephemeral_globs = _string_list(local_projection, "ignored_ephemeral_globs")
    entry_count = upstream_tree.get("entry_count")
    if not isinstance(entry_count, int) or isinstance(entry_count, bool) or entry_count < 1:
        raise SlimeVendorError("upstream_tree.entry_count must be a positive integer")

    return SlimeUpstreamLock(
        vendor_id=_string_field(payload, "vendor_id"),
        vendor_path=_string_field(payload, "vendor_path"),
        repository_url=_string_field(source, "repository_url"),
        commit=commit,
        archive_url=_string_field(source, "archive_url"),
        acquired_at=_string_field(acquisition, "acquired_at"),
        acquisition_evidence_commit=evidence_commit,
        license_spdx=_string_field(license_record, "spdx"),
        license_path=_string_field(license_record, "vendor_path"),
        license_sha256=license_sha256,
        tree_sha256=tree_sha256,
        entry_count=entry_count,
        expected_symlinks=expected_symlinks,
        overlay_candidate_paths=tuple(overlay_paths),
        ignored_ephemeral_globs=tuple(ephemeral_globs),
        baseline_report_path=_string_field(evidence, "baseline_report"),
    )


def load_slime_overlay_manifest(path: str | Path) -> SlimeOverlayManifest:
    """Load and validate the repo-owned overlay and expected-tree contract."""
    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SlimeVendorError(
            f"Slime overlay manifest is missing: {manifest_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise SlimeVendorError(
            f"Slime overlay manifest is invalid JSON: {manifest_path}"
        ) from exc
    if not isinstance(payload, dict):
        raise SlimeVendorError("Slime overlay manifest root must be an object")
    if payload.get("schema") != SLIME_OVERLAY_MANIFEST_SCHEMA:
        raise SlimeVendorError(
            "Unsupported slime overlay manifest schema: "
            f"{payload.get('schema')!r}"
        )
    if payload.get("purpose") != "repo_owned_slime_integration_overlay":
        raise SlimeVendorError(
            "Slime overlay purpose must be repo_owned_slime_integration_overlay"
        )

    vendor_path = _string_field(payload, "vendor_path")
    files_payload = payload.get("files")
    if not isinstance(files_payload, list) or not files_payload:
        raise SlimeVendorError("files must be a non-empty list")
    files: list[SlimeOverlayFile] = []
    seen_paths: set[str] = set()
    for item in files_payload:
        if not isinstance(item, dict):
            raise SlimeVendorError("Each overlay file record must be an object")
        path = _string_field(item, "path")
        source_path = _string_field(item, "source_path")
        _validate_relative_path(path, field="overlay path")
        _validate_relative_path(source_path, field="overlay source_path")
        if path in seen_paths:
            raise SlimeVendorError(f"Duplicate overlay path: {path}")
        seen_paths.add(path)
        if source_path != f"{vendor_path}/{path}":
            raise SlimeVendorError(
                f"Overlay source_path must be the tracked vendor file for {path}"
            )
        operation = _string_field(item, "operation")
        if operation != "add":
            raise SlimeVendorError(
                f"Unsupported overlay operation for {path}: {operation!r}"
            )
        mode_text = _string_field(item, "mode")
        if (
            len(mode_text) != 4
            or mode_text[0] != "0"
            or any(char not in "01234567" for char in mode_text)
        ):
            raise SlimeVendorError(f"Invalid overlay mode for {path}: {mode_text!r}")
        size = item.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise SlimeVendorError(
                f"Overlay size must be a non-negative integer for {path}"
            )
        files.append(
            SlimeOverlayFile(
                path=path,
                operation=operation,
                owner=_string_field(item, "owner"),
                reason=_string_field(item, "reason"),
                source_path=source_path,
                mode=int(mode_text, 8),
                size=size,
                sha256=_sha256(item, "sha256"),
            )
        )

    expected_tree = _object_field(payload, "expected_tree")
    if expected_tree.get("digest_algorithm") != TREE_DIGEST_ALGORITHM:
        raise SlimeVendorError(
            "Unsupported expected tree digest algorithm: "
            f"{expected_tree.get('digest_algorithm')!r}"
        )
    entry_count = expected_tree.get("entry_count")
    if not isinstance(entry_count, int) or isinstance(entry_count, bool) or entry_count < 1:
        raise SlimeVendorError("expected_tree.entry_count must be a positive integer")
    rebuild = _object_field(payload, "rebuild")
    return SlimeOverlayManifest(
        vendor_id=_string_field(payload, "vendor_id"),
        vendor_path=vendor_path,
        upstream_lock_path=_string_field(payload, "upstream_lock"),
        upstream_commit=_full_git_sha(payload, "upstream_commit"),
        files=tuple(sorted(files, key=lambda item: item.path)),
        tree_sha256=_sha256(expected_tree, "tree_sha256"),
        entry_count=entry_count,
        ignored_ephemeral_globs=tuple(
            _string_list(expected_tree, "ignored_ephemeral_globs")
        ),
        rebuild_command=_string_field(rebuild, "command"),
    )


def verify_slime_upstream_projection(
    repo_root: str | Path,
    *,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    vendor_path: str | Path | None = None,
) -> SlimeProjectionReport:
    """Verify upstream bytes while deliberately excluding overlay candidates."""
    root = Path(repo_root).resolve()
    resolved_lock_path = _resolve_under_root(root, lock_path)
    lock = load_slime_upstream_lock(resolved_lock_path)
    resolved_vendor_path = _resolve_under_root(
        root, vendor_path if vendor_path is not None else lock.vendor_path
    )
    if not resolved_vendor_path.is_dir():
        return SlimeProjectionReport(
            status="missing",
            vendor_path=resolved_vendor_path,
            expected_sha256=lock.tree_sha256,
            actual_sha256=None,
            expected_entry_count=lock.entry_count,
            actual_entry_count=None,
            message=f"Vendored slime tree is missing: {resolved_vendor_path}",
        )

    digest = digest_reference_tree(
        resolved_vendor_path,
        expected_symlinks=lock.expected_symlinks,
        excluded_paths=lock.overlay_candidate_paths,
        excluded_globs=lock.ignored_ephemeral_globs,
    )
    if digest.sha256 != lock.tree_sha256 or digest.entry_count != lock.entry_count:
        return SlimeProjectionReport(
            status="mismatch",
            vendor_path=resolved_vendor_path,
            expected_sha256=lock.tree_sha256,
            actual_sha256=digest.sha256,
            expected_entry_count=lock.entry_count,
            actual_entry_count=digest.entry_count,
            message=(
                "Vendored slime upstream projection does not match locked commit "
                f"{lock.commit}. Do not overwrite local files; inspect the baseline "
                f"report at {lock.baseline_report_path}."
            ),
            portable_symlink_placeholders=digest.portable_symlink_placeholders,
        )

    license_path = _resolve_under_root(root, lock.license_path)
    if not license_path.is_file():
        return SlimeProjectionReport(
            status="mismatch",
            vendor_path=resolved_vendor_path,
            expected_sha256=lock.tree_sha256,
            actual_sha256=digest.sha256,
            expected_entry_count=lock.entry_count,
            actual_entry_count=digest.entry_count,
            message=f"Vendored slime license is missing: {license_path}",
            portable_symlink_placeholders=digest.portable_symlink_placeholders,
        )
    actual_license_sha256 = hashlib.sha256(license_path.read_bytes()).hexdigest()
    if actual_license_sha256 != lock.license_sha256:
        return SlimeProjectionReport(
            status="mismatch",
            vendor_path=resolved_vendor_path,
            expected_sha256=lock.tree_sha256,
            actual_sha256=digest.sha256,
            expected_entry_count=lock.entry_count,
            actual_entry_count=digest.entry_count,
            message=(
                "Vendored slime LICENSE does not match the locked upstream license: "
                f"expected {lock.license_sha256}, got {actual_license_sha256}"
            ),
            portable_symlink_placeholders=digest.portable_symlink_placeholders,
        )

    placeholder_note = ""
    if digest.portable_symlink_placeholders:
        placeholder_note = (
            " Portable symlink placeholders normalized: "
            + ", ".join(digest.portable_symlink_placeholders)
            + "."
        )
    return SlimeProjectionReport(
        status="ok",
        vendor_path=resolved_vendor_path,
        expected_sha256=lock.tree_sha256,
        actual_sha256=digest.sha256,
        expected_entry_count=lock.entry_count,
        actual_entry_count=digest.entry_count,
        message=(
            f"Vendored slime upstream projection matches locked commit {lock.commit} "
            f"({digest.entry_count} entries). Overlay candidates are excluded and "
            f"remain governed by RC-048.{placeholder_note}"
        ),
        portable_symlink_placeholders=digest.portable_symlink_placeholders,
    )


def verify_slime_vendor(
    repo_root: str | Path,
    *,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    manifest_path: str | Path = DEFAULT_OVERLAY_MANIFEST_PATH,
    vendor_path: str | Path | None = None,
) -> SlimeVendorReport:
    """Verify upstream provenance, overlay files, modes, and the final tree."""
    root = Path(repo_root).resolve()
    resolved_lock_path = _resolve_under_root(root, lock_path)
    resolved_manifest_path = _resolve_under_root(root, manifest_path)
    lock = load_slime_upstream_lock(resolved_lock_path)
    manifest = load_slime_overlay_manifest(resolved_manifest_path)
    _validate_lock_manifest_boundary(lock, manifest, resolved_lock_path, root)
    resolved_vendor_path = _resolve_under_root(
        root, vendor_path if vendor_path is not None else manifest.vendor_path
    )

    upstream = verify_slime_upstream_projection(
        root,
        lock_path=resolved_lock_path,
        vendor_path=resolved_vendor_path,
    )
    issues: list[str] = []
    if not upstream.ok:
        issues.append(
            "upstream or unknown-path drift: "
            + upstream.message
        )
    issues.extend(_overlay_file_issues(root, resolved_vendor_path, manifest))

    actual_sha256: str | None = None
    actual_entry_count: int | None = None
    if resolved_vendor_path.is_dir():
        final_digest = digest_reference_tree(
            resolved_vendor_path,
            expected_symlinks=lock.expected_symlinks,
            excluded_globs=manifest.ignored_ephemeral_globs,
        )
        actual_sha256 = final_digest.sha256
        actual_entry_count = final_digest.entry_count
        if (
            final_digest.sha256 != manifest.tree_sha256
            or final_digest.entry_count != manifest.entry_count
        ):
            issues.append(
                "final vendor tree drift or unknown file: expected "
                f"{manifest.tree_sha256}/{manifest.entry_count}, got "
                f"{final_digest.sha256}/{final_digest.entry_count}"
            )

    if issues:
        return SlimeVendorReport(
            status="mismatch",
            vendor_path=resolved_vendor_path,
            upstream_status=upstream.status,
            expected_sha256=manifest.tree_sha256,
            actual_sha256=actual_sha256,
            expected_entry_count=manifest.entry_count,
            actual_entry_count=actual_entry_count,
            overlay_file_count=len(manifest.files),
            issues=tuple(issues),
            message="Vendored slime verification failed:\n- " + "\n- ".join(issues),
        )

    return SlimeVendorReport(
        status="ok",
        vendor_path=resolved_vendor_path,
        upstream_status=upstream.status,
        expected_sha256=manifest.tree_sha256,
        actual_sha256=actual_sha256,
        expected_entry_count=manifest.entry_count,
        actual_entry_count=actual_entry_count,
        overlay_file_count=len(manifest.files),
        issues=(),
        message=(
            f"Vendored slime matches upstream {lock.commit} plus "
            f"{len(manifest.files)} checksum-locked overlay files "
            f"({manifest.entry_count} total entries)."
        ),
    )


def rebuild_slime_vendor(
    repo_root: str | Path,
    *,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    manifest_path: str | Path = DEFAULT_OVERLAY_MANIFEST_PATH,
    archive_path: str | Path | None = None,
    destination: str | Path | None = None,
) -> SlimeRebuildReport:
    """Rebuild upstream + overlay in staging without replacing the vendor tree."""
    root = Path(repo_root).resolve()
    resolved_lock_path = _resolve_under_root(root, lock_path)
    resolved_manifest_path = _resolve_under_root(root, manifest_path)
    lock = load_slime_upstream_lock(resolved_lock_path)
    manifest = load_slime_overlay_manifest(resolved_manifest_path)
    _validate_lock_manifest_boundary(lock, manifest, resolved_lock_path, root)
    overlay_source_root = _resolve_under_root(root, manifest.vendor_path)
    overlay_issues = _overlay_file_issues(root, overlay_source_root, manifest)
    if overlay_issues:
        raise SlimeVendorError(
            "Cannot rebuild from drifted overlay sources:\n- "
            + "\n- ".join(overlay_issues)
        )

    resolved_destination: Path | None = None
    temporary_parent: Path | None = None
    if destination is not None:
        destination_path = Path(destination)
        resolved_destination = (
            destination_path.resolve()
            if destination_path.is_absolute()
            else (root / destination_path).resolve()
        )
        if resolved_destination.exists() or resolved_destination.is_symlink():
            raise SlimeVendorError(
                f"Refusing to overwrite existing rebuild destination: "
                f"{resolved_destination}"
            )
        resolved_destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_parent = resolved_destination.parent

    temporary_root = Path(
        tempfile.mkdtemp(prefix=".slime-rebuild-", dir=temporary_parent)
    )
    try:
        if archive_path is None:
            source_archive = temporary_root / "upstream.tar.gz"
            with urllib.request.urlopen(lock.archive_url) as response:
                with source_archive.open("wb") as output:
                    shutil.copyfileobj(response, output)
        else:
            source_archive = Path(archive_path).resolve()
            if not source_archive.is_file():
                raise SlimeVendorError(
                    f"Upstream archive is missing: {source_archive}"
                )

        staging = temporary_root / "slime-main"
        staging.mkdir()
        _extract_full_commit_archive(source_archive, staging)
        pristine = digest_reference_tree(
            staging,
            expected_symlinks=lock.expected_symlinks,
        )
        if pristine.sha256 != lock.tree_sha256 or pristine.entry_count != lock.entry_count:
            raise SlimeVendorError(
                "Upstream archive failed the locked pristine-tree checksum: "
                f"expected {lock.tree_sha256}/{lock.entry_count}, got "
                f"{pristine.sha256}/{pristine.entry_count}"
            )
        upstream_license = staging / _vendor_relative_license_path(lock)
        if (
            not upstream_license.is_file()
            or hashlib.sha256(upstream_license.read_bytes()).hexdigest()
            != lock.license_sha256
        ):
            raise SlimeVendorError(
                "Upstream archive LICENSE failed the locked checksum"
            )

        for overlay in manifest.files:
            source = _resolve_under_root(root, overlay.source_path)
            target = staging.joinpath(*PurePosixPath(overlay.path).parts)
            if target.exists() or target.is_symlink():
                raise SlimeVendorError(
                    f"Overlay add path already exists upstream: {overlay.path}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(overlay.mode)

        rebuilt = digest_reference_tree(
            staging,
            expected_symlinks=lock.expected_symlinks,
            excluded_globs=manifest.ignored_ephemeral_globs,
        )
        if (
            rebuilt.sha256 != manifest.tree_sha256
            or rebuilt.entry_count != manifest.entry_count
        ):
            raise SlimeVendorError(
                "Rebuilt vendor tree failed the overlay manifest checksum: "
                f"expected {manifest.tree_sha256}/{manifest.entry_count}, got "
                f"{rebuilt.sha256}/{rebuilt.entry_count}"
            )

        if resolved_destination is not None:
            os.replace(staging, resolved_destination)
        return SlimeRebuildReport(
            status="ok",
            tree_sha256=rebuilt.sha256,
            entry_count=rebuilt.entry_count,
            destination=resolved_destination,
            message=(
                f"Rebuilt slime upstream {lock.commit} plus "
                f"{len(manifest.files)} overlays "
                f"({rebuilt.entry_count} entries, {rebuilt.sha256})."
            ),
        )
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def _validate_lock_manifest_boundary(
    lock: SlimeUpstreamLock,
    manifest: SlimeOverlayManifest,
    resolved_lock_path: Path,
    repo_root: Path,
) -> None:
    declared_lock = _resolve_under_root(repo_root, manifest.upstream_lock_path)
    if declared_lock != resolved_lock_path:
        raise SlimeVendorError(
            "Overlay manifest upstream_lock does not match the selected lock"
        )
    if manifest.vendor_id != lock.vendor_id:
        raise SlimeVendorError("Overlay manifest vendor_id does not match source lock")
    if manifest.vendor_path != lock.vendor_path:
        raise SlimeVendorError("Overlay manifest vendor_path does not match source lock")
    if manifest.upstream_commit != lock.commit:
        raise SlimeVendorError(
            "Overlay manifest upstream_commit does not match source lock"
        )
    overlay_paths = {item.path for item in manifest.files}
    if overlay_paths != set(lock.overlay_candidate_paths):
        raise SlimeVendorError(
            "Overlay manifest paths must exactly classify the RC-047 candidates"
        )
    if set(manifest.ignored_ephemeral_globs) != set(lock.ignored_ephemeral_globs):
        raise SlimeVendorError(
            "Overlay and upstream locks disagree on ignored ephemeral paths"
        )
    if manifest.entry_count != lock.entry_count + len(manifest.files):
        raise SlimeVendorError(
            "Expected final entry count must equal upstream plus overlay files"
        )


def _overlay_file_issues(
    repo_root: Path,
    vendor_root: Path,
    manifest: SlimeOverlayManifest,
) -> list[str]:
    issues: list[str] = []
    for overlay in manifest.files:
        source = _resolve_under_root(repo_root, overlay.source_path)
        expected_source = vendor_root.joinpath(*PurePosixPath(overlay.path).parts)
        if source != expected_source:
            issues.append(f"overlay source boundary drift: {overlay.path}")
            continue
        if not source.is_file() or source.is_symlink():
            issues.append(f"overlay file missing or not regular: {overlay.path}")
            continue
        actual_bytes = source.read_bytes()
        actual_sha256 = hashlib.sha256(actual_bytes).hexdigest()
        if len(actual_bytes) != overlay.size:
            issues.append(
                f"overlay size drift for {overlay.path}: "
                f"expected {overlay.size}, got {len(actual_bytes)}"
            )
        if actual_sha256 != overlay.sha256:
            issues.append(
                f"overlay checksum drift for {overlay.path}: "
                f"expected {overlay.sha256}, got {actual_sha256}"
            )
        actual_mode = stat.S_IMODE(source.stat().st_mode)
        if actual_mode != overlay.mode:
            issues.append(
                f"overlay mode drift for {overlay.path}: "
                f"expected {overlay.mode:04o}, got {actual_mode:04o}"
            )
    return issues


def _extract_full_commit_archive(archive_path: Path, destination: Path) -> None:
    matched_entries = 0
    with tarfile.open(archive_path, mode="r:*") as archive:
        for member in archive.getmembers():
            parts = PurePosixPath(member.name).parts
            if len(parts) < 2:
                continue
            relative = PurePosixPath(*parts[1:])
            _validate_archive_relative_path(relative)
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.isfile():
                source = archive.extractfile(member)
                if source is None:
                    raise SlimeVendorError(
                        f"Unable to read archive member: {member.name}"
                    )
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)
            elif member.issym():
                _validate_archive_symlink(relative, member.linkname)
                try:
                    target.symlink_to(member.linkname)
                except OSError:
                    target.write_text(member.linkname, encoding="utf-8")
            else:
                raise SlimeVendorError(
                    f"Unsupported archive member: {member.name}"
                )
            matched_entries += 1
    if matched_entries == 0:
        raise SlimeVendorError("Archive contains no files below its root directory")


def _validate_archive_relative_path(path: PurePosixPath) -> None:
    if path.is_absolute() or ".." in path.parts:
        raise SlimeVendorError(f"Unsafe archive path: {path}")


def _validate_archive_symlink(path: PurePosixPath, target: str) -> None:
    target_path = PurePosixPath(target)
    if target_path.is_absolute():
        raise SlimeVendorError(f"Unsafe absolute symlink target for {path}: {target}")
    stack = list(path.parent.parts)
    for part in target_path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not stack:
                raise SlimeVendorError(
                    f"Archive symlink escapes root for {path}: {target}"
                )
            stack.pop()
        else:
            stack.append(part)


def _vendor_relative_license_path(lock: SlimeUpstreamLock) -> Path:
    license_path = PurePosixPath(lock.license_path)
    vendor_path = PurePosixPath(lock.vendor_path)
    try:
        relative = license_path.relative_to(vendor_path)
    except ValueError as exc:
        raise SlimeVendorError(
            "Locked license path is not inside the vendor tree"
        ) from exc
    return Path(*relative.parts)


def _object_field(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise SlimeVendorError(f"{key} must be an object")
    return value


def _string_field(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SlimeVendorError(f"{key} must be a non-empty string")
    return value


def _full_git_sha(payload: Mapping[str, Any], key: str) -> str:
    value = _string_field(payload, key)
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise SlimeVendorError(f"{key} must be a full lowercase Git SHA")
    return value


def _sha256(payload: Mapping[str, Any], key: str) -> str:
    value = _string_field(payload, key)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise SlimeVendorError(f"{key} must be a lowercase SHA-256")
    return value


def _string_map(payload: Mapping[str, Any], key: str) -> dict[str, str]:
    value = payload.get(key, {})
    if not isinstance(value, dict) or not all(
        isinstance(item_key, str) and isinstance(item_value, str)
        for item_key, item_value in value.items()
    ):
        raise SlimeVendorError(f"{key} must map strings to strings")
    return dict(sorted(value.items()))


def _string_list(payload: Mapping[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if (
        not isinstance(value, list)
        or not all(isinstance(item, str) and item for item in value)
        or len(value) != len(set(value))
    ):
        raise SlimeVendorError(f"{key} must be a unique list of non-empty strings")
    return sorted(value)


def _validate_relative_path(path: str, *, field: str) -> None:
    value = PurePosixPath(path)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise SlimeVendorError(f"Invalid {field}: {path!r}")


def _resolve_under_root(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SlimeVendorError(f"Path escapes repository root: {path}") from exc
    return resolved


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("verify", "verify-upstream", "rebuild"),
        default="verify",
        nargs="?",
    )
    parser.add_argument("--repo-root", type=Path, default=project_root())
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_OVERLAY_MANIFEST_PATH,
    )
    parser.add_argument("--vendor-path", type=Path)
    parser.add_argument(
        "--archive",
        type=Path,
        help="use a local full-commit archive instead of downloading the lock URL",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        help="materialize a rebuild at a new path; omitted means verify in staging",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "rebuild":
            if args.vendor_path is not None:
                raise SlimeVendorError("--vendor-path is not valid with rebuild")
            report = rebuild_slime_vendor(
                args.repo_root,
                lock_path=args.lock,
                manifest_path=args.manifest,
                archive_path=args.archive,
                destination=args.destination,
            )
        elif args.command == "verify-upstream":
            if args.archive is not None or args.destination is not None:
                raise SlimeVendorError(
                    "--archive/--destination are only valid with rebuild"
                )
            report = verify_slime_upstream_projection(
                args.repo_root,
                lock_path=args.lock,
                vendor_path=args.vendor_path,
            )
        else:
            if args.archive is not None or args.destination is not None:
                raise SlimeVendorError(
                    "--archive/--destination are only valid with rebuild"
                )
            report = verify_slime_vendor(
                args.repo_root,
                lock_path=args.lock,
                manifest_path=args.manifest,
                vendor_path=args.vendor_path,
            )
    except (SlimeVendorError, CodexReferenceError, OSError) as exc:
        print(f"slime-vendor: error: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        if isinstance(report, SlimeRebuildReport):
            payload = {
                "status": report.status,
                "tree_sha256": report.tree_sha256,
                "entry_count": report.entry_count,
                "destination": (
                    str(report.destination)
                    if report.destination is not None
                    else None
                ),
                "message": report.message,
            }
        elif isinstance(report, SlimeVendorReport):
            payload = {
                "status": report.status,
                "vendor_path": str(report.vendor_path),
                "upstream_status": report.upstream_status,
                "expected_sha256": report.expected_sha256,
                "actual_sha256": report.actual_sha256,
                "expected_entry_count": report.expected_entry_count,
                "actual_entry_count": report.actual_entry_count,
                "overlay_file_count": report.overlay_file_count,
                "issues": list(report.issues),
                "message": report.message,
            }
        else:
            payload = {
                "status": report.status,
                "vendor_path": str(report.vendor_path),
                "expected_sha256": report.expected_sha256,
                "actual_sha256": report.actual_sha256,
                "expected_entry_count": report.expected_entry_count,
                "actual_entry_count": report.actual_entry_count,
                "portable_symlink_placeholders": list(
                    report.portable_symlink_placeholders
                ),
                "message": report.message,
            }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(report.message)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
