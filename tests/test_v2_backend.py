from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from image_store import ImageStore
from importers import discover_installed_sources, parse_csv, parse_directory, parse_json, parse_txt
from library_store import CATEGORIES, LibraryStore, ValidationError
from prompt_library_node import MasterPromptLibraryV2, _apply_loras, set_library_store


PNG = b"\x89PNG\r\n\x1a\nminimal"


def v2_seed() -> dict:
    return {
        "version": 2,
        "categories": [
            {
                "id": category,
                "key": category,
                "name": category.title(),
                "protected": True,
                "folders": [],
                "entries": [],
            }
            for category in CATEGORIES
        ],
        "applied_seed_packs": [],
    }


class V2BackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.seed = root / "seed-v2.json"
        self.seed.write_text(json.dumps(v2_seed()), encoding="utf-8")
        self.store = LibraryStore(root / "user", seed_path=self.seed)

    def tearDown(self) -> None:
        set_library_store(None)
        self.tmp.cleanup()

    def test_categories_and_entry_metadata_are_normalized(self) -> None:
        category = self.store.create_category("  Details  ")
        folder = self.store.create_folder(category["id"], "  Closeups ")
        entry = self.store.create_entry(
            category["id"],
            "  Surface  ",
            " brushed metal ",
            tags=[" B ", "a", "b", "A"],
            favorite=True,
            folder_id=folder["id"],
        )
        self.assertEqual(entry["tags"], ["a", "B"])
        self.assertTrue(entry["favorite"])
        self.assertEqual(entry["folder_id"], folder["id"])
        self.store.update_entry(entry["id"], folder_id=None)
        self.assertIsNone(self.store.get_entry(entry["id"])["folder_id"])
        self.store.delete_folder(category["id"], folder["id"])
        self.assertEqual(self.store.get_entry(entry["id"])["folder_id"], None)

    def test_entry_loras_are_validated_and_persisted(self) -> None:
        entry = self.store.create_entry(
            "style",
            "LoRA concept",
            "etched line work",
            loras=[{"name": "styles/etched.safetensors", "strength_model": 0.8, "strength_clip": 0.65}],
        )
        self.assertEqual(entry["loras"], [{"name": "styles/etched.safetensors", "strength_model": 0.8, "strength_clip": 0.65}])
        updated = self.store.update_entry(entry["id"], loras=[{"name": "styles/etched-v2.safetensors"}])
        self.assertEqual(updated["loras"], [{"name": "styles/etched-v2.safetensors", "strength_model": 1.0, "strength_clip": 1.0}])
        with self.assertRaises(ValidationError):
            self.store.update_entry(entry["id"], loras=[{"name": "same.safetensors"}, {"name": "SAME.safetensors"}])
        with self.assertRaises(ValidationError):
            self.store.update_entry(entry["id"], loras=[{"name": "bad.safetensors", "strength_model": float("inf")}])

    def test_gallery_upload_reorder_primary_and_delete(self) -> None:
        entry = self.store.create_entry("style", "Gallery", "a prompt")
        images = self.store.upload_images(entry["id"], [(PNG, "first"), (PNG, "second")], kind="preview")
        self.assertEqual(len(images), 2)
        updated = self.store.replace_images(
            entry["id"],
            [{"id": images[1]["id"], "caption": "second"}, {"id": images[0]["id"], "caption": "first"}],
            images[1]["id"],
        )
        self.assertEqual(updated["primary_image_id"], images[1]["id"])
        self.assertEqual(updated["images"][0]["id"], images[1]["id"])
        self.store.delete_image(entry["id"], images[1]["id"])
        self.assertIsNone(self.store.get_entry(entry["id"])["primary_image_id"])

    def test_empty_custom_category_can_delete_without_confirmation(self) -> None:
        category = self.store.create_category("Empty")
        self.store.delete_category(category["id"])
        self.assertNotIn(category["id"], [item["id"] for item in self.store.get_library()["categories"]])

    def test_entry_ids_are_unique_across_categories(self) -> None:
        duplicate_id = str(uuid.uuid4())
        document = v2_seed()
        document["categories"][0]["entries"].append({"id": duplicate_id, "name": "One", "prompt": "one"})
        document["categories"][1]["entries"].append({"id": duplicate_id, "name": "Two", "prompt": "two"})
        with self.assertRaises(ValidationError):
            self.store.replace_library(document)

    def test_gallery_batch_prevalidates_and_leaves_no_orphan_on_bad_second_file(self) -> None:
        entry = self.store.create_entry("style", "Batch", "prompt")
        with self.assertRaises(ValueError):
            self.store.upload_images(entry["id"], [(PNG, "ok"), (b"not an image", "bad")])
        self.assertEqual(self.store.get_entry(entry["id"])["images"], [])
        self.assertFalse((self.store.images_directory / entry["id"]).exists())

    def test_seed_upgrade_is_idempotent_and_preserves_user_edit(self) -> None:
        entry_id = str(uuid.uuid4())
        upgrade_seed = v2_seed()
        upgrade_seed["categories"][0]["entries"].append({"id": entry_id, "name": "Seeded", "prompt": "seed prompt", "tags": [], "favorite": False, "folder_id": None, "images": [], "primary_image_id": None})
        seed_path = Path(self.tmp.name) / "upgrade-seed.json"
        seed_path.write_text(json.dumps(upgrade_seed), encoding="utf-8")
        manifest_path = Path(self.tmp.name) / "upgrade-manifest.json"
        manifest_path.write_text(json.dumps({"id": "upgrade-pack", "version": 3}), encoding="utf-8")
        library_path = Path(self.tmp.name) / "old" / "library.json"
        old = v2_seed()
        old["applied_seed_packs"] = [{"id": "upgrade-pack", "version": 2}]
        old["categories"][0]["entries"].append({"id": entry_id, "name": "User Name", "prompt": "user prompt", "tags": [], "favorite": False, "folder_id": None, "images": [], "primary_image_id": None})
        library_path.parent.mkdir(parents=True)
        library_path.write_text(json.dumps(old), encoding="utf-8")
        store = LibraryStore(Path(self.tmp.name) / "old", library_path=library_path, seed_path=seed_path, seed_manifest_path=manifest_path)
        upgraded = store.get_library()
        result = next(entry for category in upgraded["categories"] for entry in category["entries"] if entry["id"] == entry_id)
        self.assertEqual(result["name"], "User Name")
        self.assertIn({"id": "upgrade-pack", "version": 3}, upgraded["applied_seed_packs"])
        before = store.fingerprint()
        self.assertEqual(store.fingerprint(), before)

    def test_v1_migration_rehomes_image_and_preserves_ids(self) -> None:
        root = Path(self.tmp.name) / "migrate"
        image_store = ImageStore(root / "prompt_library" / "images")
        entry_id = str(uuid.uuid4())
        old_image = image_store.save(entry_id, PNG)
        document = {"version": 1, "categories": {category: [] for category in CATEGORIES}}
        document["categories"]["style"] = [{"id": entry_id, "name": "Legacy", "prompt": "old prompt", "image": old_image}]
        library_path = root / "prompt_library" / "library.json"
        library_path.parent.mkdir(parents=True, exist_ok=True)
        library_path.write_text(json.dumps(document), encoding="utf-8")
        store = LibraryStore(root / "user", library_path=library_path, seed_path=self.seed)
        migrated = store.get_library()
        migrated_entry = migrated["categories"][0]["entries"][0]
        self.assertEqual(migrated_entry["id"], entry_id)
        self.assertEqual(migrated_entry["images"][0]["kind"], "preview")
        self.assertTrue(store.backup_path.exists())
        self.assertFalse((image_store.directory / old_image["filename"]).exists())
        self.assertTrue(store.image_store.resolve_path(entry_id, migrated_entry["images"][0]).exists())
        self.assertEqual(store.get_library()["version"], 2)

    def test_v1_replacement_preserves_custom_and_core_gallery_metadata(self) -> None:
        category = self.store.create_category("Custom")
        custom_entry = self.store.create_entry(category["id"], "Keep", "custom")
        core_entry = self.store.create_entry("style", "Core", "old")
        self.store.update_entry(core_entry["id"], tags=["edited"], favorite=True)
        image = self.store.upload_image(core_entry["id"], PNG, kind="preview")
        omitted = self.store.create_entry("style", "Remove", "remove")
        source = {"version": 1, "categories": {category_id: [] for category_id in CATEGORIES}}
        source["categories"]["style"] = [{"id": core_entry["id"], "name": "Core Renamed", "prompt": "new" , "image": None}]
        self.store.replace_v1_library(source)
        current = self.store.get_entry(core_entry["id"])
        self.assertEqual(current["tags"], ["edited"])
        self.assertTrue(current["favorite"])
        self.assertEqual(current["images"][0]["id"], image["id"])
        self.assertEqual(self.store.get_entry(custom_entry["id"])["name"], "Keep")
        with self.assertRaises(Exception):
            self.store.get_entry(omitted["id"])
        self.assertFalse((self.store.images_directory / omitted["id"]).exists())

    def test_v2_node_reports_stale_ids_and_keeps_selection_order(self) -> None:
        first = self.store.create_entry("style", "First", "one")
        second = self.store.create_entry("style", "Second", "two")
        set_library_store(self.store)
        state = json.dumps({"version": 1, "selections": {"style": [second["id"], first["id"], second["id"], str(uuid.uuid4())]}})
        result = MasterPromptLibraryV2.assemble("", state, json.dumps(["style", "prompt"]))
        self.assertEqual(result[1], "two, one")
        components = json.loads(result[5])
        self.assertEqual([item["name"] for item in components["categories"][0]["selected"]], ["Second", "First"])
        self.assertEqual(len(components["missing_entry_ids"]), 1)

    def test_v2_node_keeps_existing_output_indices_and_appends_lora_io(self) -> None:
        set_library_store(self.store)
        inputs = MasterPromptLibraryV2.INPUT_TYPES()
        self.assertEqual(set(inputs["optional"]), {"model", "clip"})
        self.assertEqual(MasterPromptLibraryV2.RETURN_NAMES[:6], (
            "combined_prompt", "style_prompt", "character_prompt", "action_prompt", "background_prompt", "components_json",
        ))
        self.assertEqual(MasterPromptLibraryV2.RETURN_NAMES[6:], ("loras_json", "model", "clip"))

    def test_v2_node_activates_selected_loras_once_and_reports_strength_conflicts(self) -> None:
        first = self.store.create_entry("style", "First", "one", loras=[{"name": "shared.safetensors", "strength_model": 0.8, "strength_clip": 0.7}])
        second = self.store.create_entry("style", "Second", "two", loras=[
            {"name": "SHARED.safetensors", "strength_model": 0.4, "strength_clip": 0.5},
            {"name": "detail.safetensors", "strength_model": 1.1, "strength_clip": 1.0},
        ])
        set_library_store(self.store)
        state = json.dumps({"version": 1, "selections": {"style": [first["id"], second["id"]]}})
        with patch("prompt_library_node._apply_loras", return_value=("loaded-model", "loaded-clip")) as apply_loras:
            result = MasterPromptLibraryV2.assemble("", state, json.dumps(["style", "prompt"]), model="base-model", clip="base-clip")
        activations = apply_loras.call_args.args[2]
        self.assertEqual([item["name"] for item in activations], ["shared.safetensors", "detail.safetensors"])
        self.assertEqual(len(activations[0]["sources"]), 2)
        report = json.loads(result[6])
        self.assertTrue(report["applied"])
        self.assertEqual(len(report["conflicts"]), 1)
        self.assertEqual(result[7:], ("loaded-model", "loaded-clip"))

    def test_lora_runtime_applies_each_attachment_in_order(self) -> None:
        comfy = types.ModuleType("comfy")
        comfy.__path__ = []
        comfy_sd = types.ModuleType("comfy.sd")
        calls: list[tuple[object, object, object, float, float, object]] = []

        def load_lora_for_models(model, clip, state, strength_model, strength_clip, lora_metadata=None):
            calls.append((model, clip, state, strength_model, strength_clip, lora_metadata))
            return f"{model}+{state}", f"{clip}+{state}"

        comfy_sd.load_lora_for_models = load_lora_for_models
        comfy.sd = comfy_sd
        activations = [
            {"name": "one.safetensors", "strength_model": 0.8, "strength_clip": 0.7},
            {"name": "two.safetensors", "strength_model": 1.1, "strength_clip": 1.0},
        ]
        with patch.dict(sys.modules, {"comfy": comfy, "comfy.sd": comfy_sd}), patch(
            "prompt_library_node._load_lora_state",
            side_effect=[("state-one", {"source": "one"}), ("state-two", {"source": "two"})],
        ):
            model, clip = _apply_loras("model", "clip", activations)
        self.assertEqual((model, clip), ("model+state-one+state-two", "clip+state-one+state-two"))
        self.assertEqual([call[2] for call in calls], ["state-one", "state-two"])
        self.assertEqual(calls[0][3:], (0.8, 0.7, {"source": "one"}))

    def test_importers_are_local_and_normalized(self) -> None:
        root = Path(self.tmp.name) / "imports"
        root.mkdir()
        txt = root / "styles.txt"
        txt.write_text("# comment\nink wash\n\n// ignored\n", encoding="utf-8")
        self.assertEqual(len(parse_txt(txt)), 1)
        (root / "Character").mkdir()
        (root / "Character" / "faces.txt").write_text("round face\n", encoding="utf-8")
        self.assertIn("Character", {record["category"] for record in parse_directory(root)})
        data = root / "styles.json"
        data.write_text(json.dumps([{"name": "Named", "prompt": "positive", "negative_prompt": "omit"}]), encoding="utf-8")
        self.assertEqual(parse_json(data)[0]["negative_prompt"], "omit")
        csv_path = root / "styles.csv"
        csv_path.write_text("name,prompt\nCSV,from csv\n", encoding="utf-8")
        self.assertEqual(parse_csv(csv_path)[0]["prompt"], "from csv")

    def test_discovery_emits_library_directories_once_and_standalone_style_files(self) -> None:
        comfy = Path(self.tmp.name) / "ComfyUI"
        node = comfy / "custom_nodes" / "ExamplePack"
        wildcards = node / "wildcards"
        wildcards.mkdir(parents=True)
        (wildcards / "people.txt").write_text("person\n", encoding="utf-8")
        (wildcards / "nested.json").write_text("[]", encoding="utf-8")
        custom_wildcards = node / "custom_wildcards"
        custom_wildcards.mkdir()
        (custom_wildcards / "things.txt").write_text("thing\n", encoding="utf-8")
        empty_styles = node / "styles"
        empty_styles.mkdir()
        nested_styles = node / "js" / "styles"
        nested_styles.mkdir(parents=True)
        (nested_styles / "legitimate.txt").write_text("legitimate\n", encoding="utf-8")
        docs_wildcards = node / "docs" / "wildcards"
        docs_wildcards.mkdir(parents=True)
        (docs_wildcards / "documentation.txt").write_text("documentation\n", encoding="utf-8")
        tests_wildcards = node / "tests" / "wildcards"
        tests_wildcards.mkdir(parents=True)
        (tests_wildcards / "test-fixture.txt").write_text("fixture\n", encoding="utf-8")
        too_deep = node / "level1" / "level2" / "level3" / "level4" / "wildcards"
        too_deep.mkdir(parents=True)
        (too_deep / "deep.txt").write_text("too deep\n", encoding="utf-8")
        standalone = node / "style_library.json"
        standalone.write_text("[]", encoding="utf-8")
        (node / "workflow.json").write_text("{}", encoding="utf-8")
        sources = discover_installed_sources([comfy])
        paths = {Path(source["path"]) for source in sources}
        self.assertIn(wildcards, paths)
        self.assertIn(custom_wildcards, paths)
        self.assertIn(nested_styles, paths)
        self.assertIn(standalone, paths)
        self.assertNotIn(empty_styles, paths)
        self.assertNotIn(docs_wildcards, paths)
        self.assertNotIn(tests_wildcards, paths)
        self.assertNotIn(too_deep, paths)
        self.assertNotIn(wildcards / "people.txt", paths)
        self.assertNotIn(wildcards / "nested.json", paths)
        self.assertNotIn(node / "workflow.json", paths)
        self.assertEqual(len([path for path in paths if path == wildcards]), 1)


if __name__ == "__main__":
    unittest.main()
