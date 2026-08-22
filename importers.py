"""Explicit local importers for wildcard and style-library sources.

Importers only parse local files. They return normalized records and never
write to the library; callers can preview and then apply a chosen conflict
policy through LibraryStore.
"""

from __future__ import annotations

import csv
import hashlib
import json
import ntpath
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


MAX_IMPORT_FILE_SIZE = 32 * 1024 * 1024
MAX_IMPORT_TOTAL_SIZE = 64 * 1024 * 1024
MAX_IMPORT_RECORDS = 50_000
RECOGNIZED_LIBRARY_DIRS = frozenset(("wildcards", "custom_wildcards", "styles", "style", "collections"))
DISCOVERY_MAX_DEPTH = 4
DISCOVERY_PRUNE_DIRS = frozenset(
    (
        ".git",
        "node_modules",
        "__pycache__",
        "test",
        "tests",
        "docs",
        "doc",
        "build",
        "builds",
        "dist",
        "cache",
        "caches",
        ".cache",
        "coverage",
        "out",
        "tmp",
        "temp",
        ".pytest_cache",
        ".mypy_cache",
        ".tox",
        "venv",
        ".venv",
    )
)
SUPPORTED_DISCOVERY_SUFFIXES = frozenset((".txt", ".json", ".csv"))


class ImporterError(ValueError):
    """An uploaded or discovered source could not be safely parsed."""


@dataclass(frozen=True)
class ImportRecord:
    name: str
    prompt: str
    category: str = "style"
    folder: str | None = None
    tags: tuple[str, ...] = ()
    favorite: bool = False
    negative_prompt: str | None = None
    source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["tags"] = list(self.tags)
        return value


def _safe_source(path: str | os.PathLike[str]) -> Path:
    candidate = Path(path)
    if not candidate.exists():
        raise ImporterError("import source does not exist")
    if candidate.is_symlink():
        raise ImporterError("symbolic-link import sources are not supported")
    return candidate.resolve()


def _check_size(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ImporterError("import source is unreadable") from exc
    if size > MAX_IMPORT_FILE_SIZE:
        raise ImporterError("import source exceeds the size limit")


def _text(path: Path) -> str:
    _check_size(path)
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImporterError("import source must be UTF-8") from exc
    except OSError as exc:
        raise ImporterError("import source is unreadable") from exc


def _name(value: Any, fallback: str) -> str:
    value = fallback if value is None else str(value).strip()
    if not value:
        value = fallback
    return value[:120]


def _prompt(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ImporterError("import record is missing a prompt")
    return value.strip()[:20_000]


def _record(raw: Any, *, category: str, folder: str | None, fallback_name: str, source: str) -> ImportRecord:
    if isinstance(raw, str):
        return ImportRecord(_name(raw, fallback_name), _prompt(raw), category, folder, source=source)
    if not isinstance(raw, dict):
        raise ImporterError("import record must be a string or object")
    prompt = raw.get("prompt", raw.get("positive_prompt", raw.get("text")))
    if prompt is None and isinstance(raw.get("value"), str):
        prompt = raw["value"]
    negative = raw.get("negative_prompt")
    tags = raw.get("tags", ())
    if isinstance(tags, str):
        tags = [part.strip() for part in tags.split(",") if part.strip()]
    if not isinstance(tags, (list, tuple)):
        tags = ()
    return ImportRecord(
        _name(raw.get("name"), fallback_name),
        _prompt(prompt),
        str(raw.get("category", category) or category),
        str(raw.get("folder", folder)).strip() if raw.get("folder", folder) else None,
        tuple(str(tag).strip() for tag in tags if str(tag).strip()),
        bool(raw.get("favorite", False)),
        str(negative).strip() if isinstance(negative, str) and negative.strip() else None,
        source,
    )


def parse_txt(path: str | os.PathLike[str], *, category: str = "style", folder: str | None = None) -> list[dict[str, Any]]:
    source = _safe_source(path)
    if source.is_dir() or source.suffix.casefold() != ".txt":
        raise ImporterError("expected a .txt file")
    records: list[dict[str, Any]] = []
    for line in _text(source).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        records.append(_record(line, category=category, folder=folder, fallback_name=line, source=str(source)).as_dict())
    return _limit(records)


def parse_directory(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    root = _safe_source(path)
    if not root.is_dir():
        raise ImporterError("expected an import directory")
    return parse_staged_files(root)


def parse_json(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    source = _safe_source(path)
    if source.is_dir() or source.suffix.casefold() != ".json":
        raise ImporterError("expected a .json file")
    try:
        value = json.loads(_text(source))
    except json.JSONDecodeError as exc:
        raise ImporterError("JSON import source is malformed") from exc
    if isinstance(value, dict):
        value = value.get("entries", value.get("styles", value.get("prompts")))
    if not isinstance(value, list):
        raise ImporterError("JSON source must contain an array")
    records: list[dict[str, Any]] = []
    for index, item in enumerate(value, 1):
        records.append(_record(item, category="style", folder=None, fallback_name=f"Imported {index}", source=str(source)).as_dict())
    return _limit(records)


def parse_csv(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    source = _safe_source(path)
    if source.is_dir() or source.suffix.casefold() != ".csv":
        raise ImporterError("expected a .csv file")
    rows = csv.DictReader(_text(source).splitlines())
    fields = {str(field).strip().casefold() for field in (rows.fieldnames or []) if field}
    if "prompt" not in fields and "positive_prompt" not in fields:
        raise ImporterError("CSV source must contain a prompt column")
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        normalized = {str(key).strip().casefold(): value for key, value in row.items() if key}
        records.append(_record(normalized, category="style", folder=None, fallback_name=f"Imported {index}", source=str(source)).as_dict())
    return _limit(records)


def parse_source(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    source = _safe_source(path)
    if source.is_dir():
        return parse_directory(source)
    suffix = source.suffix.casefold()
    if suffix == ".txt":
        return parse_txt(source)
    if suffix == ".json":
        return parse_json(source)
    if suffix == ".csv":
        return parse_csv(source)
    raise ImporterError("unsupported import source type")


def parse_staged_files(root: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Parse all supported files beneath a validated staging directory.

    Relative parent folders become the source group/folder metadata. This is
    the path used by browser directory uploads, where each multipart filename
    carries a webkitRelativePath.
    """
    root = _safe_source(root)
    if not root.is_dir():
        raise ImporterError("expected an import directory")
    records: list[dict[str, Any]] = []
    for source in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
        if source.is_symlink():
            raise ImporterError("symbolic-link import files are not supported")
        if not source.is_file() or source.suffix.casefold() not in (".txt", ".json", ".csv"):
            continue
        relative = source.relative_to(root)
        parts = relative.parts
        group = parts[0] if len(parts) > 1 else source.stem
        folder_parts = parts[1:-1]
        folder = " / ".join(folder_parts) if folder_parts else None
        suffix = source.suffix.casefold()
        if suffix == ".txt":
            parsed = parse_txt(source, category=group, folder=folder)
        elif suffix == ".json":
            parsed = parse_json(source)
        else:
            parsed = parse_csv(source)
        for record in parsed:
            record["category"] = group
            if folder:
                record["folder"] = folder
            record["group_id"] = group
            record["group_name"] = group
            record["source"] = str(relative)
        records.extend(parsed)
    return _limit(records)


def _limit(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(records) > MAX_IMPORT_RECORDS:
        raise ImporterError("import contains too many records")
    return records


def summarize_records(records: Iterable[dict[str, Any]], existing: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    records = list(records)
    existing_names = {str(item.get("name", "")).casefold() for item in (existing or [])}
    categories: dict[str, int] = {}
    folders: dict[str, int] = {}
    grouped: dict[str, dict[str, Any]] = {}
    conflicts = 0
    omitted_negative = 0
    for record in records:
        category = str(record.get("category") or "style")
        categories[category] = categories.get(category, 0) + 1
        group_id = str(record.get("group_id") or category)
        group_name = str(record.get("group_name") or category)
        group = grouped.setdefault(group_id, {"id": group_id, "name": group_name, "count": 0})
        group["count"] += 1
        folder = record.get("folder")
        if folder:
            folders[str(folder)] = folders.get(str(folder), 0) + 1
        if str(record.get("name", "")).casefold() in existing_names:
            conflicts += 1
        if record.get("negative_prompt"):
            omitted_negative += 1
    return {
        "count": len(records),
        "record_count": len(records),
        "groups": list(grouped.values()),
        "group_count": len(grouped),
        "categories": categories,
        "folders": folders,
        "conflicts": conflicts,
        "omitted_negative": omitted_negative,
        "warnings": ["negative_prompt fields are reported but never imported"] if omitted_negative else [],
        "records": records,
    }


def preview_source(path: str | os.PathLike[str], *, existing: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Parse and summarize a source without mutating any library files."""
    return summarize_records(parse_source(path), existing=existing)


def _bounded_discovery_walk(root: Path, *, max_depth: int = DISCOVERY_MAX_DEPTH) -> Iterable[tuple[Path, int]]:
    """Yield non-symlink descendants without crawling an entire extension tree."""
    pending: list[tuple[Path, int]] = [(root.resolve(), 0)]
    while pending:
        current, depth = pending.pop(0)
        try:
            with os.scandir(current) as entries:
                children = sorted(entries, key=lambda item: item.name.casefold())
        except OSError:
            continue
        for entry in children:
            try:
                if entry.is_symlink():
                    continue
                child_depth = depth + 1
                child = current / entry.name
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.casefold() in DISCOVERY_PRUNE_DIRS or child_depth > max_depth:
                        continue
                    yield child, child_depth
                    pending.append((child, child_depth))
                elif entry.is_file(follow_symlinks=False) and child_depth <= max_depth:
                    yield child, child_depth
            except (OSError, ValueError):
                continue


def discover_installed_sources(roots: Iterable[str | os.PathLike[str]] | None = None) -> list[dict[str, Any]]:
    """Discover common local wildcard/style directories, read-only."""
    candidates: list[Path] = []
    recognized: list[Path] = []
    standalone: list[Path] = []
    if roots is None:
        env_roots = os.environ.get("COMFYUI_ROOTS", "")
        roots = [item for item in env_roots.split(os.pathsep) if item]
        if not roots:
            roots = [os.environ.get("COMFYUI_ROOT", "")]
        if not any(roots):
            try:
                import folder_paths  # type: ignore
                roots = [str(folder_paths.get_user_directory())]
                roots.extend(str(item) for item in folder_paths.get_folder_paths("custom_nodes"))
            except (ImportError, AttributeError, TypeError):
                roots = []
    for root_value in roots:
        if not root_value:
            continue
        root = Path(root_value).expanduser()
        if not root.exists() or not root.is_dir():
            continue
        search_roots = [root / "custom_nodes", root / "user", root / "wildcards"]
        if root.name.casefold() in ("custom_nodes", "user", "wildcards", "custom_wildcards", "styles", "style", "collections") or root.parent.name.casefold() in ("custom_nodes", "user"):
            search_roots.append(root)
        for search in search_roots:
            if not search.exists() or not search.is_dir():
                continue
            # Only inspect bounded, known source locations. Do not crawl all
            # workflow/configuration JSON under a ComfyUI installation.
            if search.name.casefold() == "custom_nodes":
                extension_roots = [item for item in search.iterdir() if item.is_dir() and not item.is_symlink()]
            else:
                extension_roots = [search]
            for extension_root in extension_roots:
                local_known: list[Path] = []
                local_files: list[Path] = []
                if extension_root.name.casefold() in RECOGNIZED_LIBRARY_DIRS:
                    local_known.append(extension_root.resolve())
                for item, _depth in _bounded_discovery_walk(extension_root):
                    if item.is_dir() and item.name.casefold() in RECOGNIZED_LIBRARY_DIRS:
                        local_known.append(item.resolve())
                    elif item.is_file() and item.suffix.casefold() in SUPPORTED_DISCOVERY_SUFFIXES:
                        local_files.append(item.resolve())
                # A directory is useful only when the bounded walk found at
                # least one supported descendant. This avoids offering empty
                # placeholders or repository-internal directories as sources.
                for known in local_known:
                    if any(known in source.parents for source in local_files):
                        recognized.append(known)
                try:
                    direct_children = sorted(extension_root.iterdir(), key=lambda item: item.name.casefold())
                except OSError:
                    direct_children = []
                for item in direct_children:
                    if item.is_file() and not item.is_symlink() and item.suffix.casefold() in (".json", ".csv") and "style" in item.stem.casefold():
                        standalone.append(item.resolve())
    # A recognized directory is the unit shown to users. Nested recognized
    # directories and every descendant file remain inside that source choice.
    recognized = sorted(set(recognized), key=lambda path: str(path).casefold())
    selected_dirs: list[Path] = []
    for candidate in recognized:
        if not any(candidate != parent and parent in candidate.parents for parent in selected_dirs):
            selected_dirs.append(candidate)
    candidates.extend(selected_dirs)
    for item in standalone:
        if not any(item.parent == directory or directory in item.parents for directory in selected_dirs):
            candidates.append(item)
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for item in sorted(candidates, key=lambda path: str(path).casefold()):
        key = os.path.normcase(str(item))
        if key in seen:
            continue
        seen.add(key)
        kind = "directory" if item.is_dir() else item.suffix.casefold().lstrip(".")
        source_id = "source-" + hashlib.sha256(str(item).encode("utf-8")).hexdigest()[:24]
        results.append({"id": source_id, "path": str(item), "kind": kind, "name": item.name, "read_only": True})
    return results


parse_import_source = parse_source
discover_sources = discover_installed_sources
preview_import = preview_source


__all__ = [
    "ImporterError", "ImportRecord", "MAX_IMPORT_FILE_SIZE", "MAX_IMPORT_TOTAL_SIZE", "MAX_IMPORT_RECORDS", "RECOGNIZED_LIBRARY_DIRS",
    "parse_txt", "parse_directory", "parse_json", "parse_csv", "parse_source",
    "parse_import_source", "parse_staged_files", "summarize_records", "preview_source", "preview_import",
    "discover_installed_sources", "discover_sources",
]
