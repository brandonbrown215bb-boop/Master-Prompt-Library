import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  DEFAULT_LAYOUT,
  MODAL_LAYOUT_STORAGE_KEY,
  activateOnKeydown,
  clampLayoutGeometry,
  layoutCSSVariables,
  loadLayoutState,
  nextTabIndex,
  resetLayoutState,
  saveLayoutState,
} from "../web/modal_ui_state.mjs";

function storage(initial = {}, { fail = false } = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) { if (fail) throw new Error("storage unavailable"); return values.get(key) ?? null; },
    setItem(key, value) { if (fail) throw new Error("storage unavailable"); values.set(key, String(value)); },
    removeItem(key) { if (fail) throw new Error("storage unavailable"); values.delete(key); },
    values,
  };
}

test("layout geometry clamps restored dimensions and split to the viewport", () => {
  assert.deepEqual(clampLayoutGeometry({ dialogWidth: 9999, dialogHeight: -5, listWidth: 9999 }, { width: 900, height: 700 }), {
    dialogWidth: 884,
    dialogHeight: 420,
    listWidth: 564,
  });
  assert.deepEqual(clampLayoutGeometry({ dialogWidth: "nope", dialogHeight: null, listWidth: undefined }, { width: 1600, height: 1200 }), {
    dialogWidth: 1584,
    dialogHeight: 1184,
    listWidth: 912,
  });
});

test("malformed or unavailable namespaced storage falls back safely", () => {
  const malformed = storage({ [MODAL_LAYOUT_STORAGE_KEY]: "{not-json" });
  assert.deepEqual(loadLayoutState(malformed, { width: 1600, height: 1200 }), { dialogWidth: 1584, dialogHeight: 1184, listWidth: 912 });
  assert.deepEqual(loadLayoutState(storage({}, { fail: true }), { width: 1600, height: 1200 }), { dialogWidth: 1584, dialogHeight: 1184, listWidth: 912 });
  assert.equal(saveLayoutState(DEFAULT_LAYOUT, storage({}, { fail: true }), { width: 1600, height: 1200 }), false);
});

test("layout writes only the namespaced geometry state and reset removes it", () => {
  const state = storage();
  assert.equal(saveLayoutState({ dialogWidth: 900, dialogHeight: 600, listWidth: 300 }, state, { width: 1200, height: 800 }), true);
  assert.deepEqual(JSON.parse(state.values.get(MODAL_LAYOUT_STORAGE_KEY)), { dialogWidth: 900, dialogHeight: 600, listWidth: 300 });
  assert.deepEqual(resetLayoutState(state, { width: 1200, height: 800 }), { dialogWidth: 1184, dialogHeight: 784, listWidth: 864 });
  assert.equal(state.values.has(MODAL_LAYOUT_STORAGE_KEY), false);
});

test("keyboard activation consumes Enter and Space but leaves other keys alone", () => {
  let count = 0;
  const enter = { key: "Enter", prevented: false, preventDefault() { this.prevented = true; } };
  assert.equal(activateOnKeydown(enter, () => { count += 1; }), true);
  assert.equal(enter.prevented, true);
  const space = { key: " ", preventDefault() { this.prevented = true; } };
  assert.equal(activateOnKeydown(space, () => { count += 1; }), true);
  assert.equal(count, 2);
  assert.equal(activateOnKeydown({ key: "Tab" }, () => { count += 1; }), false);
  assert.equal(count, 2);
});

test("gallery tab navigation wraps and supports Home/End", () => {
  assert.equal(nextTabIndex(0, "ArrowRight", 2), 1);
  assert.equal(nextTabIndex(1, "ArrowRight", 2), 0);
  assert.equal(nextTabIndex(0, "ArrowLeft", 2), 1);
  assert.equal(nextTabIndex(1, "Home", 2), 0);
  assert.equal(nextTabIndex(0, "End", 2), 1);
  assert.equal(nextTabIndex(0, "PageDown", 2), 0);
  assert.equal(nextTabIndex(0, "ArrowRight", 0), -1);
});

test("CSS variables are derived from clamped geometry", () => {
  assert.deepEqual(layoutCSSVariables({ dialogWidth: 9999, dialogHeight: 9999, listWidth: 9999 }, { width: 1000, height: 700 }), {
    "--mpl2-dialog-width": "984px",
    "--mpl2-dialog-height": "684px",
    "--mpl2-list-width": "664px",
  });
});

test("extraction chooser uses the native file input without duplicate tab stops", () => {
  const source = readFileSync(new URL("../web/prompt_library_v2.js", import.meta.url), "utf8");
  const paneStart = source.indexOf("renderExtractImagePane() {");
  const paneEnd = source.indexOf("\n  async saveExtractedToLibrary()", paneStart);
  assert.ok(paneStart >= 0 && paneEnd > paneStart);
  const pane = source.slice(paneStart, paneEnd);
  assert.match(pane, /const dropzone = element\("label"/);
  assert.match(pane, /for: "mpl2-extract-file"/);
  assert.doesNotMatch(pane, /dropzone\.addEventListener\("keydown"/);
  assert.doesNotMatch(pane, /dropzone\.addEventListener\("click"/);
  const start = source.indexOf('const hiddenFile = element("input", {');
  const end = source.indexOf("});", start);
  assert.ok(start >= 0 && end > start);
  assert.match(source.slice(start, end), /id:\s*"mpl2-extract-file"/);
  assert.match(source.slice(start, end), /tabindex:\s*"0"/);
});

test("concept editor exposes installed LoRA attachments and separate model and CLIP strengths", () => {
  const source = readFileSync(new URL("../web/prompt_library_v2.js", import.meta.url), "utf8");
  const styles = readFileSync(new URL("../web/prompt_library_v2.css", import.meta.url), "utf8");
  assert.match(source, /async refreshLoras\(\)/);
  assert.match(source, /LoRAs activated by this concept/);
  assert.match(source, /strength_model/);
  assert.match(source, /strength_clip/);
  assert.match(source, /A concept cannot attach the same LoRA more than once/);
  assert.match(styles, /\.mpl2-lora-row/);
  assert.match(styles, /grid-template-columns/);
});

test("structured extraction keeps field selection independent from target category and resets stale drafts", () => {
  const source = readFileSync(new URL("../web/prompt_library_v2.js", import.meta.url), "utf8");
  const paneStart = source.indexOf("renderExtractImagePane() {");
  const paneEnd = source.indexOf("\n  async saveExtractedToLibrary()", paneStart);
  assert.ok(paneStart >= 0 && paneEnd > paneStart);
  const pane = source.slice(paneStart, paneEnd);
  assert.match(pane, /Field to Edit/);
  assert.match(pane, /Fields to Add/);
  assert.match(pane, /extractedFields\.length > 1/);
  assert.match(pane, /selectExtractionField\(this\.extractState/);
  assert.match(pane, /toggleExtractionFieldSelection\(this\.extractState/);
  assert.match(pane, /extractionSavePlan\(this\.extractState, this\.categories\(\)\)/);
  assert.match(pane, /Target Category/);
  assert.match(pane, /selectedExtractionDraft\(this\.extractState\)/);
  assert.match(pane, /updateExtractionFieldDraft\(this\.extractState, promptTextarea\.value\)/);
  assert.match(pane, /Confidence: \$\{confidence\}/);
  assert.match(source, /structured: null/);
  assert.match(source, /selectedExtractedField: "positive_prompt"/);
  assert.match(source, /extractedFieldDrafts: \{ positive_prompt: "" \}/);
  assert.match(source, /state\.structured = null/);
});

test("remediation and extraction UI modules carry cache revisions", () => {
  const source = readFileSync(new URL("../web/prompt_library_v2.js", import.meta.url), "utf8");
  assert.match(source, /prompt_library_quick_picker\.mjs\?v=2\.1\.0-lora1/);
  assert.match(source, /modal_ui_state\.mjs\?v=2\.1\.0-uiux1/);
  assert.match(source, /vision_connection_state\.mjs\?v=2\.1\.0-vision1/);
  assert.match(source, /library_v2_logic\.mjs\?v=2\.1\.0-lora1/);
});

test("v2 node controls wait for serialized widgets and retry after node construction", () => {
  const source = readFileSync(new URL("../web/prompt_library_v2.js", import.meta.url), "utf8");
  assert.match(source, /if \(!selectionWidget \|\| !orderWidget \|\| typeof node\.addWidget !== "function"\) return false/);
  assert.match(source, /function scheduleBrowseButton\(node, knownV2 = false\)/);
  assert.match(source, /\[0, 50, 250, 1000\]/);
  assert.match(source, /nodeCreated\(node\) \{ scheduleBrowseButton\(node\); \}/);
});

test("vision extraction uses saved provider controls and model discovery with a custom fallback", () => {
  const source = readFileSync(new URL("../web/prompt_library_v2.js", import.meta.url), "utf8");
  const paneStart = source.indexOf("renderExtractImagePane() {");
  const paneEnd = source.indexOf("\n  async saveExtractedToLibrary()", paneStart);
  assert.ok(paneStart >= 0 && paneEnd > paneStart);
  const pane = source.slice(paneStart, paneEnd);
  assert.match(pane, /id: "mpl2-vision-provider"/);
  assert.match(pane, /id: "mpl2-vision-model"/);
  assert.match(pane, /Custom model…/);
  assert.match(pane, /Remember API key in this browser profile/);
  assert.match(pane, /Forget saved connection/);
  assert.match(source, /\/vision\/models/);
  assert.match(source, /saveVisionConnection\(this\.extractState\)/);
});
