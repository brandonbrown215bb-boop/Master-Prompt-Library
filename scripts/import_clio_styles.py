#!/usr/bin/env python3
"""Convert Clio's ``styles.json`` into the v1 prompt-library seed.

The conversion is deliberately small and deterministic.  Entry IDs use the
fixed UUID namespace below and the name-based key
``master-prompt-library:v1:<category>:<name>``.  The source path therefore has
no effect on the generated IDs, and rerunning this script produces the same
seed bytes for the same source data.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any


CATEGORIES = ("style", "character", "action", "background")
SEED_NAMESPACE = uuid.UUID("6f7f6e79-0f7b-5c35-9b75-2a3dfb8f6d1f")
ID_KEY_TEMPLATE = "master-prompt-library:v1:{category}:{name}"


def _load_styles(source_path: Path) -> list[dict[str, str]]:
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"unable to read Clio styles file: {source_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Clio styles file is not valid JSON: {source_path}") from exc

    if not isinstance(source, list):
        raise ValueError("Clio styles JSON must contain a top-level array")

    styles: list[dict[str, str]] = []
    names: set[str] = set()
    for index, item in enumerate(source):
        if not isinstance(item, dict):
            raise ValueError(f"Clio style at index {index} must be an object")
        name = item.get("name")
        prompt = item.get("prompt")
        if not isinstance(name, str) or not name:
            raise ValueError(f"Clio style at index {index} has no non-empty name")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError(f"Clio style {name!r} has no non-empty prompt")
        normalized_name = name.casefold()
        if normalized_name in names:
            raise ValueError(f"duplicate Clio style name (case-insensitive): {name!r}")
        names.add(normalized_name)
        # Do not trim or otherwise normalize either value: prompt data must be
        # preserved exactly as supplied by the Clio source file.
        styles.append({"name": name, "prompt": prompt})
    return styles


def convert(source_path: Path) -> dict[str, Any]:
    """Return a v1 seed document for *source_path*."""

    styles = _load_styles(source_path)
    entries = [
        {
            "id": str(uuid.uuid5(SEED_NAMESPACE, ID_KEY_TEMPLATE.format(category="style", name=item["name"]))),
            "name": item["name"],
            "prompt": item["prompt"],
            "image": None,
        }
        for item in styles
    ]
    return {
        "version": 1,
        "categories": {
            "style": entries,
            "character": [],
            "action": [],
            "background": [],
        },
    }


def write_seed(document: dict[str, Any], output_path: Path) -> None:
    """Write *document* as stable, UTF-8 JSON at *output_path*."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="path to Clio's styles.json")
    parser.add_argument("output", type=Path, help="path for the v1 seed_library.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        document = convert(args.source)
        write_seed(document, args.output)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {len(document['categories']['style'])} styles to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
