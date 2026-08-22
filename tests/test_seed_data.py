from __future__ import annotations

import importlib.util
import json
import os
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V1_SEED_PATH = ROOT / "seed_library.json"
V2_SEED_PATH = ROOT / "seed_library_v2.json"
MANIFEST_PATH = ROOT / "seed_manifest_v2.json"
GENERATOR_PATH = ROOT / "scripts" / "generate_seed_v2.py"
V1_CONVERTER_PATH = ROOT / "scripts" / "import_clio_styles.py"
DEFAULT_CLIO_PATH = Path(
    r"C:\Users\brand\AppData\Local\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\custom_nodes\clio-style-node\styles.json"
)
CLIO_PATH = Path(os.environ.get("CLIO_STYLES_PATH", str(DEFAULT_CLIO_PATH)))


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SeedDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        for path in (V1_SEED_PATH, V2_SEED_PATH, MANIFEST_PATH, GENERATOR_PATH, V1_CONVERTER_PATH, CLIO_PATH):
            if not path.is_file():
                raise AssertionError(f"missing seed fixture: {path}; set CLIO_STYLES_PATH to override")
        cls.v1 = json.loads(V1_SEED_PATH.read_text(encoding="utf-8"))
        cls.v2 = json.loads(V2_SEED_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.clio = json.loads(CLIO_PATH.read_text(encoding="utf-8"))
        cls.generator = _load_module(GENERATOR_PATH, "generate_seed_v2_for_test")
        cls.converter = _load_module(V1_CONVERTER_PATH, "import_clio_styles_for_test")

    def test_v1_seed_still_matches_deterministic_clio_converter(self) -> None:
        self.assertEqual(self.v1, self.converter.convert(CLIO_PATH))
        self.assertEqual(self.v1["version"], 1)
        self.assertEqual(tuple(self.v1["categories"]), ("style", "character", "action", "background"))

    def test_v2_schema_and_pack_counts(self) -> None:
        self.assertEqual(self.v2["version"], 2)
        self.assertEqual(self.v2["applied_seed_packs"], [{"id": "master-prompt-library-core", "version": 2}])
        self.assertEqual(
            [(category["key"], category["name"]) for category in self.v2["categories"]],
            [
                ("style", "Style"),
                ("character", "Character"),
                ("action", "Action"),
                ("background", "Background"),
                (None, "Camera"),
                (None, "Lighting"),
                (None, "Mood"),
            ],
        )
        self.assertEqual(
            [len(category["entries"]) for category in self.v2["categories"]],
            [281, 24, 24, 24, 16, 16, 16],
        )
        self.assertEqual(self.manifest["total_entries"], 401)
        self.assertEqual(self.manifest["pack_id"], "master-prompt-library-core")
        self.assertEqual(self.manifest["version"], 2)

    def test_checked_in_v2_files_are_generator_outputs(self) -> None:
        generated_seed = self.generator.build_seed(self.v1)
        generated_manifest = self.generator.build_manifest(generated_seed, self.v1)
        self.assertEqual(self.v2, generated_seed)
        self.assertEqual(self.manifest, generated_manifest)
        self.generator.validate_seed(self.v2, v1_seed=self.v1)

    def test_clio_style_ids_names_and_prompts_are_unchanged(self) -> None:
        styles = self.v2["categories"][0]["entries"]
        self.assertEqual(len(self.clio), 281)
        self.assertEqual(
            [(entry["id"], entry["name"], entry["prompt"]) for entry in styles],
            [(entry["id"], entry["name"], entry["prompt"]) for entry in self.v1["categories"]["style"]],
        )
        self.assertEqual(
            [(entry["name"], entry["prompt"]) for entry in styles],
            [(entry["name"], entry["prompt"]) for entry in self.clio],
        )

    def test_every_seed_entry_has_empty_user_metadata_and_no_remote_image(self) -> None:
        ids: set[str] = set()
        for category in self.v2["categories"]:
            names: set[str] = set()
            for entry in category["entries"]:
                self.assertEqual(
                    set(entry),
                    {"id", "name", "prompt", "tags", "favorite", "folder_id", "images", "primary_image_id"},
                )
                parsed_id = uuid.UUID(entry["id"])
                self.assertEqual(str(parsed_id), entry["id"])
                self.assertNotIn(entry["id"], ids)
                ids.add(entry["id"])
                self.assertNotIn(entry["name"].casefold(), names)
                names.add(entry["name"].casefold())
                self.assertEqual(entry["tags"], [])
                self.assertFalse(entry["favorite"])
                self.assertIsNone(entry["folder_id"])
                self.assertEqual(entry["images"], [])
                self.assertIsNone(entry["primary_image_id"])

    def test_original_component_ids_are_uuid5_and_manifest_keeps_clio_qualification(self) -> None:
        self.generator.validate_seed(self.v2, v1_seed=self.v1)
        self.assertEqual(self.manifest["deterministic_ids"]["algorithm"], "UUID5")
        self.assertEqual(self.manifest["sources"][0]["entry_count"], 281)
        clio_license = self.manifest["sources"][0]["license"]
        self.assertIn("u/Dear-Spend-2865", " ".join(author["name"] for author in self.manifest["authors"]))
        self.assertIn("no relicensing claim", clio_license.lower())
        self.assertIn("not claimed under the Master Prompt Library MIT license", self.manifest["licensing"]["clio_style_records"])
        self.assertFalse(self.manifest["images"]["remote_urls"])

    def test_example_workflow_connects_v2_prompt_to_builtin_text_generate(self) -> None:
        workflow = json.loads((ROOT / "examples" / "generate_text_workflow.json").read_text(encoding="utf-8"))
        nodes = {node["id"]: node for node in workflow["nodes"]}
        self.assertIn("MasterPromptLibraryV2", {node["type"] for node in workflow["nodes"]})
        self.assertIn("TextGenerate", {node["type"] for node in workflow["nodes"]})
        v2 = next(node for node in workflow["nodes"] if node["type"] == "MasterPromptLibraryV2")
        text_generate = next(node for node in workflow["nodes"] if node["type"] == "TextGenerate")
        self.assertEqual(v2["outputs"][0]["name"], "combined_prompt")
        prompt_input = next(input_ for input_ in text_generate["inputs"] if input_["name"] == "prompt")
        self.assertEqual(prompt_input["type"], "STRING")
        self.assertEqual(prompt_input["link"], v2["outputs"][0]["links"][0])
        self.assertEqual(next(node for node in nodes.values() if node["type"] == "CLIPLoader")["type"], "CLIPLoader")
        inspection = next(node for node in nodes.values() if node["type"] == "PrimitiveStringMultiline")
        self.assertEqual(inspection["outputs"][0]["type"], "STRING")


if __name__ == "__main__":
    unittest.main()
