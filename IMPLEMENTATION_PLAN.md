# Master Prompt Library — v1 Implementation Plan

## Product decisions

The user confirmed the proposed defaults and added visual recognition plus configurable ordering:

- One selection per fixed category: **Style**, **Character**, **Action**, and **Background**.
- Every category has a `✨ none` selection.
- The node accepts an optional freeform prompt.
- Outputs are the assembled prompt, the four resolved component prompts, and a compact JSON selection summary.
- Component ordering is controlled by one plain node string, defaulting to `style, character, action, background, prompt`.
- Style is seeded from the installed Clio library; Character, Action, and Background begin empty.
- Every entry can have one optional local JPEG, PNG, or WebP preview image for visual recognition.
- The library is shared by all workflows and stored beneath ComfyUI's configured user directory.
- Management is local-only: browse, search, add, edit, duplicate, delete, import, and export.
- Source is built in this workspace. Installation into ComfyUI is a separate final promotion after review.

## Scope boundary

### In v1

- One `MasterPromptLibrary` ComfyUI node.
- Four fixed component categories.
- One selection per category.
- Native combo widgets plus one **Browse & Manage Library** button.
- A searchable modal library manager opened from the node.
- Image attachment, replacement, removal, thumbnail display, and full preview for each entry.
- JSON persistence with validation and atomic replacement.
- Live refresh of component combo choices after a library mutation.
- Bundled Clio Style seed and first-run initialization.
- JSON import/export of the complete library.
- Python tests, lightweight JavaScript tests for pure logic, and a ComfyUI import/smoke check.
- Concise README with installation, usage, storage, backup, and v1 limits.

### Explicitly out of scope

- Multiple selections within one category.
- User-defined categories.
- Tags, favorites, generated galleries, multiple images, folders, ratings, or usage history.
- Cloud sync, accounts, telemetry, network access, prompt generation, or model calls.
- A separate sidebar or settings application.
- React/Vue/build tooling or third-party runtime dependencies.
- Automatic migration from arbitrary prompt-library formats.
- Embedding image binaries in JSON export or providing a portable image-bundle format.

## User workflow

1. Add **Master Prompt Library** from the `Prompt Library` node category.
2. Enter optional freeform text and choose any Style, Character, Action, or Background from native combos.
3. Click **Browse & Manage Library** for search and management.
4. In the modal, choose a category, search names and prompt text, use thumbnails to recognize entries, inspect the prompt and larger preview, and select the entry for the active node.
5. Add, edit, duplicate, or delete entries and attach, replace, or remove one preview image. Mutations persist immediately and refresh all Master Prompt Library nodes in the open workflow.
6. Adjust the component-order string when a model needs a different prompt order.
7. Queue the workflow. The backend resolves the current library text and emits labelled, separated prompt sections.

## Data contract

Bundled seed file and writable library use the same versioned shape:

```json
{
  "version": 1,
  "categories": {
    "style": [{"id": "uuid", "name": "Name", "prompt": "Text", "image": null}],
    "character": [],
    "action": [],
    "background": []
  }
}
```

Rules:

- Categories are a fixed allowlist and always appear in the order above.
- IDs are UUID strings and remain stable across edits.
- Names are trimmed, 1–120 characters, and unique case-insensitively within a category.
- Prompt text is trimmed, non-empty, and limited to 20,000 characters.
- `image` is either `null` or server-owned metadata containing a generated filename and media type. Client-supplied paths are never trusted.
- Unknown fields are ignored on individual entries; malformed categories or entries reject the write.
- The writable file is `<ComfyUI user directory>/prompt_library/library.json`.
- Preview files live in `<ComfyUI user directory>/prompt_library/images/` and are always named from the entry UUID.
- Uploads are limited to 8 MiB and accepted only when their file signature is JPEG, PNG, or WebP. SVG and arbitrary files are rejected.
- On first access, the bundled `seed_library.json` is copied into that location.
- Writes are serialized with a process lock, written to a sibling temporary file, flushed, and replaced atomically.
- Before replacement, the prior valid library is retained as `library.json.bak`.
- Reads that encounter invalid JSON raise a clear error and do not silently overwrite user data.

## Backend contract

### Files

- `__init__.py` — node registration, `WEB_DIRECTORY`, exported mappings.
- `prompt_library_node.py` — ComfyUI node only.
- `library_store.py` — schema validation, first-run seeding, CRUD, import, atomic persistence, lookup, fingerprint.
- `routes.py` — thin aiohttp request/response adapter.
- `image_store.py` — image signature validation, generated paths, safe serving, replacement, and removal.
- `seed_library.json` — Clio Style entries plus empty remaining categories.

### Local API

- `GET /master_prompt_library/v1/library` — return the validated complete library.
- `POST /master_prompt_library/v1/entries` — create one entry; return `201` and the entry.
- `PUT /master_prompt_library/v1/entries/{id}` — update name/prompt/category for an existing entry.
- `DELETE /master_prompt_library/v1/entries/{id}` — delete one entry.
- `PUT /master_prompt_library/v1/library` — validate and replace the complete library for import.
- `GET /master_prompt_library/v1/entries/{id}/image` — serve an attached preview by resolved entry ID.
- `POST /master_prompt_library/v1/entries/{id}/image` — multipart upload or replacement of one preview.
- `DELETE /master_prompt_library/v1/entries/{id}/image` — remove one preview and clear its metadata.

Responses use JSON. Validation failures return `400`; duplicate names return `409`; missing IDs return `404`; unexpected failures return a short `500` message without filesystem paths or tracebacks.

### Node inputs

- `prompt`: multiline `STRING`, default empty.
- `style`, `character`, `action`, `background`: native combos, `✨ none` followed by current library names in stored order.
- `component_order`: `STRING`, default `style, character, action, background, prompt`.

`VALIDATE_INPUTS` accepts stale/deleted combo selections so old workflows still queue; unresolved selections become empty components. `IS_CHANGED` includes the library fingerprint so editing an entry invalidates cached output.

### Node outputs

1. `combined_prompt`
2. `style_prompt`
3. `character_prompt`
4. `action_prompt`
5. `background_prompt`
6. `selection_summary`

Assembly includes only non-empty labelled sections. `component_order` is parsed as a comma-separated list of the five fixed tokens. Unknown and duplicate tokens are ignored; omitted known tokens are appended in the default order so a typo cannot silently discard prompt content. The default order is:

1. `Style: ...`
2. `Character: ...`
3. `Action: ...`
4. `Background: ...`
5. `Prompt: ...`

Sections are separated by blank lines. `selection_summary` is compact JSON containing the four selected display names, using `null` for unresolved or `none` selections.

## Frontend contract

### Files

- `web/prompt_library.js` — extension registration, node button, API adapter, modal behavior, combo refresh.
- `web/prompt_library.css` — scoped modal styling.
- `web/library_logic.mjs` — pure filter/sort/validation helpers usable from the browser and Node-based tests.

### Interaction model

- `app.registerExtension` adds a non-serialized button only to `MasterPromptLibrary` nodes.
- One singleton modal is reused rather than created per node.
- Modal layout: fixed-category rail, search and count header, entry list, and editor/detail pane.
- Entry rows show a small image thumbnail or a restrained text placeholder; the detail pane shows the larger preview.
- Clicking an entry previews its full prompt. **Use Selection** writes its name into the matching category combo on the node that opened the modal.
- Add begins a blank editor in the active category.
- Edit updates the selected entry.
- Duplicate creates `Copy of <name>` and requires a unique final name before save.
- Delete requires explicit confirmation and clears matching selections from open nodes after success.
- Image attachment uses a local file picker. Replacement and removal are explicit actions; accepted formats and the 8 MiB limit are visible beside the control.
- Import uses a file picker, parses JSON client-side for an early error, requires replacement confirmation, then sends the whole document to the backend.
- Export downloads the current validated prompt records as UTF-8 JSON. Preview binaries remain in the local image directory and are not embedded in v1 JSON export; imported missing image references are cleared by backend validation.
- Successful writes refetch the authoritative library and update `widget.options.values` on every open Master Prompt Library node.
- API errors remain visible in the modal until the next action; no silent failure.

### Visual direction

A compact, dark **working archive**: charcoal surfaces, warm paper labels, muted brass accent, restrained borders, image-forward catalog rows, and dense but readable copy. It should feel like a prompt catalog used at a workbench, not a generic purple-gradient dashboard. It must remain legible with ComfyUI's dark canvas, use no remote assets, and support keyboard focus, Escape to close, labelled controls, useful alt text, and visible focus states.

## Verification and acceptance

### Automated backend coverage

- First-run seed copy creates the user library without mutating the bundled seed.
- All 281 Clio styles are present and other categories are empty.
- CRUD works across all four categories.
- Case-insensitive duplicate names are rejected within a category but allowed across categories.
- Invalid category, blank/oversized name, blank/oversized prompt, malformed UUID, and malformed import are rejected.
- Image signature, size, safe generated filename, replacement, removal, missing image, and deleted-entry cleanup are covered.
- Update and delete missing IDs return the correct not-found behavior.
- Atomic save leaves parseable JSON and creates a last-good backup after the first replacement.
- Invalid on-disk JSON is reported and never overwritten automatically.
- Node default/custom assembly order, invalid/duplicate/missing order tokens, omission of empty sections, component outputs, summary JSON, stale selection behavior, and cache fingerprint are covered.

### Automated frontend coverage

- Search matches names and prompt text case-insensitively.
- Category filtering never leaks entries from another category.
- Duplicate-name checks are case-insensitive and exclude the entry being edited.
- Combo value rebuilding preserves valid selections and resets deleted selections to `✨ none`.
- Thumbnail URL building, image-state updates, and local upload validation behave deterministically.

### Integration checks owned by the orchestrator

- Import the package using the exact ComfyUI v0.33.1 Python environment with a temporary user directory.
- Confirm node mappings, display name, `WEB_DIRECTORY`, input contract, output contract, and 281-style seed count.
- Exercise the registered aiohttp handlers, store boundary, and image boundary against a temporary data root.
- Run JavaScript syntax/tests with the bundled Node.js runtime.
- Install/copy the accepted files into a separate `master-prompt-library` custom-node directory only after source review.
- Start or reuse local ComfyUI, confirm `/object_info/MasterPromptLibrary`, extension loading, modal rendering, one CRUD round trip, one image attach/preview/remove round trip, live combo refresh, custom ordering, workflow queue, and output text.
- Preserve the user's existing Clio checkout and all unrelated custom nodes.

## Delegation and review loop

- Luna backend agent owns backend files and backend tests.
- Luna frontend agent owns browser files and frontend tests.
- Luna packaging agent owns seed conversion, README, license/credits, and seed integrity tests.
- Agents implement only; they do not review or accept their own work.
- The orchestrator reviews the merged source, runs all checks, and returns concrete defects to the owning Luna agent. This repeats until the orchestrator's final review accepts every requirement above.
