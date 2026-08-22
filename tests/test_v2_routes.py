from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import FormData, web
from aiohttp.test_utils import AioHTTPTestCase

from library_store import CATEGORIES, LibraryStore
from routes import BASE_PATH, BASE_PATH_V2, build_handlers


def seed_document() -> dict:
    return {
        "version": 2,
        "categories": [
            {"id": category, "key": category, "name": category.title(), "protected": True, "folders": [], "entries": []}
            for category in CATEGORIES
        ],
        "applied_seed_packs": [],
    }


class V2RouteTests(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        seed = root / "seed.json"
        seed.write_text(json.dumps(seed_document()), encoding="utf-8")
        self.store = LibraryStore(root / "user", seed_path=seed, seed_manifest_path=root / "missing-manifest.json")
        self.store.get_library()
        handlers = build_handlers(self.store)
        app = web.Application()
        app.router.add_post(f"{BASE_PATH}/entries", handlers["create_entry"])
        app.router.add_post(f"{BASE_PATH}/entries/{{entry_id}}/image", handlers["upload_image"])
        app.router.add_get(f"{BASE_PATH}/entries/{{entry_id}}/image", handlers["get_image"])
        app.router.add_get(f"{BASE_PATH_V2}/library", handlers["get_library_v2"])
        app.router.add_post(f"{BASE_PATH_V2}/categories", handlers["create_category"])
        app.router.add_delete(f"{BASE_PATH_V2}/categories/{{category_id}}", handlers["delete_category"])
        app.router.add_post(f"{BASE_PATH_V2}/imports/preview", handlers["preview_import_v2"])
        app.router.add_post(f"{BASE_PATH_V2}/imports/apply", handlers["apply_import_v2"])
        app.router.add_post(f"{BASE_PATH_V2}/extract_image", handlers["extract_image_v2"])
        return app

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.tmp.cleanup()

    async def test_empty_category_delete_accepts_empty_json(self):
        response = await self.client.post(f"{BASE_PATH_V2}/categories", json={"name": "Empty"})
        category = await response.json()
        response = await self.client.delete(f"{BASE_PATH_V2}/categories/{category['id']}", json={})
        self.assertEqual(response.status, 200, await response.text())

    async def test_multipart_preview_combines_directory_files_and_does_not_write(self):
        before = self.store.library_path.read_text(encoding="utf-8")
        form = FormData()
        form.add_field("files", b"one prompt\n", filename="Pack/Style/one.txt", content_type="text/plain")
        form.add_field("files", b"name,prompt\nTwo,two prompt\n", filename="Pack/Character/two.csv", content_type="text/csv")
        response = await self.client.post(f"{BASE_PATH_V2}/imports/preview", data=form)
        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertEqual(payload["record_count"], 2)
        self.assertEqual(payload["group_count"], 1)
        self.assertEqual(payload["groups"][0]["count"], 2)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(self.store.library_path.read_text(encoding="utf-8"), before)

    async def test_source_id_preview_uses_allowlist(self):
        source = Path(self.tmp.name) / "source.txt"
        source.write_text("approved prompt\n", encoding="utf-8")
        allowlist = [{"id": "source-approved", "name": "Approved", "path": str(source), "kind": "txt", "read_only": True}]
        with patch("routes.discover_installed_sources", return_value=allowlist):
            form = FormData()
            form.add_field("source_id", "source-approved")
            response = await self.client.post(f"{BASE_PATH_V2}/imports/preview", data=form)
        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertEqual(payload["record_count"], 1)

    async def test_apply_accepts_frontend_mapping_and_rejects_arbitrary_paths(self):
        payload = {
            "records": [{"name": "Imported", "prompt": "mapped prompt", "group_id": "source-group", "category": "source-group"}],
            "mapping": {"source-group": "character"},
            "conflict_policy": "skip",
        }
        response = await self.client.post(f"{BASE_PATH_V2}/imports/apply", json=payload)
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await response.json())["imported"], 1)
        self.assertEqual(self.store.options("character")[-1], "Imported")
        response = await self.client.post(f"{BASE_PATH_V2}/imports/preview", json={"source_path": str(Path(self.tmp.name) / "not-approved.txt")})
        self.assertEqual(response.status, 400)

    async def test_v1_replacement_keeps_one_primary_image_over_v2_store(self):
        response = await self.client.post(f"{BASE_PATH}/entries", json={"category": "style", "name": "Legacy", "prompt": "legacy"})
        entry = await response.json()
        for value in (b"\x89PNG\r\n\x1a\nfirst", b"\x89PNG\r\n\x1a\nsecond"):
            form = FormData()
            form.add_field("image", value, filename="preview.png", content_type="image/png")
            response = await self.client.post(f"{BASE_PATH}/entries/{entry['id']}/image", data=form)
            self.assertEqual(response.status, 200, await response.text())
        current = self.store.get_entry(entry["id"])
        self.assertEqual(len(current["images"]), 1)
        response = await self.client.get(f"{BASE_PATH}/entries/{entry['id']}/image")
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.read(), b"\x89PNG\r\n\x1a\nsecond")

    async def test_extract_image_v2_multipart_png(self):
        from tests.test_image_extractor import _make_png_with_chunks

        png_data = _make_png_with_chunks({"parameters": "Style: Retro Synthwave\nNegative prompt: ugly\nSteps: 20"})
        form = FormData()
        form.add_field("image", png_data, filename="synth.png", content_type="image/png")
        response = await self.client.post(f"{BASE_PATH_V2}/extract_image", data=form)
        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["prompt"], "Style: Retro Synthwave")
        self.assertEqual(payload["source"], "metadata")
        self.assertEqual(payload["suggested_name"], "Synth")
        self.assertEqual(payload["sections"].get("Style"), "Retro Synthwave")

    async def test_extract_image_v2_json_base64(self):
        import base64
        from tests.test_image_extractor import _make_png_with_chunks

        png_data = _make_png_with_chunks({"parameters": "A beautiful golden retriever puppy\nSteps: 20"})
        b64 = base64.b64encode(png_data).decode("ascii")
        response = await self.client.post(f"{BASE_PATH_V2}/extract_image", json={"image_base64": b64, "filename": "dog.png"})
        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["prompt"], "A beautiful golden retriever puppy")
        self.assertEqual(payload["suggested_name"], "Dog")


if __name__ == "__main__":
    unittest.main()
