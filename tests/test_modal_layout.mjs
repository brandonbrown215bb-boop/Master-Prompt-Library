import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const styles = readFileSync(new URL("../web/prompt_library_v2.css", import.meta.url), "utf8");
const source = readFileSync(new URL("../web/prompt_library_v2.js", import.meta.url), "utf8");

// These are structural contracts for the presentation layer. They do not
// claim that a browser has exercised focus, sizing, or media-query behavior.
test("modal geometry exposes stored dimensions and viewport bounds", () => {
  assert.match(styles, /--mpl2-dialog-width\s*:\s*2400px/);
  assert.match(styles, /--mpl2-dialog-height\s*:\s*1320px/);
  assert.match(styles, /--mpl2-list-width\s*:\s*38%/);
  assert.match(styles, /width:\s*min\(var\(--mpl2-dialog-width\),\s*calc\(100vw/);
  assert.match(styles, /height:\s*min\(var\(--mpl2-dialog-height\),\s*calc\(100vh/);
  assert.match(styles, /max-width:\s*calc\(100vw/);
  assert.match(styles, /max-height:\s*calc\(100vh/);
  assert.match(styles, /resize:\s*both/);
});

test("desktop split and narrow pane-switch hooks have explicit layout rules", () => {
  assert.match(styles, /\.mpl2-layout-controls\s*\{/);
  assert.match(styles, /\.mpl2-pane-tabs\s*\{/);
  assert.match(styles, /\.mpl2-pane-tab\s*\{/);
  assert.match(styles, /\.mpl2-main-splitter\s*\{/);
  assert.match(styles, /\.mpl2-main:has\(\.mpl2-main-splitter\)/);
  assert.match(styles, /@media\s*\(max-width:\s*730px\)/);
  assert.match(styles, /\.mpl2-main\[data-mobile-pane="catalog"\]/);
  assert.match(styles, /\.mpl2-main\[data-mobile-pane="detail"\]/);
  assert.doesNotMatch(styles, /data-mobile-pane="details"/);
  assert.match(styles, /grid-template-rows:\s*auto\s+auto\s+minmax\(0,\s*1fr\)/);
  assert.match(styles, /\.mpl2-pane-tabs\s*\{[\s\S]*display:\s*flex/);
});

test("modal copy and interactive targets use the legible baseline", () => {
  assert.match(styles, /\.mpl2-modal\s*\{[\s\S]*font-size:\s*12px/);
  assert.match(styles, /\.mpl2-button\s*\{[\s\S]*min-width:\s*24px[\s\S]*min-height:\s*33px[\s\S]*font-size:\s*12px/);
  assert.match(styles, /\.mpl2-pane-tab\s*\{[\s\S]*min-width:\s*24px[\s\S]*min-height:\s*32px[\s\S]*font-size:\s*12px/);
  assert.match(styles, /\.mpl2-chip-remove\s*\{[\s\S]*min-width:\s*24px[\s\S]*min-height:\s*24px/);
  assert.match(styles, /\.mpl2-button:focus-within/);
  assert.match(styles, /\.mpl2-hidden-file:focus-visible\s*\+\s*\.mpl2-dropzone/);
  assert.match(styles, /\.mpl2-dropzone:focus-visible/);
});

test("dropzone presentation resets native button chrome without changing its focus contract", () => {
  const dropzoneRule = styles.match(/\.mpl2-dropzone\s*\{[^}]+\}/)?.[0] || "";
  assert.match(dropzoneRule, /width:\s*100%/);
  assert.match(dropzoneRule, /appearance:\s*none/);
  assert.match(dropzoneRule, /-webkit-appearance:\s*none/);
  assert.match(dropzoneRule, /color:\s*inherit/);
  assert.match(dropzoneRule, /font:\s*inherit/);
  assert.match(styles, /\.mpl2-dropzone:focus-visible/);
  assert.match(styles, /\.mpl2-dropzone\s*\{[\s\S]*border:\s*1px solid ButtonText/);
});

test("accessibility presentation has forced-colors and reduced-motion fallbacks", () => {
  assert.match(styles, /@media\s*\(forced-colors:\s*active\)/);
  assert.match(styles, /ButtonText/);
  assert.match(styles, /Highlight/);
  assert.match(styles, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.match(styles, /transition-duration:\s*\.01ms\s*!important/);
  assert.match(styles, /scroll-behavior:\s*auto\s*!important/);
});

test("vision connection controls use a compact responsive grid", () => {
  assert.match(styles, /\.mpl2-vision-fields\s*\{[^}]*grid-template-columns:\s*repeat\(2,/);
  assert.match(styles, /\.mpl2-vision-model-controls\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto/);
  assert.match(styles, /\.mpl2-vision-model-field,[\s\S]*grid-column:\s*1\s*\/\s*-1/);
  assert.match(styles, /@media\s*\(max-width:\s*520px\)/);
  assert.match(styles, /\.mpl2-vision-fields\s*\{\s*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
});

test("detected section badges show complete text in responsive wrapping cards", () => {
  const tagRule = styles.match(/\.mpl2-section-tag\s*\{[^}]+\}/)?.[0] || "";
  assert.match(tagRule, /flex:\s*1\s+1\s+260px/);
  assert.match(tagRule, /max-width:\s*100%/);
  assert.match(tagRule, /white-space:\s*normal/);
  assert.match(tagRule, /overflow-wrap:\s*anywhere/);
  assert.doesNotMatch(source, /extractState\.sections\[k\]\.slice\(/);
  assert.match(source, /textContent:\s*`\$\{k\}:\s*\$\{sectionText\}`/);
});

test("structured extraction choices remain legible in a responsive checklist", () => {
  assert.match(styles, /\.mpl2-extraction-choices\s*\{[^}]*grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(210px,\s*1fr\)\)/s);
  assert.match(styles, /\.mpl2-extraction-choice\s*\{[^}]*grid-template-columns:\s*16px\s+minmax\(0,\s*auto\)\s+minmax\(0,\s*1fr\)/s);
  assert.match(styles, /\.mpl2-extraction-choice-target\s*\{[^}]*text-overflow:\s*ellipsis/s);
});
