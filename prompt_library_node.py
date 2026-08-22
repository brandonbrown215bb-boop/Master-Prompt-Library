"""ComfyUI node adapters for Master Prompt Library v1 and v2."""

from __future__ import annotations

import json
from typing import Any

try:
    from .library_store import CATEGORIES, NONE_SELECTION, LibraryStore, ValidationError, create_default_store
    from .image_extractor import clean_positive_prompt, extract_prompt_from_metadata, parse_prompt_sections, query_vision_api
except ImportError:  # direct source import for hermetic tests
    from library_store import CATEGORIES, NONE_SELECTION, LibraryStore, ValidationError, create_default_store
    from image_extractor import clean_positive_prompt, extract_prompt_from_metadata, parse_prompt_sections, query_vision_api


DEFAULT_COMPONENT_ORDER = "style, character, action, background, prompt"
DEFAULT_SELECTION_STATE = '{"version":1,"selections":{}}'
_DEFAULT_ORDER = ("style", "character", "action", "background", "prompt")
_STORE: LibraryStore | None = None


def set_library_store(store: LibraryStore | None) -> None:
    global _STORE
    _STORE = store


def get_library_store() -> LibraryStore:
    global _STORE
    if _STORE is None:
        _STORE = create_default_store()
    return _STORE


def _order_tokens(value: Any) -> list[str]:
    supplied = value if isinstance(value, str) else DEFAULT_COMPONENT_ORDER
    result: list[str] = []
    for token in supplied.split(","):
        normalized = token.strip().casefold()
        if normalized in _DEFAULT_ORDER and normalized not in result:
            result.append(normalized)
    result.extend(token for token in _DEFAULT_ORDER if token not in result)
    return result


def _section(label: str, value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return f"{label}: {value}" if value else ""


class MasterPromptLibrary:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        store = get_library_store()
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": "", "dynamicPrompts": False}),
                "style": (store.options("style"), {"default": NONE_SELECTION}),
                "character": (store.options("character"), {"default": NONE_SELECTION}),
                "action": (store.options("action"), {"default": NONE_SELECTION}),
                "background": (store.options("background"), {"default": NONE_SELECTION}),
                "component_order": ("STRING", {"default": DEFAULT_COMPONENT_ORDER}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("combined_prompt", "style_prompt", "character_prompt", "action_prompt", "background_prompt", "selection_summary")
    FUNCTION = "assemble"
    CATEGORY = "Prompt Library"
    DESCRIPTION = "Assemble a prompt from the shared Style, Character, Action, and Background library."

    @classmethod
    def VALIDATE_INPUTS(cls, style: str = NONE_SELECTION, character: str = NONE_SELECTION, action: str = NONE_SELECTION, background: str = NONE_SELECTION) -> bool:
        return True

    @classmethod
    def IS_CHANGED(cls, *args: Any, **kwargs: Any) -> str:
        return get_library_store().fingerprint()

    @classmethod
    def _resolve_component(cls, category: str, selection: Any) -> tuple[str, str | None]:
        if not isinstance(selection, str) or selection == NONE_SELECTION:
            return "", None
        entry = get_library_store().resolve(category, selection)
        if entry is None:
            return "", None
        return entry["prompt"], entry["name"]

    @classmethod
    def assemble(cls, prompt: str = "", style: str = NONE_SELECTION, character: str = NONE_SELECTION, action: str = NONE_SELECTION, background: str = NONE_SELECTION, component_order: str = DEFAULT_COMPONENT_ORDER) -> tuple[str, str, str, str, str, str]:
        values: dict[str, str] = {}
        selected_names: dict[str, str | None] = {}
        for category, selection in (("style", style), ("character", character), ("action", action), ("background", background)):
            values[category], selected_names[category] = cls._resolve_component(category, selection)
        values["prompt"] = prompt.strip() if isinstance(prompt, str) else ""
        labels = {"style": "Style", "character": "Character", "action": "Action", "background": "Background", "prompt": "Prompt"}
        sections = [section for token in _order_tokens(component_order) if (section := _section(labels[token], values[token]))]
        combined = "\n\n".join(sections)
        summary = json.dumps({category: selected_names[category] for category in CATEGORIES}, ensure_ascii=False, separators=(",", ":"))
        return combined, values["style"], values["character"], values["action"], values["background"], summary

    apply = assemble


def _parse_json_string(value: Any, label: str) -> Any:
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be JSON text")
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{label} is malformed JSON") from exc


def _selection_state(value: Any) -> dict[str, list[str]]:
    raw = _parse_json_string(value, "selection_state") if isinstance(value, str) else value
    if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("selections"), dict):
        raise ValidationError("selection_state must contain version 1 and selections")
    result: dict[str, list[str]] = {}
    for category_id, selected in raw["selections"].items():
        if not isinstance(category_id, str) or not isinstance(selected, list):
            raise ValidationError("selection_state selections are invalid")
        unique: list[str] = []
        for entry_id in selected:
            if not isinstance(entry_id, str):
                raise ValidationError("selection_state entry IDs are invalid")
            if entry_id not in unique:
                unique.append(entry_id)
        result[category_id] = unique
    return result


def _component_order(value: Any, known_ids: list[str]) -> list[str]:
    raw = _parse_json_string(value, "component_order") if isinstance(value, str) else value
    if not isinstance(raw, list) or any(not isinstance(token, str) for token in raw):
        raise ValidationError("component_order must be a JSON array")
    result: list[str] = []
    for token in raw:
        token = token.strip()
        if token == "prompt" or token in known_ids:
            if token not in result:
                result.append(token)
    for category_id in known_ids:
        if category_id not in result:
            result.append(category_id)
    if "prompt" not in result:
        result.append("prompt")
    return result


def _default_v2_order(store: LibraryStore) -> str:
    ids = [category["id"] for category in store.get_library().get("categories", [])]
    return json.dumps(ids + ["prompt"], ensure_ascii=False, separators=(",", ":"))


class MasterPromptLibraryV2:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        store = get_library_store()
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": "", "dynamicPrompts": False}),
                "selection_state": ("STRING", {"default": DEFAULT_SELECTION_STATE, "multiline": False}),
                "component_order": ("STRING", {"default": _default_v2_order(store), "multiline": False}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("combined_prompt", "style_prompt", "character_prompt", "action_prompt", "background_prompt", "components_json")
    FUNCTION = "assemble"
    CATEGORY = "Prompt Library"
    DESCRIPTION = "Select and deterministically assemble ordered prompt components from Master Prompt Library v2."

    @classmethod
    def VALIDATE_INPUTS(cls, selection_state: str = DEFAULT_SELECTION_STATE, component_order: str | None = None, **kwargs: Any) -> bool:
        store = get_library_store()
        _selection_state(selection_state)
        if component_order is not None:
            known = [category["id"] for category in store.get_library()["categories"]]
            _component_order(component_order, known)
        return True

    @classmethod
    def IS_CHANGED(cls, prompt: str = "", selection_state: str = DEFAULT_SELECTION_STATE, component_order: str | None = None, **kwargs: Any) -> str:
        store = get_library_store()
        payload = {"fingerprint": store.fingerprint(), "prompt": prompt if isinstance(prompt, str) else "", "selection_state": selection_state, "component_order": component_order or _default_v2_order(store)}
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def assemble(cls, prompt: str = "", selection_state: str = DEFAULT_SELECTION_STATE, component_order: str | None = None) -> tuple[str, str, str, str, str, str]:
        store = get_library_store()
        library = store.get_library()
        if library.get("version") != 2:
            raise ValidationError("MasterPromptLibraryV2 requires a v2 library")
        selections = _selection_state(selection_state)
        category_order = [category["id"] for category in library["categories"]]
        order = _component_order(component_order if component_order is not None else _default_v2_order(store), category_order)
        by_category = {category["id"]: category for category in library["categories"]}
        by_entry = {entry["id"]: (category, entry) for category in library["categories"] for entry in category["entries"]}
        missing_categories: list[str] = []
        missing_entries: list[str] = []
        selected_by_category: dict[str, list[dict[str, Any]]] = {}
        for category_id, entry_ids in selections.items():
            if category_id not in by_category:
                if category_id not in missing_categories:
                    missing_categories.append(category_id)
                continue
            selected: list[dict[str, Any]] = []
            for entry_id in entry_ids:
                found = by_entry.get(entry_id)
                if found is None or found[0]["id"] != category_id:
                    if entry_id not in missing_entries:
                        missing_entries.append(entry_id)
                    continue
                entry = found[1]
                selected.append({"id": entry["id"], "name": entry["name"], "prompt": entry["prompt"]})
            if selected:
                selected_by_category[category_id] = selected
        values: dict[str, str] = {category_id: ", ".join(item["prompt"] for item in selected_by_category.get(category_id, [])) for category_id in category_order}
        values["prompt"] = prompt.strip() if isinstance(prompt, str) else ""
        sections: list[str] = []
        categories_payload: list[dict[str, Any]] = []
        for token in order:
            if token == "prompt":
                section = _section("Prompt", values["prompt"])
            else:
                category = by_category[token]
                selected = selected_by_category.get(token, [])
                if selected:
                    categories_payload.append({"id": category["id"], "key": category["key"], "name": category["name"], "selected": selected})
                    section = _section(category["name"], values[token])
                else:
                    section = ""
            if section:
                sections.append(section)
        combined = "\n\n".join(sections)
        components = {"schema_version": 1, "component_order": order, "categories": categories_payload, "free_prompt": values["prompt"], "missing_category_ids": missing_categories, "missing_entry_ids": missing_entries}
        components_json = json.dumps(components, ensure_ascii=False, separators=(",", ":"))
        core_outputs = tuple(values.get(category, "") for category in CATEGORIES)
        return (combined, *core_outputs, components_json)

    apply = assemble


def _tensor_to_png_bytes(tensor: Any) -> bytes | None:
    if tensor is None:
        return None
    try:
        import io
        import numpy as np
        from PIL import Image

        if hasattr(tensor, "cpu"):
            tensor = tensor.cpu().numpy()
        arr = np.array(tensor)
        if arr.ndim == 4:
            arr = arr[0]
        if arr.dtype != np.uint8:
            arr = (arr * 255).clip(0, 255).astype(np.uint8)
        img = Image.fromarray(arr)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


class MasterPromptImageExtractor:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        store = get_library_store()
        category_options = ["auto"]
        try:
            lib = store.get_library()
            if lib.get("version") == 2:
                for cat in lib.get("categories", []):
                    cat_id = cat.get("id") or cat.get("name")
                    if cat_id not in category_options:
                        category_options.append(cat_id)
            else:
                category_options.extend(list(CATEGORIES))
        except Exception:
            category_options.extend(list(CATEGORIES))

        return {
            "required": {
                "target_category": (category_options, {"default": "auto"}),
            },
            "optional": {
                "image": ("IMAGE",),
                "image_path": ("STRING", {"default": "", "multiline": False}),
                "caption_override": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
                "api_endpoint": ("STRING", {"default": ""}),
                "api_key": ("STRING", {"default": ""}),
                "api_model": ("STRING", {"default": ""}),
                "vision_prompt": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "IMAGE")
    RETURN_NAMES = (
        "extracted_prompt",
        "target_prompt",
        "style_prompt",
        "character_prompt",
        "action_prompt",
        "background_prompt",
        "components_json",
        "image",
    )
    FUNCTION = "extract"
    CATEGORY = "Prompt Library"
    DESCRIPTION = "Extract positive prompts from an image via metadata or vision API, with library category mapping."

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs: Any) -> bool:
        return True

    @classmethod
    def IS_CHANGED(
        cls,
        target_category: str = "auto",
        image_path: str = "",
        caption_override: str = "",
        api_endpoint: str = "",
        api_model: str = "",
        vision_prompt: str = "",
        **kwargs: Any,
    ) -> str:
        store = get_library_store()
        payload = {
            "fingerprint": store.fingerprint(),
            "target_category": target_category,
            "image_path": image_path,
            "caption_override": caption_override,
            "api_endpoint": api_endpoint,
            "api_model": api_model,
            "vision_prompt": vision_prompt,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def extract(
        cls,
        target_category: str = "auto",
        image: Any = None,
        image_path: str = "",
        caption_override: str = "",
        api_endpoint: str = "",
        api_key: str = "",
        api_model: str = "",
        vision_prompt: str = "",
    ) -> tuple[str, str, str, str, str, str, str, Any]:
        from pathlib import Path

        store = get_library_store()
        library = store.get_library()
        v2 = library.get("version") == 2

        extracted = ""
        source_mode = "none"

        # 1. Caption override takes highest precedence if non-empty
        if isinstance(caption_override, str) and caption_override.strip():
            extracted = clean_positive_prompt(caption_override)
            source_mode = "caption_override"

        # 2. Extract from image file metadata if image_path is provided
        if not extracted and isinstance(image_path, str) and image_path.strip():
            p = Path(image_path.strip())
            if p.exists() and p.is_file():
                try:
                    file_bytes = p.read_bytes()
                    meta_prompt = extract_prompt_from_metadata(file_bytes)
                    if meta_prompt:
                        extracted = meta_prompt
                        source_mode = "metadata"
                    elif api_endpoint and api_endpoint.strip():
                        extracted = query_vision_api(file_bytes, api_endpoint, api_key, api_model, vision_prompt)
                        source_mode = "vision"
                except Exception:
                    pass

        # 3. If image tensor is provided and vision API is configured
        if not extracted and image is not None and api_endpoint and api_endpoint.strip():
            png_bytes = _tensor_to_png_bytes(image)
            if png_bytes:
                try:
                    extracted = query_vision_api(png_bytes, api_endpoint, api_key, api_model, vision_prompt)
                    source_mode = "vision"
                except Exception:
                    pass

        # Parse sections
        category_names: list[str] = []
        if v2:
            for cat in library.get("categories", []):
                category_names.append(cat["name"])
                if cat.get("key"):
                    category_names.append(cat["key"])
        else:
            category_names = list(CATEGORIES)

        sections = parse_prompt_sections(extracted, category_names) if extracted else {}

        def _get_sec(key: str) -> str:
            for k, v in sections.items():
                if k.casefold() == key.casefold():
                    return v
            return ""

        style_prompt = _get_sec("style")
        character_prompt = _get_sec("character")
        action_prompt = _get_sec("action")
        background_prompt = _get_sec("background")

        target_prompt = ""
        if target_category == "auto" or not target_category:
            target_prompt = extracted
        else:
            matched_name = target_category
            if v2:
                for cat in library.get("categories", []):
                    if cat["id"] == target_category:
                        matched_name = cat["name"]
                        break
            sec_val = _get_sec(matched_name) or _get_sec(target_category)
            target_prompt = sec_val if sec_val else extracted

        components = {
            "schema_version": 1,
            "extracted_prompt": extracted,
            "target_category": target_category,
            "target_prompt": target_prompt,
            "source_mode": source_mode,
            "sections": sections,
        }
        components_json = json.dumps(components, ensure_ascii=False, separators=(",", ":"))

        return (
            extracted,
            target_prompt,
            style_prompt,
            character_prompt,
            action_prompt,
            background_prompt,
            components_json,
            image,
        )


NODE_CLASS_MAPPINGS = {
    "MasterPromptLibrary": MasterPromptLibrary,
    "MasterPromptLibraryV2": MasterPromptLibraryV2,
    "MasterPromptImageExtractor": MasterPromptImageExtractor,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "MasterPromptLibrary": "Master Prompt Library",
    "MasterPromptLibraryV2": "Master Prompt Library v2",
    "MasterPromptImageExtractor": "Master Prompt Image Extractor",
}


__all__ = [
    "MasterPromptLibrary",
    "MasterPromptLibraryV2",
    "MasterPromptImageExtractor",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "DEFAULT_COMPONENT_ORDER",
    "DEFAULT_SELECTION_STATE",
    "set_library_store",
    "get_library_store",
]
