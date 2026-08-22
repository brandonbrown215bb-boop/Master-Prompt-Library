"""Tests for image_extractor module."""

from __future__ import annotations

import io
import json
import struct
import unittest
import zlib
from unittest.mock import MagicMock, patch

from image_extractor import (
    clean_positive_prompt,
    extract_prompt_from_metadata,
    parse_prompt_sections,
    query_vision_api,
    suggest_entry_name,
)


def _make_png_with_chunks(chunks: dict[str, str], chunk_type: str = "tEXt") -> bytes:
    """Build a minimal valid PNG image with arbitrary text chunks."""
    header = b"\x89PNG\r\n\x1a\n"
    # Minimal 1x1 IHDR: width=1, height=1, bit_depth=8, color_type=2 (RGB), def=0, flt=0, int=0
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data)
    ihdr_chunk = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)

    raw_chunks: list[bytes] = [header, ihdr_chunk]

    for key, val in chunks.items():
        if chunk_type == "tEXt":
            cdata = key.encode("latin-1") + b"\x00" + val.encode("latin-1", errors="replace")
            crc = zlib.crc32(b"tEXt" + cdata)
            raw_chunks.append(struct.pack(">I", len(cdata)) + b"tEXt" + cdata + struct.pack(">I", crc))
        elif chunk_type == "zTXt":
            compressed = zlib.compress(val.encode("latin-1", errors="replace"))
            cdata = key.encode("latin-1") + b"\x00\x00" + compressed
            crc = zlib.crc32(b"zTXt" + cdata)
            raw_chunks.append(struct.pack(">I", len(cdata)) + b"zTXt" + cdata + struct.pack(">I", crc))
        elif chunk_type == "iTXt":
            # keyword \0 comp_flag comp_method lang_tag \0 trans_key \0 text
            cdata = key.encode("utf-8") + b"\x00\x00\x00\x00\x00" + val.encode("utf-8")
            crc = zlib.crc32(b"iTXt" + cdata)
            raw_chunks.append(struct.pack(">I", len(cdata)) + b"iTXt" + cdata + struct.pack(">I", crc))

    # Minimal IDAT with 1 raw pixel
    raw_pixel = b"\x00\xff\x00\x00"  # filter 0 + RGB
    compressed_idat = zlib.compress(raw_pixel)
    idat_crc = zlib.crc32(b"IDAT" + compressed_idat)
    idat_chunk = struct.pack(">I", len(compressed_idat)) + b"IDAT" + compressed_idat + struct.pack(">I", idat_crc)
    raw_chunks.append(idat_chunk)

    # IEND chunk
    iend_crc = zlib.crc32(b"IEND")
    iend_chunk = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    raw_chunks.append(iend_chunk)

    return b"".join(raw_chunks)


class ImageExtractorTests(unittest.TestCase):
    def test_clean_positive_prompt_a1111(self) -> None:
        raw = (
            "masterpiece, best quality, a cyberpunk detective in neon rain\n"
            "Negative prompt: low quality, blurry, bad anatomy\n"
            "Steps: 25, Sampler: DPM++ 2M Karras, CFG scale: 7, Seed: 4294967295, Size: 512x768, Model: cyber_v1"
        )
        self.assertEqual(clean_positive_prompt(raw), "masterpiece, best quality, a cyberpunk detective in neon rain")

    def test_clean_positive_prompt_steps_only(self) -> None:
        raw = "epic mountain landscape at sunset\nSteps: 20, Sampler: Euler"
        self.assertEqual(clean_positive_prompt(raw), "epic mountain landscape at sunset")

    def test_clean_positive_prompt_plain(self) -> None:
        raw = "  a vintage red sports car on a winding road  "
        self.assertEqual(clean_positive_prompt(raw), "a vintage red sports car on a winding road")

    def test_extract_png_tEXt_a1111(self) -> None:
        params = (
            "golden hour portrait of a cyborg warrior\n"
            "Negative prompt: ugly, deformed\n"
            "Steps: 30, Sampler: Euler a, Seed: 12345"
        )
        png_bytes = _make_png_with_chunks({"parameters": params}, chunk_type="tEXt")
        extracted = extract_prompt_from_metadata(png_bytes)
        self.assertEqual(extracted, "golden hour portrait of a cyborg warrior")

    def test_extract_png_zTXt_comfyui_prompt(self) -> None:
        comfy_prompt = {
            "3": {
                "class_type": "KSampler",
                "inputs": {"positive": ["6", 0], "negative": ["7", 0]},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "vibrant watercolor illustration of a magical forest with glowing fireflies"},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "blurry, dark"},
            },
        }
        png_bytes = _make_png_with_chunks({"prompt": json.dumps(comfy_prompt)}, chunk_type="zTXt")
        extracted = extract_prompt_from_metadata(png_bytes)
        self.assertEqual(extracted, "vibrant watercolor illustration of a magical forest with glowing fireflies")

    def test_extract_png_iTXt_master_prompt_library(self) -> None:
        comfy_prompt = {
            "10": {
                "class_type": "MasterPromptLibraryV2",
                "inputs": {"prompt": "Style: Retro Synthwave\n\nCharacter: Cyber Samurai\n\nBackground: Neon Alley"},
            }
        }
        png_bytes = _make_png_with_chunks({"prompt": json.dumps(comfy_prompt)}, chunk_type="iTXt")
        extracted = extract_prompt_from_metadata(png_bytes)
        self.assertEqual(
            extracted,
            "Style: Retro Synthwave\n\nCharacter: Cyber Samurai\n\nBackground: Neon Alley",
        )

    def test_extract_empty_or_non_image(self) -> None:
        self.assertEqual(extract_prompt_from_metadata(b""), "")
        self.assertEqual(extract_prompt_from_metadata(b"not an image at all"), "")

    def test_parse_prompt_sections(self) -> None:
        prompt = (
            "Style: Cinematic 35mm film grain, moody lighting\n\n"
            "Character: Female astronaut in retro space suit\n\n"
            "Action: Floating in zero gravity repairing a satellite\n\n"
            "Background: Orbit around Jupiter with swirling orange storms\n\n"
            "Camera: Wide angle close-up"
        )
        sections = parse_prompt_sections(prompt, category_names=["Camera", "Lighting"])
        self.assertEqual(sections["Style"], "Cinematic 35mm film grain, moody lighting")
        self.assertEqual(sections["Character"], "Female astronaut in retro space suit")
        self.assertEqual(sections["Action"], "Floating in zero gravity repairing a satellite")
        self.assertEqual(sections["Background"], "Orbit around Jupiter with swirling orange storms")
        self.assertEqual(sections["Camera"], "Wide angle close-up")

    def test_suggest_entry_name(self) -> None:
        self.assertEqual(
            suggest_entry_name("Style: Watercolor brush strokes on canvas", "00123_cyber_samurai_hero.png"),
            "Cyber Samurai Hero",
        )
        self.assertEqual(
            suggest_entry_name("Cinematic portrait of an ancient wizard holding a crystal staff"),
            "Cinematic portrait of an ancient wizard",
        )
        self.assertEqual(suggest_entry_name("", ""), "Extracted Prompt")

    @patch("urllib.request.urlopen")
    def test_query_vision_api_success(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "A majestic dragon perched on a snow-covered cliff"}}]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        result = query_vision_api(b"\x89PNG1234", endpoint="http://localhost:11434/v1", model="llava")
        self.assertEqual(result, "A majestic dragon perched on a snow-covered cliff")

    def test_query_vision_api_missing_endpoint(self) -> None:
        with self.assertRaises(ValueError):
            query_vision_api(b"\x89PNG1234", endpoint="")


if __name__ == "__main__":
    unittest.main()
