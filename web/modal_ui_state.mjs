/**
 * Pure UI-state helpers for the v2 modal.
 *
 * This module intentionally knows nothing about ComfyUI, the DOM, or the
 * workflow.  Geometry belongs to the browser's namespaced local storage only.
 */

export const MODAL_LAYOUT_STORAGE_KEY = "PromptLibrary.MasterPromptLibraryV2.layout";
export const LAYOUT_STORAGE_KEY = MODAL_LAYOUT_STORAGE_KEY;
export const DEFAULT_LAYOUT = Object.freeze({
  dialogWidth: 2400,
  dialogHeight: 1320,
  listWidth: 912,
});
export const DEFAULT_MODAL_LAYOUT = DEFAULT_LAYOUT;
export const DEFAULT_LAYOUT_STATE = DEFAULT_LAYOUT;

const VIEWPORT_GUTTER = 8;
const MIN_DIALOG_WIDTH = 320;
const MIN_DIALOG_HEIGHT = 420;
const MIN_LIST_WIDTH = 220;
const MIN_DETAIL_WIDTH = 320;

function finiteNumber(value, fallback) {
  if (value === null || value === undefined || value === "") return fallback;
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
}

export function viewportSize(viewport = {}) {
  let fallbackWidth = 1280;
  let fallbackHeight = 840;
  try {
    fallbackWidth = globalThis.innerWidth || fallbackWidth;
    fallbackHeight = globalThis.innerHeight || fallbackHeight;
  } catch {
    // A worker, test, or restricted host may not expose a window.
  }
  return {
    width: Math.max(MIN_DIALOG_WIDTH, finiteNumber(viewport.width ?? viewport.innerWidth, fallbackWidth)),
    height: Math.max(MIN_DIALOG_HEIGHT, finiteNumber(viewport.height ?? viewport.innerHeight, fallbackHeight)),
  };
}

/** Clamp restored or user-edited geometry to the current usable viewport. */
export function clampLayoutGeometry(layout = {}, viewport = {}) {
  const size = viewportSize(viewport);
  const gutter = Math.max(0, finiteNumber(viewport.gutter, VIEWPORT_GUTTER));
  const maxWidth = Math.max(MIN_DIALOG_WIDTH, size.width - (gutter * 2));
  const maxHeight = Math.max(MIN_DIALOG_HEIGHT, size.height - (gutter * 2));
  const minWidth = Math.min(MIN_DIALOG_WIDTH + 160, maxWidth);
  const minHeight = Math.min(MIN_DIALOG_HEIGHT, maxHeight);
  const dialogWidth = clamp(
    finiteNumber(layout.dialogWidth ?? layout.width, DEFAULT_LAYOUT.dialogWidth),
    minWidth,
    maxWidth,
  );
  const dialogHeight = clamp(
    finiteNumber(layout.dialogHeight ?? layout.height, DEFAULT_LAYOUT.dialogHeight),
    minHeight,
    maxHeight,
  );
  const maxListWidth = Math.max(MIN_LIST_WIDTH, dialogWidth - MIN_DETAIL_WIDTH);
  const minListWidth = Math.min(MIN_LIST_WIDTH, maxListWidth);
  const listWidth = clamp(
    finiteNumber(layout.listWidth, DEFAULT_LAYOUT.listWidth),
    minListWidth,
    maxListWidth,
  );
  return {
    dialogWidth: Math.round(dialogWidth),
    dialogHeight: Math.round(dialogHeight),
    listWidth: Math.round(listWidth),
  };
}

export const clampLayout = clampLayoutGeometry;

function resolveStorage(storage) {
  if (storage !== undefined) return storage;
  try {
    return globalThis.localStorage;
  } catch {
    return null;
  }
}

function looksLikeViewport(value) {
  return value && typeof value === "object" && !value.getItem
    && ("width" in value || "height" in value || "innerWidth" in value || "innerHeight" in value);
}

function looksLikeStorage(value) {
  return value && typeof value === "object" && typeof value.setItem === "function";
}

function parseLayout(raw) {
  if (!raw || typeof raw !== "string") return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** Read namespaced geometry without allowing storage failures to break the UI. */
export function loadLayoutState(storage, viewport = {}) {
  if (looksLikeViewport(storage)) {
    viewport = storage;
    storage = undefined;
  }
  const source = resolveStorage(storage);
  let raw = null;
  try {
    raw = source?.getItem?.(MODAL_LAYOUT_STORAGE_KEY) || null;
  } catch {
    raw = null;
  }
  return clampLayoutGeometry(parseLayout(raw) || DEFAULT_LAYOUT, viewport);
}

export const readLayoutState = loadLayoutState;
export const readLayout = loadLayoutState;
export const readLayoutGeometry = loadLayoutState;

/** Persist only modal geometry.  Returns false for unavailable storage. */
export function saveLayoutState(layout, storage, viewport = {}) {
  if (looksLikeStorage(layout)) {
    const originalStorage = layout;
    layout = storage || DEFAULT_LAYOUT;
    storage = originalStorage;
  }
  if (looksLikeViewport(storage)) {
    viewport = storage;
    storage = undefined;
  }
  const source = resolveStorage(storage);
  const next = clampLayoutGeometry(layout, viewport);
  try {
    if (!source?.setItem) return false;
    source.setItem(MODAL_LAYOUT_STORAGE_KEY, JSON.stringify(next));
    return true;
  } catch {
    return false;
  }
}

export const writeLayoutState = saveLayoutState;
export const writeLayout = saveLayoutState;
export const writeLayoutGeometry = saveLayoutState;

/** Remove persisted geometry and return a clamped default for this viewport. */
export function resetLayoutState(storage, viewport = {}) {
  if (looksLikeViewport(storage)) {
    viewport = storage;
    storage = undefined;
  }
  const source = resolveStorage(storage);
  try {
    source?.removeItem?.(MODAL_LAYOUT_STORAGE_KEY);
  } catch {
    // Storage is optional; the reset action must still work in private mode.
  }
  return clampLayoutGeometry(DEFAULT_LAYOUT, viewport);
}

export const clearLayoutState = resetLayoutState;
export const resetLayout = resetLayoutState;
export const resetLayoutGeometry = resetLayoutState;

export function layoutCSSVariables(layout, viewport = {}) {
  const next = clampLayoutGeometry(layout, viewport);
  return {
    "--mpl2-dialog-width": `${next.dialogWidth}px`,
    "--mpl2-dialog-height": `${next.dialogHeight}px`,
    "--mpl2-list-width": `${next.listWidth}px`,
  };
}

export function isKeyboardActivationKey(key) {
  return key === "Enter" || key === " " || key === "Spacebar";
}

/** Run a button-like action for Enter/Space and consume the browser default. */
export function activateOnKeydown(event, callback) {
  if (!event || !isKeyboardActivationKey(event.key)) return false;
  event.preventDefault?.();
  callback?.();
  return true;
}

export const activateKeyboard = activateOnKeydown;

/** Return the next roving tab index for Left/Right/Home/End navigation. */
export function nextTabIndex(currentIndex, key, count) {
  const total = Number.isInteger(count) ? count : Number(count);
  if (!Number.isFinite(total) || total <= 0) return -1;
  const current = clamp(Number.isInteger(currentIndex) ? currentIndex : Number(currentIndex) || 0, 0, total - 1);
  if (key === "Home") return 0;
  if (key === "End") return total - 1;
  if (key === "ArrowLeft" || key === "ArrowUp") return (current - 1 + total) % total;
  if (key === "ArrowRight" || key === "ArrowDown") return (current + 1) % total;
  return current;
}

export const moveTabIndex = nextTabIndex;
