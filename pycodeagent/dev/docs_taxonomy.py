"""Validate repository-owned documentation taxonomy and local Markdown links."""

from __future__ import annotations

import argparse
import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DOCS_README = Path("docs/README.md")
_ALLOWED_CATEGORIES = frozenset(
    {
        "current-driver",
        "contract-reference",
        "runbook",
        "archive",
    }
)
_INVENTORY_HEADING = "## Document Inventory"
_READING_ORDER_HEADING = "## Reading Order"
_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\((?P<target>[^)]+)\)")
_DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")


class DocumentationTaxonomyError(ValueError):
    """Raised when documentation navigation or local links drift."""


@dataclass(frozen=True)
class DocumentationInventoryEntry:
    """One row in the canonical documentation inventory table."""

    pattern: str
    category: str
    role: str
    owner: str
    status: str
    superseded_by: str
    provenance: str


@dataclass(frozen=True)
class DocumentationTaxonomyReport:
    """Validated documentation inventory summary."""

    document_paths: tuple[str, ...]
    inventory_entries: tuple[DocumentationInventoryEntry, ...]
    local_link_count: int


def validate_documentation_taxonomy(
    repo_root: str | Path = _PROJECT_ROOT,
) -> DocumentationTaxonomyReport:
    """Validate docs coverage, category ownership, and reading-order boundaries."""
    root = Path(repo_root).resolve()
    docs_readme = root / _DOCS_README
    entries = read_documentation_inventory(docs_readme)
    document_paths = _documentation_paths(root)
    _validate_inventory_entries(entries)
    _validate_document_coverage(document_paths, entries)
    _validate_current_driver(entries)
    _validate_archive_records(entries)
    _validate_reading_order(docs_readme, root, entries)
    local_link_count = check_relative_markdown_links(root)
    return DocumentationTaxonomyReport(
        document_paths=tuple(document_paths),
        inventory_entries=tuple(entries),
        local_link_count=local_link_count,
    )


def read_documentation_inventory(
    docs_readme: str | Path,
) -> list[DocumentationInventoryEntry]:
    """Read the inventory table from the canonical documentation homepage."""
    path = Path(docs_readme)
    if not path.is_file():
        raise DocumentationTaxonomyError(f"Missing documentation homepage: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    section = _section_lines(lines, _INVENTORY_HEADING)
    while section and not section[0].strip():
        section.pop(0)
    if len(section) < 3:
        raise DocumentationTaxonomyError("Document Inventory table is missing")

    header = _table_cells(section[0])
    expected_header = [
        "Path",
        "Category",
        "Role",
        "Owner",
        "Status",
        "Superseded by / next action",
        "Provenance / archive date",
    ]
    if header != expected_header:
        raise DocumentationTaxonomyError("Document Inventory table header drift")
    if not _is_table_separator(section[1]):
        raise DocumentationTaxonomyError("Document Inventory table separator is missing")

    entries: list[DocumentationInventoryEntry] = []
    for line in section[2:]:
        if not line.strip():
            continue
        if not line.lstrip().startswith("|"):
            raise DocumentationTaxonomyError(
                f"Unexpected Document Inventory content: {line!r}"
            )
        cells = _table_cells(line)
        if len(cells) != len(expected_header):
            raise DocumentationTaxonomyError(
                f"Document Inventory row has {len(cells)} columns, expected {len(expected_header)}"
            )
        entries.append(
            DocumentationInventoryEntry(
                pattern=_strip_inline_code(cells[0]),
                category=_strip_inline_code(cells[1]),
                role=_strip_inline_code(cells[2]),
                owner=_strip_inline_code(cells[3]),
                status=_strip_inline_code(cells[4]),
                superseded_by=_strip_inline_code(cells[5]),
                provenance=_strip_inline_code(cells[6]),
            )
        )
    if not entries:
        raise DocumentationTaxonomyError("Document Inventory table has no entries")
    return entries


def check_relative_markdown_links(repo_root: str | Path = _PROJECT_ROOT) -> int:
    """Ensure repo-owned Markdown local links resolve within the repository."""
    root = Path(repo_root).resolve()
    issues: list[str] = []
    local_link_count = 0
    for source in _markdown_sources(root):
        text = source.read_text(encoding="utf-8")
        for target in _markdown_targets(text):
            target_path = _local_target_path(target)
            if target_path is None:
                continue
            local_link_count += 1
            candidate = (source.parent / target_path).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                issues.append(
                    f"{source.relative_to(root)}: link escapes repository: {target!r}"
                )
                continue
            if not candidate.exists():
                issues.append(
                    f"{source.relative_to(root)}: missing local link target: {target!r}"
                )
    if issues:
        raise DocumentationTaxonomyError("\n".join(issues))
    return local_link_count


def _documentation_paths(root: Path) -> list[str]:
    docs_root = root / "docs"
    if not docs_root.is_dir():
        raise DocumentationTaxonomyError(f"Missing docs directory: {docs_root}")
    return sorted(path.relative_to(root).as_posix() for path in docs_root.rglob("*.md"))


def _validate_inventory_entries(entries: list[DocumentationInventoryEntry]) -> None:
    patterns: set[str] = set()
    for entry in entries:
        if not entry.pattern.startswith("docs/"):
            raise DocumentationTaxonomyError(
                f"Inventory path must be docs-relative: {entry.pattern!r}"
            )
        if entry.pattern in patterns:
            raise DocumentationTaxonomyError(
                f"Duplicate Document Inventory pattern: {entry.pattern}"
            )
        patterns.add(entry.pattern)
        if entry.category not in _ALLOWED_CATEGORIES:
            raise DocumentationTaxonomyError(
                f"Unsupported documentation category for {entry.pattern}: {entry.category}"
            )
        for field_name, value in (
            ("role", entry.role),
            ("owner", entry.owner),
            ("status", entry.status),
            ("superseded_by", entry.superseded_by),
            ("provenance", entry.provenance),
        ):
            if not value:
                raise DocumentationTaxonomyError(
                    f"Inventory {field_name} is empty for {entry.pattern}"
                )


def _validate_document_coverage(
    document_paths: list[str],
    entries: list[DocumentationInventoryEntry],
) -> None:
    matches_by_pattern = {entry.pattern: 0 for entry in entries}
    for document_path in document_paths:
        matches = [
            entry for entry in entries if fnmatch.fnmatchcase(document_path, entry.pattern)
        ]
        if len(matches) != 1:
            raise DocumentationTaxonomyError(
                f"Document inventory coverage drift for {document_path}: "
                f"matched {[entry.pattern for entry in matches]!r}"
            )
        matches_by_pattern[matches[0].pattern] += 1
    empty_patterns = [
        pattern for pattern, count in matches_by_pattern.items() if count == 0
    ]
    if empty_patterns:
        raise DocumentationTaxonomyError(
            f"Document Inventory patterns match no documents: {empty_patterns!r}"
        )


def _validate_current_driver(entries: list[DocumentationInventoryEntry]) -> None:
    drivers = [entry for entry in entries if entry.category == "current-driver"]
    expected_pattern = "docs/codex_rs_subsystem_implementation_plan.md"
    if len(drivers) != 1 or drivers[0].pattern != expected_pattern:
        raise DocumentationTaxonomyError(
            "Documentation taxonomy must declare exactly one current driver: "
            f"{expected_pattern}"
        )
    industrial_gap = next(
        (
            entry
            for entry in entries
            if entry.pattern == "docs/local_runtime_industrial_gap_roadmap.md"
        ),
        None,
    )
    if industrial_gap is None or industrial_gap.category != "contract-reference":
        raise DocumentationTaxonomyError(
            "Industrial gap roadmap must remain a contract-reference acceptance framework"
        )


def _validate_archive_records(entries: list[DocumentationInventoryEntry]) -> None:
    for entry in entries:
        if entry.category != "archive":
            continue
        if not entry.status.startswith("archive-"):
            raise DocumentationTaxonomyError(
                f"Archive record has invalid status: {entry.pattern}"
            )
        if entry.superseded_by == "—":
            raise DocumentationTaxonomyError(
                f"Archive record is missing replacement relation: {entry.pattern}"
            )
        if _DATE_RE.search(entry.provenance) is None:
            raise DocumentationTaxonomyError(
                f"Archive record is missing provenance date: {entry.pattern}"
            )


def _validate_reading_order(
    docs_readme: Path,
    root: Path,
    entries: list[DocumentationInventoryEntry],
) -> None:
    lines = docs_readme.read_text(encoding="utf-8").splitlines()
    section = "\n".join(_section_lines(lines, _READING_ORDER_HEADING))
    if not section:
        raise DocumentationTaxonomyError("Reading Order section is missing")
    entry_by_pattern = {entry.pattern: entry for entry in entries}
    reading_paths: set[str] = set()
    for target in _markdown_targets(section):
        target_path = _local_target_path(target)
        if target_path is None:
            continue
        resolved = (docs_readme.parent / target_path).resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError:
            continue
        entry = entry_by_pattern.get(relative)
        if entry is None:
            continue
        reading_paths.add(relative)
        if entry.category == "archive":
            raise DocumentationTaxonomyError(
                f"Archive document appears in Reading Order: {relative}"
            )
    required_paths = {
        "docs/codex_rs_subsystem_implementation_plan.md",
        "docs/local_runtime_industrial_gap_roadmap.md",
        "docs/tool_runtime_native_family_acceptance_and_regression_plan.md",
    }
    missing = sorted(required_paths - reading_paths)
    if missing:
        raise DocumentationTaxonomyError(
            f"Reading Order is missing canonical documents: {missing!r}"
        )


def _markdown_sources(root: Path) -> list[Path]:
    sources: set[Path] = set()
    for name in (
        "README.md",
        "AGENTS.md",
        "CLAUDE.md",
        "PYCODEAGENT_MULTI_AGENT_SCAFFOLD_DESIGN.md",
    ):
        candidate = root / name
        if candidate.is_file():
            sources.add(candidate)
    for relative_dir in ("docs", "configs/local", "examples"):
        directory = root / relative_dir
        if directory.is_dir():
            sources.update(directory.rglob("*.md"))
    return sorted(sources)


def _markdown_targets(text: str) -> Iterable[str]:
    for match in _MARKDOWN_LINK_RE.finditer(text):
        raw_target = match.group("target").strip()
        if not raw_target:
            continue
        yield raw_target


def _local_target_path(target: str) -> Path | None:
    raw_target = target.strip()
    if raw_target.startswith("<") and raw_target.endswith(">"):
        raw_target = raw_target[1:-1].strip()
    raw_target = raw_target.split(maxsplit=1)[0]
    if not raw_target or raw_target.startswith("#"):
        return None
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw_target) or raw_target.startswith("//"):
        return None
    path_text = raw_target.split("#", 1)[0].split("?", 1)[0]
    if not path_text:
        return None
    path = Path(path_text)
    if path.is_absolute():
        raise DocumentationTaxonomyError(f"Absolute local Markdown link is forbidden: {target!r}")
    return path


def _section_lines(lines: list[str], heading: str) -> list[str]:
    try:
        start = lines.index(heading) + 1
    except ValueError as exc:
        raise DocumentationTaxonomyError(f"Missing required heading: {heading}") from exc
    section: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        section.append(line)
    return section


def _table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        raise DocumentationTaxonomyError(f"Invalid Markdown table row: {line!r}")
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _is_table_separator(line: str) -> bool:
    try:
        cells = _table_cells(line)
    except DocumentationTaxonomyError:
        return False
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _strip_inline_code(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("`") and stripped.endswith("`") and len(stripped) >= 2:
        return stripped[1:-1]
    return stripped


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_PROJECT_ROOT,
        help="repository root to validate",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = validate_documentation_taxonomy(args.repo_root)
    print(
        "documentation taxonomy verified: "
        f"documents={len(report.document_paths)} "
        f"inventory_entries={len(report.inventory_entries)} "
        f"local_links={report.local_link_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
