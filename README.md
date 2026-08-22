# Master Prompt Library

Master Prompt Library is a local-first ComfyUI custom node for assembling
repeatable prompts from reusable visual components. The package keeps the
original **MasterPromptLibrary** node and adds **MasterPromptLibraryV2** beside
it; old workflows continue to use the v1 contract.

This source tree describes package release **2.1.0**. It is intended for local
installation as a ComfyUI custom node; no registry publication is implied.

The source is tested against the local ComfyUI **v0.33.3** environment with
frontend **1.49.6**. It uses Python's standard library and browser APIs already
provided by ComfyUI. There is no network service, model call, or third-party
runtime dependency.

## Install from this source

1. Copy the accepted contents of this repository into a directory named
   `master-prompt-library` under `ComfyUI/custom_nodes/`.
2. Start or restart ComfyUI.
3. Add **Master Prompt Library** or **Master Prompt Library v2** from the
   **Prompt Library** node category.

The bundled `seed_library.json` is the v1 seed. `seed_library_v2.json` and
`seed_manifest_v2.json` are the v2 core pack. Seed files are read-only. On
first access, the current node copies the matching seed into the configured
ComfyUI user directory; later edits are made only to that writable copy.

## v1 node: `MasterPromptLibrary`

The v1 node has one native combo selection per fixed category:

- `prompt`: optional multiline freeform prompt text;
- `style`, `character`, `action`, `background`: one selection, beginning with
  `✨ none`;
- `component_order`: comma-separated order of the four categories and
  `prompt`, defaulting to `style, character, action, background, prompt`.

It emits `combined_prompt`, the four resolved component prompt strings, and a
compact `selection_summary`. Combined sections are labelled (`Style:`,
`Character:`, `Action:`, `Background:`, and `Prompt:`) and separated by blank
lines. Unknown or duplicate order tokens are ignored and omitted known tokens
are appended, so a typo cannot silently discard prompt content.

The v1 behavior remains one selected entry per protected category and one
preview image per entry. Existing serialized display-name selections remain
queueable if an entry is later renamed or deleted; the adapter resolves them
against the current library.

## v2 node: `MasterPromptLibraryV2`

The v2 node stores stable IDs rather than display names and supports multiple
ordered selections per category. Its serialized inputs are:

- `prompt`: optional multiline freeform text;
- `selection_state`: compact JSON containing ordered entry IDs per category;
- `component_order`: compact JSON containing ordered category IDs plus the
  reserved `prompt` token.

Its outputs are `combined_prompt`, `style_prompt`, `character_prompt`,
`action_prompt`, `background_prompt`, and deterministic `components_json`.
`combined_prompt` uses the node-local category order, includes only selected
or non-empty sections, and labels each section with its current display name.
The four compatibility outputs join all selected prompts in their category
with `, `. Missing category or entry IDs are reported in `components_json` but
do not prevent an old workflow from queueing. Malformed serialized JSON is a
validation error rather than a misleading prompt.

The manager behind v2 adds ordered custom categories, tags, favorites, one
flat folder per entry, and separate **Previews** and **Generated** galleries.
On the node, the component quick picker is collapsed by default. Expanding it
provides category and search controls, six text-first rows per page,
**Previous**/**Next**, and keyboard navigation. Its stable-ID toggles update
`selection_state` immediately and only; the picker has no management or
reordering surface. The **Choose Components** button remains available for
the full manager modal and its fallback workflow.

The modal catalog shows ten entries per page and renders only the current page.
Changing category or filters resets the page, while a library refresh clamps the
current page to the available range. Arrow keys, **PageUp**/**PageDown**, and
**Home**/**End** move through the catalog; **Enter** inspects an entry and
**Space** toggles its selection. Quick-picker toggles write only
`selection_state`; modal selection and ordering changes stay draft until
**Apply to Node**, which writes `selection_state` and `component_order`
together. Closing the modal without applying preserves the node's prior
applied state. Generated images are attached by explicit local file selection.
The node does not watch output folders or capture workflow images automatically.

## Workflow Node: `MasterPromptImageExtractor`

The `MasterPromptImageExtractor` node extracts positive prompts from input images via
embedded metadata (PNG chunks, EXIF tags, ComfyUI graphs, A1111/Forge parameter blocks)
or external Vision APIs (e.g. local Ollama, OpenAI vision endpoints).

- **Inputs**:
  - `target_category`: dropdown of available library categories (or `auto`);
  - `image`: optional `IMAGE` tensor input;
  - `image_path`: optional local image file path;
  - `caption_override`: optional string input (for chaining with external vision/caption nodes);
  - `api_endpoint`, `api_key`, `api_model`, `vision_prompt`: optional vision model configuration.
- **Outputs**:
  - `extracted_prompt`: full positive prompt extracted from metadata/vision;
  - `target_prompt`: prompt mapped to the chosen target category (or full prompt);
  - `style_prompt`, `character_prompt`, `action_prompt`, `background_prompt`: standard category strings;
  - `components_json`: structured JSON with category mappings and source metadata;
  - `image`: pass-through `IMAGE` tensor.

In the Library Manager modal, clicking **Extract Image…** provides an interactive
drag-and-drop zone with instant metadata extraction, prompt editing, category assignment,
and one-click **Add to Library** (attaching the image as a preview) or **Apply to Active Node**.

## Bundled v2 core pack

The checked-in v2 pack contains 401 records:

| Category | Entries | Kind |
| --- | ---: | --- |
| Style | 281 | credited Clio snapshot, preserved unchanged |
| Character | 24 | original reusable fragments |
| Action | 24 | original reusable fragments |
| Background | 24 | original reusable fragments |
| Camera | 16 | original reusable fragments |
| Lighting | 16 | original reusable fragments |
| Mood | 16 | original reusable fragments |

Camera, Lighting, and Mood are seeded custom categories with deterministic
UUID5 IDs. Every new component has a deterministic UUID5 entry ID. All seed
entries start with `tags: []`, `favorite: false`, `folder_id: null`,
`images: []`, and `primary_image_id: null`; the pack contains no remote image
URLs or binary gallery files.

The manifest records pack ID/version, category counts, UUID5 namespace and
templates, content digest, authorship, source, and licensing/provenance notes.
The pack is applied by ID and version: missing records are added, but a user
edited record is never overwritten by a later seed application.

To regenerate the v2 files from the installed Clio source and the checked-in
v1 snapshot:

```text
python scripts/generate_seed_v2.py --clio-source C:\path\to\clio-style-node\styles.json
```

The command performs a source match before writing `seed_library_v2.json` and
`seed_manifest_v2.json`. It performs no network access.

Use `--check` with the same arguments to validate the checked-in files without
writing them.

## Migration and local storage

The writable library lives under ComfyUI's user directory:

```text
<ComfyUI user directory>/prompt_library/library.json
<ComfyUI user directory>/prompt_library/images/<entry-id>/<image-id>.<ext>
```

Migration from a v1 document happens under the store's process lock and
atomic-write boundary. It first validates the complete source and keeps
`library.json.bak`, then converts the four category maps to the v2 ordered
array. Entry IDs, names, prompts, and valid legacy preview references are
preserved. Legacy image files remain in place while deterministic v2 copies
are staged; only successfully rehomed files are removed after the replacement
is reread. Missing v2 seed records are then applied and the pack version is
recorded. Repeating migration is idempotent.

If validation or staging fails, the original JSON and legacy images remain
untouched. Before any replacement, the store validates the current document;
it refuses to overwrite malformed user data. JSON import/export is metadata
focused and does not create a portable gallery archive. Gallery binaries stay
in the local `images/` directory and must be backed up with the normal
ComfyUI user-data backup. A JSON backup alone cannot restore those files.

## Explicit import safety and provenance

Imports are opt-in and local. Initialization, source discovery, preview, and
apply make no network requests and never clone repositories or download
wildcard corpora. The supported adapters accept:

- plain wildcard `.txt` files (one nonblank, non-comment prompt per line);
- selected directory trees of `.txt` files, with relative parents flattened
  into folder labels;
- JSON arrays containing strings or objects with `name` and `prompt`;
- CSV files with `name` and `prompt` columns;
- positive fields from style records that also contain `negative_prompt`.

Negative prompts are counted and reported, not merged into positive entries.
Preview parses and normalizes without writing. Apply requires an explicit
source-to-category mapping and one batch conflict policy: **Skip** (default),
**Rename imported**, or **Replace matching name**. Replacement is never the
default. Path traversal, unsupported encodings/types, oversized batches, and
unsupported media are rejected at the boundary. Installed-source discovery
is read-only beneath approved local ComfyUI custom-node and wildcard roots;
generic file/directory upload remains the fallback.

No third-party wildcard collection is bundled. An imported local collection
retains its own provenance and is the user's responsibility to license.

## Compose with local Generate Text

`MasterPromptLibraryV2.combined_prompt` is an ordinary `STRING` output. It can
feed ComfyUI's built-in **Generate Text** node (`TextGenerate.prompt`), which
owns CLIP/model loading, sampling, and text generation. The example workflow
is [examples/generate_text_workflow.json](examples/generate_text_workflow.json).
It contains only built-in `CLIPLoader`, `TextGenerate`, and
`PrimitiveStringMultiline` nodes around the library node:

1. Replace `YOUR_LOCAL_TEXT_ENCODER.safetensors` in `CLIPLoader` with a
   compatible text encoder available on the host (the example does not ship a
   model).
2. Keep its `CLIP` output connected to `TextGenerate.clip`.
3. The library's `combined_prompt` is connected to `TextGenerate.prompt`.
4. `generated_text` is sent to the built-in multiline string node for
   inspection; connect that output to the user's normal downstream path as
   needed.

The current local `TextGenerate` contract has optional image, video, and audio
inputs plus `max_length`, sampling, thinking, and template controls. The
example leaves those at host defaults. It is structurally valid, but it cannot
queue until the placeholder text-encoder filename is replaced by a model that
exists in the local ComfyUI installation.

## Troubleshooting

- **Node is missing:** confirm the folder is directly under
  `ComfyUI/custom_nodes/`, then restart ComfyUI and inspect its startup log.
- **Dropdowns or the manager are stale:** refresh the browser after a frontend
  change; close and reopen an old modal after a library mutation.
- **Library will not load:** preserve `prompt_library/library.json`; inspect it
  and use `library.json.bak` only after confirming that it is the last known
  good document.
- **Image rejected:** use a real JPEG, PNG, or WebP no larger than 8 MiB.
  SVG and arbitrary files are intentionally not accepted.
- **An old workflow references a deleted entry:** v1 resolves it as empty;
  v2 reports a stale ID in `components_json` and remains queueable.
- **Generate Text cannot queue:** replace the example's placeholder
  `YOUR_LOCAL_TEXT_ENCODER.safetensors` with a compatible local encoder.

## v1 boundaries

v1 intentionally has one selection per fixed category and one preview image
per entry. It does not include user-defined categories, tags, favorites,
ratings, folders, galleries, usage history, cloud sync, accounts, telemetry,
network access, prompt generation, model calls, or arbitrary-library format
migration. Those are v2 concerns where documented above.

## Clio prompt-data credit and license

The bundled Style records are the 281 entries from the installed Clio Style
Library source (`styles.json`), preserved in source order with name, prompt,
and existing entry IDs unchanged. Clio's README credits the style prose to
[u/Dear-Spend-2865](https://www.reddit.com/user/Dear-Spend-2865), described as
community-shared wildcard prompt text (283 original entries, deduped there to
281). Master Prompt Library claims the MIT license only for its original code
and original v2 component prose. The Clio style descriptions are included
with this credit and qualification and are not claimed under that license.
See [seed_manifest_v2.json](seed_manifest_v2.json) and `LICENSE` for the
complete notice.

The v1 converter remains available for reproducing the source-order snapshot:

```text
python scripts/import_clio_styles.py C:\path\to\clio-style-node\styles.json seed_library.json
```

It uses UUID5 with the fixed namespace
`6f7f6e79-0f7b-5c35-9b75-2a3dfb8f6d1f` and the stable name
`master-prompt-library:v1:<category>:<name>`. Re-running it for the same source
produces stable IDs and source-order output.
