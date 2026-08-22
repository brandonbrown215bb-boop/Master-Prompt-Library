/**
 * Small, browser-independent operations shared by the prompt-library UI.
 *
 * Keeping these operations free of DOM and ComfyUI state makes the failure
 * cases around stale selections and image previews easy to test.  The
 * backend remains the source of truth for validation and persistence.
 */

export const CATEGORY_ORDER = Object.freeze([
  "style",
  "character",
  "action",
  "background",
]);

export const CATEGORY_LABELS = Object.freeze({
  style: "Style",
  character: "Character",
  action: "Action",
  background: "Background",
});

export const NONE_VALUE = "✨ none";
export const API_BASE = "/master_prompt_library/v1";
export const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
export const IMAGE_MIME_TYPES = Object.freeze({
  jpeg: "image/jpeg",
  jpg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
});

function stringValue(value) {
  return typeof value === "string" ? value : "";
}

function lower(value) {
  return stringValue(value).toLocaleLowerCase();
}

/**
 * Filter one category by name and prompt.  Search terms are ANDed, so a
 * query such as "ink portrait" narrows the catalog to entries containing
 * both words in either searchable field.
 */
export function filterEntries(entries, query = "") {
  const source = Array.isArray(entries) ? entries : [];
  const terms = lower(query).trim().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return source.slice();

  return source.filter((entry) => {
    const haystack = `${lower(entry?.name)} ${lower(entry?.prompt)}`;
    return terms.every((term) => haystack.includes(term));
  });
}

/** Filter a complete library to one fixed category and search query. */
export function filterLibrary(library, category, query = "") {
  const entries = library?.categories?.[category];
  return CATEGORY_ORDER.includes(category) ? filterEntries(entries, query) : [];
}

/**
 * Return true when a name conflicts with another entry in the same category.
 * The edited record is excluded by stable ID, which allows an unchanged edit
 * to pass its own duplicate check.
 */
export function hasDuplicateName(entries, name, editedId = null) {
  const candidate = lower(stringValue(name).trim());
  if (!candidate) return false;
  return (Array.isArray(entries) ? entries : []).some((entry) => (
    entry?.id !== editedId && lower(entry?.name).trim() === candidate
  ));
}

/** Alias with a predicate-shaped name for callers that read more naturally. */
export const isDuplicateName = hasDuplicateName;

/**
 * Build native ComfyUI combo values and preserve a valid current selection.
 * A stale/deleted value deliberately falls back to the visible none choice.
 */
export function rebuildComboValues(entries, currentValue = NONE_VALUE) {
  const source = Array.isArray(entries) ? entries : [];
  const names = source
    .map((entry) => stringValue(entry?.name).trim())
    .filter(Boolean);
  const values = [NONE_VALUE, ...names];
  const value = names.includes(currentValue) ? currentValue : NONE_VALUE;
  return { values, value };
}

/** Alias used by UI code and useful to consumers that prefer “options”. */
export const rebuildComboOptions = rebuildComboValues;

/** Build the server URL for an entry preview with a cache-busting revision. */
export function thumbnailUrl(entryOrId, cacheBuster = "") {
  const id = typeof entryOrId === "string" ? entryOrId : entryOrId?.id;
  const hasImage = typeof entryOrId === "string"
    ? true
    : Boolean(entryOrId?.image);
  if (!id || !hasImage) return "";

  const path = `${API_BASE}/entries/${encodeURIComponent(id)}/image`;
  return cacheBuster === "" || cacheBuster == null
    ? path
    : `${path}?cache=${encodeURIComponent(String(cacheBuster))}`;
}

/** Describe the deterministic visual state for an entry row/detail preview. */
export function imageState(entry, cacheBuster = "") {
  if (entry?.image && entry?.id) {
    return {
      kind: "image",
      url: thumbnailUrl(entry, cacheBuster),
      alt: `Preview of ${stringValue(entry.name).trim() || "prompt entry"}`,
    };
  }
  return {
    kind: "placeholder",
    url: "",
    alt: `No preview for ${stringValue(entry?.name).trim() || "prompt entry"}`,
  };
}

/** Validate a local file before sending it to the authoritative backend. */
export function validateImageFile(file, maxBytes = MAX_IMAGE_BYTES) {
  if (!file || typeof file !== "object") {
    return { valid: false, error: "Choose a JPEG, PNG, or WebP image." };
  }

  const size = Number(file.size);
  if (!Number.isFinite(size) || size < 0) {
    return { valid: false, error: "The selected file has an invalid size." };
  }
  if (size > maxBytes) {
    return { valid: false, error: "Preview images must be 8 MiB or smaller." };
  }

  const type = lower(file.type);
  const filename = stringValue(file.name).toLowerCase();
  const extension = filename.includes(".") ? filename.split(".").pop() : "";
  const accepted = type === "image/jpeg"
    || type === "image/png"
    || type === "image/webp"
    || (!type && Object.hasOwn(IMAGE_MIME_TYPES, extension));
  if (!accepted) {
    return { valid: false, error: "Accepted preview formats: JPEG, PNG, or WebP." };
  }
  return { valid: true, error: "" };
}

