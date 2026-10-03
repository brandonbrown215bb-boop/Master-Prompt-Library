from __future__ import annotations

import base64
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import FormData, web
from aiohttp.test_utils import AioHTTPTestCase

from library_store import CATEGORIES, LibraryStore
from image_store import MAX_IMAGE_SIZE
from routes import BASE_PATH, BASE_PATH_V2, PayloadTooLargeError, _decode_image_base64, build_handlers


def seed_document() -> dict:
    return {
        "version": 2,
        "categories": [
            {"id": category, "key": category, "name": category.title(), "protected": True, "folders": [], "entries": []}
            for category in CATEGORIES
        ],
        "applied_seed_packs": [],
    }


def structured_vision_fixture() -> dict[str, object]:
    return {
        "positive_prompt": "a quiet figure beside a red door",
        "style": "ink wash",
        "character": "single visible figure",
        "clothing": "dark coat and scarf",
        "action": "standing with one hand on the door",
        "background": "narrow stone courtyard",
        "camera": "waist-up framing",
        "lighting": "soft side light with a cast shadow",
        "mood": "quiet and watchful",
        "confidence": 0.82,
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
        app.router.add_post(f"{BASE_PATH_V2}/entries", handlers["create_entry_v2"])
        app.router.add_put(f"{BASE_PATH_V2}/entries/{{entry_id}}", handlers["update_entry_v2"])
        app.router.add_get(f"{BASE_PATH_V2}/loras", handlers["list_loras_v2"])
        app.router.add_post(f"{BASE_PATH_V2}/categories", handlers["create_category"])
        app.router.add_delete(f"{BASE_PATH_V2}/categories/{{category_id}}", handlers["delete_category"])
        app.router.add_post(f"{BASE_PATH_V2}/imports/preview", handlers["preview_import_v2"])
        app.router.add_post(f"{BASE_PATH_V2}/imports/apply", handlers["apply_import_v2"])
        app.router.add_post(f"{BASE_PATH_V2}/extract_image", handlers["extract_image_v2"])
        app.router.add_post(f"{BASE_PATH_V2}/vision/models", handlers["vision_models_v2"])
        return app

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.tmp.cleanup()

    async def test_empty_category_delete_accepts_empty_json(self):
        response = await self.client.post(f"{BASE_PATH_V2}/categories", json={"name": "Empty"})
        category = await response.json()
        response = await self.client.delete(f"{BASE_PATH_V2}/categories/{category['id']}", json={})
        self.assertEqual(response.status, 200, await response.text())

    async def test_entry_routes_round_trip_lora_attachments(self):
        response = await self.client.post(f"{BASE_PATH_V2}/entries", json={
            "category": "style",
            "name": "LoRA-backed concept",
            "prompt": "fine engraved lines",
            "loras": [{"name": "styles/engraving.safetensors", "strength_model": 0.9, "strength_clip": 0.75}],
        })
        self.assertEqual(response.status, 201, await response.text())
        entry = await response.json()
        self.assertEqual(entry["loras"][0]["name"], "styles/engraving.safetensors")
        response = await self.client.put(f"{BASE_PATH_V2}/entries/{entry['id']}", json={"loras": []})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await response.json())["loras"], [])

    async def test_lora_listing_uses_comfyui_inventory_adapter(self):
        with patch("routes._available_lora_names", return_value=["a.safetensors", "sub/b.safetensors"]):
            response = await self.client.get(f"{BASE_PATH_V2}/loras")
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await response.json())["loras"], ["a.safetensors", "sub/b.safetensors"])

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
        from tests.test_image_extractor import _make_png_with_chunks

        png_data = _make_png_with_chunks({"parameters": "A beautiful golden retriever puppy\nSteps: 20"})
        b64 = base64.b64encode(png_data).decode("ascii")
        response = await self.client.post(f"{BASE_PATH_V2}/extract_image", json={"image_base64": b64, "filename": "dog.png"})
        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["prompt"], "A beautiful golden retriever puppy")
        self.assertEqual(payload["suggested_name"], "Dog")

    async def test_extract_image_v2_force_vision_overrides_metadata(self):
        from tests.test_image_extractor import _make_png_with_chunks

        png_data = _make_png_with_chunks({"parameters": "embedded metadata prompt"})
        form = FormData()
        form.add_field("image", png_data, filename="metadata.png", content_type="image/png")
        form.add_field("force_vision", "true")
        form.add_field("api_endpoint", "https://generativelanguage.googleapis.com/v1beta/openai")
        form.add_field("api_model", "gemini-3.7-flash")
        with patch("routes.query_vision_api", return_value="provider prompt") as query:
            response = await self.client.post(f"{BASE_PATH_V2}/extract_image", data=form)

        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertEqual(payload["prompt"], "provider prompt")
        self.assertEqual(payload["source"], "vision")
        self.assertIsNone(payload["structured"])
        query.assert_called_once()

    async def test_extract_image_v2_returns_validated_structured_vision_contract(self):
        from tests.test_image_extractor import _make_png_with_chunks

        form = FormData()
        form.add_field("image", _make_png_with_chunks({}), filename="", content_type="image/png")
        form.add_field("api_endpoint", "https://generativelanguage.googleapis.com/v1beta/openai")
        structured = structured_vision_fixture()
        with patch("routes.query_vision_api", return_value=json.dumps(structured)) as query:
            response = await self.client.post(f"{BASE_PATH_V2}/extract_image", data=form)

        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["source"], "vision")
        self.assertEqual(payload["prompt"], structured["positive_prompt"])
        self.assertEqual(payload["structured"]["confidence"], 0.82)
        self.assertEqual(payload["sections"]["Clothing"], "dark coat and scarf")
        self.assertEqual(payload["sections"]["Prompt"], structured["positive_prompt"])
        self.assertTrue(payload["suggested_name"].startswith("A quiet figure"))
        query.assert_called_once()

    async def test_extract_image_v2_accepts_fenced_structured_vision_contract(self):
        from tests.test_image_extractor import _make_png_with_chunks

        form = FormData()
        form.add_field("image", _make_png_with_chunks({}), filename="fenced.png", content_type="image/png")
        form.add_field("api_endpoint", "https://generativelanguage.googleapis.com/v1beta/openai")
        structured = structured_vision_fixture()
        fenced = "```json\n" + json.dumps(structured) + "\n```"
        with patch("routes.query_vision_api", return_value=fenced):
            response = await self.client.post(f"{BASE_PATH_V2}/extract_image", data=form)

        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["prompt"], structured["positive_prompt"])
        self.assertEqual(payload["structured"], structured)

    async def test_extract_image_v2_returns_502_for_invalid_structured_vision(self):
        from tests.test_image_extractor import _make_png_with_chunks

        form = FormData()
        form.add_field("image", _make_png_with_chunks({}), filename="broken.png", content_type="image/png")
        form.add_field("api_endpoint", "https://generativelanguage.googleapis.com/v1beta/openai")
        with patch("routes.query_vision_api", return_value="```json\n{not valid}\n```"):
            response = await self.client.post(f"{BASE_PATH_V2}/extract_image", data=form)

        self.assertEqual(response.status, 502, await response.text())
        payload = await response.json()
        self.assertIn("Invalid structured vision response", payload["error"])

    async def test_extract_image_v2_json_force_vision_accepts_boolean_true(self):
        from tests.test_image_extractor import _make_png_with_chunks

        png_data = _make_png_with_chunks({"parameters": "embedded metadata prompt"})
        with patch("routes.query_vision_api", return_value="provider prompt") as query:
            response = await self.client.post(
                f"{BASE_PATH_V2}/extract_image",
                json={
                    "image_base64": base64.b64encode(png_data).decode("ascii"),
                    "force_vision": True,
                    "api_endpoint": "https://generativelanguage.googleapis.com/v1beta/openai",
                },
            )

        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertEqual(payload["prompt"], "provider prompt")
        self.assertEqual(payload["source"], "vision")
        query.assert_called_once()

    async def test_extract_image_v2_force_vision_requires_endpoint(self):
        from tests.test_image_extractor import _make_png_with_chunks

        form = FormData()
        form.add_field("image", _make_png_with_chunks({"parameters": "embedded"}), filename="metadata.png", content_type="image/png")
        form.add_field("force_vision", "true")
        response = await self.client.post(f"{BASE_PATH_V2}/extract_image", data=form)
        self.assertEqual(response.status, 400, await response.text())

    async def test_extract_image_v2_rejects_json_image_path_without_provider_call(self):
        with patch("routes.query_vision_api") as query:
            response = await self.client.post(
                f"{BASE_PATH_V2}/extract_image",
                json={"image_path": str(Path(self.tmp.name) / "secret.png"), "api_endpoint": "https://example.test"},
            )
        self.assertEqual(response.status, 400, await response.text())
        query.assert_not_called()

    async def test_extract_image_v2_rejects_invalid_json_base64(self):
        response = await self.client.post(
            f"{BASE_PATH_V2}/extract_image",
            json={"image_base64": "not base64!!!"},
        )
        self.assertEqual(response.status, 400, await response.text())

    async def test_extract_image_v2_rejects_json_non_image_without_provider_call(self):
        with patch("routes.query_vision_api") as query:
            response = await self.client.post(
                f"{BASE_PATH_V2}/extract_image",
                json={
                    "image_base64": base64.b64encode(b"not an image").decode("ascii"),
                    "force_vision": True,
                    "api_endpoint": "https://example.test/vision",
                },
            )
        self.assertEqual(response.status, 415, await response.text())
        query.assert_not_called()

    async def test_extract_image_v2_rejects_multipart_non_image_without_provider_call(self):
        form = FormData()
        form.add_field("image", b"not an image", filename="payload.bin", content_type="application/octet-stream")
        form.add_field("force_vision", "true")
        form.add_field("api_endpoint", "https://example.test/vision")
        with patch("routes.query_vision_api") as query:
            response = await self.client.post(f"{BASE_PATH_V2}/extract_image", data=form)
        self.assertEqual(response.status, 415, await response.text())
        query.assert_not_called()

    def test_decode_image_base64_rejects_oversized_payload(self):
        max_encoded_size = ((MAX_IMAGE_SIZE + 2) // 3) * 4
        oversized = "A" * (max_encoded_size + 1)
        with self.assertRaises(PayloadTooLargeError):
            _decode_image_base64(oversized)

    async def test_extract_image_v2_runs_vision_request_off_event_loop(self):
        from tests.test_image_extractor import _make_png_with_chunks

        caller_thread = threading.get_ident()
        worker_threads: list[int] = []

        def fake_query(*_args):
            worker_threads.append(threading.get_ident())
            return "A quiet rook perched above wet ruins"

        form = FormData()
        form.add_field("image", _make_png_with_chunks({}), filename="rook.png", content_type="image/png")
        form.add_field("api_endpoint", "https://generativelanguage.googleapis.com/v1beta/openai")
        form.add_field("api_model", "gemini-3.7-flash")
        with patch("routes.query_vision_api", side_effect=fake_query):
            response = await self.client.post(f"{BASE_PATH_V2}/extract_image", data=form)

        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await response.json())["source"], "vision")
        self.assertEqual(len(worker_threads), 1)
        self.assertNotEqual(worker_threads[0], caller_thread)

    async def test_extract_image_v2_returns_vision_api_failure(self):
        from tests.test_image_extractor import _make_png_with_chunks

        form = FormData()
        form.add_field("image", _make_png_with_chunks({}), filename="rook.png", content_type="image/png")
        form.add_field("api_endpoint", "https://generativelanguage.googleapis.com/v1beta/openai")
        with patch("routes.query_vision_api", side_effect=RuntimeError("Vision API HTTP 401: invalid API key")):
            response = await self.client.post(f"{BASE_PATH_V2}/extract_image", data=form)

        self.assertEqual(response.status, 502, await response.text())
        self.assertEqual((await response.json())["error"], "Vision API HTTP 401: invalid API key")

    async def test_vision_models_v2_discovers_models_off_event_loop(self):
        caller_thread = threading.get_ident()
        worker_threads: list[int] = []

        def fake_list(endpoint: str, api_key: str) -> list[str]:
            worker_threads.append(threading.get_ident())
            self.assertEqual(endpoint, "http://127.0.0.1:11434/v1")
            self.assertEqual(api_key, "local-secret")
            return ["llava", "qwen2.5-vl"]

        with patch("routes.list_vision_models", side_effect=fake_list):
            response = await self.client.post(
                f"{BASE_PATH_V2}/vision/models",
                json={
                    "api_endpoint": "http://127.0.0.1:11434/v1",
                    "api_key": "local-secret",
                },
            )

        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await response.json())["models"], ["llava", "qwen2.5-vl"])
        self.assertEqual(len(worker_threads), 1)
        self.assertNotEqual(worker_threads[0], caller_thread)

    async def test_vision_models_v2_requires_endpoint(self):
        with patch("routes.list_vision_models") as discover:
            response = await self.client.post(f"{BASE_PATH_V2}/vision/models", json={})
        self.assertEqual(response.status, 400, await response.text())
        discover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
