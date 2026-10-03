# Changelog

## 2.1.0 - 2026-08-21

- Added per-concept LoRA attachments to the v2 library manager. Selected concepts
  now apply their configured model/CLIP strengths through optional node inputs,
  with deterministic de-duplication and JSON conflict reporting.
- Replaced the image-extraction Vision API text-box cluster with persisted provider
  presets, optional browser-local API-key retention, model discovery, a compact
  provider/model picker, and an explicit forget action.
- Added PEP 621 package metadata for `comfyui-master-prompt-library`, including
  the `2.1.0` version, Python 3.10-or-newer requirement, MIT license file, and
  an explicit empty third-party dependency list.
- Added push and pull-request CI validation for Python compilation/tests and
  Node.js syntax/tests on Python 3.12 and Node.js 20.
- Added ten-entry modal pagination with Arrow, PageUp/PageDown, Home/End,
  Enter-inspect, and Space-toggle keyboard controls.
- Added the collapsed six-entry text-first quick picker with modal fallback;
  quick-picker toggles write `selection_state` only.
