"""Extract prompts from image metadata (PNG, WebP, JPEG) and vision APIs.

Handles ComfyUI workflow/prompt graphs, A1111/Forge parameters, EXIF tags,
section parsing against library categories, and OpenAI/Ollama vision interrogation.
"""

from __future__ import annotations

import base64
import io
import json
import re
import struct
import urllib.error
import urllib.request
import zlib
from typing import Any, Sequence

try:
    from PIL import ExifTags, Image  # type: ignore
except ImportError:
    Image = None
    ExifTags = None


# Standard categories to check for section markers
DEFAULT_SECTION_LABELS = ("Style", "Character", "Action", "Background", "Camera", "Lighting", "Mood", "Prompt")
MAX_PROMPT_CHARS = 20_000


def clean_positive_prompt(text: str) -> str:
    """Isolate positive prompt from A1111 / WebUI parameter blocks or raw text."""
    if not isinstance(text, str):
        return ""
    cleaned = text.strip()
    if not cleaned:
        return ""

    # Check for A1111 parameter blocks
    # Format: <Positive Prompt>\nNegative prompt: <Negative Prompt>\nSteps: 20, Sampler: ...
    # Or: <Positive Prompt>\nSteps: 20, ...
    lines = cleaned.splitlines()
    positive_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^Negative\s+prompt\s*:", stripped, re.IGNORECASE):
            break
        if re.match(r"^Steps\s*:\s*\d+", stripped, re.IGNORECASE):
            break
        if re.match(r"^(?:Template|Lora\s+hashes|TI\s+hashes|Version|Size|Model\s+hash|Model|Seed|Sampler|CFG\s+scale)\s*:", stripped, re.IGNORECASE):
            break
        positive_lines.append(line)

    result = "\n".join(positive_lines).strip()
    return result[:MAX_PROMPT_CHARS]


def _extract_from_comfyui_graph(graph_data: Any) -> str:
    """Extract positive prompt text from ComfyUI prompt/workflow node graphs."""
    if not isinstance(graph_data, dict):
        return ""

    # 1. Look for prompt format: mapping of node_id -> node_info dict
    # e.g., node_info = {"class_type": "CLIPTextEncode", "inputs": {"text": "..."}}
    text_candidates: list[str] = []
    positive_node_ids: set[str] = set()

    # Find nodes connecting to positive input of samplers or MasterPromptLibrary
    for _, node in graph_data.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if isinstance(inputs, dict):
            pos_input = inputs.get("positive")
            if isinstance(pos_input, list) and len(pos_input) >= 1:
                positive_node_ids.add(str(pos_input[0]))

    # Prioritize MasterPromptLibrary nodes or positive CLIPTextEncode nodes
    for node_id, node in graph_data.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue

        if "MasterPromptLibrary" in class_type:
            # Check prompt input or selections
            prompt_val = inputs.get("prompt")
            if isinstance(prompt_val, str) and prompt_val.strip():
                text_candidates.insert(0, prompt_val.strip())

        if "CLIPTextEncode" in class_type or "ShowText" in class_type or "PrimitiveString" in class_type:
            text_val = inputs.get("text") or inputs.get("string") or inputs.get("value")
            if isinstance(text_val, str) and text_val.strip():
                if str(node_id) in positive_node_ids:
                    text_candidates.insert(0, text_val.strip())
                else:
                    text_candidates.append(text_val.strip())

    # If workflow format with "nodes" list
    if "nodes" in graph_data and isinstance(graph_data["nodes"], list):
        for node in graph_data["nodes"]:
            if not isinstance(node, dict):
                continue
            ntype = str(node.get("type", ""))
            widgets_values = node.get("widgets_values")
            if "MasterPromptLibrary" in ntype and isinstance(widgets_values, list) and widgets_values:
                first_str = next((w for w in widgets_values if isinstance(w, str) and w.strip()), None)
                if first_str:
                    text_candidates.insert(0, first_str.strip())
            elif "CLIPTextEncode" in ntype and isinstance(widgets_values, list) and widgets_values:
                first_str = next((w for w in widgets_values if isinstance(w, str) and w.strip()), None)
                if first_str:
                    text_candidates.append(first_str.strip())

    if text_candidates:
        return clean_positive_prompt(text_candidates[0])
    return ""


def _parse_png_chunks(data: bytes) -> dict[str, str]:
    """Parse PNG text chunks (tEXt, zTXt, iTXt) using pure standard library."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return {}

    metadata: dict[str, str] = {}
    pos = 8
    length = len(data)

    while pos + 8 <= length:
        chunk_len = struct.unpack(">I", data[pos : pos + 4])[0]
        chunk_type = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + chunk_len]
        pos += 12 + chunk_len  # len + type + data + 4 bytes crc

        if chunk_type == b"tEXt":
            try:
                null_idx = chunk_data.find(b"\x00")
                if null_idx != -1:
                    keyword = chunk_data[:null_idx].decode("latin-1")
                    text = chunk_data[null_idx + 1 :].decode("latin-1", errors="replace")
                    metadata[keyword] = text
            except Exception:
                pass

        elif chunk_type == b"zTXt":
            try:
                null_idx = chunk_data.find(b"\x00")
                if null_idx != -1 and len(chunk_data) > null_idx + 2:
                    keyword = chunk_data[:null_idx].decode("latin-1")
                    # chunk_data[null_idx + 1] is compression method (0 = deflate)
                    compressed = chunk_data[null_idx + 2 :]
                    decompressed = zlib.decompress(compressed).decode("latin-1", errors="replace")
                    metadata[keyword] = decompressed
            except Exception:
                pass

        elif chunk_type == b"iTXt":
            try:
                null_idx = chunk_data.find(b"\x00")
                if null_idx != -1:
                    keyword = chunk_data[:null_idx].decode("utf-8", errors="replace")
                    comp_flag = chunk_data[null_idx + 1]
                    # skip comp_method (1 byte), lang_tag (null-terminated), trans_key (null-terminated)
                    rest = chunk_data[null_idx + 3 :]
                    null2 = rest.find(b"\x00")
                    if null2 != -1:
                        rest2 = rest[null2 + 1 :]
                        null3 = rest2.find(b"\x00")
                        if null3 != -1:
                            text_bytes = rest2[null3 + 1 :]
                            if comp_flag == 1:
                                text_bytes = zlib.decompress(text_bytes)
                            metadata[keyword] = text_bytes.decode("utf-8", errors="replace")
            except Exception:
                pass

        elif chunk_type == b"IEND":
            break

    return metadata


def _parse_exif_text(data: bytes) -> dict[str, str]:
    """Parse EXIF tags from JPEG/WebP data using PIL or raw marker scan."""
    metadata: dict[str, str] = {}

    if Image is not None:
        try:
            with Image.open(io.BytesIO(data)) as img:
                info = getattr(img, "info", {})
                for k, v in info.items():
                    if isinstance(v, str):
                        metadata[str(k)] = v
                    elif isinstance(v, (bytes, bytearray)):
                        try:
                            metadata[str(k)] = v.decode("utf-8")
                        except UnicodeDecodeError:
                            metadata[str(k)] = v.decode("latin-1", errors="replace")

                exif = img.getexif() if hasattr(img, "getexif") else None
                if exif:
                    for tag_id, val in exif.items():
                        tag_name = ExifTags.TAGS.get(tag_id, str(tag_id)) if ExifTags else str(tag_id)
                        if isinstance(val, str):
                            metadata[tag_name] = val
                        elif isinstance(val, (bytes, bytearray)):
                            try:
                                metadata[tag_name] = val.decode("utf-8")
                            except UnicodeDecodeError:
                                metadata[tag_name] = val.decode("latin-1", errors="replace")
        except Exception:
            pass

    return metadata


def extract_prompt_from_metadata(data: bytes) -> str:
    """Extract positive prompt text from image bytes (PNG, WebP, JPEG)."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        return ""
    data_bytes = bytes(data)
    if not data_bytes:
        return ""

    # 1. Try PNG chunks
    if data_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        chunks = _parse_png_chunks(data_bytes)

        # Automatic1111 / Forge
        if "parameters" in chunks:
            extracted = clean_positive_prompt(chunks["parameters"])
            if extracted:
                return extracted

        # ComfyUI prompt
        if "prompt" in chunks:
            try:
                graph = json.loads(chunks["prompt"])
                extracted = _extract_from_comfyui_graph(graph)
                if extracted:
                    return extracted
            except Exception:
                pass

        # ComfyUI workflow
        if "workflow" in chunks:
            try:
                workflow = json.loads(chunks["workflow"])
                extracted = _extract_from_comfyui_graph(workflow)
                if extracted:
                    return extracted
            except Exception:
                pass

        # Generic text keys
        for key in ("Description", "Comment", "UserComment", "prompt_text", "positive_prompt"):
            if key in chunks and chunks[key].strip():
                return clean_positive_prompt(chunks[key])

    # 2. Try EXIF / PIL tags for WebP/JPEG/PNG
    exif_meta = _parse_exif_text(data_bytes)
    if "parameters" in exif_meta:
        extracted = clean_positive_prompt(exif_meta["parameters"])
        if extracted:
            return extracted

    if "prompt" in exif_meta:
        try:
            graph = json.loads(exif_meta["prompt"])
            extracted = _extract_from_comfyui_graph(graph)
            if extracted:
                return extracted
        except Exception:
            pass

    for key in ("UserComment", "ImageDescription", "Comment", "workflow", "prompt"):
        if key in exif_meta:
            val = exif_meta[key]
            if val.startswith("{") and val.endswith("}"):
                try:
                    graph = json.loads(val)
                    extracted = _extract_from_comfyui_graph(graph)
                    if extracted:
                        return extracted
                except Exception:
                    pass
            extracted = clean_positive_prompt(val)
            if extracted:
                return extracted

    return ""


def parse_prompt_sections(prompt: str, category_names: Sequence[str] | None = None) -> dict[str, str]:
    """Parse section markers (e.g. 'Style: ...', 'Character: ...') into category buckets."""
    if not isinstance(prompt, str) or not prompt.strip():
        return {}

    known_labels = set(DEFAULT_SECTION_LABELS)
    if category_names:
        for name in category_names:
            if isinstance(name, str) and name.strip():
                known_labels.add(name.strip())

    # Build regex to match section headers at line starts
    pattern = r"(?:^|\n\n|\r\n\r\n)(?P<label>[A-Za-z0-9 _\-]+):\s*(?P<content>.*?)(?=(?:\n\n|\r\n\r\n)[A-Za-z0-9 _\-]+:|$)"
    matches = list(re.finditer(pattern, prompt.strip(), re.DOTALL))

    sections: dict[str, str] = {}
    if matches:
        for match in matches:
            label = match.group("label").strip()
            content = match.group("content").strip()
            # Match against known labels case-insensitively
            matched_label = next((k for k in known_labels if k.casefold() == label.casefold()), label)
            if content:
                sections[matched_label] = content

    return sections


def suggest_entry_name(prompt: str, filename: str = "") -> str:
    """Generate a clean, human-readable suggested entry name."""
    if filename:
        clean_file = re.sub(r"\.[a-zA-Z0-9]+$", "", filename)
        clean_file = re.sub(r"^[0-9_\-]+", "", clean_file)
        clean_file = clean_file.replace("_", " ").replace("-", " ").strip()
        if len(clean_file) >= 3:
            return clean_file[:80].title()

    if prompt:
        # Take first non-section line or first sentence
        first_line = prompt.strip().splitlines()[0].strip()
        first_line = re.sub(r"^[A-Za-z0-9 _\-]+:\s*", "", first_line)
        # Take first 6 words or up to 60 chars
        words = first_line.split()
        if words:
            snippet = " ".join(words[:6])
            snippet = re.sub(r"[,;:.!?]+$", "", snippet)
            if len(snippet) >= 3:
                return snippet[:60].capitalize()

    return "Extracted Prompt"


def query_vision_api(
    image_bytes: bytes,
    endpoint: str,
    api_key: str = "",
    model: str = "",
    prompt: str = "",
    timeout: float = 30.0,
) -> str:
    """Query an OpenAI or Ollama compatible `/chat/completions` vision endpoint."""
    if not endpoint or not endpoint.strip():
        raise ValueError("Vision API endpoint URL is required")

    url = endpoint.strip()
    if not url.endswith("/chat/completions"):
        url = url.rstrip("/") + "/chat/completions" if "/v1" in url else url.rstrip("/") + "/v1/chat/completions"

    prompt_text = (
        prompt.strip()
        if prompt and prompt.strip()
        else "Describe this image in detail focusing on style, subjects, actions, lighting, and background for an image generation prompt. Respond only with the prompt text."
    )
    model_name = model.strip() if model and model.strip() else "gpt-4o-mini"

    # Encode image to base64
    b64_image = base64.b64encode(image_bytes).decode("ascii")
    # Determine media type
    if image_bytes.startswith(b"\x89PNG"):
        mime_type = "image/png"
    elif image_bytes.startswith(b"\xFF\xD8\xFF"):
        mime_type = "image/jpeg"
    elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        mime_type = "image/webp"
    else:
        mime_type = "image/png"

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{b64_image}",
                        },
                    },
                ],
            }
        ],
        "max_tokens": 1000,
    }

    req_data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            resp_bytes = response.read()
            resp_json = json.loads(resp_bytes.decode("utf-8"))
            choices = resp_json.get("choices", [])
            if choices and isinstance(choices, list):
                message = choices[0].get("message", {})
                content = message.get("content", "")
                if isinstance(content, str):
                    return content.strip()
            raise ValueError("Vision API returned an unexpected response structure")
    except urllib.error.HTTPError as exc:
        err_msg = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Vision API HTTP {exc.code}: {err_msg}") from exc
    except Exception as exc:
        raise RuntimeError(f"Vision API request failed: {exc}") from exc
