import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  QUICK_PICKER_PAGE_SIZE,
  QUICK_PICKER_GRID_COLUMNS,
  entryImageUrl,
  navigateQuickPickerIndex,
  paginateQuickPicker,
  primaryImageForEntry,
  quickPickerEntries,
  shouldRefreshQuickPickerOnExpand,
  toggleQuickPickerSelection,
} from "../web/prompt_library_quick_picker.mjs";

const library = {
  version: 2,
  categories: [
    {
      id: "style",
      name: "Style",
      entries: [
        {
          id: "s1",
          name: "Warm Ink",
          prompt: "paper grain",
          primary_image_id: "img1",
          images: [
            { id: "img1", kind: "preview", caption: "Warm Ink Preview" },
            { id: "img2", kind: "generated", caption: "Generated Result" },
          ],
        },
        { id: "s2", name: "Night Glass", prompt: "blue reflection", images: [] },
        { id: "s3", name: "Paper Cut", prompt: "paper edge" },
      ],
    },
    { id: "character", name: "Character", entries: [{ id: "c1", name: "Traveler", prompt: "hooded" }] },
  ],
};

test("quick-picker pagination clamps to six rows and handles empty pages", () => {
  const entries = Array.from({ length: 13 }, (_, index) => `entry-${index}`);
  assert.equal(QUICK_PICKER_PAGE_SIZE, 6);
  assert.deepEqual(paginateQuickPicker(entries, 0).items, entries.slice(0, 6));
  assert.deepEqual(paginateQuickPicker(entries, 99).items, entries.slice(12));
  assert.deepEqual(paginateQuickPicker([], 99), { items: [], page: 0, pageCount: 1, total: 0, start: 0, end: 0 });
});

test("quick-picker keeps large categories bounded to one rendered page", () => {
  const entries = Array.from({ length: 281 }, (_, index) => ({ id: `entry-${index}` }));
  const page = paginateQuickPicker(entries, 12);
  assert.equal(page.total, 281);
  assert.equal(page.page, 12);
  assert.equal(page.pageCount, 47);
  assert.equal(page.start, 72);
  assert.equal(page.end, 78);
  assert.equal(page.items.length, QUICK_PICKER_PAGE_SIZE);
  assert.ok(page.items.length < entries.length);
});

test("quick-picker filters the active category by text without leaking other categories", () => {
  assert.deepEqual(quickPickerEntries(library, "style", "paper").entries.map((entry) => entry.id), ["s1", "s3"]);
  assert.deepEqual(quickPickerEntries(library, "character", "paper").entries, []);
  assert.deepEqual(quickPickerEntries(library, "character", "hood").entries.map((entry) => entry.id), ["c1"]);
});

test("quick-picker image helpers resolve primary preview image and build URLs", () => {
  const entryWithImage = library.categories[0].entries[0];
  const entryWithoutImage = library.categories[0].entries[1];

  const primary = primaryImageForEntry(entryWithImage);
  assert.equal(primary?.id, "img1");
  assert.equal(primary?.kind, "preview");

  assert.equal(primaryImageForEntry(entryWithoutImage), null);
  assert.equal(primaryImageForEntry(null), null);

  assert.equal(
    entryImageUrl("/master_prompt_library/v2", entryWithImage, primary),
    "/master_prompt_library/v2/entries/s1/images/img1"
  );
  assert.equal(entryImageUrl("/master_prompt_library/v2", entryWithoutImage, null), "");
});

test("quick-picker selection appends once, removes one ID, and preserves unrelated categories", () => {
  const initial = { version: 1, selections: { style: ["s1"], character: ["c1"], custom: ["m1"] } };
  const appended = toggleQuickPickerSelection(initial, "style", "s2", true);
  assert.deepEqual(appended.selections, { style: ["s1", "s2"], character: ["c1"], custom: ["m1"] });
  assert.deepEqual(toggleQuickPickerSelection(appended, "style", "s2", true), appended);
  assert.deepEqual(toggleQuickPickerSelection(appended, "style", "s1", false).selections, { style: ["s2"], character: ["c1"], custom: ["m1"] });
});

test("quick-picker keyboard navigation uses 2D grid columns and global boundaries", () => {
  assert.equal(QUICK_PICKER_GRID_COLUMNS, 3);
  // ArrowUp from 0 stays 0
  assert.equal(navigateQuickPickerIndex(0, "ArrowUp", 20, { columns: 3 }), 0);
  // ArrowLeft from 1 goes to 0
  assert.equal(navigateQuickPickerIndex(1, "ArrowLeft", 20, { columns: 3 }), 0);
  // ArrowRight from 1 goes to 2
  assert.equal(navigateQuickPickerIndex(1, "ArrowRight", 20, { columns: 3 }), 2);
  // ArrowDown from 0 jumps a row (3 items) to index 3
  assert.equal(navigateQuickPickerIndex(0, "ArrowDown", 20, { columns: 3 }), 3);
  // ArrowUp from 4 goes up one row to index 1
  assert.equal(navigateQuickPickerIndex(4, "ArrowUp", 20, { columns: 3 }), 1);
  // PageDown jumps by pageSize
  assert.equal(navigateQuickPickerIndex(4, "PageDown", 20, { columns: 3, pageSize: 6 }), 10);
  // PageUp jumps backwards by pageSize
  assert.equal(navigateQuickPickerIndex(10, "PageUp", 20, { columns: 3, pageSize: 6 }), 4);
  assert.equal(navigateQuickPickerIndex(10, "Home", 20, { columns: 3 }), 0);
  assert.equal(navigateQuickPickerIndex(10, "End", 20, { columns: 3 }), 19);
  assert.equal(navigateQuickPickerIndex(999, "ArrowDown", 5, { columns: 3 }), 4);
  assert.equal(navigateQuickPickerIndex(0, "ArrowDown", 0, { columns: 3 }), -1);
});

test("quick-picker paging navigation crosses rendered page boundaries coherently", () => {
  const options = { columns: 3, pageSize: QUICK_PICKER_PAGE_SIZE };
  assert.equal(navigateQuickPickerIndex(5, "PageDown", 281, options), 11);
  assert.equal(navigateQuickPickerIndex(11, "PageDown", 281, options), 17);
  assert.equal(navigateQuickPickerIndex(6, "PageUp", 281, options), 0);
  assert.equal(navigateQuickPickerIndex(17, "Home", 281, options), 0);
  assert.equal(navigateQuickPickerIndex(17, "End", 281, options), 280);
});

test("quick-picker refreshes only on collapsed-to-expanded transitions", () => {
  assert.equal(shouldRefreshQuickPickerOnExpand(false, true), true);
  assert.equal(shouldRefreshQuickPickerOnExpand(true, true), false);
  assert.equal(shouldRefreshQuickPickerOnExpand(true, false), false);
  assert.equal(shouldRefreshQuickPickerOnExpand(false, false), false);
});

test("quick-picker wiring is idempotent, fallback-safe, and does not write component order", () => {
  const source = readFileSync(new URL("../web/prompt_library_quick_picker.mjs", import.meta.url), "utf8");
  const styles = readFileSync(new URL("../web/prompt_library_quick_picker.css", import.meta.url), "utf8");
  const entry = readFileSync(new URL("../web/prompt_library_v2.js", import.meta.url), "utf8");
  assert.match(source, /node\.addDOMWidget\(/);
  assert.match(source, /node\.__mpl2QuickPicker/);
  assert.match(source, /if \(!node \|\| node\.__mpl2QuickPicker\)/);
  assert.match(source, /catch \{/);
  assert.match(source, /return \{\s*minWidth: 180,\s*minHeight:/);
  assert.match(source, /maxWidth: 10000,\s*maxHeight: 10000/);
  assert.doesNotMatch(source, /return \[width/);
  assert.match(source, /const wasExpanded = this\.expanded/);
  assert.match(source, /if \(shouldRefreshQuickPickerOnExpand\(wasExpanded, this\.expanded\)\)/);
  assert.match(source, /await this\.loadLibrary\(\)/);
  assert.match(source, /if \(this\.loading\) return;/);
  assert.match(source, /markLayoutDirty\(\)/);
  assert.match(source, /aria-multiselectable.*true/);
  assert.match(source, /Previous/);
  assert.match(source, /Next/);
  assert.match(source, /role.*status.*aria-live.*polite/);
  assert.match(source, /this\.page\s*=\s*0/);
  assert.match(source, /paginateQuickPicker\(entries, this\.page/);
  assert.match(source, /for \(const \[pageIndex, entry\] of pagination\.items\.entries\(\)\)/);
  assert.match(source, /this\.page = Math\.floor\(nextIndex \/ pageSize\)/);
  assert.match(source, /this\.resetView\(\)/);
  assert.match(source, /serialize: false/);
  assert.match(source, /widget\.value = serialized/);
  assert.doesNotMatch(source, /component_order/);
  assert.match(styles, /\.mpl2-quick-tile-label[\s\S]*font-size:\s*11px/);
  assert.match(styles, /\.mpl2-quick-snippet[\s\S]*font-size:\s*11px/);
  assert.doesNotMatch(styles, /max-height:\s*195px/);
  assert.match(styles, /\.mpl2-quick-page-button[\s\S]*min-height:\s*24px/);
  assert.match(styles, /\.mpl2-quick-clear-search[\s\S]*width:\s*24px[\s\S]*height:\s*24px/);
  assert.match(entry, /installQuickPicker\(node/);
  assert.match(entry, /node\.__mpl2QuickPicker\?\.syncFromNode/);
  assert.match(entry, /fetchLibrary: \(\) => requestJSON\(`\$\{API_BASE\}\/library`\)/);
});
