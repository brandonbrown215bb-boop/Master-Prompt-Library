#!/usr/bin/env python3
"""Build the deterministic Master Prompt Library v2 core pack.

The checked-in v1 seed is the canonical snapshot of the installed Clio data.
This generator wraps those records in the v2 metadata shape and adds the
small, original component vocabulary below.  It deliberately does not fetch
anything: a Clio source file can be supplied as an optional verification
input, but the generated pack is entirely local and reproducible.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable


PACK_ID = "master-prompt-library-core"
PACK_VERSION = 2
SEED_NAMESPACE = uuid.UUID("6f7f6e79-0f7b-5c35-9b75-2a3dfb8f6d1f")
CORE_CATEGORY_IDS = ("style", "character", "action", "background")
CUSTOM_CATEGORY_SPECS = (
    ("camera", "Camera", 16),
    ("lighting", "Lighting", 16),
    ("mood", "Mood", 16),
)


# These are component fragments rather than scene prompts.  Keep the source
# vocabulary as data so adding a component does not require changing the
# pack-building logic.  Every phrase is original to this pack.
COMPONENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "character": (
        ("Weathered Cartographer", "weathered cartographer with ink-stained fingers, a brass compass, and an alert, patient gaze"),
        ("Curious Street Magician", "curious street magician in a patched coat, quick hands, and a half-hidden smile"),
        ("Retired Airship Captain", "retired airship captain with a sun-faded uniform, a steady stance, and a voice worn by altitude"),
        ("Quiet Mechanic", "quiet mechanic with rolled sleeves, graphite-smudged knuckles, and careful attention to every moving part"),
        ("Young Archivist", "young archivist carrying tied bundles of notes, round spectacles, and a habit of listening before speaking"),
        ("Marshland Guide", "marshland guide in layered rain gear, practical boots, and a reed whistle at the collar"),
        ("Ceramicist", "ceramicist with clay-dusted forearms, a linen apron, and a thoughtful tilt of the head"),
        ("Night Courier", "night courier with a weatherproof satchel, reflective trim, and an unhurried stride"),
        ("Mountain Herbalist", "mountain herbalist with woven baskets, wind-reddened cheeks, and a calm knowledge of local plants"),
        ("Observant Violinist", "observant violinist with a worn instrument case, neat cuffs, and an expression held in reserve"),
        ("Rooftop Gardener", "rooftop gardener with sun-browned hands, a patched canvas hat, and pockets full of seed packets"),
        ("Riverboat Cook", "riverboat cook in a striped apron, sturdy clogs, and a ladle used like a conductor's baton"),
        ("Lighthouse Keeper", "lighthouse keeper with a wool coat, a ring of brass keys, and eyes adjusted to distant weather"),
        ("Cautious Diplomat", "cautious diplomat in an immaculate travel coat, measured gestures, and a notebook kept close"),
        ("Amateur Astronomer", "amateur astronomer with a folding star chart, a red scarf, and an eager crease between the brows"),
        ("Patient Woodcarver", "patient woodcarver with a small plane, curled shavings on the floor, and a quiet concentration"),
        ("Festival Drummer", "festival drummer with painted palms, layered cloth, and a bright rhythm waiting in the shoulders"),
        ("Canal Locksmith", "canal locksmith with a leather tool roll, narrow spectacles, and a fondness for difficult mechanisms"),
        ("Field Naturalist", "field naturalist with a canvas notebook, mud-marked trousers, and a respectful distance from every creature"),
        ("Theatre Carpenter", "theatre carpenter with a measuring tape, sawdust on the boots, and a backstage composure"),
        ("Snowbound Messenger", "snowbound messenger in a quilted parka, insulated gloves, and a sealed letter under the coat"),
        ("Market Storyteller", "market storyteller with a patched shawl, expressive hands, and an audience gathered close"),
        ("Ferry Engineer", "ferry engineer with oil-darkened cuffs, a wool cap, and an instinct for the river's changing pull"),
        ("Glassblower", "glassblower with heat-flushed features, protective lenses, and a measured breath shaping molten glass"),
    ),
    "action": (
        ("Walking Against Wind", "walking steadily against a strong crosswind, coat hem and loose fabric streaming behind"),
        ("Reaching for Light", "reaching toward a narrow shaft of light with the hand held just inside its warmth"),
        ("Turning to Listen", "turning slightly to listen, attention shifting toward a sound beyond the frame"),
        ("Marking a Map", "marking a map with a blunt pencil, pausing to compare the lines with the surrounding terrain"),
        ("Opening a Rusted Gate", "opening a rusted gate with both hands, metal resisting before giving way with a slow swing"),
        ("Balancing on Loose Stone", "balancing on loose stone with knees flexed and weight placed carefully between uncertain footholds"),
        ("Gathering Fallen Papers", "gathering windblown papers into a neat stack, smoothing each page before adding it"),
        ("Lighting a Small Lamp", "lighting a small oil lamp, cupping one hand around the flame until the wick steadies"),
        ("Crossing Shallow Water", "crossing shallow water in deliberate steps, ripples widening around each careful footfall"),
        ("Brushing Dust Away", "brushing dust from an old surface with a soft cloth, revealing a pattern beneath the grime"),
        ("Looking Over the Shoulder", "looking over one shoulder while continuing forward, expression alert without breaking stride"),
        ("Pulling a Rope", "pulling a heavy rope in a steady rhythm, shoulders engaged and hands resetting after each draw"),
        ("Setting Down a Pack", "setting down a travel pack and rolling the shoulders loose after a long carry"),
        ("Tracing a Carved Mark", "tracing a carved mark with one fingertip, following its edges as if reading a raised script"),
        ("Shielding the Eyes", "shielding the eyes from glare with one hand while searching the distance"),
        ("Stepping Through Fog", "stepping slowly through dense fog, one foot testing the ground before the next advances"),
        ("Folding a Letter", "folding a letter along its existing creases, then holding it still for a moment"),
        ("Tending a Small Fire", "tending a small fire with a short iron poker, shifting coals until the heat evens out"),
        ("Climbing a Narrow Stair", "climbing a narrow stair with one hand on the rail and the body angled toward the wall"),
        ("Swapping a Tool", "swapping one tool for another without looking down, attention fixed on the work in progress"),
        ("Waving from a Distance", "waving from a distance with a restrained, recognizable gesture across the open space"),
        ("Drawing a Curtain", "drawing a heavy curtain aside, releasing a vertical slice of the room beyond"),
        ("Holding a Door", "holding a door open with one foot while motioning another person through"),
        ("Settling Into a Chair", "settling into a worn chair, exhaling as the posture shifts from travel to rest"),
    ),
    "background": (
        ("Mossy Stone Courtyard", "mossy stone courtyard with rain-dark paving, shallow steps, and a dry fountain at the center"),
        ("Wind-Carved Cliff Path", "wind-carved cliff path above a wide valley, marked by low cairns and tough grass"),
        ("Lantern-Lit Market Lane", "lantern-lit market lane with canvas awnings, close-set stalls, and damp cobbles"),
        ("Abandoned Observatory", "abandoned observatory with a split dome, dusty brass instruments, and a view of open sky"),
        ("Willow Riverbank", "willow-lined riverbank with exposed roots, slow water, and flat stones along the edge"),
        ("Winter Orchard", "winter orchard with bare branches, pale grass, and rows fading into a low morning mist"),
        ("Tile-roofed Harbor", "tile-roofed harbor with moored skiffs, salt-stained posts, and narrow water between the piers"),
        ("Cedar Workshop", "cedar workshop with long benches, stacked boards, and curled shavings gathered near the tools"),
        ("Glasshouse Interior", "glasshouse interior filled with broad leaves, fogged panes, and paths of worn brick"),
        ("Highland Train Platform", "highland train platform with iron lamps, a weathered bench, and mountains behind the tracks"),
        ("Flooded Library Basement", "flooded library basement with floating pages, brick pillars, and shelves rising from dark water"),
        ("Rope Bridge Gorge", "rope bridge crossing a narrow gorge, timber planks uneven beneath a bright open sky"),
        ("Quiet Canal Lock", "quiet canal lock with painted guide rails, still water, and a small keeper's hut"),
        ("Cliffside Monastery", "cliffside monastery with pale walls, wind bells, and terraces stepping toward the sea"),
        ("Foggy Pine Clearing", "foggy pine clearing with soft needles underfoot, dark trunks, and a break in the clouds overhead"),
        ("Sunken Garden", "sunken garden with worn statues, climbing vines, and geometric paths below the surrounding walls"),
        ("Red Earth Quarry", "red earth quarry with stepped walls, abandoned carts, and angular shadows across the floor"),
        ("Riverside Ferry Landing", "riverside ferry landing with a low dock, coiled ropes, and reeds bending along the bank"),
        ("Copper-roofed Station", "copper-roofed station with tall windows, tiled platforms, and a clock above the entrance"),
        ("Underpass Mural", "concrete underpass with a layered mural, puddled pavement, and traffic glow beyond the opening"),
        ("Moonlit Salt Flats", "moonlit salt flats stretching to a low horizon, cracked crust reflecting thin bands of light"),
        ("Heather-covered Moor", "heather-covered moor with low stone walls, rolling ground, and distant rain curtains"),
        ("Rusted Shipyard", "rusted shipyard with skeletal hulls, stacked chains, and weeds growing through the concrete"),
        ("Candlelit Reading Room", "candlelit reading room with tall shelves, green-shaded lamps, and a long communal table"),
    ),
    "camera": (
        ("Eye-Level Medium Shot", "eye-level medium shot with balanced headroom and the subject framed from the waist up"),
        ("Low Three-Quarter View", "low three-quarter view that gives the subject a grounded, quietly imposing presence"),
        ("High Overhead Angle", "high overhead angle that organizes the subject and nearby surfaces into a readable pattern"),
        ("Close Portrait Crop", "close portrait crop centered on the face, with breathing room around the eyes and mouth"),
        ("Wide Establishing Frame", "wide establishing frame that places the subject within the full scale of the surrounding space"),
        ("Profile Silhouette", "clean profile silhouette with the face turned toward the strongest open area of the frame"),
        ("Centered Symmetry", "centered symmetrical composition with measured negative space on both sides"),
        ("Off-Center Balance", "off-center framing balanced by a strong architectural or environmental shape opposite the subject"),
        ("Long-Lens Compression", "long-lens compression that layers distant planes into a calm, flattened arrangement"),
        ("Ground-Level Perspective", "ground-level perspective with foreground texture leading the eye toward the subject"),
        ("Over-the-Shoulder View", "over-the-shoulder view that keeps the nearer figure soft while directing attention outward"),
        ("Top-Down Detail", "top-down detail view arranged around hands, tools, and the immediate working surface"),
        ("Doorway Framing", "doorway framing that uses the near architectural edge as a natural border around the subject"),
        ("Diagonal Tracking Frame", "diagonal tracking frame that gives the composition forward momentum without visible motion blur"),
        ("Negative-Space Portrait", "negative-space portrait with the subject held to one side and a quiet field opening beside them"),
        ("Distant Watcher View", "distant watcher view with the subject small against the setting and the foreground partially obscuring the frame"),
    ),
    "lighting": (
        ("Soft Window Key", "soft window key light from one side, with gentle falloff across the face and surrounding surfaces"),
        ("Overcast Daylight", "even overcast daylight with restrained shadows and clean, low-contrast color"),
        ("Warm Practical Glow", "warm practical glow from nearby lamps, leaving the room edges in softer amber shadow"),
        ("Cool Dawn Fill", "cool dawn fill that separates blue-gray planes while keeping the darkest areas readable"),
        ("Rim Light Through Haze", "thin rim light through light haze, outlining shoulders and edges without flattening the form"),
        ("Broken Leaf Shadows", "broken leaf shadows shifting across the subject and ground in a loose natural pattern"),
        ("Candle Cluster Light", "small candle cluster light with layered flicker, warm centers, and deep but detailed falloff"),
        ("High Noon Sun", "high noon sun with compact shadows directly beneath forms and crisp highlights on exposed surfaces"),
        ("Storm-Filtered Light", "storm-filtered light with a muted sky, cool reflections, and occasional brighter breaks"),
        ("Neon Edge Accent", "subtle neon edge accent separating the silhouette from a darker urban background"),
        ("Lantern Side Light", "lantern side light that warms one plane while leaving the opposite plane softly modeled"),
        ("Moonlit Backlight", "moonlit backlight with a pale edge around the subject and gentle blue-gray ambient fill"),
        ("Reflective Water Bounce", "soft reflected light bouncing upward from nearby water, brightening lower surfaces"),
        ("Dusty Skylight", "dusty skylight diffused through high windows, making suspended particles visible in the upper air"),
        ("Hard Slatted Shadow", "hard slatted shadow crossing the scene in parallel bands, with clear graphic separation"),
        ("Firelight and Blue Fill", "warm firelight on the near side balanced by a cool blue fill from the surrounding night"),
    ),
    "mood": (
        ("Quiet Resolve", "quiet resolve held beneath a composed surface, steady and unwilling to rush"),
        ("Restless Anticipation", "restless anticipation gathering in small pauses, quick glances, and unfinished movement"),
        ("Tender Nostalgia", "tender nostalgia shaped by familiar details and the ache of returning to them"),
        ("Measured Curiosity", "measured curiosity that observes closely before choosing where to reach"),
        ("Earnest Wonder", "earnest wonder meeting the unfamiliar with attention rather than spectacle"),
        ("Weathered Calm", "weathered calm that has survived difficult conditions without becoming hard"),
        ("Playful Defiance", "playful defiance carried by a bright expression and a refusal to be intimidated"),
        ("Solitary Focus", "solitary focus narrowing the world to one task, one sound, or one line of sight"),
        ("Muted Relief", "muted relief arriving after strain, visible in softened shoulders and a longer breath"),
        ("Distant Grief", "distant grief kept just below the surface, present in stillness rather than display"),
        ("Cautious Hope", "cautious hope leaving room for disappointment while still making the next choice"),
        ("Bright Companionship", "bright companionship built from shared rhythm, easy trust, and room for laughter"),
        ("Hushed Suspicion", "hushed suspicion turning ordinary details into questions without an obvious answer"),
        ("Ceremonial Gravity", "ceremonial gravity giving each gesture weight and each pause a deliberate shape"),
        ("Open-Ended Adventure", "open-ended adventure with the route uncertain and the horizon inviting another step"),
        ("Sleepy Contentment", "sleepy contentment settling over familiar surroundings at the end of a long day"),
    ),
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _source_digest(styles: Iterable[dict[str, str]]) -> str:
    payload = [{"name": item["name"], "prompt": item["prompt"]} for item in styles]
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _uuid_for(kind: str, category: str, name: str) -> str:
    return str(uuid.uuid5(SEED_NAMESPACE, f"master-prompt-library:v2:{kind}:{category}:{name}"))


def _entry_v2(entry: dict[str, Any], *, preserve_id: bool = False, category: str = "") -> dict[str, Any]:
    entry_id = entry["id"] if preserve_id else _uuid_for("entry", category, entry["name"])
    return {
        "id": entry_id,
        "name": entry["name"],
        "prompt": entry["prompt"],
        "tags": [],
        "favorite": False,
        "folder_id": None,
        "images": [],
        "primary_image_id": None,
    }


def _category(category_id: str, key: str | None, name: str, entries: list[dict[str, Any]], *, protected: bool) -> dict[str, Any]:
    return {
        "id": category_id,
        "key": key,
        "name": name,
        "protected": protected,
        "folders": [],
        "entries": entries,
    }


def load_v1_seed(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read v1 seed: {path}") from exc
    if document.get("version") != 1 or not isinstance(document.get("categories"), dict):
        raise ValueError("v1 seed must contain version 1 and category maps")
    if tuple(document["categories"]) != CORE_CATEGORY_IDS:
        raise ValueError("v1 seed categories do not match the four protected categories")
    styles = document["categories"]["style"]
    if not isinstance(styles, list) or len(styles) != 281:
        raise ValueError("v1 seed must contain exactly 281 Clio styles")
    for entry in styles:
        if not isinstance(entry, dict) or not all(isinstance(entry.get(key), str) for key in ("id", "name", "prompt")):
            raise ValueError("v1 style entries must contain string id, name, and prompt")
    return document


def build_seed(v1_seed: dict[str, Any]) -> dict[str, Any]:
    """Build and validate the v2 seed document from the checked-in v1 seed."""

    styles = [_entry_v2(entry, preserve_id=True, category="style") for entry in v1_seed["categories"]["style"]]
    categories: list[dict[str, Any]] = [
        _category("style", "style", "Style", styles, protected=True),
    ]
    for key in ("character", "action", "background"):
        entries = [
            _entry_v2({"name": name, "prompt": prompt}, category=key)
            for name, prompt in COMPONENTS[key]
        ]
        categories.append(_category(key, key, key.title(), entries, protected=True))
    for key, display_name, _minimum in CUSTOM_CATEGORY_SPECS:
        entries = [
            _entry_v2({"name": name, "prompt": prompt}, category=key)
            for name, prompt in COMPONENTS[key]
        ]
        category_id = _uuid_for("category", key, display_name)
        categories.append(_category(category_id, None, display_name, entries, protected=False))

    document = {
        "version": 2,
        "categories": categories,
        "applied_seed_packs": [{"id": PACK_ID, "version": PACK_VERSION}],
    }
    validate_seed(document, v1_seed=v1_seed)
    return document


def build_manifest(seed: dict[str, Any], v1_seed: dict[str, Any]) -> dict[str, Any]:
    counts = {category["name"]: len(category["entries"]) for category in seed["categories"]}
    style_entries = v1_seed["categories"]["style"]
    return {
        "id": PACK_ID,
        "pack_id": PACK_ID,
        "version": PACK_VERSION,
        "schema_version": 2,
        "name": "Master Prompt Library Core",
        "description": "Original reusable prompt components plus the credited Clio style snapshot.",
        "total_entries": sum(counts.values()),
        "category_counts": counts,
        "authors": [
            {
                "name": "Master Prompt Library contributors",
                "role": "Original Character, Action, Background, Camera, Lighting, and Mood components",
                "license": "MIT",
            },
            {
                "name": "u/Dear-Spend-2865",
                "role": "Author credited by the Clio Style Library for the 281 style descriptions",
                "source": "Installed Clio Style Library styles.json",
            },
        ],
        "sources": [
            {
                "name": "Clio Style Library",
                "path": "custom_nodes/clio-style-node/styles.json",
                "category": "Style",
                "entry_count": len(style_entries),
                "content_sha256": _source_digest(style_entries),
                "content_digest_algorithm": "SHA-256 over canonical UTF-8 JSON [{name,prompt}] records in source order",
                "provenance": "The 281 style records are copied in source order with name, prompt, and existing UUID unchanged.",
                "license": "The Clio README describes this community-shared prompt text as credited to u/Dear-Spend-2865 and does not claim it under the Clio code MIT license. This pack preserves that qualification and makes no relicensing claim.",
            },
            {
                "name": "Master Prompt Library original component set",
                "path": "scripts/generate_seed_v2.py",
                "category": "Character, Action, Background, Camera, Lighting, Mood",
                "entry_count": sum(len(COMPONENTS[key]) for key in COMPONENTS if key != "style"),
                "provenance": "Written for this pack as concise reusable component fragments; no remote corpus or third-party wildcard collection was imported.",
                "license": "MIT, as original project content.",
            },
        ],
        "licensing": {
            "code_and_original_components": "MIT License; see LICENSE.",
            "clio_style_records": "Included with the attribution and qualification above. They are not claimed under the Master Prompt Library MIT license.",
            "redistribution_note": "Redistributors must retain the Clio attribution and must not describe the style prose as original Master Prompt Library content.",
        },
        "deterministic_ids": {
            "algorithm": "UUID5",
            "namespace": str(SEED_NAMESPACE),
            "entry_name_template": "master-prompt-library:v2:entry:<category-key>:<display-name>",
            "category_name_template": "master-prompt-library:v2:category:<category-key>:<display-name>",
        },
        "images": {
            "included": False,
            "remote_urls": False,
            "note": "All seed entries start with empty preview and generated-image galleries.",
        },
    }


def validate_seed(document: dict[str, Any], *, v1_seed: dict[str, Any] | None = None) -> None:
    if document.get("version") != 2 or not isinstance(document.get("categories"), list):
        raise ValueError("v2 seed must contain version 2 and an ordered category array")
    categories = document["categories"]
    expected_names = ("Style", "Character", "Action", "Background", "Camera", "Lighting", "Mood")
    if tuple(category.get("name") for category in categories) != expected_names:
        raise ValueError("v2 seed categories are missing or out of order")
    seen_categories: set[str] = set()
    seen_entries: set[str] = set()
    for category in categories:
        category_id = category.get("id")
        if not isinstance(category_id, str) or not category_id:
            raise ValueError("seed category IDs must be non-empty strings")
        if category_id in seen_categories:
            raise ValueError("duplicate seed category ID")
        seen_categories.add(category_id)
        if category.get("key") in CORE_CATEGORY_IDS:
            if not category.get("protected"):
                raise ValueError("core categories must be protected")
            category_key = category["key"]
        elif category.get("key") is not None or category.get("protected"):
            raise ValueError("custom categories must have null key and protected false")
        else:
            matches = [key for key, display_name, _minimum in CUSTOM_CATEGORY_SPECS if display_name.casefold() == category.get("name", "").casefold()]
            if len(matches) != 1:
                raise ValueError("custom category name is not part of the core pack")
            category_key = matches[0]
            if category_id != _uuid_for("category", category_key, category["name"]):
                raise ValueError(f"non-deterministic category ID for {category['name']!r}")
        entries = category.get("entries")
        if not isinstance(entries, list):
            raise ValueError("seed category entries must be lists")
        names: set[str] = set()
        for entry in entries:
            required = ("id", "name", "prompt", "tags", "favorite", "folder_id", "images", "primary_image_id")
            if set(entry) != set(required):
                raise ValueError(f"seed entry fields are invalid for {entry.get('name')!r}")
            entry_id = entry["id"]
            try:
                uuid.UUID(entry_id)
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError("seed entry IDs must be UUIDs") from exc
            if entry_id in seen_entries:
                raise ValueError("duplicate seed entry ID")
            seen_entries.add(entry_id)
            name_key = entry["name"].casefold()
            if name_key in names:
                raise ValueError("duplicate entry name within seed category")
            names.add(name_key)
            if not isinstance(entry["prompt"], str) or not entry["prompt"].strip():
                raise ValueError("seed prompts must be non-empty strings")
            if entry["tags"] != [] or entry["favorite"] is not False or entry["folder_id"] is not None:
                raise ValueError("seed metadata defaults must be empty")
            if entry["images"] != [] or entry["primary_image_id"] is not None:
                raise ValueError("seed images must be empty")
            if category_key in COMPONENTS and category_key != "style":
                expected_id = _uuid_for("entry", category_key, entry["name"])
                if entry_id != expected_id:
                    raise ValueError(f"non-deterministic entry ID for {entry['name']!r}")
    if not isinstance(document.get("applied_seed_packs"), list) or document["applied_seed_packs"] != [{"id": PACK_ID, "version": PACK_VERSION}]:
        raise ValueError("seed pack application marker is invalid")
    for key, _display_name, minimum in CUSTOM_CATEGORY_SPECS:
        category = next(item for item in categories if item.get("key") is None and item["name"].casefold() == key)
        if len(category["entries"]) < minimum:
            raise ValueError(f"{category['name']} needs at least {minimum} entries")
    if len(next(item for item in categories if item.get("key") == "style")["entries"]) != 281:
        raise ValueError("Style must contain exactly 281 Clio entries")
    if v1_seed is not None:
        v1_styles = v1_seed["categories"]["style"]
        v2_styles = next(item for item in categories if item.get("key") == "style")["entries"]
        if [(entry["id"], entry["name"], entry["prompt"]) for entry in v2_styles] != [
            (entry["id"], entry["name"], entry["prompt"]) for entry in v1_styles
        ]:
            raise ValueError("Clio style IDs, names, or prompts changed")


def write_json(value: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _load_clio_styles(path: Path) -> dict[str, Any]:
    converter_path = Path(__file__).with_name("import_clio_styles.py")
    spec = importlib.util.spec_from_file_location("import_clio_styles_for_v2", converter_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"could not load Clio converter: {converter_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.convert(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--v1-seed", type=Path, default=root / "seed_library.json")
    parser.add_argument("--clio-source", type=Path, help="optional installed styles.json to verify against the v1 seed")
    parser.add_argument("--output", type=Path, default=root / "seed_library_v2.json")
    parser.add_argument("--manifest-output", type=Path, default=root / "seed_manifest_v2.json")
    parser.add_argument("--check", action="store_true", help="validate checked-in outputs without writing them")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        v1_seed = load_v1_seed(args.v1_seed)
        if args.clio_source is not None:
            source_seed = _load_clio_styles(args.clio_source)
            if source_seed["categories"]["style"] != v1_seed["categories"]["style"]:
                raise ValueError("v1 seed does not match the supplied Clio styles.json")
        seed = build_seed(v1_seed)
        manifest = build_manifest(seed, v1_seed)
        if args.check:
            checked_seed = json.loads(args.output.read_text(encoding="utf-8"))
            checked_manifest = json.loads(args.manifest_output.read_text(encoding="utf-8"))
            if checked_seed != seed or checked_manifest != manifest:
                raise ValueError("checked-in v2 seed or manifest differs from deterministic generator output")
        else:
            write_json(seed, args.output)
            write_json(manifest, args.manifest_output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.check:
        print(f"checked {manifest['total_entries']} entries and manifest; outputs are deterministic")
    else:
        print(f"wrote {manifest['total_entries']} entries to {args.output}")
        print(f"wrote manifest to {args.manifest_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
