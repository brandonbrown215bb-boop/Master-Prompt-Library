"""Server-owned image storage for prompt-library entries.

The v1 API stores one image directly beneath ``images`` using the entry UUID.
v2 stores an ordered gallery beneath ``images/<entry-id>/<image-id>.<ext>``.
Both layouts are intentionally supported so a migrated v1 workflow can keep
resolving its old thumbnail until the migration has completed successfully.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO, Any


MAX_IMAGE_SIZE = 8 * 1024 * 1024
MAX_IMAGES_PER_ENTRY = 20


class ImageStore:
    MEDIA_TYPES = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    _SIGNATURES = (
        (b"\xFF\xD8\xFF", "image/jpeg", ".jpg"),
        (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    )

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    @classmethod
    def detect_signature(cls, data: bytes) -> tuple[str, str]:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise ValueError("image data must be bytes")
        data = bytes(data)
        if len(data) > MAX_IMAGE_SIZE:
            raise ValueError("image exceeds the 8 MiB limit")
        for signature, media_type, extension in cls._SIGNATURES:
            if data.startswith(signature):
                return media_type, extension
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp", ".webp"
        raise ValueError("only JPEG, PNG, and WebP images are accepted")

    @classmethod
    def read_limited(cls, stream: BinaryIO) -> bytes:
        data = stream.read(MAX_IMAGE_SIZE + 1)
        if len(data) > MAX_IMAGE_SIZE:
            raise ValueError("image exceeds the 8 MiB limit")
        return data

    @staticmethod
    def _uuid(value: Any, label: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"{label} must be a UUID") from exc

    @classmethod
    def _entry_uuid(cls, entry_id: str) -> uuid.UUID:
        return cls._uuid(entry_id, "entry id")

    @classmethod
    def _image_uuid(cls, image_id: str) -> uuid.UUID:
        return cls._uuid(image_id, "image id")

    def _root(self) -> Path:
        return self.directory.resolve()

    def _safe_file(self, path: Path) -> Path:
        resolved = path.resolve()
        root = self._root()
        if resolved.parent != root and root not in resolved.parents:
            raise ValueError("image path is outside the image directory")
        return resolved

    def entry_directory(self, entry_id: str) -> Path:
        parsed = self._entry_uuid(entry_id)
        path = self._safe_file(self.directory / str(parsed))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def image_path(self, entry_id: str, image_id: str, extension: str) -> Path:
        parsed_entry = self._entry_uuid(entry_id)
        parsed_image = self._image_uuid(image_id)
        if extension not in self.MEDIA_TYPES.values():
            raise ValueError("image extension is invalid")
        return self._safe_file(self.directory / str(parsed_entry) / f"{parsed_image}{extension}")

    def _path_for_filename(self, filename: str) -> Path:
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError("image filename is invalid")
        return self._safe_file(self.directory / filename)

    def validate_metadata(self, entry_id: str, metadata: dict[str, Any], image_id: str | None = None) -> None:
        """Validate either v1 flat metadata or v2 gallery metadata."""
        self._entry_uuid(entry_id)
        if not isinstance(metadata, dict):
            raise ValueError("image metadata is invalid")
        filename = metadata.get("filename")
        media_type = metadata.get("media_type")
        if not isinstance(filename, str) or not isinstance(media_type, str) or media_type not in self.MEDIA_TYPES:
            raise ValueError("image metadata is invalid")
        expected = self.MEDIA_TYPES[media_type]
        if Path(filename).suffix.lower() not in (expected, ".jpeg" if expected == ".jpg" else expected):
            raise ValueError("image filename extension is invalid")
        candidate_id = image_id or metadata.get("id")
        if candidate_id is None:
            parsed = self._entry_uuid(entry_id)
            path = self._path_for_filename(filename)
            if path.stem.casefold() not in {str(parsed).casefold(), parsed.hex.casefold()}:
                raise ValueError("image filename is invalid")
            return
        parsed_image = self._image_uuid(candidate_id)
        if Path(filename).stem.casefold() not in {str(parsed_image).casefold(), parsed_image.hex.casefold()}:
            raise ValueError("image filename is invalid")
        self.image_path(entry_id, str(parsed_image), expected)

    def exists(self, entry_id: str, metadata: dict[str, Any]) -> bool:
        self.validate_metadata(entry_id, metadata)
        if metadata.get("id") is not None:
            path = self.image_path(entry_id, str(metadata["id"]), self.MEDIA_TYPES[metadata["media_type"]])
        else:
            path = self._path_for_filename(metadata["filename"])
        return path.is_file()

    def resolve_path(self, entry_id: str, metadata: dict[str, Any]) -> Path:
        self.validate_metadata(entry_id, metadata)
        if metadata.get("id") is not None:
            path = self.image_path(entry_id, str(metadata["id"]), self.MEDIA_TYPES[metadata["media_type"]])
        else:
            path = self._path_for_filename(metadata["filename"])
        if not path.is_file():
            raise FileNotFoundError("preview image not found")
        return path

    resolve = resolve_path

    @staticmethod
    def _atomic_write(destination: Path, data: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent, prefix=".image-", suffix=".tmp", delete=False) as handle:
                temporary_name = handle.name
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
            temporary_name = None
        finally:
            if temporary_name:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass

    def save(self, entry_id: str, data: bytes) -> dict[str, str]:
        """v1 replacement image API (one flat image per entry)."""
        parsed = self._entry_uuid(entry_id)
        media_type, extension = self.detect_signature(data)
        destination = self._path_for_filename(f"{parsed}{extension}")
        self._atomic_write(destination, bytes(data))
        for candidate in self._candidate_paths(str(parsed)):
            if candidate != destination:
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass
        return {"filename": destination.name, "media_type": media_type}

    def save_image(self, entry_id: str, image_id: str, data: bytes) -> dict[str, str]:
        """Save a v2 image and return server-owned metadata."""
        parsed_entry = self._entry_uuid(entry_id)
        parsed_image = self._image_uuid(image_id)
        media_type, extension = self.detect_signature(data)
        destination = self.image_path(str(parsed_entry), str(parsed_image), extension)
        self._atomic_write(destination, bytes(data))
        for old_extension in self.MEDIA_TYPES.values():
            old = self.image_path(str(parsed_entry), str(parsed_image), old_extension)
            if old != destination:
                try:
                    old.unlink()
                except FileNotFoundError:
                    pass
        return {"id": str(parsed_image), "filename": destination.name, "media_type": media_type}

    def restore(self, entry_id: str, metadata: dict[str, Any], data: bytes) -> None:
        """Restore a previously attached v1 or v2 image."""
        self.validate_metadata(entry_id, metadata)
        media_type, _ = self.detect_signature(data)
        if media_type != metadata["media_type"]:
            raise ValueError("image metadata does not match image data")
        if metadata.get("id") is not None:
            destination = self.image_path(entry_id, str(metadata["id"]), self.MEDIA_TYPES[media_type])
        else:
            destination = self._path_for_filename(metadata["filename"])
        self._atomic_write(destination, bytes(data))

    def _candidate_paths(self, entry_id: str) -> list[Path]:
        parsed = self._entry_uuid(entry_id)
        return [self.directory / f"{stem}{suffix}" for stem in (str(parsed), parsed.hex) for suffix in (".jpg", ".jpeg", ".png", ".webp")]

    def remove(self, entry_id: str, metadata: dict[str, Any] | None = None) -> None:
        parsed = self._entry_uuid(entry_id)
        if metadata is not None:
            self.validate_metadata(str(parsed), metadata)
            if metadata.get("id") is not None:
                candidates = [self.image_path(str(parsed), str(metadata["id"]), self.MEDIA_TYPES[metadata["media_type"]])]
            else:
                candidates = [self._path_for_filename(metadata["filename"])]
        else:
            candidates = self._candidate_paths(str(parsed))
        for candidate in candidates:
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass

    def remove_image(self, entry_id: str, image_id: str, metadata: dict[str, Any] | None = None) -> None:
        self._entry_uuid(entry_id)
        parsed_image = self._image_uuid(image_id)
        candidates = [self.image_path(entry_id, str(parsed_image), extension) for extension in self.MEDIA_TYPES.values()]
        if metadata is not None:
            self.validate_metadata(entry_id, metadata, str(parsed_image))
        for candidate in candidates:
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass

    def remove_entry(self, entry_id: str) -> None:
        parsed = self._entry_uuid(entry_id)
        self.remove(str(parsed))
        directory = self._safe_file(self.directory / str(parsed))
        if directory.is_dir():
            shutil.rmtree(directory)

    def read(self, entry_id: str, metadata: dict[str, Any]) -> tuple[bytes, str]:
        path = self.resolve_path(entry_id, metadata)
        return path.read_bytes(), metadata["media_type"]

    def read_image(self, entry_id: str, metadata: dict[str, Any]) -> tuple[bytes, str]:
        return self.read(entry_id, metadata)

    def rehome_legacy(self, entry_id: str, image_id: str, metadata: dict[str, Any]) -> dict[str, str] | None:
        """Copy a valid v1 flat image to its deterministic v2 location."""
        try:
            self.validate_metadata(entry_id, metadata)
            source = self._path_for_filename(metadata["filename"])
            if not source.is_file():
                return None
            data = source.read_bytes()
            media_type, _ = self.detect_signature(data)
            if media_type != metadata["media_type"]:
                return None
            return self.save_image(entry_id, image_id, data)
        except (FileNotFoundError, ValueError, OSError):
            return None


__all__ = ["ImageStore", "MAX_IMAGE_SIZE", "MAX_IMAGES_PER_ENTRY"]
