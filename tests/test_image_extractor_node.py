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

    def test_is_changed_tracks_image_content_at_same_path(self) -> None:
        img_path = Path(self.temp_dir.name) / "replace-me.png"
        img_path.write_bytes(b"first image bytes")
        before = MasterPromptImageExtractor.IS_CHANGED(image_path=str(img_path))

        img_path.write_bytes(b"second image bytes")
        after = MasterPromptImageExtractor.IS_CHANGED(image_path=str(img_path))

        self.assertNotEqual(before, after)

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

    @patch("prompt_library_node.query_vision_api")
    def test_structured_vision_populates_components_and_custom_clothing_target(self, mock_vision: MagicMock) -> None:
        clothing = self.store.create_category("Clothing")
        structured = {
            "positive_prompt": "a visible figure in a dark coat",
            "style": "ink wash",
            "character": "single visible figure",
            "clothing": "dark coat and scarf",
            "action": "standing",
            "background": "stone courtyard",
            "camera": "waist-up framing",
            "lighting": "soft side light",
            "mood": "quiet",
            "confidence": 0.81,
        }
        mock_vision.return_value = json.dumps(structured)
        img_path = Path(self.temp_dir.name) / "clothing.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")

        result = MasterPromptImageExtractor.extract(
            target_category=clothing["id"],
            image_path=str(img_path),
            api_endpoint="http://localhost:11434/v1",
        )
        extracted, target_prompt, style_prompt, char_prompt, action_prompt, bg_prompt, comp_json, _ = result
        self.assertEqual(extracted, structured["positive_prompt"])
        self.assertEqual(target_prompt, structured["clothing"])
        self.assertEqual(style_prompt, structured["style"])
        self.assertEqual(char_prompt, structured["character"])
        self.assertEqual(action_prompt, structured["action"])
        self.assertEqual(bg_prompt, structured["background"])
        components = json.loads(comp_json)
        self.assertEqual(components["structured"], structured)
        self.assertEqual(components["sections"]["Clothing"], structured["clothing"])
        self.assertEqual(components["confidence"], structured["confidence"])

    def test_output_arity_remains_unchanged(self) -> None:
        self.assertEqual(len(MasterPromptImageExtractor.RETURN_TYPES), 8)
        self.assertEqual(len(MasterPromptImageExtractor.RETURN_NAMES), 8)

    @patch("prompt_library_node._tensor_to_png_bytes", return_value=b"png")
    @patch("prompt_library_node.query_vision_api")
    def test_structured_vision_is_parsed_for_tensor_path(self, mock_vision: MagicMock, _png: MagicMock) -> None:
        mock_vision.return_value = json.dumps({
            "positive_prompt": "tensor prompt",
            "style": "ink",
            "character": "figure",
            "clothing": "coat",
            "action": "standing",
            "background": "courtyard",
            "camera": "close framing",
            "lighting": "soft light",
            "mood": "quiet",
            "confidence": 0.8,
        })
        result = MasterPromptImageExtractor.extract(
            target_category="auto",
            image=object(),
            api_endpoint="http://localhost:11434/v1",
        )
        self.assertEqual(result[0], "tensor prompt")
        self.assertEqual(json.loads(result[6])["structured"]["clothing"], "coat")

    @patch("prompt_library_node.query_vision_api")
    def test_extract_propagates_vision_failure(self, mock_vision: MagicMock) -> None:
        mock_vision.side_effect = RuntimeError("Vision API HTTP 401: invalid API key")
        img_path = Path(self.temp_dir.name) / "failure.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")

        with self.assertRaisesRegex(RuntimeError, "Vision API HTTP 401"):
            MasterPromptImageExtractor.extract(
                target_category="auto",
                image_path=str(img_path),
                api_endpoint="http://localhost:11434/v1",
                api_model="llava",
            )


if __name__ == "__main__":
    unittest.main()
