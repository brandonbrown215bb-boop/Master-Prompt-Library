import test from "node:test";
import assert from "node:assert/strict";

import {
  API_BASE,
  CATEGORY_ORDER,
  MAX_IMAGE_BYTES,
  NONE_VALUE,
  filterEntries,
  filterLibrary,
  hasDuplicateName,
  imageState,
  rebuildComboValues,
  thumbnailUrl,
  validateImageFile,
} from "../web/library_logic.mjs";

const entries = [
  { id: "a", name: "Warm Ink", prompt: "a quiet portrait in paper grain" },
  { id: "b", name: "Night Glass", prompt: "cinematic blue reflection" },
];

test("search matches name and prompt text case-insensitively", () => {
  assert.deepEqual(filterEntries(entries, "WARM"), [entries[0]]);
  assert.deepEqual(filterEntries(entries, "PORTRAIT grain"), [entries[0]]);
  assert.deepEqual(filterEntries(entries, "not present"), []);
});

test("category filtering never leaks another category", () => {
  const library = { categories: { style: [entries[0]], character: [entries[1]], action: [], background: [] } };
  assert.deepEqual(filterLibrary(library, "style", "glass"), []);
  assert.deepEqual(filterLibrary(library, "character", "glass"), [entries[1]]);
  assert.deepEqual(filterLibrary(library, "not-a-category", "glass"), []);
});

test("duplicate checks ignore only the record being edited", () => {
  assert.equal(hasDuplicateName(entries, "warm ink"), true);
  assert.equal(hasDuplicateName(entries, "warm ink", "a"), false);
  assert.equal(hasDuplicateName(entries, "new name", "a"), false);
  assert.equal(hasDuplicateName(entries, "  ", "a"), false);
});

test("combo rebuilding preserves valid values and resets stale/deleted values", () => {
  assert.deepEqual(rebuildComboValues(entries, "Night Glass"), {
    values: [NONE_VALUE, "Warm Ink", "Night Glass"],
    value: "Night Glass",
  });
  assert.deepEqual(rebuildComboValues(entries, "Deleted entry"), {
    values: [NONE_VALUE, "Warm Ink", "Night Glass"],
    value: NONE_VALUE,
  });
  assert.deepEqual(rebuildComboValues([], NONE_VALUE), { values: [NONE_VALUE], value: NONE_VALUE });
});

test("thumbnail URL and visual state are cache-busted and descriptive", () => {
  const entry = { id: "an id/1", name: "Warm Ink", image: { filename: "owned" } };
  assert.equal(thumbnailUrl(entry, 42), `${API_BASE}/entries/an%20id%2F1/image?cache=42`);
  assert.deepEqual(imageState(entry, 42), {
    kind: "image",
    url: `${API_BASE}/entries/an%20id%2F1/image?cache=42`,
    alt: "Preview of Warm Ink",
  });
  assert.equal(imageState({ id: "no-image", name: "Blank" }).kind, "placeholder");
  assert.match(imageState({ id: "no-image", name: "Blank" }).alt, /No preview/);
});

test("local upload validation accepts supported formats and rejects unsafe files", () => {
  assert.equal(validateImageFile({ name: "one.png", type: "image/png", size: 10 }).valid, true);
  assert.equal(validateImageFile({ name: "one.webp", type: "image/webp", size: 10 }).valid, true);
  assert.equal(validateImageFile({ name: "one.jpg", type: "image/jpeg", size: 10 }).valid, true);
  assert.equal(validateImageFile({ name: "one.svg", type: "image/svg+xml", size: 10 }).valid, false);
  const tooLarge = validateImageFile({ name: "large.png", type: "image/png", size: MAX_IMAGE_BYTES + 1 });
  assert.equal(tooLarge.valid, false);
  assert.match(tooLarge.error, /8 MiB/);
});

test("fixed category order is stable for combo refresh consumers", () => {
  assert.deepEqual(CATEGORY_ORDER, ["style", "character", "action", "background"]);
});
