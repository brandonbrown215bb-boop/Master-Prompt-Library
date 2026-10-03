"""Thin aiohttp adapters for the prompt-library store."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import ntpath
import tempfile
from urllib.parse import unquote
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import web

try:
    from .image_extractor import (
        clean_positive_prompt,
        extract_prompt_from_metadata,
        list_vision_models,
        parse_prompt_sections,
        parse_structured_vision_response,
        query_vision_api,
        suggest_entry_name,
        structured_vision_to_sections,
    )
    from .image_store import MAX_IMAGE_SIZE, ImageStore
    from .importers import MAX_IMPORT_FILE_SIZE, MAX_IMPORT_TOTAL_SIZE, ImporterError, discover_installed_sources, parse_source, parse_staged_files, summarize_records
    from .library_store import (
        CATEGORIES,
        CategoryNotFoundError,
        CorruptLibraryError,
        DuplicateNameError,
        EntryNotFoundError,
        FolderNotFoundError,
        ImageNotFoundError,
        LibraryError,
        LibraryStore,
        ValidationError,
        create_default_store,
    )
except ImportError:  # direct source import for hermetic tests
    from image_extractor import (
        clean_positive_prompt,
        extract_prompt_from_metadata,
        list_vision_models,
        parse_prompt_sections,
        parse_structured_vision_response,
        query_vision_api,
        suggest_entry_name,
        structured_vision_to_sections,
    )
    from image_store import MAX_IMAGE_SIZE, ImageStore
    from importers import MAX_IMPORT_FILE_SIZE, MAX_IMPORT_TOTAL_SIZE, ImporterError, discover_installed_sources, parse_source, parse_staged_files, summarize_records
    from library_store import (
        CATEGORIES,
        CategoryNotFoundError,
        CorruptLibraryError,
        DuplicateNameError,
        EntryNotFoundError,
        FolderNotFoundError,
        ImageNotFoundError,
        LibraryError,
        ValidationError,
        create_default_store,
    )


BASE_PATH = "/master_prompt_library/v1"
BASE_PATH_V2 = "/master_prompt_library/v2"
_REGISTERED_ROUTE_TABLES: set[int] = set()


class UnsupportedMediaError(ValueError):
    pass


class PayloadTooLargeError(ValueError):
    pass


def _parse_force_vision(value: Any, *, multipart: bool) -> bool:
    """Parse the explicit vision-extraction intent without truthiness traps."""

    if value is None:
        return False
    if multipart:
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            return value.strip().lower() == "true"
    elif isinstance(value, bool):
        return value
    raise ValidationError("force_vision must be a boolean (or multipart 'true'/'false')")


def _decode_image_base64(value: Any) -> bytes:
    """Decode a JSON image payload with strict validation and size limits."""

    if not isinstance(value, str) or not value:
        raise ValidationError("image_base64 must be a non-empty base64 string")

    encoded = value
    if "," in encoded:
        prefix, encoded = encoded.split(",", 1)
        if not prefix.lower().startswith("data:"):
            raise ValidationError("image_base64 must be valid base64 or a data URL")
    if not encoded:
        raise ValidationError("image_base64 must be a non-empty base64 string")

    # Reject an over-limit payload before decoding it into memory. The upper
    # bound is the canonical base64 size for MAX_IMAGE_SIZE bytes.
    max_encoded_size = ((MAX_IMAGE_SIZE + 2) // 3) * 4
    if len(encoded) > max_encoded_size:
        raise PayloadTooLargeError("image exceeds the 8 MiB limit")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("image_base64 must be valid base64") from exc
    if not image_bytes:
        raise ValidationError("image_base64 must decode to image data")
    if len(image_bytes) > MAX_IMAGE_SIZE:
        raise PayloadTooLargeError("image exceeds the 8 MiB limit")
    return image_bytes


def _json_error(message: str, status: int) -> web.Response:
    return web.json_response({"error": message}, status=status)


def _error_response(exc: Exception) -> web.Response:
    if isinstance(exc, web.HTTPRequestEntityTooLarge):
        return _json_error("request body exceeds the 8 MiB image limit", 413)
    if isinstance(exc, DuplicateNameError):
        return _json_error(str(exc) or "duplicate name", 409)
    if isinstance(exc, (EntryNotFoundError, CategoryNotFoundError, FolderNotFoundError, ImageNotFoundError, FileNotFoundError)):
        return _json_error(str(exc) or "not found", 404)
    if isinstance(exc, PayloadTooLargeError):
        return _json_error(str(exc) or "upload is too large", 413)
    if isinstance(exc, UnsupportedMediaError):
        return _json_error(str(exc) or "unsupported media type", 415)
    if isinstance(exc, ValueError) and "only JPEG" in str(exc):
        return _json_error(str(exc), 415)
    if isinstance(exc, ValueError) and "exceeds" in str(exc):
        return _json_error(str(exc), 413)
    if isinstance(exc, (ValidationError, ImporterError, ValueError)):
        return _json_error(str(exc) or "invalid request", 400)
    if isinstance(exc, CorruptLibraryError):
        return _json_error("prompt library is unavailable", 500)
    if isinstance(exc, LibraryError):
        return _json_error(str(exc) or "prompt library request failed", 500)
    return _json_error("prompt library request failed", 500)


def _available_lora_names() -> list[str]:
    """Return ComfyUI's configured LoRA paths without making it a test dependency."""

    try:
        import folder_paths  # type: ignore

        values = folder_paths.get_filename_list("loras")
    except (ImportError, AttributeError, KeyError, OSError, RuntimeError, TypeError):
        return []
    return sorted({value for value in values if isinstance(value, str) and value.strip()}, key=str.casefold)


async def _request_json(request: web.Request) -> Any:
    try:
        return await request.json()
    except (ValueError, TypeError) as exc:
        raise ValidationError("request body must be JSON") from exc


async def _read_upload(request: web.Request) -> bytes:
    if request.content_type == "multipart/form-data":
        reader = await request.multipart()
        while True:
            part = await reader.next()
            if part is None:
                break
            if not getattr(part, "filename", None) and getattr(part, "name", "") != "image":
                continue
            if hasattr(part, "read_chunk"):
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = await part.read_chunk(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_IMAGE_SIZE:
                        raise PayloadTooLargeError("image exceeds the 8 MiB limit")
                    chunks.append(chunk)
                return b"".join(chunks)
            data = await part.read()
            if len(data) > MAX_IMAGE_SIZE:
                raise PayloadTooLargeError("image exceeds the 8 MiB limit")
            return data
        raise ValidationError("multipart request has no image")
    data = await request.read()
    if len(data) > MAX_IMAGE_SIZE:
        raise PayloadTooLargeError("image exceeds the 8 MiB limit")
    return data


def _entry_id(request: web.Request) -> str:
    return request.match_info.get("entry_id", "")


def _category_id(request: web.Request) -> str:
    return request.match_info.get("category_id", "")


def _folder_id(request: web.Request) -> str:
    return request.match_info.get("folder_id", "")


def _image_id(request: web.Request) -> str:
    return request.match_info.get("image_id", "")


def build_handlers(store: LibraryStore, image_store: ImageStore | None = None) -> dict[str, Callable[[web.Request], Awaitable[web.StreamResponse]]]:
    """Build both v1 and v2 handlers without registering them."""

    image_store = image_store or store.image_store

    async def get_library(request: web.Request) -> web.Response:
        try:
            return web.json_response(store.get_v1_library() if hasattr(store, "get_v1_library") else store.get_library())
        except Exception as exc:
            return _error_response(exc)

    async def create_entry(request: web.Request) -> web.Response:
        try:
            payload = await _request_json(request)
            if not isinstance(payload, dict):
                raise ValidationError("request body must be an object")
            entry = store.create_entry(payload.get("category"), payload.get("name"), payload.get("prompt"))
            if store.get_library().get("version") == 2 and hasattr(store, "get_v1_entry"):
                entry = store.get_v1_entry(entry["id"])
            return web.json_response(entry, status=201)
        except Exception as exc:
            return _error_response(exc)

    async def update_entry(request: web.Request) -> web.Response:
        try:
            payload = await _request_json(request)
            if not isinstance(payload, dict):
                raise ValidationError("request body must be an object")
            allowed = {key: payload[key] for key in ("name", "prompt", "category") if key in payload}
            entry = store.update_entry(_entry_id(request), **allowed)
            if store.get_library().get("version") == 2 and hasattr(store, "get_v1_entry"):
                entry = store.get_v1_entry(entry["id"])
            return web.json_response(entry)
        except Exception as exc:
            return _error_response(exc)

    async def delete_entry(request: web.Request) -> web.Response:
        try:
            entry = store.delete_entry(_entry_id(request))
            if store.get_library().get("version") == 2 and hasattr(store, "get_v1_entry"):
                entry = {"id": entry["id"], "name": entry["name"], "prompt": entry["prompt"], "image": None}
            return web.json_response(entry)
        except Exception as exc:
            return _error_response(exc)

    async def replace_library(request: web.Request) -> web.Response:
        try:
            document = await _request_json(request)
            library = store.replace_v1_library(document) if store.get_library().get("version") == 2 else store.replace_library(document)
            return web.json_response(library)
        except Exception as exc:
            return _error_response(exc)

    async def get_image(request: web.Request) -> web.StreamResponse:
        try:
            entry = store.get_entry(_entry_id(request))
            if store.get_library().get("version") == 2:
                metadata = next((image for image in entry["images"] if image["id"] == entry.get("primary_image_id")), None)
            else:
                metadata = entry.get("image")
            if metadata is None:
                raise FileNotFoundError("preview image not found")
            path = image_store.resolve_path(entry["id"], metadata)
            return web.FileResponse(path, headers={"Content-Type": metadata["media_type"]})
        except Exception as exc:
            return _error_response(exc)

    async def upload_image(request: web.Request) -> web.Response:
        entry_id = _entry_id(request)
        try:
            entry = store.get_entry(entry_id)
            v2 = store.get_library().get("version") == 2
            prior_metadata = next((image for image in entry.get("images", []) if image["id"] == entry.get("primary_image_id")), None) if v2 else entry.get("image")
            prior_bytes: bytes | None = None
            if prior_metadata is not None:
                try:
                    prior_bytes, _ = image_store.read(entry["id"], prior_metadata)
                except FileNotFoundError:
                    prior_metadata = None
            data = await _read_upload(request)
            try:
                if v2:
                    metadata = store.upload_image(entry["id"], data, kind="preview")
                    updated = store.replace_images(entry["id"], store.get_entry(entry["id"])["images"], metadata["id"])
                    if prior_metadata is not None and prior_metadata.get("id") != metadata.get("id"):
                        store.delete_image(entry["id"], prior_metadata["id"])
                    updated = store.get_v1_entry(entry["id"])
                else:
                    metadata = image_store.save(entry["id"], data)
                    updated = store.update_image(entry["id"], metadata)
            except Exception:
                if not v2:
                    image_store.remove(entry["id"], metadata)
                if prior_metadata is not None and prior_bytes is not None:
                    image_store.restore(entry["id"], prior_metadata, prior_bytes)
                raise
            return web.json_response(updated)
        except Exception as exc:
            return _error_response(exc)

    async def remove_image(request: web.Request) -> web.Response:
        try:
            entry = store.get_entry(_entry_id(request))
            v2 = store.get_library().get("version") == 2
            metadata = next((image for image in entry.get("images", []) if image["id"] == entry.get("primary_image_id")), None) if v2 else entry.get("image")
            if metadata is None:
                raise FileNotFoundError("preview image not found")
            if v2:
                updated = store.delete_image(entry["id"], metadata["id"])
                updated = store.get_v1_entry(entry["id"])
            else:
                updated = store.update_image(entry["id"], None)
                image_store.remove(entry["id"], metadata)
            return web.json_response(updated)
        except Exception as exc:
            return _error_response(exc)

    async def get_library_v2(request: web.Request) -> web.Response:
        try:
            return web.json_response(store.get_library_with_fingerprint())
        except Exception as exc:
            return _error_response(exc)

    async def replace_library_v2(request: web.Request) -> web.Response:
        try:
            payload = await _request_json(request)
            if isinstance(payload, dict) and isinstance(payload.get("library"), dict):
                payload = payload["library"]
            return web.json_response(store.replace_library(payload))
        except Exception as exc:
            return _error_response(exc)

    async def create_category(request: web.Request) -> web.Response:
        try:
            payload = await _request_json(request)
            return web.json_response(store.create_category(payload.get("name") if isinstance(payload, dict) else payload), status=201)
        except Exception as exc:
            return _error_response(exc)

    async def update_category(request: web.Request) -> web.Response:
        try:
            payload = await _request_json(request)
            if not isinstance(payload, dict):
                raise ValidationError("request body must be an object")
            return web.json_response(store.update_category(_category_id(request), name=payload.get("name")))
        except Exception as exc:
            return _error_response(exc)

    async def reorder_categories(request: web.Request) -> web.Response:
        try:
            payload = await _request_json(request)
            order = payload.get("order", payload.get("category_ids")) if isinstance(payload, dict) else payload
            return web.json_response({"categories": store.reorder_categories(order)})
        except Exception as exc:
            return _error_response(exc)

    async def delete_category(request: web.Request) -> web.Response:
        try:
            payload = await _request_json(request) if request.can_read_body and request.content_length not in (None, 0) else {}
            payload = payload if isinstance(payload, dict) else {}
            result = store.delete_category(_category_id(request), move_to_category_id=payload.get("move_to_category_id"), delete_entries=bool(payload.get("delete_entries", False)))
            return web.json_response(result)
        except Exception as exc:
            return _error_response(exc)

    async def create_folder(request: web.Request) -> web.Response:
        try:
            payload = await _request_json(request)
            if not isinstance(payload, dict):
                raise ValidationError("request body must be an object")
            return web.json_response(store.create_folder(_category_id(request), payload.get("name")), status=201)
        except Exception as exc:
            return _error_response(exc)

    async def update_folder(request: web.Request) -> web.Response:
        try:
            payload = await _request_json(request)
            if not isinstance(payload, dict):
                raise ValidationError("request body must be an object")
            return web.json_response(store.update_folder(_category_id(request), _folder_id(request), name=payload.get("name")))
        except Exception as exc:
            return _error_response(exc)

    async def delete_folder(request: web.Request) -> web.Response:
        try:
            return web.json_response(store.delete_folder(_category_id(request), _folder_id(request)))
        except Exception as exc:
            return _error_response(exc)

    async def create_entry_v2(request: web.Request) -> web.Response:
        try:
            payload = await _request_json(request)
            if not isinstance(payload, dict):
                raise ValidationError("request body must be an object")
            entry = store.create_entry(payload.get("category_id", payload.get("category")), payload.get("name"), payload.get("prompt"), tags=payload.get("tags"), loras=payload.get("loras"), favorite=payload.get("favorite", False), folder_id=payload.get("folder_id"), entry_id=payload.get("id"))
            return web.json_response(entry, status=201)
        except Exception as exc:
            return _error_response(exc)

    async def update_entry_v2(request: web.Request) -> web.Response:
        try:
            payload = await _request_json(request)
            if not isinstance(payload, dict):
                raise ValidationError("request body must be an object")
            allowed = {key: payload[key] for key in ("name", "prompt", "category_id", "category", "tags", "loras", "favorite", "folder_id") if key in payload}
            if "category_id" in allowed and "category" not in allowed:
                allowed["category"] = allowed.pop("category_id")
            return web.json_response(store.update_entry(_entry_id(request), **allowed))
        except Exception as exc:
            return _error_response(exc)

    async def delete_entry_v2(request: web.Request) -> web.Response:
        try:
            return web.json_response(store.delete_entry(_entry_id(request)))
        except Exception as exc:
            return _error_response(exc)

    async def list_loras_v2(request: web.Request) -> web.Response:
        return web.json_response({"loras": _available_lora_names()})

    async def get_image_v2(request: web.Request) -> web.StreamResponse:
        try:
            metadata, path = store.get_image(_entry_id(request), _image_id(request))
            return web.FileResponse(path, headers={"Content-Type": metadata["media_type"]})
        except Exception as exc:
            return _error_response(exc)

    async def upload_images_v2(request: web.Request) -> web.Response:
        uploaded: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        entry_id = _entry_id(request)
        try:
            # Resolve the entry before reading files, so an unknown ID cannot
            # produce orphaned server files.
            store.get_entry(entry_id)
            if request.content_type == "multipart/form-data":
                reader = await request.multipart()
                kind = request.query.get("kind", "preview")
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    if not getattr(part, "filename", None):
                        if getattr(part, "name", "") == "kind":
                            kind = (await part.text()).strip() or kind
                        continue
                    try:
                        chunks: list[bytes] = []
                        total = 0
                        while True:
                            chunk = await part.read_chunk(64 * 1024)
                            if not chunk:
                                break
                            total += len(chunk)
                            if total > MAX_IMAGE_SIZE:
                                raise PayloadTooLargeError("image exceeds the 8 MiB limit")
                            chunks.append(chunk)
                        uploaded.extend(store.upload_images(entry_id, [(b"".join(chunks), "")], kind=kind))
                    except Exception as exc:
                        errors.append({"filename": getattr(part, "filename", ""), "error": str(exc)})
            else:
                payload = await _request_json(request)
                if not isinstance(payload, dict):
                    raise ValidationError("request body must be an object")
                kind = payload.get("kind", "preview")
                data = payload.get("data")
                if not isinstance(data, str):
                    raise UnsupportedMediaError("image upload requires multipart data")
                # JSON image uploads are intentionally not decoded from an
                # arbitrary client path; use multipart bytes only.
                raise UnsupportedMediaError("image upload requires multipart data")
            if not uploaded and errors:
                first = errors[0]["error"]
                if "8 MiB" in first:
                    raise PayloadTooLargeError(first)
                if "only JPEG" in first:
                    raise UnsupportedMediaError(first)
                raise ValidationError(first)
            return web.json_response({"uploaded": uploaded, "errors": errors}, status=200)
        except Exception as exc:
            return _error_response(exc)

    async def replace_images_v2(request: web.Request) -> web.Response:
        try:
            payload = await _request_json(request)
            if not isinstance(payload, dict):
                raise ValidationError("request body must be an object")
            images = payload.get("images")
            primary = payload.get("primary_image_id")
            return web.json_response(store.replace_images(_entry_id(request), images, primary))
        except Exception as exc:
            return _error_response(exc)

    async def delete_image_v2(request: web.Request) -> web.Response:
        try:
            return web.json_response(store.delete_image(_entry_id(request), _image_id(request)))
        except Exception as exc:
            return _error_response(exc)

    async def import_sources(request: web.Request) -> web.Response:
        try:
            return web.json_response({"sources": discover_installed_sources()})
        except Exception as exc:
            return _error_response(exc)

    def _resolve_import_source(source_id: Any) -> Path:
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValidationError("source_id is required")
        for source in discover_installed_sources():
            if source.get("id") == source_id:
                return Path(source["path"])
        raise EntryNotFoundError("approved import source not found")

    @staticmethod
    def _safe_upload_relative_name(filename: Any) -> Path:
        if not isinstance(filename, str) or not filename.strip():
            raise ValidationError("import file name is required")
        filename = unquote(filename)
        normalized = filename.replace("\\", "/")
        if normalized.startswith("/") or ntpath.isabs(filename) or ntpath.splitdrive(filename)[0]:
            raise ValidationError("import file path must be relative")
        parts = [part for part in normalized.split("/") if part not in ("", ".")]
        if not parts or any(part == ".." for part in parts):
            raise ValidationError("import file path traversal is not allowed")
        relative = Path(*parts)
        if relative.suffix.casefold() not in (".txt", ".json", ".csv"):
            raise UnsupportedMediaError("unsupported import source type")
        return relative

    async def _import_records(request: web.Request) -> list[dict[str, Any]]:
        if request.content_type == "multipart/form-data":
            reader = await request.multipart()
            source_id: str | None = None
            total_size = 0
            staged_files = 0
            seen_paths: set[str] = set()
            with tempfile.TemporaryDirectory(prefix="master-prompt-import-") as staging:
                staging_root = Path(staging)
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    field_name = getattr(part, "name", "")
                    filename = getattr(part, "filename", None)
                    if filename is None:
                        if field_name == "source_id":
                            source_id = (await part.text()).strip()
                        continue
                    relative = _safe_upload_relative_name(filename)
                    key = str(relative).casefold()
                    if key in seen_paths:
                        raise ValidationError("duplicate import file path")
                    seen_paths.add(key)
                    chunks: list[bytes] = []
                    file_size = 0
                    while True:
                        chunk = await part.read_chunk(64 * 1024)
                        if not chunk:
                            break
                        file_size += len(chunk)
                        if file_size > MAX_IMPORT_FILE_SIZE:
                            raise PayloadTooLargeError("import file exceeds the 32 MiB limit")
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    if file_size > MAX_IMPORT_FILE_SIZE:
                        raise PayloadTooLargeError("import file exceeds the 32 MiB limit")
                    total_size += len(data)
                    if total_size > MAX_IMPORT_TOTAL_SIZE:
                        raise PayloadTooLargeError("import batch exceeds the 64 MiB limit")
                    destination = staging_root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                    staged_files += 1
                records: list[dict[str, Any]] = []
                if source_id:
                    records.extend(parse_source(_resolve_import_source(source_id)))
                if staged_files:
                    records.extend(parse_staged_files(staging_root))
                if not records and not source_id:
                    raise ValidationError("multipart request has no import source")
                return records
        if request.content_type == "application/x-www-form-urlencoded":
            form_payload = await request.post()
            source_id = form_payload.get("source_id")
            if isinstance(source_id, str):
                return parse_source(_resolve_import_source(source_id))
            raise ValidationError("source_id or records is required")
        payload = await _request_json(request)
        if not isinstance(payload, dict):
            raise ValidationError("request body must be an object")
        if "source_path" in payload or "path" in payload:
            raise ValidationError("arbitrary source paths are not accepted; use source_id")
        records = payload.get("records")
        if isinstance(records, list):
            return records
        if isinstance(payload.get("source_id"), str):
            return parse_source(_resolve_import_source(payload["source_id"]))
        raise ValidationError("source_id or records is required")

    async def preview_import_v2(request: web.Request) -> web.Response:
        try:
            records = await _import_records(request)
            existing: list[dict[str, Any]] = []
            # Preview must not initialize, migrate, or otherwise write the
            # library. Read only an already-materialized v2 document for
            # conflict counts; Apply owns all store mutation.
            if store.library_path.exists():
                try:
                    raw = json.loads(store.library_path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict) and raw.get("version") == 2:
                        existing = [entry for category in raw.get("categories", []) for entry in category.get("entries", [])]
                except (OSError, json.JSONDecodeError):
                    existing = []
            result = summarize_records(records, existing=existing)
            # The raw normalized records are returned so Apply can be an
            # explicit second action; no store write occurs here.
            return web.json_response(result)
        except Exception as exc:
            return _error_response(exc)

    async def apply_import_v2(request: web.Request) -> web.Response:
        try:
            payload: dict[str, Any] = {}
            if request.content_type == "multipart/form-data":
                records = await _import_records(request)
            else:
                payload = await _request_json(request)
                if not isinstance(payload, dict):
                    raise ValidationError("request body must be an object")
                if "source_path" in payload or "path" in payload:
                    raise ValidationError("arbitrary source paths are not accepted; use source_id")
                records = payload.get("records")
                if not isinstance(records, list):
                    if not isinstance(payload.get("source_id"), str):
                        raise ValidationError("source_id or records is required")
                    records = parse_source(_resolve_import_source(payload["source_id"]))
            policy = payload.get("conflict_policy", request.query.get("conflict_policy", "skip"))
            mapping = payload.get("mapping", payload.get("category_mapping"))
            if mapping is None:
                mapping_raw = request.query.get("category_mapping")
                mapping = json.loads(mapping_raw) if mapping_raw else None
            return web.json_response(store.apply_import_records(records, conflict_policy=policy, category_mapping=mapping))
        except Exception as exc:
            return _error_response(exc)

    async def extract_image_v2(request: web.Request) -> web.Response:
        try:
            api_endpoint = ""
            api_key = ""
            api_model = ""
            vision_prompt = ""
            filename = ""
            image_bytes: bytes | None = None
            force_vision = False

            if request.content_type == "multipart/form-data":
                reader = await request.multipart()
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    part_name = getattr(part, "name", "")
                    part_filename = getattr(part, "filename", "")
                    if part_filename or part_name == "image":
                        filename = part_filename or filename
                        chunks: list[bytes] = []
                        total = 0
                        while True:
                            chunk = await part.read_chunk(64 * 1024)
                            if not chunk:
                                break
                            total += len(chunk)
                            if total > MAX_IMAGE_SIZE:
                                raise PayloadTooLargeError("image exceeds the 8 MiB limit")
                            chunks.append(chunk)
                        image_bytes = b"".join(chunks)
                    elif part_name == "api_endpoint":
                        api_endpoint = (await part.text()).strip()
                    elif part_name == "api_key":
                        api_key = (await part.text()).strip()
                    elif part_name == "api_model":
                        api_model = (await part.text()).strip()
                    elif part_name == "vision_prompt":
                        vision_prompt = (await part.text()).strip()
                    elif part_name == "force_vision":
                        force_vision = _parse_force_vision(await part.text(), multipart=True)
                if image_bytes is None:
                    raise ValidationError("multipart request has no image")
            else:
                payload = await _request_json(request)
                if not isinstance(payload, dict):
                    raise ValidationError("request body must be an object")
                api_endpoint = str(payload.get("api_endpoint", "")).strip()
                api_key = str(payload.get("api_key", "")).strip()
                api_model = str(payload.get("api_model", "")).strip()
                vision_prompt = str(payload.get("vision_prompt", "")).strip()
                filename = str(payload.get("filename", "")).strip()
                force_vision = _parse_force_vision(payload.get("force_vision"), multipart=False)

                if "image_base64" in payload:
                    image_bytes = _decode_image_base64(payload["image_base64"])
                elif "image_path" in payload:
                    raise ValidationError("image_path is not accepted; use image_base64 or multipart image")

                if image_bytes is None:
                    raise ValidationError("image_base64 or multipart image is required")

            try:
                ImageStore.detect_signature(image_bytes)
            except ValueError as exc:
                raise UnsupportedMediaError(str(exc)) from exc

            if force_vision and not api_endpoint:
                raise ValidationError("api_endpoint is required when force_vision is true")

            extracted = ""
            source_mode = "none"
            meta_prompt = extract_prompt_from_metadata(image_bytes)
            if meta_prompt and not force_vision:
                extracted = meta_prompt
                source_mode = "metadata"
            elif api_endpoint:
                try:
                    extracted = await asyncio.to_thread(
                        query_vision_api,
                        image_bytes,
                        api_endpoint,
                        api_key,
                        api_model,
                        vision_prompt,
                    )
                except RuntimeError as exc:
                    return _json_error(str(exc) or "Vision API request failed", 502)
                source_mode = "vision"

            lib = store.get_library()
            category_names = [cat["name"] for cat in lib.get("categories", [])] if lib.get("version") == 2 else list(CATEGORIES)
            structured: dict[str, Any] | None = None
            if source_mode == "vision" and extracted:
                try:
                    structured = parse_structured_vision_response(extracted)
                except ValueError as exc:
                    return _json_error(f"Invalid structured vision response: {exc}", 502)

            if structured is not None:
                extracted = structured["positive_prompt"]
                sections = structured_vision_to_sections(structured)
            else:
                sections = parse_prompt_sections(extracted, category_names) if extracted else {}
            suggested_name = suggest_entry_name(extracted, filename)

            return web.json_response({
                "success": bool(extracted),
                "prompt": extracted,
                "source": source_mode,
                "suggested_name": suggested_name,
                "sections": sections,
                "structured": structured,
            })
        except Exception as exc:
            return _error_response(exc)

    async def vision_models_v2(request: web.Request) -> web.Response:
        try:
            payload = await _request_json(request)
            if not isinstance(payload, dict):
                raise ValidationError("request body must be an object")
            api_endpoint = str(payload.get("api_endpoint", "")).strip()
            api_key = str(payload.get("api_key", "")).strip()
            if not api_endpoint:
                raise ValidationError("api_endpoint is required")
            try:
                models = await asyncio.to_thread(
                    list_vision_models,
                    api_endpoint,
                    api_key,
                )
            except RuntimeError as exc:
                return _json_error(str(exc) or "Vision API model discovery failed", 502)
            return web.json_response({"models": models})
        except Exception as exc:
            return _error_response(exc)

    handlers: dict[str, Callable[[web.Request], Awaitable[web.StreamResponse]]] = {
        "get_library": get_library, "create_entry": create_entry, "update_entry": update_entry,
        "delete_entry": delete_entry, "replace_library": replace_library, "get_image": get_image,
        "upload_image": upload_image, "remove_image": remove_image,
        "get_library_v2": get_library_v2, "replace_library_v2": replace_library_v2,
        "create_category": create_category, "update_category": update_category, "reorder_categories": reorder_categories,
        "delete_category": delete_category, "create_folder": create_folder, "update_folder": update_folder,
        "delete_folder": delete_folder, "create_entry_v2": create_entry_v2, "update_entry_v2": update_entry_v2,
        "delete_entry_v2": delete_entry_v2, "get_image_v2": get_image_v2, "upload_images_v2": upload_images_v2,
        "replace_images_v2": replace_images_v2, "delete_image_v2": delete_image_v2, "import_sources": import_sources,
        "preview_import_v2": preview_import_v2, "apply_import_v2": apply_import_v2,
        "extract_image_v2": extract_image_v2, "vision_models_v2": vision_models_v2, "list_loras_v2": list_loras_v2,
    }
    # Friendly aliases for integration tests and embedders.
    handlers.update({
        "v2_get_library": get_library_v2, "v2_replace_library": replace_library_v2, "v2_create_category": create_category,
        "v2_update_category": update_category, "v2_reorder_categories": reorder_categories, "v2_delete_category": delete_category,
        "v2_create_folder": create_folder, "v2_update_folder": update_folder, "v2_delete_folder": delete_folder,
        "v2_create_entry": create_entry_v2, "v2_update_entry": update_entry_v2, "v2_delete_entry": delete_entry_v2,
        "v2_get_image": get_image_v2, "v2_upload_images": upload_images_v2, "v2_replace_images": replace_images_v2,
        "v2_delete_image": delete_image_v2, "v2_import_sources": import_sources, "v2_preview_import": preview_import_v2,
        "v2_apply_import": apply_import_v2, "v2_extract_image": extract_image_v2,
        "v2_vision_models": vision_models_v2, "v2_list_loras": list_loras_v2,
    })
    return handlers


def register_routes(store: LibraryStore | None = None, image_store: ImageStore | None = None, prompt_server: Any | None = None) -> dict[str, Callable[[web.Request], Awaitable[web.StreamResponse]]] | None:
    """Register v1 and v2 routes on ComfyUI's shared route table."""
    if prompt_server is None:
        try:
            from server import PromptServer  # type: ignore
            prompt_server = PromptServer.instance
        except (ImportError, AttributeError):
            return None
    if prompt_server is None or not hasattr(prompt_server, "routes"):
        return None
    route_table = prompt_server.routes
    if id(route_table) in _REGISTERED_ROUTE_TABLES:
        return None
    store = store or create_default_store()
    handlers = build_handlers(store, image_store)
    routes = route_table
    routes.get(f"{BASE_PATH}/library")(handlers["get_library"])
    routes.post(f"{BASE_PATH}/entries")(handlers["create_entry"])
    routes.put(f"{BASE_PATH}/entries/{{entry_id}}")(handlers["update_entry"])
    routes.delete(f"{BASE_PATH}/entries/{{entry_id}}")(handlers["delete_entry"])
    routes.put(f"{BASE_PATH}/library")(handlers["replace_library"])
    routes.get(f"{BASE_PATH}/entries/{{entry_id}}/image")(handlers["get_image"])
    routes.post(f"{BASE_PATH}/entries/{{entry_id}}/image")(handlers["upload_image"])
    routes.delete(f"{BASE_PATH}/entries/{{entry_id}}/image")(handlers["remove_image"])
    routes.get(f"{BASE_PATH_V2}/library")(handlers["get_library_v2"])
    routes.put(f"{BASE_PATH_V2}/library")(handlers["replace_library_v2"])
    routes.post(f"{BASE_PATH_V2}/categories")(handlers["create_category"])
    routes.put(f"{BASE_PATH_V2}/categories/order")(handlers["reorder_categories"])
    routes.put(f"{BASE_PATH_V2}/categories/{{category_id}}")(handlers["update_category"])
    routes.delete(f"{BASE_PATH_V2}/categories/{{category_id}}")(handlers["delete_category"])
    routes.post(f"{BASE_PATH_V2}/categories/{{category_id}}/folders")(handlers["create_folder"])
    routes.put(f"{BASE_PATH_V2}/categories/{{category_id}}/folders/{{folder_id}}")(handlers["update_folder"])
    routes.delete(f"{BASE_PATH_V2}/categories/{{category_id}}/folders/{{folder_id}}")(handlers["delete_folder"])
    routes.post(f"{BASE_PATH_V2}/entries")(handlers["create_entry_v2"])
    routes.put(f"{BASE_PATH_V2}/entries/{{entry_id}}")(handlers["update_entry_v2"])
    routes.delete(f"{BASE_PATH_V2}/entries/{{entry_id}}")(handlers["delete_entry_v2"])
    routes.get(f"{BASE_PATH_V2}/loras")(handlers["list_loras_v2"])
    routes.get(f"{BASE_PATH_V2}/entries/{{entry_id}}/images/{{image_id}}")(handlers["get_image_v2"])
    routes.post(f"{BASE_PATH_V2}/entries/{{entry_id}}/images")(handlers["upload_images_v2"])
    routes.put(f"{BASE_PATH_V2}/entries/{{entry_id}}/images")(handlers["replace_images_v2"])
    routes.delete(f"{BASE_PATH_V2}/entries/{{entry_id}}/images/{{image_id}}")(handlers["delete_image_v2"])
    routes.get(f"{BASE_PATH_V2}/imports/sources")(handlers["import_sources"])
    routes.post(f"{BASE_PATH_V2}/imports/preview")(handlers["preview_import_v2"])
    routes.post(f"{BASE_PATH_V2}/imports/apply")(handlers["apply_import_v2"])
    routes.post(f"{BASE_PATH_V2}/extract_image")(handlers["extract_image_v2"])
    routes.post(f"{BASE_PATH_V2}/vision/models")(handlers["vision_models_v2"])
    _REGISTERED_ROUTE_TABLES.add(id(route_table))
    return handlers


__all__ = ["BASE_PATH", "BASE_PATH_V2", "build_handlers", "register_routes", "UnsupportedMediaError", "PayloadTooLargeError"]
