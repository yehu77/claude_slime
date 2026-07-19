"""Canonical, versioned workspace-tree digest used by agent adapters."""

from __future__ import annotations

import hashlib
from pathlib import Path


WORKSPACE_DIGEST_VERSION = 1
WORKSPACE_DIGEST_ALGORITHM = "sha256-tree-v1"


def compute_workspace_digest(workspace_dir: str | Path) -> str:
    """Return the legacy-compatible v1 digest for a workspace tree.

    Version 1 sorts every descendant by relative POSIX path, hashes the path
    and a NUL separator, then hashes file bytes or the ``<dir>`` marker and a
    final NUL. File symlinks follow their target; directory, broken, and other
    entries use the directory marker. A missing root hashes ``<missing>``.
    """
    workspace_dir = Path(workspace_dir)
    digest = hashlib.sha256()
    if not workspace_dir.exists():
        digest.update(b"<missing>")
        return digest.hexdigest()

    for path in sorted(workspace_dir.rglob("*")):
        relative = path.relative_to(workspace_dir).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        if path.is_file():
            digest.update(path.read_bytes())
        else:
            digest.update(b"<dir>")
        digest.update(b"\0")
    return digest.hexdigest()
