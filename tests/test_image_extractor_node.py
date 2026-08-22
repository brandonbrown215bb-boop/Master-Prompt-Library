"""Tests for MasterPromptImageExtractor node."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from library_store import LibraryStore
from prompt_library_node import MasterPromptImageExtractor, set_library_store
from tests.test_image_extractor import _make_png_with_chunks


class MasterPromptImageExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = LibraryStore(self.temp_dir.name)
        set_library_store(self.store)

    def tearDown(self) -> None:
        set_library_store(None)
        self.temp_dir.cleanup()

    def test_input_types_includes_categories(self) -> None:
        inputs = MasterPromptImageExtractor.INPUT_TYPES()
        self.assertIn("required", inputs)
        self.assertIn("target_category", inputs["required"])
        options = inputs["required"]["target_category"][0]
        self.assertIn("auto", options)
        self.assertIn("style", options)

    def test_is_changed_and_validate_inputs(self) -> None:
        self.assertTrue(MasterPromptImageExtractor.VALIDATE_INPUTS())
        fp1 = MasterPromptImageExtractor.IS_CHANGED(target_category="style", image_path="test.png")
        fp2 = MasterPromptImageExtractor.IS_CHANGED(target_category="style", image_path="test.png")
        fp3 = MasterPromptImageExtractor.IS_CHANGED(target_category="character", image_path="test.png")
        self.assertEqual(fp1, fp2)
        self.assertNotEqual(fp1, fp3)

    def test_extract_from_caption_override(self) -> None:
        raw_caption = (
            "Style: Cyberpunk neon\n\n"
            "Character: Android detective\n\n"
            "Negative prompt: low quality\n"
            "Steps: 20"
        )
        res = MasterPromptImageExtractor.extract(
            target_category="auto",
            caption_override=raw_caption,
        )
        extracted, target_prompt, style_prompt, char_prompt, action_prompt, bg_prompt, comp_json, img = res
        self.assertEqual(extracted, "Style: Cyberpunk neon\n\nCharacter: Android detective")
        self.assertEqual(target_prompt, "Style: Cyberpunk neon\n\nCharacter: Android detective")
        self.assertEqual(style_prompt, "Cyberpunk neon")
        self.assertEqual(char_prompt, "Android detective")
        self.assertEqual(action_prompt, "")
        self.assertEqual(bg_prompt, "")
        comp = json.loads(comp_json)
        self.assertEqual(comp["source_mode"], "caption_override")

    def test_extract_from_image_path_file(self) -> None:
        png_data = _make_png_with_chunks({
            "parameters": "A vintage 1950s diner at night\nNegative prompt: blur\nSteps: 25"
        })
        img_path = Path(self.temp_dir.name) / "diner.png"
        img_path.write_bytes(png_data)

        res = MasterPromptImageExtractor.extract(
            target_category="auto",
            image_path=str(img_path),
        )
        extracted, target_prompt, style_prompt, char_prompt, action_prompt, bg_prompt, comp_json, img = res
        self.assertEqual(extracted, "A vintage 1950s diner at night")
        self.assertEqual(target_prompt, "A vintage 1950s diner at night")
        comp = json.loads(comp_json)
        self.assertEqual(comp["source_mode"], "metadata")

    def test_extract_target_category_filtering(self) -> None:
        raw_caption = "Style: Anime cel shaded\n\nCharacter: Magical girl"
        res = MasterPromptImageExtractor.extract(
            target_category="style",
            caption_override=raw_caption,
        )
        extracted, target_prompt, style_prompt, char_prompt, action_prompt, bg_prompt, comp_json, img = res
        self.assertEqual(extracted, "Style: Anime cel shaded\n\nCharacter: Magical girl")
        self.assertEqual(target_prompt, "Anime cel shaded")
        self.assertEqual(style_prompt, "Anime cel shaded")
        self.assertEqual(char_prompt, "Magical girl")

    @patch("prompt_library_node.query_vision_api")
    def test_extract_with_vision_api(self, mock_vision: MagicMock) -> None:
        mock_vision.return_value = "A futuristic laboratory with glowing test tubes"
        png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00"
        img_path = Path(self.temp_dir.name) / "lab.png"
        img_path.write_bytes(png_data)

        res = MasterPromptImageExtractor.extract(
            target_category="auto",
            image_path=str(img_path),
            api_endpoint="http://localhost:11434/v1",
            api_model="llava",
        )
        extracted, target_prompt, style_prompt, char_prompt, action_prompt, bg_prompt, comp_json, img = res
        self.assertEqual(extracted, "A futuristic laboratory with glowing test tubes")
        comp = json.loads(comp_json)
        self.assertEqual(comp["source_mode"], "vision")


if __name__ == "__main__":
    unittest.main()
