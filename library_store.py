"""Validated local persistence for Master Prompt Library v1 and v2.

The store is deliberately the only owner of the JSON contract.  Route and
ComfyUI adapters call it for validation, migration, CRUD, and image metadata;
they never reach into the files directly.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable

try:
    from .image_store import ImageStore, MAX_IMAGES_PER_ENTRY
except ImportError:  # direct source import for hermetic tests
    from image_store import ImageStore, MAX_IMAGES_PER_ENTRY

try:
    import folder_paths  # type: ignore
except ImportError:  # pragma: no cover - exercised only by ComfyUI
    folder_paths = None


VERSION = 2
V1_VERSION = 1
CATEGORIES = ("style", "character", "action", "background")
CORE_CATEGORY_IDS = CATEGORIES
NONE_SELECTION = "✨ none"
MAX_NAME_LENGTH = 120
MAX_CATEGORY_NAME_LENGTH = 80
MAX_PROMPT_LENGTH = 20_000
MAX_TAG_LENGTH = 80
MAX_TAGS = 100
MAX_LORA_NAME_LENGTH = 512
MAX_LORAS_PER_ENTRY = 16

_WRITE_LOCK = threading.RLock()
_UNSET = object()


class LibraryError(Exception):
    """Base class for expected library failures."""


class ValidationError(LibraryError):
    """The caller supplied a document or field outside the data contract."""


class DuplicateNameError(ValidationError):
    """A name is already used in the requested scope."""


class EntryNotFoundError(LibraryError):
    """No current entry has the requested UUID."""


class CategoryNotFoundError(LibraryError):
    """No current category has the requested ID or key."""


class FolderNotFoundError(LibraryError):
    """No current folder has the requested UUID."""


class ImageNotFoundError(LibraryError):
    """No current image has the requested UUID."""


class CorruptLibraryError(LibraryError):
    """The existing user library is not valid JSON or schema."""


def _uuid_text(value: Any, label: str = "id") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a UUID string")
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError(f"{label} must be a UUID string") from exc


def _category_id(value: Any) -> str:
    if value in CATEGORIES:
        return str(value)
    try:
        return _uuid_text(value, "category id")
    except ValidationError as exc:
        raise CategoryNotFoundError("category not found") from exc


def _trim_text(value: Any, label: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a string")
    value = value.strip()
    if not allow_empty and not value:
        raise ValidationError(f"{label} is required")
    if len(value) > maximum:
        raise ValidationError(f"{label} is too long")
    return value


def _validate_v1(document: Any, *, image_store: ImageStore | None = None, clear_missing_images: bool = False) -> dict[str, Any]:
    if not isinstance(document, dict) or document.get("version") != V1_VERSION:
        raise ValidationError("unsupported library version")
    categories = document.get("categories")
    if not isinstance(categories, dict) or set(categories) != set(CATEGORIES):
        raise ValidationError("library categories are invalid")
    result: dict[str, Any] = {"version": V1_VERSION, "categories": {}}
    for category in CATEGORIES:
        values = categories[category]
        if not isinstance(values, list):
            raise ValidationError(f"{category} must be a list")
        names: set[str] = set()
        output: list[dict[str, Any]] = []
        for raw in values:
            if not isinstance(raw, dict):
                raise ValidationError("entry must be an object")
            entry_id = _uuid_text(raw.get("id"), "entry id")
            name = _trim_text(raw.get("name"), "entry name", MAX_NAME_LENGTH)
            prompt = _trim_text(raw.get("prompt"), "entry prompt", MAX_PROMPT_LENGTH)
            if name.casefold() in names:
                raise DuplicateNameError(f"duplicate entry name in {category}")
            names.add(name.casefold())
            image = raw.get("image")
            if image is not None:
                if not isinstance(image, dict) or not isinstance(image.get("filename"), str) or not isinstance(image.get("media_type"), str):
                    raise ValidationError("image metadata is invalid")
                if image_store is not None:
                    try:
                        image_store.validate_metadata(entry_id, image)
                        if clear_missing_images and not image_store.exists(entry_id, image):
                            image = None
                    except (ValueError, FileNotFoundError) as exc:
                        raise ValidationError("image metadata is invalid") from exc
                elif Path(image["filename"]).name != image["filename"] or image["media_type"] not in ImageStore.MEDIA_TYPES:
                    raise ValidationError("image metadata is invalid")
                else:
                    image = {"filename": image["filename"], "media_type": image["media_type"]}
            output.append({"id": entry_id, "name": name, "prompt": prompt, "image": image})
        result["categories"][category] = output
    return result


def _normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError("tags must be a list")
    unique: dict[str, str] = {}
    for raw in value:
        tag = _trim_text(raw, "tag", MAX_TAG_LENGTH)
        unique.setdefault(tag.casefold(), tag)
    if len(unique) > MAX_TAGS:
        raise ValidationError("too many tags")
    return sorted(unique.values(), key=lambda tag: (tag.casefold(), tag))


def _normalize_loras(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_LORAS_PER_ENTRY:
        raise ValidationError("entry LoRA attachments are invalid")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValidationError("LoRA attachment must be an object")
        name = _trim_text(raw.get("name"), "LoRA name", MAX_LORA_NAME_LENGTH)
        key = name.casefold()
        if key in seen:
            raise ValidationError("duplicate LoRA attachment")
        seen.add(key)
        strengths: dict[str, float] = {}
        for field in ("strength_model", "strength_clip"):
            raw_strength = raw.get(field, 1.0)
            if isinstance(raw_strength, bool) or not isinstance(raw_strength, (int, float)):
                raise ValidationError(f"LoRA {field} must be a number")
            strength = float(raw_strength)
            if not math.isfinite(strength) or strength < -100.0 or strength > 100.0:
                raise ValidationError(f"LoRA {field} is outside the supported range")
            strengths[field] = strength
        normalized.append({"name": name, **strengths})
    return normalized


def _validate_v2(document: Any, *, image_store: ImageStore | None = None, clear_missing_images: bool = False) -> dict[str, Any]:
    if not isinstance(document, dict) or document.get("version") != VERSION:
        raise ValidationError("unsupported library version")
    raw_categories = document.get("categories")
    if not isinstance(raw_categories, list):
        raise ValidationError("categories must be a list")
    if not raw_categories:
        raise ValidationError("library must contain core categories")
    result: dict[str, Any] = {"version": VERSION, "categories": [], "applied_seed_packs": []}
    seen_categories: set[str] = set()
    seen_entry_ids: set[str] = set()
    seen_category_names: set[str] = set()
    for raw_category in raw_categories:
        if not isinstance(raw_category, dict):
            raise ValidationError("category must be an object")
        category_id = raw_category.get("id")
        if category_id in CATEGORIES:
            category_id = str(category_id)
            key = raw_category.get("key")
            if key != category_id:
                raise ValidationError("core category key is invalid")
            protected = raw_category.get("protected")
            if protected is not True:
                raise ValidationError("core category must be protected")
        else:
            category_id = _uuid_text(category_id, "category id")
            if raw_category.get("key") is not None or raw_category.get("protected") is not False:
                raise ValidationError("custom category metadata is invalid")
            key = None
            protected = False
        if category_id in seen_categories:
            raise ValidationError("duplicate category id")
        seen_categories.add(category_id)
        name = _trim_text(raw_category.get("name"), "category name", MAX_CATEGORY_NAME_LENGTH)
        name_key = name.casefold()
        if name_key in seen_category_names:
            raise DuplicateNameError("duplicate category name")
        seen_category_names.add(name_key)
        raw_folders = raw_category.get("folders", [])
        if not isinstance(raw_folders, list):
            raise ValidationError("folders must be a list")
        folders: list[dict[str, str]] = []
        folder_ids: set[str] = set()
        folder_names: set[str] = set()
        for raw_folder in raw_folders:
            if not isinstance(raw_folder, dict):
                raise ValidationError("folder must be an object")
            folder_id = _uuid_text(raw_folder.get("id"), "folder id")
            folder_name = _trim_text(raw_folder.get("name"), "folder name", MAX_CATEGORY_NAME_LENGTH)
            if folder_id in folder_ids or folder_name.casefold() in folder_names:
                raise DuplicateNameError("duplicate folder name")
            folder_ids.add(folder_id)
            folder_names.add(folder_name.casefold())
            folders.append({"id": folder_id, "name": folder_name})
        raw_entries = raw_category.get("entries", [])
        if not isinstance(raw_entries, list):
            raise ValidationError("entries must be a list")
        entries: list[dict[str, Any]] = []
        entry_ids: set[str] = set()
        entry_names: set[str] = set()
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                raise ValidationError("entry must be an object")
            entry_id = _uuid_text(raw_entry.get("id"), "entry id")
            if entry_id in entry_ids or entry_id in seen_entry_ids:
                raise ValidationError("duplicate entry id")
            entry_ids.add(entry_id)
            seen_entry_ids.add(entry_id)
            entry_name = _trim_text(raw_entry.get("name"), "entry name", MAX_NAME_LENGTH)
            entry_prompt = _trim_text(raw_entry.get("prompt"), "entry prompt", MAX_PROMPT_LENGTH)
            if entry_name.casefold() in entry_names:
                raise DuplicateNameError("duplicate entry name")
            entry_names.add(entry_name.casefold())
            folder_id = raw_entry.get("folder_id")
            if folder_id is not None:
                folder_id = _uuid_text(folder_id, "folder id")
                if folder_id not in folder_ids:
                    raise ValidationError("entry folder is not in its category")
            favorite = raw_entry.get("favorite", False)
            if not isinstance(favorite, bool):
                raise ValidationError("favorite must be boolean")
            tags = _normalize_tags(raw_entry.get("tags", []))
            raw_images = raw_entry.get("images", [])
            if not isinstance(raw_images, list) or len(raw_images) > MAX_IMAGES_PER_ENTRY:
                raise ValidationError("entry image count is invalid")
            images: list[dict[str, Any]] = []
            image_ids: set[str] = set()
            preview_ids: set[str] = set()
            for raw_image in raw_images:
                if not isinstance(raw_image, dict):
                    raise ValidationError("image metadata is invalid")
                image_id = _uuid_text(raw_image.get("id"), "image id")
                if image_id in image_ids:
                    raise ValidationError("duplicate image id")
                image_ids.add(image_id)
                kind = raw_image.get("kind")
                if kind not in ("preview", "generated"):
                    raise ValidationError("image kind is invalid")
                filename = raw_image.get("filename")
                media_type = raw_image.get("media_type")
                caption = raw_image.get("caption", "")
                caption = _trim_text(caption, "image caption", 240, allow_empty=True)
                metadata: dict[str, Any] = {
                    "id": image_id,
                    "filename": filename,
                    "media_type": media_type,
                    "kind": kind,
                    "caption": caption,
                }
                try:
                    if image_store is not None:
                        image_store.validate_metadata(entry_id, metadata)
                        if clear_missing_images and not image_store.exists(entry_id, metadata):
                            continue
                    else:
                        if not isinstance(filename, str) or Path(filename).name != filename or media_type not in ImageStore.MEDIA_TYPES:
                            raise ValueError("image metadata is invalid")
                        if Path(filename).stem.casefold() not in {image_id.casefold(), uuid.UUID(image_id).hex.casefold()}:
                            raise ValueError("image filename is invalid")
                except (ValueError, FileNotFoundError) as exc:
                    raise ValidationError("image metadata is invalid") from exc
                images.append(metadata)
                if kind == "preview":
                    preview_ids.add(image_id)
            primary = raw_entry.get("primary_image_id")
            if primary is not None:
                primary = _uuid_text(primary, "primary image id")
                if primary not in preview_ids:
                    raise ValidationError("primary image must be a preview")
            entries.append({
                "id": entry_id,
                "name": entry_name,
                "prompt": entry_prompt,
                "tags": tags,
                "loras": _normalize_loras(raw_entry.get("loras", [])),
                "favorite": favorite,
                "folder_id": folder_id,
                "images": images,
                "primary_image_id": primary,
            })
        result["categories"].append({
            "id": category_id,
            "key": key,
            "name": name,
            "protected": protected,
            "folders": folders,
            "entries": entries,
        })
    if any(category not in seen_categories for category in CATEGORIES):
        raise ValidationError("library is missing a core category")
    raw_packs = document.get("applied_seed_packs", [])
    if not isinstance(raw_packs, list):
        raise ValidationError("applied_seed_packs must be a list")
    for raw_pack in raw_packs:
        if not isinstance(raw_pack, dict) or not isinstance(raw_pack.get("id"), str) or not isinstance(raw_pack.get("version"), int) or isinstance(raw_pack.get("version"), bool):
            raise ValidationError("seed pack state is invalid")
        result["applied_seed_packs"].append({"id": raw_pack["id"], "version": raw_pack["version"]})
    return result


def validate_library(document: Any, *, image_store: ImageStore | None = None, clear_missing_images: bool = False) -> dict[str, Any]:
    """Validate and normalize a v2 document."""
    return _validate_v2(document, image_store=image_store, clear_missing_images=clear_missing_images)


def empty_library() -> dict[str, Any]:
    return {
        "version": VERSION,
        "categories": [
            {"id": key, "key": key, "name": key.title(), "protected": True, "folders": [], "entries": []}
            for key in CATEGORIES
        ],
        "applied_seed_packs": [],
    }


def _canonical_json(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class LibraryStore:
    """Validated JSON store with atomic replacement, migration, and CRUD."""

    def __init__(self, user_directory: str | os.PathLike[str] | None = None, *, library_path: str | os.PathLike[str] | None = None, seed_path: str | os.PathLike[str] | None = None, seed_manifest_path: str | os.PathLike[str] | None = None, image_store: ImageStore | None = None) -> None:
        if library_path is None:
            root = Path(user_directory) if user_directory is not None else _user_directory()
            library_path = root / "prompt_library" / "library.json"
        self.library_path = Path(library_path)
        self.library_path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_path = self.library_path.with_name(self.library_path.name + ".bak")
        default_v2_seed = Path(__file__).with_name("seed_library_v2.json")
        default_v1_seed = Path(__file__).with_name("seed_library.json")
        provided_seed_path = seed_path is not None
        if seed_path is None:
            seed_path = default_v2_seed if default_v2_seed.exists() else default_v1_seed
        self.seed_path = Path(seed_path)
        self.seed_manifest_path = Path(seed_manifest_path) if seed_manifest_path is not None else Path(__file__).with_name("seed_manifest_v2.json")
        self.image_store = image_store or ImageStore(self.library_path.parent / "images")
        self._legacy_seed_mode = False
        if not self.library_path.exists() and provided_seed_path:
            try:
                raw_seed = json.loads(self.seed_path.read_text(encoding="utf-8"))
                self._legacy_seed_mode = raw_seed.get("version") == V1_VERSION
            except (OSError, json.JSONDecodeError, AttributeError):
                pass

    @property
    def images_directory(self) -> Path:
        return self.image_store.directory

    def _raw_file(self, path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise CorruptLibraryError("prompt library is unreadable") from exc
        if not isinstance(raw, dict):
            raise CorruptLibraryError("prompt library must be an object")
        return raw

    def _read_file(self, path: Path) -> dict[str, Any]:
        raw = self._raw_file(path)
        try:
            if raw.get("version") == V1_VERSION:
                return _validate_v1(raw, image_store=self.image_store, clear_missing_images=True)
            return validate_library(raw, image_store=self.image_store, clear_missing_images=True)
        except LibraryError as exc:
            raise CorruptLibraryError("prompt library failed validation") from exc

    def _seed_raw(self) -> dict[str, Any]:
        try:
            raw = self._raw_file(self.seed_path)
        except CorruptLibraryError as exc:
            raise CorruptLibraryError("bundled prompt seed is unreadable") from exc
        return raw

    def _seed_v2(self) -> dict[str, Any]:
        raw = self._seed_raw()
        if raw.get("version") == V1_VERSION:
            return self._convert_v1(raw, rehome_images=False)
        return validate_library(raw, image_store=self.image_store, clear_missing_images=False)

    def _seed_state(self) -> tuple[str, int] | None:
        if not self.seed_manifest_path.exists():
            return None
        try:
            manifest = self._raw_file(self.seed_manifest_path)
        except CorruptLibraryError:
            return None
        pack_id = manifest.get("id", manifest.get("pack_id"))
        version = manifest.get("version", manifest.get("pack_version"))
        if isinstance(pack_id, str) and isinstance(version, int) and not isinstance(version, bool):
            return pack_id, version
        return None

    def _merge_seed(self, document: dict[str, Any], seed: dict[str, Any] | None = None) -> dict[str, Any]:
        seed = seed or self._seed_v2()
        target = copy.deepcopy(document)
        target = validate_library(target, image_store=self.image_store, clear_missing_images=False)
        applied = {(item["id"], item["version"]) for item in target.get("applied_seed_packs", [])}
        pack_state = self._seed_state()
        if pack_state is None:
            pack_state = ("master-prompt-library-core", 2)
        for seed_category in seed["categories"]:
            target_category = next((cat for cat in target["categories"] if cat["id"] == seed_category["id"] or (seed_category["key"] and cat["id"] == seed_category["key"])), None)
            if target_category is None:
                # Bundled custom categories are deterministic and safe to add;
                # user categories are never replaced by a same-name category.
                if any(cat["name"].casefold() == seed_category["name"].casefold() for cat in target["categories"]):
                    continue
                target_category = copy.deepcopy(seed_category)
                target["categories"].append(target_category)
                continue
            existing_ids = {entry["id"] for entry in target_category["entries"]}
            existing_names = {entry["name"].casefold() for entry in target_category["entries"]}
            for seed_entry in seed_category["entries"]:
                if seed_entry["id"] in existing_ids or seed_entry["name"].casefold() in existing_names:
                    continue
                target_category["entries"].append(copy.deepcopy(seed_entry))
                existing_ids.add(seed_entry["id"])
                existing_names.add(seed_entry["name"].casefold())
            # Seed folders can be added by stable ID, but user folders win on
            # name conflicts and are never renamed.
            folder_ids = {folder["id"] for folder in target_category["folders"]}
            folder_names = {folder["name"].casefold() for folder in target_category["folders"]}
            for seed_folder in seed_category["folders"]:
                if seed_folder["id"] not in folder_ids and seed_folder["name"].casefold() not in folder_names:
                    target_category["folders"].append(copy.deepcopy(seed_folder))
        if pack_state not in applied:
            target.setdefault("applied_seed_packs", []).append({"id": pack_state[0], "version": pack_state[1]})
        return validate_library(target, image_store=self.image_store, clear_missing_images=False)

    def _write_json_locked(self, document: dict[str, Any]) -> None:
        self.library_path.parent.mkdir(parents=True, exist_ok=True)
        if self.library_path.exists():
            current_raw = self._raw_file(self.library_path)
            try:
                if current_raw.get("version") == V1_VERSION:
                    _validate_v1(current_raw, image_store=self.image_store, clear_missing_images=False)
                elif current_raw.get("version") == VERSION:
                    validate_library(current_raw, image_store=self.image_store, clear_missing_images=False)
                else:
                    raise CorruptLibraryError("prompt library failed validation")
            except LibraryError as exc:
                raise CorruptLibraryError("prompt library failed validation") from exc
            shutil.copy2(self.library_path, self.backup_path)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.library_path.parent, prefix=f".{self.library_path.name}.", suffix=".tmp", delete=False) as handle:
                temporary_name = handle.name
                json.dump(document, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.library_path)
            temporary_name = None
        finally:
            if temporary_name:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass

    def _convert_v1(self, raw: dict[str, Any], *, rehome_images: bool) -> dict[str, Any]:
        source = _validate_v1(raw, image_store=self.image_store, clear_missing_images=False)
        converted = empty_library()
        legacy_files: list[tuple[str, dict[str, str]]] = []
        for category in CATEGORIES:
            target_category = next(cat for cat in converted["categories"] if cat["id"] == category)
            for old_entry in source["categories"][category]:
                images: list[dict[str, Any]] = []
                primary: str | None = None
                old_image = old_entry.get("image")
                if old_image is not None and rehome_images:
                    image_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"master-prompt-library:{old_entry['id']}:legacy"))
                    metadata = self.image_store.rehome_legacy(old_entry["id"], image_id, old_image)
                    if metadata is not None:
                        metadata.update({"kind": "preview", "caption": ""})
                        images.append(metadata)
                        primary = image_id
                        legacy_files.append((old_entry["id"], old_image))
                target_category["entries"].append({
                    "id": old_entry["id"],
                    "name": old_entry["name"],
                    "prompt": old_entry["prompt"],
                    "tags": [],
                    "loras": [],
                    "favorite": False,
                    "folder_id": None,
                    "images": images,
                    "primary_image_id": primary,
                })
        converted = validate_library(converted, image_store=self.image_store, clear_missing_images=False)
        converted["_legacy_files"] = legacy_files
        return converted

    def _migrate_existing_locked(self, raw: dict[str, Any]) -> dict[str, Any]:
        converted = self._convert_v1(raw, rehome_images=True)
        legacy_files = converted.pop("_legacy_files", [])
        converted = self._merge_seed(converted)
        self._write_json_locked(converted)
        reread = validate_library(self._raw_file(self.library_path), image_store=self.image_store, clear_missing_images=False)
        for entry_id, metadata in legacy_files:
            try:
                self.image_store.remove(entry_id, metadata)
            except (OSError, ValueError):
                pass
        return reread

    def ensure_library(self) -> dict[str, Any]:
        with _WRITE_LOCK:
            if self.library_path.exists():
                raw = self._raw_file(self.library_path)
                if raw.get("version") == V1_VERSION:
                    if self._legacy_seed_mode:
                        return _validate_v1(raw, image_store=self.image_store, clear_missing_images=True)
                    return self._migrate_existing_locked(raw)
                try:
                    current = validate_library(raw, image_store=self.image_store, clear_missing_images=True)
                    pack_state = self._seed_state() or ("master-prompt-library-core", 2)
                    applied = {(item["id"], item["version"]) for item in current.get("applied_seed_packs", [])}
                    if pack_state not in applied:
                        upgraded = self._merge_seed(current)
                        self._write_json_locked(upgraded)
                        return copy.deepcopy(upgraded)
                    return current
                except LibraryError as exc:
                    raise CorruptLibraryError("prompt library failed validation") from exc
            if self._legacy_seed_mode:
                legacy = _validate_v1(self._seed_raw(), image_store=self.image_store, clear_missing_images=False)
                self._write_json_locked(legacy)
                return copy.deepcopy(legacy)
            seed = self._merge_seed(empty_library(), self._seed_v2())
            self._write_json_locked(seed)
            return copy.deepcopy(seed)

    def migrate(self) -> dict[str, Any]:
        """Load, migrate if necessary, and return the current v2 library."""
        return self.ensure_library()

    migrate_v1_to_v2 = migrate

    def get_library(self) -> dict[str, Any]:
        return copy.deepcopy(self.ensure_library())

    def get_v1_library(self) -> dict[str, Any]:
        """Return the legacy display-name/image shape over a v2 library."""
        library = self.get_library()
        if library.get("version") == V1_VERSION:
            return library
        categories: dict[str, list[dict[str, Any]]] = {category: [] for category in CATEGORIES}
        for category_id in CATEGORIES:
            category = self._find_category(library, category_id)
            for entry in category["entries"]:
                primary = next((image for image in entry["images"] if image["id"] == entry.get("primary_image_id")), None)
                categories[category_id].append({"id": entry["id"], "name": entry["name"], "prompt": entry["prompt"], "image": copy.deepcopy(primary) if primary else None})
        return {"version": V1_VERSION, "categories": categories}

    def get_v1_entry(self, entry_id: Any) -> dict[str, Any]:
        entry = self.get_entry(entry_id)
        if self.ensure_library().get("version") == V1_VERSION:
            return entry
        primary = next((image for image in entry["images"] if image["id"] == entry.get("primary_image_id")), None)
        return {"id": entry["id"], "name": entry["name"], "prompt": entry["prompt"], "image": copy.deepcopy(primary) if primary else None}

    def replace_v1_library(self, document: Any) -> dict[str, Any]:
        """Replace through the v1 shape while persisting a validated v2 document."""
        with _WRITE_LOCK:
            source = _validate_v1(document, image_store=self.image_store, clear_missing_images=True)
            current = self.ensure_library()
            if current.get("version") == V1_VERSION:
                return self.replace_library(source)
            current_by_category = {category["id"]: category for category in current["categories"]}
            removed_entry_ids: list[str] = []
            legacy_files: list[tuple[str, dict[str, str]]] = []
            next_library = copy.deepcopy(current)
            next_by_category = {category["id"]: category for category in next_library["categories"]}
            for category_id in CATEGORIES:
                current_category = current_by_category[category_id]
                target_category = next_by_category[category_id]
                existing_by_id = {entry["id"]: entry for entry in current_category["entries"]}
                source_entries = source["categories"][category_id]
                replacement_entries: list[dict[str, Any]] = []
                retained_ids: set[str] = set()
                for raw_entry in source_entries:
                    existing = existing_by_id.get(raw_entry["id"])
                    if existing is None:
                        entry = {
                            "id": raw_entry["id"],
                            "name": raw_entry["name"],
                            "prompt": raw_entry["prompt"],
                            "tags": [],
                            "favorite": False,
                            "folder_id": None,
                            "images": [],
                            "primary_image_id": None,
                        }
                    else:
                        entry = copy.deepcopy(existing)
                        entry["name"] = raw_entry["name"]
                        entry["prompt"] = raw_entry["prompt"]
                        if entry.get("folder_id") not in {folder["id"] for folder in target_category["folders"]}:
                            entry["folder_id"] = None
                    retained_ids.add(raw_entry["id"])
                    raw_image = raw_entry.get("image")
                    if raw_image is not None:
                        matching_image = next(
                            (
                                image for image in entry["images"]
                                if image["filename"] == raw_image.get("filename")
                                and image["media_type"] == raw_image.get("media_type")
                            ),
                            None,
                        )
                        if matching_image is not None:
                            entry["primary_image_id"] = matching_image["id"]
                        elif self.image_store.exists(raw_entry["id"], raw_image):
                            image_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"master-prompt-library:{raw_entry['id']}:v1-replace:{raw_image['filename']}"))
                            if not any(image["id"] == image_id for image in entry["images"]):
                                metadata = self.image_store.rehome_legacy(raw_entry["id"], image_id, raw_image)
                                if metadata is not None:
                                    metadata.update({"kind": "preview", "caption": ""})
                                    entry["images"].append(metadata)
                                    legacy_files.append((raw_entry["id"], raw_image))
                                    entry["primary_image_id"] = image_id
                    replacement_entries.append(entry)
                removed_entry_ids.extend(
                    entry_id for entry_id in existing_by_id
                    if entry_id not in retained_ids
                )
                target_category["entries"] = replacement_entries
            normalized = validate_library(next_library, image_store=self.image_store, clear_missing_images=True)
            self._write_json_locked(normalized)
            # Files are removed only after the replacement JSON has committed.
            for entry_id in removed_entry_ids:
                self.image_store.remove_entry(entry_id)
            for entry_id, metadata in legacy_files:
                try:
                    self.image_store.remove(entry_id, metadata)
                except (OSError, ValueError):
                    pass
            return self.get_v1_library()

    def get_library_with_fingerprint(self) -> dict[str, Any]:
        library = self.get_library()
        library["fingerprint"] = hashlib.sha256(_canonical_json(library).encode("utf-8")).hexdigest()
        return library

    def fingerprint(self) -> str:
        return hashlib.sha256(_canonical_json(self.ensure_library()).encode("utf-8")).hexdigest()

    def _save(self, document: dict[str, Any]) -> dict[str, Any]:
        with _WRITE_LOCK:
            if document.get("version") == V1_VERSION:
                normalized = _validate_v1(document, image_store=self.image_store, clear_missing_images=True)
            else:
                normalized = validate_library(document, image_store=self.image_store, clear_missing_images=True)
            self._write_json_locked(normalized)
        return copy.deepcopy(normalized)

    def _v2(self) -> dict[str, Any]:
        library = self.ensure_library()
        if library.get("version") != VERSION:
            raise ValidationError("v2 operation requires a v2 library")
        return library

    @staticmethod
    def _find_category(library: dict[str, Any], category: Any) -> dict[str, Any]:
        if category in CATEGORIES:
            wanted = str(category)
        else:
            try:
                wanted = _uuid_text(category, "category id")
            except ValidationError as exc:
                raise CategoryNotFoundError("category not found") from exc
        for item in library["categories"]:
            if item["id"] == wanted or item.get("key") == wanted:
                return item
        raise CategoryNotFoundError("category not found")

    @staticmethod
    def _find_entry(library: dict[str, Any], entry_id: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        wanted = _uuid_text(entry_id, "entry id")
        for category in library["categories"]:
            for entry in category["entries"]:
                if entry["id"] == wanted:
                    return category, entry
        raise EntryNotFoundError("entry not found")

    def _locate(self, entry_id: Any) -> tuple[str, dict[str, Any]]:
        library = self.ensure_library()
        if library.get("version") == V1_VERSION:
            wanted = _uuid_text(entry_id, "entry id")
            for category in CATEGORIES:
                for entry in library["categories"][category]:
                    if entry["id"] == wanted:
                        return category, entry
            raise EntryNotFoundError("entry not found")
        category, entry = self._find_entry(library, entry_id)
        return category["id"], entry

    def get_entry(self, entry_id: Any) -> dict[str, Any]:
        _, entry = self._locate(entry_id)
        return copy.deepcopy(entry)

    def get_entry_with_category(self, entry_id: Any) -> tuple[str, dict[str, Any]]:
        category, entry = self._locate(entry_id)
        return category, copy.deepcopy(entry)

    def resolve(self, category: str, name: Any) -> dict[str, Any] | None:
        if not isinstance(name, str) or name == NONE_SELECTION:
            return None
        library = self.ensure_library()
        if library.get("version") == V1_VERSION:
            if category not in CATEGORIES:
                return None
            for entry in library["categories"][category]:
                if entry["name"].casefold() == name.casefold():
                    return copy.deepcopy(entry)
            return None
        try:
            current = self._find_category(library, category)
        except CategoryNotFoundError:
            return None
        for entry in current["entries"]:
            if entry["name"].casefold() == name.casefold():
                return copy.deepcopy(entry)
        return None

    def options(self, category: str) -> list[str]:
        library = self.ensure_library()
        if library.get("version") == V1_VERSION:
            if category not in CATEGORIES:
                raise ValidationError("unknown category")
            return [NONE_SELECTION] + [entry["name"] for entry in library["categories"][category]]
        current = self._find_category(library, category)
        return [NONE_SELECTION] + [entry["name"] for entry in current["entries"]]

    def create_category(self, name: str) -> dict[str, Any]:
        with _WRITE_LOCK:
            library = self._v2()
            name = _trim_text(name, "category name", MAX_CATEGORY_NAME_LENGTH)
            if any(item["name"].casefold() == name.casefold() for item in library["categories"]):
                raise DuplicateNameError("duplicate category name")
            category = {"id": str(uuid.uuid4()), "key": None, "name": name, "protected": False, "folders": [], "entries": []}
            library["categories"].append(category)
            self._save(library)
            return copy.deepcopy(category)

    def update_category(self, category: Any, *, name: str) -> dict[str, Any]:
        with _WRITE_LOCK:
            library = self._v2()
            current = self._find_category(library, category)
            name = _trim_text(name, "category name", MAX_CATEGORY_NAME_LENGTH)
            if any(item["id"] != current["id"] and item["name"].casefold() == name.casefold() for item in library["categories"]):
                raise DuplicateNameError("duplicate category name")
            current["name"] = name
            self._save(library)
            return copy.deepcopy(current)

    def reorder_categories(self, order: Iterable[Any]) -> list[dict[str, Any]]:
        with _WRITE_LOCK:
            library = self._v2()
            if not isinstance(order, list):
                raise ValidationError("category order must be a list")
            normalized = [_category_id(value) for value in order]
            actual = [category["id"] for category in library["categories"]]
            if len(normalized) != len(set(normalized)) or set(normalized) != set(actual):
                raise ValidationError("category order must contain every category exactly once")
            by_id = {category["id"]: category for category in library["categories"]}
            library["categories"] = [by_id[item] for item in normalized]
            self._save(library)
            return copy.deepcopy(library["categories"])

    def delete_category(self, category: Any, *, move_to_category_id: Any = None, delete_entries: bool = False) -> dict[str, Any]:
        with _WRITE_LOCK:
            library = self._v2()
            current = self._find_category(library, category)
            if current["protected"]:
                raise ValidationError("protected category cannot be deleted")
            if current["entries"] and move_to_category_id is None and not delete_entries:
                raise ValidationError("choose a destination category or confirm deletion")
            target = None if move_to_category_id is None else self._find_category(library, move_to_category_id)
            if target is current:
                raise ValidationError("destination category must differ")
            if target is not None:
                target_names = {entry["name"].casefold() for entry in target["entries"]}
                for entry in current["entries"]:
                    if entry["name"].casefold() in target_names:
                        raise DuplicateNameError("destination contains a duplicate entry name")
                for entry in current["entries"]:
                    # Folder IDs are scoped to their old category.
                    entry["folder_id"] = None
                target["entries"].extend(current["entries"])
            deleted_entry_ids = [] if target is not None else [entry["id"] for entry in current["entries"]]
            library["categories"] = [item for item in library["categories"] if item["id"] != current["id"]]
            self._save(library)
            for entry_id in deleted_entry_ids:
                self.image_store.remove_entry(entry_id)
            return copy.deepcopy(current)

    def create_folder(self, category: Any, name: str) -> dict[str, str]:
        with _WRITE_LOCK:
            library = self._v2()
            current = self._find_category(library, category)
            name = _trim_text(name, "folder name", MAX_CATEGORY_NAME_LENGTH)
            if any(folder["name"].casefold() == name.casefold() for folder in current["folders"]):
                raise DuplicateNameError("duplicate folder name")
            folder = {"id": str(uuid.uuid4()), "name": name}
            current["folders"].append(folder)
            self._save(library)
            return copy.deepcopy(folder)

    def update_folder(self, category: Any, folder_id: Any, *, name: str) -> dict[str, str]:
        with _WRITE_LOCK:
            library = self._v2()
            current = self._find_category(library, category)
            folder_wanted = _uuid_text(folder_id, "folder id")
            folder = next((item for item in current["folders"] if item["id"] == folder_wanted), None)
            if folder is None:
                raise FolderNotFoundError("folder not found")
            name = _trim_text(name, "folder name", MAX_CATEGORY_NAME_LENGTH)
            if any(item["id"] != folder_wanted and item["name"].casefold() == name.casefold() for item in current["folders"]):
                raise DuplicateNameError("duplicate folder name")
            folder["name"] = name
            self._save(library)
            return copy.deepcopy(folder)

    def delete_folder(self, category: Any, folder_id: Any) -> dict[str, str]:
        with _WRITE_LOCK:
            library = self._v2()
            current = self._find_category(library, category)
            folder_wanted = _uuid_text(folder_id, "folder id")
            folder = next((item for item in current["folders"] if item["id"] == folder_wanted), None)
            if folder is None:
                raise FolderNotFoundError("folder not found")
            for entry in current["entries"]:
                if entry.get("folder_id") == folder_wanted:
                    entry["folder_id"] = None
            current["folders"] = [item for item in current["folders"] if item["id"] != folder_wanted]
            self._save(library)
            return copy.deepcopy(folder)

    def create_entry(self, category: str, name: str, prompt: str, *, tags: Any = None, loras: Any = None, favorite: bool = False, folder_id: Any = None, entry_id: Any = None) -> dict[str, Any]:
        with _WRITE_LOCK:
            library = self.ensure_library()
            if library.get("version") == V1_VERSION:
                if category not in CATEGORIES:
                    raise ValidationError("unknown category")
                name = _trim_text(name, "entry name", MAX_NAME_LENGTH)
                prompt = _trim_text(prompt, "entry prompt", MAX_PROMPT_LENGTH)
                if any(entry["name"].casefold() == name.casefold() for entry in library["categories"][category]):
                    raise DuplicateNameError("duplicate entry name")
                entry = {"id": str(uuid.uuid4()), "name": name, "prompt": prompt, "image": None}
                library["categories"][category].append(entry)
                self._save(library)
                return copy.deepcopy(entry)
            current = self._find_category(library, category)
            name = _trim_text(name, "entry name", MAX_NAME_LENGTH)
            prompt = _trim_text(prompt, "entry prompt", MAX_PROMPT_LENGTH)
            if any(entry["name"].casefold() == name.casefold() for entry in current["entries"]):
                raise DuplicateNameError("duplicate entry name")
            entry_id = _uuid_text(entry_id, "entry id") if entry_id is not None else str(uuid.uuid4())
            if any(entry_id == entry["id"] for cat in library["categories"] for entry in cat["entries"]):
                raise ValidationError("duplicate entry id")
            folder_id = None if folder_id is None else _uuid_text(folder_id, "folder id")
            if folder_id is not None and folder_id not in {folder["id"] for folder in current["folders"]}:
                raise ValidationError("entry folder is not in its category")
            if not isinstance(favorite, bool):
                raise ValidationError("favorite must be boolean")
            entry = {"id": entry_id, "name": name, "prompt": prompt, "tags": _normalize_tags(tags), "loras": _normalize_loras(loras), "favorite": favorite, "folder_id": folder_id, "images": [], "primary_image_id": None}
            current["entries"].append(entry)
            self._save(library)
            return copy.deepcopy(entry)

    def update_entry(self, entry_id: Any, *, name: str | None = None, prompt: str | None = None, category: str | None = None, tags: Any = None, loras: Any = _UNSET, favorite: bool | None = None, folder_id: Any = _UNSET, **kwargs: Any) -> dict[str, Any]:
        with _WRITE_LOCK:
            if category is None and "category_id" in kwargs:
                category = kwargs["category_id"]
            library = self.ensure_library()
            if library.get("version") == V1_VERSION:
                current_category, current = self._locate(entry_id)
                target_category = current_category if category is None else category
                if target_category not in CATEGORIES:
                    raise ValidationError("unknown category")
                target = next(item for item in library["categories"][current_category] if item["id"] == current["id"])
                next_name = target["name"] if name is None else _trim_text(name, "entry name", MAX_NAME_LENGTH)
                next_prompt = target["prompt"] if prompt is None else _trim_text(prompt, "entry prompt", MAX_PROMPT_LENGTH)
                if any(item["id"] != target["id"] and item["name"].casefold() == next_name.casefold() for item in library["categories"][target_category]):
                    raise DuplicateNameError("duplicate entry name")
                if target_category != current_category:
                    library["categories"][current_category].remove(target)
                    library["categories"][target_category].append(target)
                target["name"], target["prompt"] = next_name, next_prompt
                self._save(library)
                return copy.deepcopy(target)
            current_category, entry = self._find_entry(library, entry_id)
            target_category = current_category if category is None else self._find_category(library, category)
            next_name = entry["name"] if name is None else _trim_text(name, "entry name", MAX_NAME_LENGTH)
            next_prompt = entry["prompt"] if prompt is None else _trim_text(prompt, "entry prompt", MAX_PROMPT_LENGTH)
            if any(item["id"] != entry["id"] and item["name"].casefold() == next_name.casefold() for item in target_category["entries"]):
                raise DuplicateNameError("duplicate entry name")
            if favorite is not None and not isinstance(favorite, bool):
                raise ValidationError("favorite must be boolean")
            if tags is not None:
                entry["tags"] = _normalize_tags(tags)
            if loras is not _UNSET:
                entry["loras"] = _normalize_loras(loras)
            if favorite is not None:
                entry["favorite"] = favorite
            if folder_id is not _UNSET and folder_id is not None:
                folder_id = _uuid_text(folder_id, "folder id")
                if folder_id not in {folder["id"] for folder in target_category["folders"]}:
                    raise ValidationError("entry folder is not in its category")
            elif folder_id is not _UNSET and folder_id is None:
                folder_id = None
            elif category is not None and target_category is not current_category:
                folder_id = None
            else:
                folder_id = entry.get("folder_id")
            if target_category is not current_category:
                current_category["entries"].remove(entry)
                target_category["entries"].append(entry)
            entry.update({"name": next_name, "prompt": next_prompt, "folder_id": folder_id})
            self._save(library)
            return copy.deepcopy(entry)

    def update_image(self, entry_id: Any, image: dict[str, str] | None) -> dict[str, Any]:
        """v1 image metadata operation retained for old routes."""
        with _WRITE_LOCK:
            library = self.ensure_library()
            if library.get("version") != V1_VERSION:
                raise ValidationError("use gallery image operations for v2")
            category, current = self._locate(entry_id)
            normalized = None
            if image is not None:
                try:
                    self.image_store.validate_metadata(current["id"], image)
                    if not self.image_store.exists(current["id"], image):
                        raise ValidationError("preview image not found")
                except ValueError as exc:
                    raise ValidationError("image metadata is invalid") from exc
                normalized = {"filename": image["filename"], "media_type": image["media_type"]}
            target = next(item for item in library["categories"][category] if item["id"] == current["id"])
            target["image"] = normalized
            self._save(library)
            return copy.deepcopy(target)

    def _gallery_entry(self, entry_id: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        library = self._v2()
        return self._find_entry(library, entry_id)

    def upload_image(self, entry_id: Any, data: bytes, *, kind: str = "preview", caption: str = "") -> dict[str, Any]:
        return self.upload_images(entry_id, [(data, caption)], kind=kind)[0]

    def upload_images(self, entry_id: Any, files: Iterable[Any], *, kind: str = "preview") -> list[dict[str, Any]]:
        if kind not in ("preview", "generated"):
            raise ValidationError("image kind is invalid")
        with _WRITE_LOCK:
            library = self._v2()
            _, entry = self._find_entry(library, entry_id)
            files = list(files)
            if len(entry["images"]) + len(files) > MAX_IMAGES_PER_ENTRY:
                raise ValidationError("entry image count exceeds 20")
            prepared: list[tuple[bytes, str]] = []
            for item in files:
                if isinstance(item, tuple):
                    data, caption = item[0], item[1] if len(item) > 1 else ""
                else:
                    data, caption = item, ""
                if not isinstance(data, (bytes, bytearray, memoryview)):
                    raise ValidationError("image data must be bytes")
                self.image_store.detect_signature(bytes(data))
                prepared.append((bytes(data), _trim_text(caption, "image caption", 240, allow_empty=True)))
            created: list[dict[str, Any]] = []
            try:
                for data, caption in prepared:
                    image_id = str(uuid.uuid4())
                    metadata = self.image_store.save_image(entry["id"], image_id, data)
                    metadata.update({"kind": kind, "caption": caption})
                    created.append(metadata)
                entry["images"].extend(created)
                self._save(library)
            except Exception:
                for metadata in created:
                    self.image_store.remove_image(entry["id"], metadata["id"], metadata)
                raise
            return copy.deepcopy(created)

    def replace_images(self, entry_id: Any, images: list[dict[str, Any]], primary_image_id: Any = None) -> dict[str, Any]:
        with _WRITE_LOCK:
            library = self._v2()
            _, entry = self._find_entry(library, entry_id)
            if not isinstance(images, list) or len(images) > MAX_IMAGES_PER_ENTRY:
                raise ValidationError("image list is invalid")
            known = {image["id"]: image for image in entry["images"]}
            ordered: list[dict[str, Any]] = []
            for raw in images:
                if not isinstance(raw, dict):
                    raise ValidationError("image metadata is invalid")
                image_id = _uuid_text(raw.get("id"), "image id")
                if image_id not in known or image_id in {image["id"] for image in ordered}:
                    raise ValidationError("image order contains an unknown or duplicate image")
                image = copy.deepcopy(known[image_id])
                if "caption" in raw:
                    image["caption"] = _trim_text(raw["caption"], "image caption", 240, allow_empty=True)
                ordered.append(image)
            if len(ordered) != len(known):
                raise ValidationError("image order must contain every image")
            primary = None if primary_image_id is None else _uuid_text(primary_image_id, "primary image id")
            if primary is not None and not any(image["id"] == primary and image["kind"] == "preview" for image in ordered):
                raise ValidationError("primary image must be a preview")
            entry["images"] = ordered
            entry["primary_image_id"] = primary
            self._save(library)
            return copy.deepcopy(entry)

    def delete_image(self, entry_id: Any, image_id: Any) -> dict[str, Any]:
        with _WRITE_LOCK:
            library = self._v2()
            _, entry = self._find_entry(library, entry_id)
            image_id = _uuid_text(image_id, "image id")
            image = next((item for item in entry["images"] if item["id"] == image_id), None)
            if image is None:
                raise ImageNotFoundError("image not found")
            entry["images"] = [item for item in entry["images"] if item["id"] != image_id]
            if entry.get("primary_image_id") == image_id:
                entry["primary_image_id"] = None
            self._save(library)
            self.image_store.remove_image(entry["id"], image_id, image)
            return copy.deepcopy(entry)

    def get_image(self, entry_id: Any, image_id: Any) -> tuple[dict[str, Any], Path]:
        _, entry = self._gallery_entry(entry_id)
        image_id = _uuid_text(image_id, "image id")
        image = next((item for item in entry["images"] if item["id"] == image_id), None)
        if image is None:
            raise ImageNotFoundError("image not found")
        return copy.deepcopy(image), self.image_store.resolve_path(entry["id"], image)

    def delete_entry(self, entry_id: Any) -> dict[str, Any]:
        with _WRITE_LOCK:
            library = self.ensure_library()
            if library.get("version") == V1_VERSION:
                category, entry = self._locate(entry_id)
                library["categories"][category] = [item for item in library["categories"][category] if item["id"] != entry["id"]]
                self._save(library)
                if entry.get("image") is not None:
                    self.image_store.remove(entry["id"], entry["image"])
                return copy.deepcopy(entry)
            category, entry = self._find_entry(library, entry_id)
            category["entries"].remove(entry)
            self._save(library)
            self.image_store.remove_entry(entry["id"])
            return copy.deepcopy(entry)

    def replace_library(self, document: Any) -> dict[str, Any]:
        with _WRITE_LOCK:
            if isinstance(document, dict) and document.get("version") == V1_VERSION and self._legacy_seed_mode:
                normalized_v1 = _validate_v1(document, image_store=self.image_store, clear_missing_images=True)
                self._write_json_locked(normalized_v1)
                return copy.deepcopy(normalized_v1)
            normalized = validate_library(document, image_store=self.image_store, clear_missing_images=True)
            self._write_json_locked(normalized)
            return copy.deepcopy(normalized)

    def apply_seed_pack(self, seed: Any = None, manifest: Any = None) -> dict[str, Any]:
        with _WRITE_LOCK:
            library = self._v2()
            if seed is None:
                seed_doc = self._seed_v2()
            elif isinstance(seed, (str, os.PathLike)):
                seed_doc = validate_library(self._raw_file(Path(seed)), image_store=self.image_store, clear_missing_images=False)
            else:
                seed_doc = validate_library(seed, image_store=self.image_store, clear_missing_images=False)
            if manifest is not None:
                raw_manifest = self._raw_file(Path(manifest)) if isinstance(manifest, (str, os.PathLike)) else manifest
                if isinstance(raw_manifest, dict) and isinstance(raw_manifest.get("id", raw_manifest.get("pack_id")), str):
                    self.seed_manifest_path = Path(manifest) if isinstance(manifest, (str, os.PathLike)) else self.seed_manifest_path
            merged = self._merge_seed(library, seed_doc)
            self._save(merged)
            return copy.deepcopy(merged)

    def apply_import_records(self, records: Iterable[dict[str, Any]], *, conflict_policy: str = "skip", category_mapping: dict[str, Any] | None = None) -> dict[str, Any]:
        aliases = {"rename_imported": "rename", "replace_matching_name": "replace", "Rename imported": "rename", "Replace matching name": "replace", "Skip": "skip"}
        conflict_policy = aliases.get(conflict_policy, conflict_policy)
        if conflict_policy not in ("skip", "rename", "replace"):
            raise ValidationError("unsupported conflict policy")
        category_mapping = category_mapping or {}
        stats = {"imported": 0, "skipped": 0, "renamed": 0, "replaced": 0, "omitted_negative": 0, "warnings": []}
        for record in records:
            if not isinstance(record, dict):
                raise ValidationError("import record is invalid")
            source_category = record.get("category") or record.get("source_category") or "style"
            source_group = record.get("group_id") or source_category
            target_category = category_mapping.get(source_group, category_mapping.get(source_category, source_category))
            if isinstance(target_category, str) and target_category.casefold() in CATEGORIES:
                target_category = target_category.casefold()
            if target_category not in CATEGORIES:
                try:
                    target_category = _category_id(target_category)
                except ValidationError as exc:
                    raise CategoryNotFoundError("import category not found") from exc
            name = _trim_text(record.get("name"), "entry name", MAX_NAME_LENGTH)
            prompt = _trim_text(record.get("prompt"), "entry prompt", MAX_PROMPT_LENGTH)
            if record.get("negative_prompt"):
                stats["omitted_negative"] += 1
            current = self._find_category(self._v2(), target_category)
            existing = next((entry for entry in current["entries"] if entry["name"].casefold() == name.casefold()), None)
            if existing is not None and conflict_policy == "skip":
                stats["skipped"] += 1
                continue
            if existing is not None and conflict_policy == "replace":
                self.update_entry(existing["id"], prompt=prompt, tags=record.get("tags", []), favorite=bool(record.get("favorite", False)))
                stats["replaced"] += 1
                continue
            if existing is not None:
                suffix = 2
                base = name
                while any(entry["name"].casefold() == f"{base} ({suffix})".casefold() for entry in current["entries"]):
                    suffix += 1
                name = f"{base} ({suffix})"
                stats["renamed"] += 1
            folder_id = None
            folder_name = record.get("folder")
            if folder_name:
                current = self._find_category(self._v2(), target_category)
                existing_folder = next((folder for folder in current["folders"] if folder["name"].casefold() == str(folder_name).strip().casefold()), None)
                folder_id = existing_folder["id"] if existing_folder is not None else self.create_folder(target_category, str(folder_name).strip())["id"]
            self.create_entry(target_category, name, prompt, tags=record.get("tags", []), favorite=bool(record.get("favorite", False)), folder_id=folder_id)
            stats["imported"] += 1
        return stats

    # Stable descriptive aliases for embedders that prefer CRUD verbs.
    create_custom_category = create_category
    rename_category = update_category
    add_images = upload_images
    update_images = replace_images
    remove_gallery_image = delete_image


def _user_directory() -> Path:
    if folder_paths is None:
        return Path.home() / "ComfyUI" / "user"
    return Path(folder_paths.get_user_directory())


def create_default_store() -> LibraryStore:
    return LibraryStore()


__all__ = [
    "CATEGORIES", "CORE_CATEGORY_IDS", "NONE_SELECTION", "VERSION", "MAX_NAME_LENGTH", "MAX_PROMPT_LENGTH",
    "LibraryError", "ValidationError", "DuplicateNameError", "EntryNotFoundError", "CategoryNotFoundError",
    "FolderNotFoundError", "ImageNotFoundError", "CorruptLibraryError", "LibraryStore", "empty_library",
    "validate_library", "create_default_store",
]
