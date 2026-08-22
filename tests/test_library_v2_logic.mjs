import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  CORE_CATEGORY_IDS,
  PROMPT_TOKEN,
  availableTags,
  buildAssembledPrompt,
  defaultComponentOrder,
  filterEntriesV2,
  galleryState,
  importPreviewSummary,
  moveByOffset,
  navigateCatalogIndex,
  normalizeComponentOrder,
  normalizeImportMapping,
  normalizeLibraryPayload,
  normalizeSelectionState,
  normalizeTags,
  paginateEntries,
  reorderIds,
  selectImportFiles,
  selectImportSource,
  serializeComponentOrder,
  serializeSelectionState,
  setGalleryPrimary,
  staleSelectionIds,
  cleanPositivePrompt,
  suggestEntryName,
  parsePromptSections,
} from "../web/library_v2_logic.mjs";

const library = {
  version: 2,
  categories: [
    {
      id: "style", key: "style", name: "Style", protected: true, folders: [{ id: "f1", name: "Ink" }],
      entries: [
        { id: "s1", name: "Warm Ink", prompt: "paper grain", tags: ["ink", "Portrait", "ink"], favorite: true, folder_id: "f1", images: [{ id: "p1", kind: "preview" }, { id: "g1", kind: "generated" }], primary_image_id: "p1" },
        { id: "s2", name: "Night Glass", prompt: "blue reflection", tags: ["night"], favorite: false, folder_id: null, images: [] },
      ],
    },
    { id: "character", key: "character", name: "Character", protected: true, folders: [], entries: [{ id: "c1", name: "Traveler", prompt: "hooded", tags: ["figure"] }] },
    { id: "custom", key: null, name: "Mood", folders: [], entries: [{ id: "m1", name: "Quiet", prompt: "still", tags: ["mood"] }] },
  ],
};

test("v2 loading state preserves the modal body structure for the async render", () => {
  const source = readFileSync(new URL("../web/prompt_library_v2.js", import.meta.url), "utf8");
  const start = source.indexOf("  renderLoading() {");
  const end = source.indexOf("\n  async refreshLibrary()", start);
  assert.ok(start >= 0 && end > start, "renderLoading method should remain present");
  const method = source.slice(start, end);
  assert.doesNotMatch(method, /clear\(this\.body\)/);
  assert.match(method, /this\.body\.contains\(this\.rail\)/);
  assert.match(method, /this\.body\.contains\(this\.main\)/);
  assert.match(method, /this\.listPane\.appendChild/);
});

test("v2 catalog source wires paged status, roving cards, and keyboard cursor actions", () => {
  const source = readFileSync(new URL("../web/prompt_library_v2.js", import.meta.url), "utf8");
  assert.match(source, /const CATALOG_PAGE_SIZE = 10/);
  assert.match(source, /Page \$\{pagination\.page \+ 1\} of \$\{pagination\.pageCount\}/);
  assert.match(source, /aria-live.*polite/);
  assert.match(source, /tabindex: entry\.id === this\.cursorEntryId \? "0" : "-1"/);
  assert.match(source, /navigateCatalogIndex\(currentIndex/);
  assert.match(source, /event\.key === "Enter"/);
  assert.match(source, /event\.key === " "/);
});

test("modal keeps body and apply footer in fixed grid rows when the error is hidden", () => {
  const styles = readFileSync(new URL("../web/prompt_library_v2.css", import.meta.url), "utf8");
  const headerRule = styles.match(/\.mpl2-header\s*\{[^}]+\}/)?.[0] || "";
  const toolbarRule = styles.match(/\.mpl2-toolbar\s*\{[^}]+\}/)?.[0] || "";
  const errorRule = styles.match(/\.mpl2-error\s*\{[^}]+\}/)?.[0] || "";
  const bodyRule = styles.match(/\.mpl2-body\s*\{[^}]+\}/)?.[0] || "";
  const mainRule = styles.match(/\.mpl2-main\s*\{[^}]+\}/)?.[0] || "";
  const footerRule = styles.match(/\.mpl2-footer\s*\{[^}]+\}/)?.[0] || "";
  assert.match(headerRule, /grid-row:\s*1/);
  assert.match(toolbarRule, /grid-row:\s*2/);
  assert.match(errorRule, /grid-row:\s*3/);
  assert.match(bodyRule, /grid-row:\s*4/);
  assert.match(footerRule, /grid-row:\s*5/);
  assert.match(bodyRule, /overflow:\s*hidden/);
  assert.match(mainRule, /overflow:\s*hidden/);
  assert.match(footerRule, /position:\s*relative/);
  assert.match(footerRule, /z-index:\s*1/);
  assert.match(footerRule, /flex:\s*0\s+0\s+auto/);
});

test("normalization deduplicates tags, preserves IDs, and fills protected categories", () => {
  const result = normalizeLibraryPayload(library).library;
  assert.deepEqual(normalizeTags([" Portrait ", "ink", "INK", "portrait"]), ["ink", "Portrait"]);
  assert.deepEqual(result.categories.map((category) => category.id), ["style", "character", "custom", "action", "background"]);
  assert.deepEqual(result.categories[0].entries[0].tags, ["ink", "Portrait"]);
  assert.equal(result.categories[0].entries[0].primary_image_id, "p1");
});

test("selection and component order round trips are compact and deterministic", () => {
  const categories = normalizeLibraryPayload(library).library.categories;
  const state = normalizeSelectionState(JSON.stringify({ version: 99, selections: { style: ["s2", "s2", "s1"], custom: ["m1"] } }), categories);
  assert.deepEqual(state.selections.style, ["s2", "s1"]);
  assert.deepEqual(state.selections.action, []);
  assert.equal(serializeSelectionState(state, categories), '{"version":1,"selections":{"style":["s2","s1"],"custom":["m1"],"character":[],"action":[],"background":[]}}');
  assert.deepEqual(normalizeComponentOrder(JSON.stringify(["custom", "prompt", "style", "custom", "bad"]), categories), ["custom", "prompt", "style", "character", "action", "background"]);
  assert.equal(serializeComponentOrder(["custom", "style"], categories), '["custom","style","character","action","background","prompt"]');
  assert.deepEqual(defaultComponentOrder(categories), ["style", "character", "custom", "action", "background", "prompt"]);
});

test("prompt keeps its first requested position while duplicates and unknown IDs normalize", () => {
  const categories = normalizeLibraryPayload(library).library.categories;
  assert.deepEqual(normalizeComponentOrder(["prompt", "style", "prompt", "missing"], categories), ["prompt", "style", "character", "custom", "action", "background"]);
  assert.deepEqual(normalizeComponentOrder(["style", "prompt", "character"], categories), ["style", "prompt", "character", "custom", "action", "background"]);
  assert.deepEqual(normalizeComponentOrder(["style", "character"], categories), ["style", "character", "custom", "action", "background", "prompt"]);
  assert.deepEqual(normalizeComponentOrder(["unknown", "prompt", "unknown"], categories), ["prompt", "style", "character", "custom", "action", "background"]);
  assert.deepEqual(normalizeComponentOrder(["unknown", "prompt"], categories, { includeUnknown: true }), ["unknown", "prompt", "style", "character", "custom", "action", "background"]);
});

test("filters intersect search, folder, tag, and favorite constraints", () => {
  const entries = library.categories[0].entries.map((entry) => ({ ...entry }));
  assert.deepEqual(filterEntriesV2(entries, { query: "warm grain", folderId: "f1", tag: "portrait", favoritesOnly: true }).map((entry) => entry.id), ["s1"]);
  assert.deepEqual(filterEntriesV2(entries, { tag: "portrait", favoritesOnly: false }).map((entry) => entry.id), ["s1"]);
  assert.deepEqual(availableTags(entries), ["ink", "night", "Portrait"]);
});

test("pagination clamps pages, preserves order, and handles empty results", () => {
  const entries = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"];
  assert.deepEqual(paginateEntries(entries, 0, 10), {
    items: entries.slice(0, 10), page: 0, pageCount: 2, total: 12, start: 0, end: 10,
  });
  assert.deepEqual(paginateEntries(entries, 99, 10), {
    items: ["k", "l"], page: 1, pageCount: 2, total: 12, start: 10, end: 12,
  });
  assert.deepEqual(paginateEntries(entries, -4, 0), {
    items: entries.slice(0, 10), page: 0, pageCount: 2, total: 12, start: 0, end: 10,
  });
  assert.deepEqual(paginateEntries([], 8, 10), {
    items: [], page: 0, pageCount: 1, total: 0, start: 0, end: 0,
  });
});

test("catalog navigation clamps arrows, retains page rows, and handles Home/End", () => {
  assert.equal(navigateCatalogIndex(0, "ArrowLeft", 20), 0);
  assert.equal(navigateCatalogIndex(0, "ArrowUp", 20), 0);
  assert.equal(navigateCatalogIndex(0, "ArrowRight", 20), 1);
  assert.equal(navigateCatalogIndex(10, "ArrowDown", 20), 11);
  assert.equal(navigateCatalogIndex(8, "PageDown", 25, { pageSize: 10 }), 18);
  assert.equal(navigateCatalogIndex(18, "PageUp", 25, { pageSize: 10 }), 8);
  assert.equal(navigateCatalogIndex(5, "ArrowUp", 20, { columns: 2 }), 3);
  assert.equal(navigateCatalogIndex(3, "ArrowDown", 20, { columns: 2 }), 5);
  assert.equal(navigateCatalogIndex(7, "PageDown", 20, { pageSize: 4, columns: 2 }), 11);
  assert.equal(navigateCatalogIndex(7, "PageUp", 20, { pageSize: 4, columns: 2 }), 3);
  assert.equal(navigateCatalogIndex(7, "Home", 20), 0);
  assert.equal(navigateCatalogIndex(7, "End", 20), 19);
  assert.equal(navigateCatalogIndex(999, "Unknown", 5), 4);
  assert.equal(navigateCatalogIndex(-10, "Unknown", 5), 0);
  assert.equal(navigateCatalogIndex(0, "ArrowRight", 0), -1);
});

test("stale IDs are reported without blocking valid selections", () => {
  const categories = normalizeLibraryPayload(library).library.categories;
  const result = staleSelectionIds({ selections: { style: ["s1", "gone"], deleted: ["old"] } }, categories);
  assert.deepEqual(result, { missingCategoryIds: ["deleted"], missingEntryIds: ["gone"] });
});

test("gallery and reorder helpers preserve primary preview rules", () => {
  const entry = library.categories[0].entries[0];
  assert.deepEqual(galleryState(entry, "preview").images.map((image) => image.id), ["p1"]);
  assert.deepEqual(galleryState(entry, "generated").images.map((image) => image.id), ["g1"]);
  assert.equal(setGalleryPrimary(entry, "g1"), null);
  assert.equal(setGalleryPrimary(entry, "p1"), "p1");
  assert.deepEqual(reorderIds(["a", "b", "c"], 0, 2), ["b", "c", "a"]);
  assert.deepEqual(reorderIds(["a", "b"], 8, 0), ["a", "b"]);
  assert.deepEqual(moveByOffset(["a", "b", "c"], 1, -1), ["b", "a", "c"]);
  assert.deepEqual(moveByOffset(["a", "b", "c"], 2, 1), ["a", "b", "c"]);
});

test("import mapping and preview summary normalize alternate API shapes", () => {
  assert.deepEqual(normalizeImportMapping({ sourceA: "style", sourceB: "custom" }, [{ id: "sourceA" }]), { sourceA: "style" });
  assert.deepEqual(normalizeImportMapping({ sourceA: "style" }, []), { sourceA: "style" });
  assert.deepEqual(importPreviewSummary({ counts: { records: 4, groups: 2, conflicts: 1, omitted_negative: 3 }, warnings: ["negative_prompt omitted"] }), {
    records: 4, groups: 2, conflicts: 1, omittedNegative: 3, warnings: ["negative_prompt omitted"],
  });
});

test("import input state keeps installed sources and local files mutually exclusive", () => {
  const state = { sourceId: "installed", files: [{ name: "old.txt" }], policy: "skip" };
  assert.deepEqual(selectImportSource(state, "other-installed"), { sourceId: "other-installed", files: [], policy: "skip" });
  assert.deepEqual(selectImportFiles(state, [{ name: "local.txt" }]), { sourceId: "", files: [{ name: "local.txt" }], policy: "skip" });
});

test("core category IDs remain stable even when a custom category is present", () => {
  assert.deepEqual(CORE_CATEGORY_IDS, ["style", "character", "action", "background"]);
});

test("cleanPositivePrompt extracts only positive text and strips negative/steps", () => {
  const raw = "Cyberpunk street with rain\nNegative prompt: blurry, bad anatomy\nSteps: 20, Sampler: Euler";
  assert.equal(cleanPositivePrompt(raw), "Cyberpunk street with rain");
  assert.equal(cleanPositivePrompt("Simple prompt"), "Simple prompt");
  assert.equal(cleanPositivePrompt(""), "");
});

test("suggestEntryName formats titles from filenames or prompt snippets", () => {
  assert.equal(suggestEntryName("Style: Oil painting", "0012_space_warrior_hero.png"), "Space Warrior Hero");
  assert.equal(suggestEntryName("Cinematic portrait of an ancient wizard holding a staff"), "Cinematic portrait of an ancient wizard");
  assert.equal(suggestEntryName("", ""), "Extracted Prompt");
});

test("parsePromptSections parses section markers into category mapping", () => {
  const prompt = "Style: Synthwave neon\n\nCharacter: Robot cat\n\nBackground: Mars base\n\nMood: Dark";
  const sections = parsePromptSections(prompt, ["Mood"]);
  assert.equal(sections.Style, "Synthwave neon");
  assert.equal(sections.Character, "Robot cat");
  assert.equal(sections.Background, "Mars base");
  assert.equal(sections.Mood, "Dark");
});

test("modal wires extract image button, dropzone, and extraction handler", () => {
  const source = readFileSync(new URL("../web/prompt_library_v2.js", import.meta.url), "utf8");
  assert.match(source, /this\.extractButton = this\.actionButton\("Extract Image…"/);
  assert.match(source, /renderExtractImagePane/);
  assert.match(source, /processExtractFile/);
  assert.match(source, /saveExtractedToLibrary/);
  assert.match(source, /applyExtractedToNode/);
});

test("buildAssembledPrompt deterministically formats ordered multi-component prompts", () => {
  const categories = normalizeLibraryPayload(library).library.categories;
  const selection = {
    version: 1,
    selections: {
      style: ["s1", "s2"],
      character: ["c1"],
      custom: ["m1"],
      action: [],
      background: [],
    },
  };
  const order = ["style", "prompt", "character", "custom"];
  const assembled = buildAssembledPrompt(selection, order, categories, "masterpiece, 8k");
  assert.equal(
    assembled,
    "Style:\npaper grain, blue reflection\n\nPrompt:\nmasterpiece, 8k\n\nCharacter:\nhooded\n\nMood:\nstill"
  );

  // Empty freeform prompt is omitted cleanly
  const withoutFreeform = buildAssembledPrompt(selection, order, categories, "");
  assert.equal(
    withoutFreeform,
    "Style:\npaper grain, blue reflection\n\nCharacter:\nhooded\n\nMood:\nstill"
  );
});

test("v2 modal implements in-modal subdialogs and prompt preview drawer", () => {
  const source = readFileSync(new URL("../web/prompt_library_v2.js", import.meta.url), "utf8");
  assert.match(source, /showSubdialog\(/);
  assert.match(source, /promptDialog\(/);
  assert.match(source, /confirmDialog\(/);
  assert.match(source, /choiceDialog\(/);
  assert.match(source, /chooseCategoryDialog\(/);
  assert.match(source, /chooseFolderDialog\(/);
  assert.match(source, /buildAssembledPrompt\(/);
  assert.match(source, /mpl2-assembled-preview/);
  assert.match(source, /mpl2-caption-saved/);
});

test("v2 CSS tokens implement WCAG AA contrast and in-modal subdialog layout", () => {
  const styles = readFileSync(new URL("../web/prompt_library_v2.css", import.meta.url), "utf8");
  assert.match(styles, /--mpl2-muted:\s*#b8ab94/);
  assert.match(styles, /::placeholder\s*\{\s*color:\s*#a69a84/);
  assert.match(styles, /\.mpl2-subdialog-backdrop/);
  assert.match(styles, /\.mpl2-subdialog/);
  assert.match(styles, /\.mpl2-assembled-box/);
  assert.match(styles, /@media\s*\(forced-colors:\s*active\)/);
});

