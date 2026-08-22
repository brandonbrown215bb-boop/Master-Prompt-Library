# Master Prompt Library — v2 Implementation Plan

## Status

This plan is approved for implementation. It extends the shipped v1 library without changing the v1 node's serialized workflow contract.

## Confirmed product decisions

- A category can contain multiple selected entries.
- Selection order within a category is explicit and affects prompt order.
- Users can create, rename, reorder, and delete custom categories.
- The four core categories — **Style**, **Character**, **Action**, and **Background** — remain protected because v1 workflows and v2 compatibility outputs depend on them.
- Custom categories contribute to `combined_prompt` and `components_json`. They do not create arbitrary node sockets.
- Every entry can have tags, a favorite flag, one optional flat folder, multiple preview images, and a generated-image gallery.
- v2 ships more starter data automatically and can explicitly import prompt data from installed wildcard/style libraries.
- Runtime network fetching is not part of v2. Third-party content is not silently copied or redistributed.
- Prompt generation uses ComfyUI's local built-in **Generate Text** node through an ordinary STRING connection. Master Prompt Library does not call a model or external API itself.
- No companion prompt-save or image-capture nodes are added.

## Outcome

The user can open one Master Prompt Library v2 node, browse visually, select and order several reusable components from any category, and emit a deterministic assembled prompt. The same manager is the local source of truth for organizing entries and their images. Existing v1 workflows continue to load and queue.

## Scope

### In v2

- A new `MasterPromptLibraryV2` node alongside the existing `MasterPromptLibrary` node.
- Multiple ordered selections per category.
- User-defined categories with explicit display order.
- Tags, favorites, and one-level folders.
- Multiple preview images and a separate generated-image gallery on every entry.
- An expanded, redistributable bundled starter pack.
- Explicit import of common wildcard/style-library files and discoverable installed sources.
- v1-to-v2 data migration with backup and a v1 compatibility adapter.
- A documented example connecting `combined_prompt` to ComfyUI's built-in `TextGenerate` node.
- Backend, frontend, migration, importer, and local ComfyUI integration tests.

### Explicitly out of scope

- Dynamic or user-created output sockets.
- Nested folders, saved smart searches, ratings, usage history, or cross-entry relationships.
- Random wildcard expansion, combinatorial prompt generation, or a wildcard templating language.
- Automatic internet downloads, repository cloning, subscriptions, or update polling.
- External AI providers, API keys, provider abstractions, or model execution inside this node.
- Automatic capture of workflow output images. Generated images are attached through the manager's file picker.
- Negative-prompt management. Importers report but do not merge `negative_prompt` fields.
- Cloud sync, accounts, telemetry, collaboration, or a separate desktop application.
- A portable ZIP archive containing gallery binaries. Existing JSON import/export remains metadata-focused; local image directories are backed up with the normal ComfyUI user data.
- A mandatory migration of the node implementation to ComfyUI's V3 custom-node API.

## Architecture decisions

### Preserve v1 rather than mutating it

ComfyUI workflow widgets are positional. Adding v2 behavior to the existing node risks remapping old widget values. v2 therefore registers a separate node ID and leaves the v1 inputs and six outputs unchanged.

Both nodes read the v2 library through different adapters:

- v1 sees only the four core categories, one selected name per category, and the primary preview image.
- v2 works with stable category and entry IDs, ordered selection lists, metadata, and galleries.

### Do not depend on dynamic sockets

ComfyUI's V3 schema now documents `Autogrow` and `DynamicCombo`, but its current versioned API is still described as under development. Those features do not solve the requirement for an arbitrary number of user-defined output sockets without introducing workflow fragility. v2 remains on the proven node registration path and serializes its selection state in one fixed string widget managed by the frontend.

Reference: <https://docs.comfy.org/custom-nodes/v3_migration>

### Compose with local Generate Text

The built-in `TextGenerate` node accepts a multiline STRING prompt and emits generated text. v2 only needs to emit `combined_prompt`; ComfyUI owns CLIP/model selection, sampling controls, optional media context, and execution.

Reference: <https://docs.comfy.org/built-in-nodes/TextGenerate>

This keeps the library model-agnostic and avoids duplicating model-loading or sampling code.

## Data contract

The writable library advances from schema version 1 to version 2:

```json
{
  "version": 2,
  "categories": [
    {
      "id": "style",
      "key": "style",
      "name": "Style",
      "protected": true,
      "folders": [
        {"id": "uuid", "name": "Illustration"}
      ],
      "entries": [
        {
          "id": "uuid",
          "name": "Ink Wash",
          "prompt": "ink wash illustration",
          "tags": ["ink", "monochrome"],
          "favorite": true,
          "folder_id": "uuid",
          "images": [
            {
              "id": "uuid",
              "filename": "server-owned.webp",
              "media_type": "image/webp",
              "kind": "preview",
              "caption": "Primary example"
            }
          ],
          "primary_image_id": "uuid"
        }
      ]
    }
  ],
  "applied_seed_packs": [
    {"id": "master-prompt-library-core", "version": 2}
  ]
}
```

### Category rules

- Core category IDs and keys are the stable strings `style`, `character`, `action`, and `background`.
- Custom category IDs are UUIDs. Custom categories have `key: null`.
- Category names are trimmed, 1–80 characters, and unique case-insensitively.
- Array order is display and default assembly order. No separate position field is stored.
- Core categories can be renamed for display and reordered, but cannot be deleted or lose their stable IDs/keys.
- Deleting a custom category requires the user to choose another category to receive its entries or explicitly confirm permanent deletion.

### Folder and tag rules

- Folders are flat and scoped to one category.
- Folder names are trimmed, 1–80 characters, and unique case-insensitively within a category.
- Deleting a folder unfiles its entries; it never deletes them.
- An entry belongs to zero or one folder.
- Tags are trimmed strings stored directly on the entry, deduplicated case-insensitively, and sorted by their displayed spelling.
- There is no global tag table. The filter UI derives available tags from current entries.
- `favorite` is a boolean with a default of `false`.

### Entry and image rules

- Existing v1 name, prompt, UUID, and image-security limits remain unless explicitly changed here.
- Entry names remain unique case-insensitively within a category.
- `images` is ordered. Reordering the array reorders the gallery.
- `kind` is either `preview` or `generated`.
- `primary_image_id` is null or identifies one `preview` image. It supplies the library card thumbnail and the v1 compatibility image.
- An entry may have up to 20 images total, each no larger than 8 MiB, in JPEG, PNG, or WebP format.
- Captions are optional, trimmed, and limited to 240 characters.
- Image files live at `images/<entry-id>/<image-id>.<ext>` beneath the existing prompt-library data directory.
- The server generates every stored filename and verifies file signatures. Client paths and filenames are never trusted.
- Deleting an entry deletes its image directory. Deleting one image clears `primary_image_id` when necessary.

### Seed-state rules

- `applied_seed_packs` records only bundled packs that were successfully merged.
- A seed pack has a stable ID, integer version, source/credit manifest, and deterministic entry IDs.
- Applying or upgrading a pack adds missing deterministic IDs but never overwrites a user-edited entry.
- Existing v1/v2 libraries are never wholesale replaced by seed data.

## v1-to-v2 migration

Migration occurs under the store's existing process lock and atomic-write boundary:

1. Read and fully validate the existing v1 document.
2. Preserve `library.json.bak` before replacement.
3. Convert the four category maps into the ordered category array with protected core IDs.
4. Preserve every entry ID, name, and prompt.
5. Convert `image` into a one-item `images` array with `kind: preview` and set `primary_image_id`; leave both empty when v1 had no image.
6. Copy each valid legacy flat image into its staged v2 entry/image-ID path while leaving the legacy file intact.
7. Add empty tags, `favorite: false`, and `folder_id: null`.
8. Apply only missing bundled seed entries and record the seed-pack version.
9. Validate the complete v2 document, atomically replace the file, reread it, then remove successfully rehomed legacy image files.

Migration failure leaves the v1 JSON and legacy images untouched and returns a clear error. Staged copies can be retried or cleaned safely because their target names are deterministic. Repeating migration is idempotent. The v1 node adapter continues resolving its stored display-name selections from the four core categories.

## v2 node contract

### Serialized inputs

- `prompt`: optional multiline STRING.
- `selection_state`: compact JSON STRING containing stable IDs and order. The frontend hides the raw JSON behind the selector UI.
- `component_order`: compact JSON STRING containing ordered category IDs plus the reserved token `prompt`. The frontend presents this as drag ordering, not hand-edited JSON.

Default state contains no selected entries and follows current library category order, with `prompt` last.

Example selection state:

```json
{
  "version": 1,
  "selections": {
    "style": ["entry-uuid-a", "entry-uuid-b"],
    "custom-category-uuid": ["entry-uuid-c"]
  }
}
```

Rules:

- Entry array order is prompt order within that category.
- Category order is node-local so changing global library order does not silently rewrite existing workflows.
- Newly created categories are appended when the selector is next opened and remain unselected.
- Missing category or entry IDs are ignored for assembly and reported in `components_json`; they do not prevent an old workflow from queueing.
- Duplicate IDs are ignored after their first occurrence.
- Corrupt JSON fails validation with a concise message instead of emitting a misleading prompt.
- `IS_CHANGED` includes the library fingerprint and serialized selection/order state.

### Outputs

1. `combined_prompt`
2. `style_prompt`
3. `character_prompt`
4. `action_prompt`
5. `background_prompt`
6. `components_json`

The four compatibility strings join selected prompts in that category with `, `. `combined_prompt` uses the node-local category order, includes only non-empty categories/freeform text, labels each section with its current display name, and separates sections with blank lines.

`components_json` is compact and deterministic:

```json
{
  "schema_version": 1,
  "component_order": ["style", "custom-category-uuid", "prompt"],
  "categories": [
    {
      "id": "style",
      "key": "style",
      "name": "Style",
      "selected": [
        {"id": "entry-uuid-a", "name": "Ink Wash", "prompt": "ink wash illustration"}
      ]
    }
  ],
  "free_prompt": "portrait of a traveler",
  "missing_category_ids": [],
  "missing_entry_ids": []
}
```

Only categories with selected entries are included. `component_order` is normalized to known IDs and `prompt`. Keys are emitted in the documented order so tests and downstream parsing remain stable.

## Manager UX

The existing working-archive visual direction remains. v2 extends the modal rather than adding a sidebar or second application.

### On-node surface

- Keep the freeform prompt visible.
- Add one **Choose Components** button.
- Show a compact read-only summary: category name, selected count, and the first few selected names.
- Add a transient quick picker, collapsed by default, with category and search controls, six text-first rows per page, **Previous**/**Next**, and keyboard navigation.
- Quick-picker toggles write stable IDs to `selection_state` immediately and only. The quick picker has no management, gallery, filtering-management, reordering, or `component_order` surface; **Choose Components** remains the full modal and fallback.
- Show stale-selection warnings without expanding the node into a full editor.

### Browse and select

- Left rail: ordered categories, category count, add/edit controls, and drag handles.
- Filter row: search, folder, tag chips, **Favorites only**, and clear filters.
- Catalog: image-forward entry cards with checkbox selection and visible favorite state.
- Catalog pagination shows ten entries per page and renders only the current page. Changing category or filters resets the page; library refresh clamps the current page to the available range.
- Catalog keyboard navigation uses Arrow keys, **PageUp**/**PageDown**, and **Home**/**End**; **Enter** inspects the focused entry and **Space** toggles its selection.
- Selected tray: grouped by category; drag entries to order them and drag category groups to set assembly order. The freeform `Prompt` group is orderable here too.
- **Apply to Node** writes `selection_state` and `component_order` together. Closing without applying preserves the node's prior state.
- Search/filtering never changes selection order.

### Manage entries and metadata

- Entry editor retains name and prompt fields and adds tags, folder, and favorite.
- Folder creation is available inline from the folder field. Folder rename/delete lives in the category menu.
- Category deletion uses the migration-or-delete decision described in the data rules.
- Bulk editing, nested folder trees, and tag administration pages are intentionally absent.

### Image gallery

- Two tabs: **Previews** and **Generated**.
- Users can select several local files in one upload action.
- Each image supports preview, caption edit, reorder, and delete.
- Preview images additionally support **Set primary**.
- Generated images are ordinary attached local files selected from ComfyUI's output folder or elsewhere; v2 does not watch output folders or intercept workflow execution.
- Upload progress and per-file errors stay visible. One failed file does not roll back successful sibling uploads.

### Accessibility and interruption state

- Keyboard focus, visible focus rings, Escape-to-close, labelled buttons, and useful image alt text remain required.
- The modal catalog and transient quick picker are both roving-keyboard surfaces; quick-picker expansion, category, search, page, and cursor state are transient UI state and are not serialized.
- Unsaved editor changes prompt before switching entries/categories or closing.
- Manager filters, active category, and draft selection survive a close/reopen during the browser session. Quick-picker toggles write `selection_state` immediately; modal changes remain draft until **Apply to Node** commits `selection_state` and `component_order` together.

## Local API

Existing `/master_prompt_library/v1/*` routes remain for the v1 frontend. New routes use `/master_prompt_library/v2/*`.

- `GET /library` — complete validated v2 library plus fingerprint.
- `PUT /library` — validate and replace metadata for JSON import.
- `POST /categories` — create a custom category.
- `PUT /categories/{id}` — rename a category.
- `PUT /categories/order` — replace category order after validating the complete ID set.
- `DELETE /categories/{id}` — delete with `move_to_category_id` or explicit `delete_entries=true`.
- `POST /categories/{id}/folders` — create a folder.
- `PUT /categories/{id}/folders/{folder_id}` — rename a folder.
- `DELETE /categories/{id}/folders/{folder_id}` — unfile entries and delete the folder.
- `POST /entries` — create an entry.
- `PUT /entries/{id}` — update category, name, prompt, tags, favorite, and folder.
- `DELETE /entries/{id}` — delete an entry and its images.
- `GET /entries/{id}/images/{image_id}` — serve one validated image.
- `POST /entries/{id}/images` — upload one or more files with `kind`.
- `PUT /entries/{id}/images` — replace image order, captions, and primary ID as one validated metadata operation.
- `DELETE /entries/{id}/images/{image_id}` — delete one image.
- `GET /imports/sources` — list supported installed sources found in approved ComfyUI roots.
- `POST /imports/preview` — parse an uploaded file/directory or installed source and return counts, inferred categories/folders, warnings, and conflicts without writing.
- `POST /imports/apply` — apply the previewed normalized records with an explicit conflict policy.

Routes stay thin. Schema/store, image storage, import parsing, and HTTP adaptation remain separate responsibilities. Validation errors use `400`, duplicate names `409`, missing IDs `404`, unsupported media/type `415`, and oversized uploads `413`.

## Starter data and external import policy

### Bundled starter pack

The v2 core pack is applied automatically during first initialization or migration. It contains:

- the existing 281 credited Clio styles unchanged;
- at least 24 original entries each for Character, Action, and Background;
- automatically created Camera, Lighting, and Mood categories with at least 16 original entries each.

The new entries are concise reusable components, not full scene prompts. They ship without remote image URLs. Each seed file has deterministic UUID5 IDs and a manifest containing pack ID/version, entry counts, authorship/source, and licensing notes.

### Installed-library import

v2 supports explicit local import rather than runtime downloading. The first adapters are:

- plain wildcard `.txt`: one nonblank prompt per line; comments and blank lines ignored;
- directory trees of `.txt`: the selected top-level directory suggests categories and each relative parent path is flattened into one folder label;
- JSON arrays with `name` plus `prompt` or plain string values;
- CSV with `name` and `prompt` columns;
- style JSON/CSV containing `negative_prompt`: positive fields import, negative fields are counted and reported as omitted.

The source preview lets the user map inferred source groups to library categories and choose one batch conflict policy: **Skip** (default), **Rename imported**, or **Replace matching name**. Replacement is never the default.

Known installed sources may be discovered read-only beneath ComfyUI's custom-node and user wildcard directories. The initial discovery adapters target common Dynamic Prompts/Impact Pack-style wildcard directories and simple style JSON/CSV resources. Generic file/directory upload remains the fallback, so v2 is not coupled to another extension's Python APIs.

Dynamic Prompts documents the conventional one-value-per-line wildcard files and large directory-based collections; its library code is MIT-licensed. Individual prompt collections may have separate provenance, so they are importable from a user's local installation but are not bundled until their content license has been audited independently.

References:

- <https://github.com/adieyal/dynamicprompts>
- <https://github.com/adieyal/sd-dynamic-prompts/tree/main/collections>

## Generate Text workflow recipe

Ship one example workflow JSON and a README section showing:

1. `MasterPromptLibraryV2.combined_prompt` connected to `TextGenerate.prompt`.
2. A locally loaded compatible CLIP/model connected to `TextGenerate.clip`.
3. `TextGenerate.generated_text` connected to the user's normal text-conditioning or inspection path.

The example does not package a model, assume a specific model family, alter Generate Text sampling defaults, or save generated text back into the library automatically.

## Implementation structure

Keep the current modules and add only cohesive units:

- `library_store.py` — v2 schema, migration, CRUD, v1 adapter, seed merging.
- `prompt_library_node.py` — unchanged v1 class plus the v2 node and deterministic assembly.
- `image_store.py` — entry/image-ID paths and gallery operations.
- `importers.py` — normalized import records, parsers, safe installed-source discovery.
- `routes.py` — v1 routes preserved; v2 HTTP adapters added.
- `seed_library_v2.json` and `seed_manifest_v2.json` — deterministic starter data.
- `web/prompt_library_v2.js` — v2 node binding and manager orchestration.
- `web/prompt_library_v2.css` — scoped extensions to the existing visual system.
- `web/prompt_library_quick_picker.mjs` — cohesive transient six-row quick-picker controller and selection bridge.
- `web/prompt_library_quick_picker.css` — scoped quick-picker presentation and focus states.
- `web/library_v2_logic.mjs` — pure selection, ordering, filter, pagination, and keyboard-navigation helpers.
- `examples/generate_text_workflow.json` — local composition recipe.

Do not introduce a database, frontend framework, build step, dependency-injection container, repository layer, plugin system, or third-party runtime package.

## Implementation sequence and gates

### Phase 1 — schema, migration, and v1 compatibility

Implement schema v2, migration, seed-pack state, category/folder/entry validation, and the v1 read adapter.

Gate:

- A production-shaped v1 fixture migrates without ID/text loss.
- Image metadata migrates and existing files still resolve.
- Migration is atomic and idempotent.
- v1 node tests pass unchanged against the v2 store.
- Failed migration preserves the original file and backup.

### Phase 2 — v2 node and selection contract

Implement fixed serialized inputs, multi-selection resolution, ordering, compatibility outputs, `components_json`, stale-ID handling, and cache invalidation.

Gate:

- Multiple selections preserve their chosen order.
- Custom categories assemble in node-local order.
- Core outputs contain every selected prompt from their category.
- Renames do not break selections because workflows store IDs.
- Deleted IDs are reported but do not block queueing.
- Malformed selection JSON is rejected clearly.

### Phase 3 — categories, folders, tags, and favorites

Implement APIs and the v2 browse/manage/select UI, excluding galleries and import.

Gate:

- CRUD, protection rules, reordering, move-on-delete, and unfile-on-folder-delete are covered end to end.
- Search combines text, category, folder, tag, and favorite filters correctly.
- Applying/closing behavior preserves workflow and draft state as specified.
- Keyboard navigation and visible error/focus states pass manual inspection.

### Phase 4 — image galleries

Implement multi-upload, kind tabs, primary image, captions, reorder, serving, and cleanup.

Gate:

- Signature, size, count, entry/image ID, and path-boundary checks are automated.
- Partial multi-upload reports per-file results.
- Primary preview behavior and v1 thumbnail compatibility work.
- Entry/image deletion leaves no orphaned files.
- The installed ComfyUI manager displays thumbnails and full previews without remote assets.

### Phase 5 — starter pack and imports

Create original seed components, manifest/integrity checks, generic importers, installed-source discovery, preview/mapping, and conflict handling.

Gate:

- Minimum seed counts and deterministic IDs are tested.
- Seed upgrade never overwrites edited entries and is idempotent.
- Every importer rejects traversal, malformed input, oversized batches, and unsupported encodings with useful errors.
- Preview performs no writes.
- Apply results report imported, skipped, renamed, replaced, and omitted-negative counts.
- No network request occurs during initialization, discovery, preview, or apply.

### Phase 6 — Generate Text recipe, integration, and promotion

Add the example workflow and documentation, run all test suites, install accepted source into the local ComfyUI node directory, and exercise the real host.

Gate:

- The example uses the current built-in `TextGenerate` contract and needs no companion node.
- Both node IDs appear in ComfyUI object info.
- A migrated v1 workflow and a new v2 workflow both queue.
- One real manager pass covers category creation, ordered selection, metadata filtering, gallery upload, and import preview/apply.
- `combined_prompt` reaches `TextGenerate.prompt` as a STRING.
- Source and installed package match after final promotion.

## Automated verification matrix

Backend tests cover:

- v1/v2 validation, migration, backup, atomicity, fingerprinting, and concurrency;
- category/folder/entry CRUD and all destructive-operation rules;
- tags/favorites normalization;
- gallery metadata, media verification, path safety, partial upload, and cleanup;
- seed determinism, pack upgrades, edit preservation, and provenance manifest integrity;
- import parsing, mapping, conflicts, batch limits, encoding errors, and no-write preview;
- v1 and v2 node assembly, stale IDs, stable JSON, and cache invalidation;
- v1 and v2 route status/payload behavior.

Frontend tests cover pure logic for:

- ordered multi-selection and category order;
- filter intersection and available filter derivation;
- ID-preserving refresh after rename and stale-ID warnings after deletion;
- category/folder/tag normalization and duplicate checks;
- gallery reorder/primary-state transitions;
- import mapping/conflict preview transformations;
- serialization round trips for selection and component order.

Orchestrator-owned checks cover:

- source inspection for scope and backward compatibility;
- Python and JavaScript test suites;
- exact ComfyUI-environment import and route smoke;
- browser syntax/runtime console inspection;
- local installed-host interaction and workflow queueing;
- source/install parity and documentation accuracy.

## Delegation and acceptance loop

- A Luna xhigh backend agent owns schema, migration, node execution, routes, importers, and Python tests.
- A Luna xhigh frontend agent owns the v2 node UI, manager interaction, styles, pure JavaScript logic, and JavaScript tests.
- A Luna xhigh data/packaging agent owns original seed expansion, deterministic manifests, example workflow, documentation, and seed/import fixtures.
- Agents implement and report evidence; they do not review or accept their own work.
- The orchestrator reviews every changed file and runs the integrated acceptance gates.
- Any blocking finding returns to the owning Luna agent with file-level reproduction details and expected behavior. Review repeats until the orchestrator accepts the complete v2 scope.
