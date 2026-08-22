import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from aiohttp import FormData, web
from aiohttp.test_utils import AioHTTPTestCase

from image_store import ImageStore
from library_store import CATEGORIES, LibraryStore
from routes import BASE_PATH, build_handlers


class RouteTests(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        seed = root / "seed.json"
        seed.write_text(json.dumps({"version": 1, "categories": {category: [] for category in CATEGORIES}}), encoding="utf-8")
        self.store = LibraryStore(root / "user", seed_path=seed)
        self.image_store = ImageStore(root / "user" / "prompt_library" / "images")
        handlers = build_handlers(self.store, self.image_store)
        app = web.Application()
        app.router.add_get(f"{BASE_PATH}/library", handlers["get_library"])
        app.router.add_post(f"{BASE_PATH}/entries", handlers["create_entry"])
        app.router.add_put(f"{BASE_PATH}/entries/{{entry_id}}", handlers["update_entry"])
        app.router.add_delete(f"{BASE_PATH}/entries/{{entry_id}}", handlers["delete_entry"])
        app.router.add_put(f"{BASE_PATH}/library", handlers["replace_library"])
        app.router.add_get(f"{BASE_PATH}/entries/{{entry_id}}/image", handlers["get_image"])
        app.router.add_post(f"{BASE_PATH}/entries/{{entry_id}}/image", handlers["upload_image"])
        app.router.add_delete(f"{BASE_PATH}/entries/{{entry_id}}/image", handlers["remove_image"])
        return app

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.tmp.cleanup()

    async def test_library_and_create_statuses(self):
        response = await self.client.get(f"{BASE_PATH}/library")
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await response.json())["version"], 1)
        response = await self.client.post(
            f"{BASE_PATH}/entries", json={"category": "style", "name": "Ink", "prompt": "ink"}
        )
        self.assertEqual(response.status, 201)
        entry = await response.json()
        response = await self.client.post(
            f"{BASE_PATH}/entries", json={"category": "style", "name": "ink", "prompt": "again"}
        )
        self.assertEqual(response.status, 409)

    async def test_image_upload_uses_signature_and_missing_is_not_found(self):
        response = await self.client.post(
            f"{BASE_PATH}/entries", json={"category": "style", "name": "Ink", "prompt": "ink"}
        )
        entry = await response.json()
        form = FormData()
        form.add_field("image", b"\x89PNG\r\n\x1a\nminimal", filename="preview.png", content_type="image/png")
        response = await self.client.post(f"{BASE_PATH}/entries/{entry['id']}/image", data=form)
        self.assertEqual(response.status, 200, await response.text())
        updated = await response.json()
        self.assertEqual(updated["image"]["media_type"], "image/png")
        response = await self.client.get(f"{BASE_PATH}/entries/{entry['id']}/image")
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.read(), b"\x89PNG\r\n\x1a\nminimal")
        response = await self.client.get(f"{BASE_PATH}/entries/{uuid.uuid4()}/image")
        self.assertEqual(response.status, 404)

    async def test_update_delete_replace_and_remove_statuses(self):
        missing_id = str(uuid.uuid4())
        response = await self.client.put(f"{BASE_PATH}/entries/{missing_id}", json={"name": "Name"})
        self.assertEqual(response.status, 404)
        response = await self.client.put(f"{BASE_PATH}/library", json={"version": 1, "categories": {}})
        self.assertEqual(response.status, 400)
        response = await self.client.post(
            f"{BASE_PATH}/entries", json={"category": "style", "name": "Ink", "prompt": "ink"}
        )
        entry = await response.json()
        response = await self.client.post(
            f"{BASE_PATH}/entries", json={"category": "style", "name": "ink", "prompt": "duplicate"}
        )
        self.assertEqual(response.status, 409)
        response = await self.client.put(
            f"{BASE_PATH}/entries/{entry['id']}", json={"name": "Ink Updated", "prompt": "new"}
        )
        self.assertEqual(response.status, 200)
        response = await self.client.delete(f"{BASE_PATH}/entries/{missing_id}")
        self.assertEqual(response.status, 404)
        response = await self.client.delete(f"{BASE_PATH}/entries/{entry['id']}/image")
        self.assertEqual(response.status, 404)

    async def test_failed_replacement_restores_prior_image_and_metadata(self):
        response = await self.client.post(
            f"{BASE_PATH}/entries", json={"category": "style", "name": "Ink", "prompt": "ink"}
        )
        entry = await response.json()
        original_bytes = b"\x89PNG\r\n\x1a\noriginal"
        form = FormData()
        form.add_field("image", original_bytes, filename="original.png", content_type="image/png")
        response = await self.client.post(f"{BASE_PATH}/entries/{entry['id']}/image", data=form)
        self.assertEqual(response.status, 200)
        original = self.store.get_entry(entry["id"])
        original_metadata = original["image"]

        replacement = FormData()
        replacement.add_field("image", b"\x89PNG\r\n\x1a\nreplacement", filename="replacement.png", content_type="image/png")
        with patch.object(self.store, "update_image", side_effect=RuntimeError("test failure")):
            response = await self.client.post(f"{BASE_PATH}/entries/{entry['id']}/image", data=replacement)
        self.assertEqual(response.status, 500)
        current = self.store.get_entry(entry["id"])
        self.assertEqual(current["image"], original_metadata)
        self.assertEqual(self.store.image_store.read(entry["id"], original_metadata)[0], original_bytes)

    async def test_remove_commits_metadata_before_filesystem_cleanup(self):
        response = await self.client.post(
            f"{BASE_PATH}/entries", json={"category": "style", "name": "Ink", "prompt": "ink"}
        )
        entry = await response.json()
        image_bytes = b"\x89PNG\r\n\x1a\noriginal"
        form = FormData()
        form.add_field("image", image_bytes, filename="original.png", content_type="image/png")
        await self.client.post(f"{BASE_PATH}/entries/{entry['id']}/image", data=form)
        metadata = self.store.get_entry(entry["id"])["image"]
        with patch.object(self.image_store, "remove", side_effect=OSError("test failure")):
            response = await self.client.delete(f"{BASE_PATH}/entries/{entry['id']}/image")
        self.assertEqual(response.status, 500)
        self.assertIsNone(self.store.get_entry(entry["id"])["image"])
        self.assertEqual(self.store.image_store.read(entry["id"], metadata)[0], image_bytes)


if __name__ == "__main__":
    unittest.main()
