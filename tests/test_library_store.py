import json
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from image_store import ImageStore
from library_store import (
    CATEGORIES,
    CorruptLibraryError,
    DuplicateNameError,
    LibraryStore,
    ValidationError,
)


PNG = b"\x89PNG\r\n\x1a\nminimal"


def seed_document(*entries):
    categories = {category: [] for category in CATEGORIES}
    for category, name, prompt in entries:
        categories[category].append({"id": str(uuid.uuid4()), "name": name, "prompt": prompt, "image": None})
    return {"version": 1, "categories": categories}


class LibraryStoreTests(unittest.TestCase):
    def make_store(self, *entries):
        root = Path(self.tmp.name)
        seed = root / "seed.json"
        seed.write_text(json.dumps(seed_document(*entries)), encoding="utf-8")
        return LibraryStore(root / "user", seed_path=seed)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_run_is_seeded_and_read_is_detached(self):
        store = self.make_store(("style", "Ink", "black ink"))
        library = store.get_library()
        self.assertEqual(library["categories"]["style"][0]["name"], "Ink")
        library["categories"]["style"].clear()
        self.assertEqual(len(store.get_library()["categories"]["style"]), 1)
        self.assertFalse(store.backup_path.exists())

    def test_crud_duplicate_and_cross_category_names(self):
        store = self.make_store()
        style = store.create_entry("style", "  Film  ", " grain ")
        self.assertEqual(style["name"], "Film")
        with self.assertRaises(DuplicateNameError):
            store.create_entry("style", "film", "other")
        character = store.create_entry("character", "film", "a person")
        self.assertEqual(store.update_entry(style["id"], prompt="new text")["prompt"], "new text")
        store.delete_entry(character["id"])
        with self.assertRaises(Exception):
            store.get_entry(character["id"])

    def test_concurrent_creates_keep_every_unique_update(self):
        store = self.make_store()
        count = 8
        barrier = threading.Barrier(count)

        def create(index):
            barrier.wait()
            return store.create_entry("character", f"Character {index}", f"prompt {index}")

        with ThreadPoolExecutor(max_workers=count) as pool:
            created = list(pool.map(create, range(count)))
        names = {entry["name"] for entry in created}
        self.assertEqual(len(names), count)
        self.assertEqual(len(store.get_library()["categories"]["character"]), count)

    def test_atomic_backup_and_corrupt_refusal(self):
        store = self.make_store()
        store.create_entry("style", "One", "one")
        previous = store.library_path.read_text(encoding="utf-8")
        store.create_entry("style", "Two", "two")
        self.assertTrue(store.backup_path.exists())
        self.assertEqual(json.loads(store.library_path.read_text(encoding="utf-8"))["version"], 1)
        store.library_path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(CorruptLibraryError):
            store.create_entry("style", "Three", "three")
        self.assertEqual(store.library_path.read_text(encoding="utf-8"), "{broken")
        self.assertEqual(previous, store.backup_path.read_text(encoding="utf-8"))

    def test_image_metadata_is_synchronized_and_deleted_with_entry(self):
        store = self.make_store()
        entry = store.create_entry("style", "Image", "picture")
        metadata = store.image_store.save(entry["id"], PNG)
        updated = store.update_image(entry["id"], metadata)
        self.assertEqual(updated["image"], metadata)
        path = store.image_store.resolve_path(entry["id"], metadata)
        self.assertTrue(path.exists())
        store.delete_entry(entry["id"])
        self.assertFalse(path.exists())

    def test_validation_bounds_and_import_clears_missing_images(self):
        store = self.make_store()
        bad = {"version": 1, "categories": {category: [] for category in CATEGORIES}}
        bad["categories"]["style"] = [{"id": "nope", "name": "x", "prompt": "y", "image": None}]
        with self.assertRaises(ValidationError):
            store.replace_library(bad)
        entry_id = str(uuid.uuid4())
        imported = seed_document()
        imported["categories"]["style"] = [{
            "id": entry_id, "name": "Missing", "prompt": "prompt",
            "image": {"filename": f"{entry_id}.png", "media_type": "image/png"},
        }]
        result = store.replace_library(imported)
        self.assertIsNone(result["categories"]["style"][0]["image"])

    def test_invalid_entry_and_import_contract(self):
        store = self.make_store()
        for name, prompt in (("", "prompt"), ("name", ""), ("n" * 121, "prompt"), ("name", "p" * 20_001)):
            with self.assertRaises(ValidationError):
                store.create_entry("style", name, prompt)
        entry = store.create_entry("style", "Valid", "prompt")
        with self.assertRaises(ValidationError):
            store.update_entry(entry["id"], name="")
        with self.assertRaises(ValidationError):
            store.update_entry(entry["id"], prompt="p" * 20_001)
        for bad_document in (
            {"version": 1, "categories": []},
            {"version": 1, "categories": {"style": [], "character": [], "action": [], "background": [], "other": []}},
            {"version": 1, "categories": {"style": {}, "character": [], "action": [], "background": []}},
        ):
            with self.assertRaises(ValidationError):
                store.replace_library(bad_document)
        duplicate = seed_document()
        duplicate["categories"]["style"] = [
            {"id": str(uuid.uuid4()), "name": "Same", "prompt": "one", "image": None},
            {"id": str(uuid.uuid4()), "name": "same", "prompt": "two", "image": None},
        ]
        with self.assertRaises(DuplicateNameError):
            store.replace_library(duplicate)
        malformed_id = seed_document()
        malformed_id["categories"]["style"] = [{"id": "not-a-uuid", "name": "Name", "prompt": "text", "image": None}]
        with self.assertRaises(ValidationError):
            store.replace_library(malformed_id)

    def test_image_signature_and_size_contract(self):
        image_store = ImageStore(Path(self.tmp.name) / "images")
        entry_id = str(uuid.uuid4())
        with self.assertRaises(ValueError):
            image_store.save(entry_id, b"not an image")
        with self.assertRaises(ValueError):
            image_store.save(entry_id, b"\x89PNG\r\n\x1a\n" + b"x" * (8 * 1024 * 1024))


if __name__ == "__main__":
    unittest.main()
