"""Stable short path helpers for run artifacts."""

from __future__ import annotations

import hashlib
import re


_SAFE_CHARS = re.compile(r"[^A-Za-z0-9_-]+")


def short_hash(*parts: object, length: int = 8) -> str:
    """Return a stable short hash for path disambiguation."""
    payload = "\0".join(str(p) for p in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:length]


def short_slug(value: object, *, max_len: int = 18) -> str:
    """Return a filesystem-friendly short slug."""
    text = _SAFE_CHARS.sub("_", str(value)).strip("_").lower()
    if not text:
        text = "x"
    return text[:max_len].strip("_") or "x"


def mode_dir_name(mode: str) -> str:
    """Short deterministic directory name for a profile mode."""
    aliases = {
        "base": "base",
        "name_only": "name",
        "description_only": "desc",
        "schema_only": "schema",
        "name_description_schema": "nds",
    }
    return aliases.get(mode, short_slug(mode, max_len=12))


def experiment_dir_name(experiment_id: str, mode: str | None = None) -> str:
    """Short experiment directory name preserving uniqueness via hash."""
    if mode:
        prefix = f"e_{mode_dir_name(mode)}"
        return f"{prefix}_{short_hash(experiment_id, mode, length=6)}"
    return f"e_{short_slug(experiment_id, max_len=16)}_{short_hash(experiment_id, length=6)}"


def run_dir_name(task_id: str, profile_id: str) -> str:
    """Short run directory name for a task/profile pair."""
    return f"r_{short_slug(task_id, max_len=16)}_{short_hash(task_id, profile_id, length=8)}"
