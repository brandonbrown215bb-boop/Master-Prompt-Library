/**
 * Browser-independent v2 selection, filtering, and metadata helpers.
 *
 * The manager deliberately keeps these operations pure.  The ComfyUI node
 * and the API remain the authorities for persistence and validation; this
 * module makes the UI's drafts deterministic and easy to exercise in Node.
 */

export const V2_VERSION = 1;
export const PROMPT_TOKEN = "prompt";
export const CORE_CATEGORY_IDS = Object.freeze(["style", "character", "action", "background"]);

const CORE_LABELS = Object.freeze({
  style: "Style",
  character: "Character",
  action: "Action",
  background: "Background",
});

function text(value) {
  return typeof value === "string" ? value : "";
}

function trimmed(value) {
  return text(value).trim();
}

function lower(value) {
  return trimmed(value).toLocaleLowerCase();
}

function array(value) {
  return Array.isArray(value) ? value : [];
}

function object(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

export function categoryLabel(category) {
  const id = typeof category === "string" ? category : category?.id;
  return trimmed(category?.name) || CORE_LABELS[id] || (id ? id : "Category");
}

export function normalizeTags(tags) {
  const seen = new Map();
  for (const raw of array(tags)) {
    const value = trimmed(raw);
    const key = lower(value);
    if (value && !seen.has(key)) seen.set(key, value);
  }
  return [...seen.values()].sort((a, b) => lower(a).localeCompare(lower(b)) || a.localeCompare(b));
}

export function normalizeFolder(folder) {
  if (folder && typeof folder === "object") {
    const id = trimmed(folder.id);
    const name = trimmed(folder.name);
    return id && name ? { id, name } : null;
  }
  const name = trimmed(folder);
  return name ? { id: "", name } : null;
}

function normalizeImage(image) {
  const source = object(image);
  const id = trimmed(source.id);
  if (!id) return null;
  return {
    id,
    filename: trimmed(source.filename),
    media_type: trimmed(source.media_type || source.mime_type),
    kind: source.kind === "generated" ? "generated" : "preview",
    caption: trimmed(source.caption),
    status: trimmed(source.status),
  };
}

export function normalizeEntry(entry) {
  const source = object(entry);
  const images = array(source.images).map(normalizeImage).filter(Boolean);
  const legacyImage = source.image && typeof source.image === "object" ? normalizeImage({ ...source.image, id: source.image.id || "legacy-preview" }) : null;
  if (legacyImage && !images.length) images.push(legacyImage);
  const imageIds = new Set(images.map((image) => image.id));
  const primary = trimmed(source.primary_image_id);
  return {
    id: trimmed(source.id),
    name: text(source.name),
    prompt: text(source.prompt),
    tags: normalizeTags(source.tags),
    favorite: source.favorite === true,
    folder_id: trimmed(source.folder_id) || null,
    images,
    primary_image_id: primary && imageIds.has(primary) && images.some((image) => image.id === primary && image.kind === "preview") ? primary : null,
  };
}

export function normalizeCategory(category, index = 0) {
  const source = object(category);
  const id = trimmed(source.id) || CORE_CATEGORY_IDS[index] || `category-${index + 1}`;
  const key = source.key === null ? null : trimmed(source.key) || (CORE_CATEGORY_IDS.includes(id) ? id : null);
  const folders = array(source.folders).map((folder) => normalizeFolder(folder)).filter((folder) => folder?.id);
  const folderSeen = new Set();
  const normalizedFolders = folders.filter((folder) => {
    const keyName = lower(folder.name);
    if (folderSeen.has(keyName)) return false;
    folderSeen.add(keyName);
    return true;
  });
  return {
    id,
    key,
    name: trimmed(source.name) || CORE_LABELS[id] || id,
    protected: source.protected === true || CORE_CATEGORY_IDS.includes(id),
    folders: normalizedFolders,
    entries: array(source.entries).map(normalizeEntry).filter((entry) => entry.id),
  };
}

export function normalizeLibraryPayload(payload) {
  const source = payload?.library && typeof payload.library === "object" ? payload.library : payload;
  const categories = array(source?.categories).map(normalizeCategory).filter((category) => category.id);
  const known = new Set();
  const unique = categories.filter((category) => {
    if (known.has(category.id)) return false;
    known.add(category.id);
    return true;
  });
  for (const id of CORE_CATEGORY_IDS) {
    if (!unique.some((category) => category.id === id)) {
      unique.push(normalizeCategory({ id, key: id, name: CORE_LABELS[id], protected: true, folders: [], entries: [] }));
    }
  }
  return {
    library: {
      version: Number(source?.version) || 2,
      categories: unique,
      applied_seed_packs: array(source?.applied_seed_packs).map((pack) => ({ ...pack })),
    },
    fingerprint: text(payload?.fingerprint || source?.fingerprint),
  };
}

export function categoryIds(categories) {
  return array(categories).map((category) => trimmed(category?.id)).filter(Boolean);
}

export function defaultComponentOrder(categories) {
  return [...categoryIds(categories), PROMPT_TOKEN];
}

export function normalizeComponentOrder(value, categories, { includeUnknown = false } = {}) {
  const known = new Set(categoryIds(categories));
  const parsed = Array.isArray(value) ? value : parseJson(value, null);
  const supplied = Array.isArray(parsed) ? parsed : text(value).split(",");
  const result = [];
  let promptSeen = false;
  for (const raw of supplied) {
    const token = trimmed(raw);
    if (!token || (!known.has(token) && token !== PROMPT_TOKEN && !includeUnknown) || result.includes(token)) continue;
    if (token === PROMPT_TOKEN) {
      if (promptSeen) continue;
      promptSeen = true;
    }
    result.push(token);
  }
  for (const id of categoryIds(categories)) if (!result.includes(id)) result.push(id);
  if (!promptSeen) result.push(PROMPT_TOKEN);
  return result;
}

export function serializeComponentOrder(value, categories) {
  return JSON.stringify(normalizeComponentOrder(value, categories));
}

export const normalizeCategoryOrder = normalizeComponentOrder;
export const serializeCategoryOrder = serializeComponentOrder;

export function parseJson(value, fallback = null) {
  if (value && typeof value === "object") return value;
  if (typeof value !== "string" || !value.trim()) return fallback;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

export function normalizeSelectionState(value, categories = []) {
  const source = object(parseJson(value, {}));
  const rawSelections = object(source.selections);
  const selections = {};
  for (const [categoryId, rawIds] of Object.entries(rawSelections)) {
    if (!categoryId || !Array.isArray(rawIds)) continue;
    const seen = new Set();
    selections[categoryId] = rawIds.map((id) => trimmed(id)).filter((id) => {
      if (!id || seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  }
  for (const id of categoryIds(categories)) if (!Object.hasOwn(selections, id)) selections[id] = [];
  return { version: V2_VERSION, selections };
}

export function serializeSelectionState(value, categories = []) {
  const normalized = normalizeSelectionState(value, categories);
  return JSON.stringify({ version: normalized.version, selections: normalized.selections });
}

// Short aliases keep the pure contract pleasant for small consumers and tests.
export const normalizeSelection = normalizeSelectionState;
export const serializeSelection = serializeSelectionState;

export function selectedIdsForCategory(selectionState, categoryId) {
  const state = normalizeSelectionState(selectionState);
  return array(state.selections?.[categoryId]);
}

export function selectedEntries(category, selectionState) {
  const entries = array(category?.entries);
  const byId = new Map(entries.map((entry) => [entry.id, entry]));
  return selectedIdsForCategory(selectionState, category?.id).map((id) => byId.get(id)).filter(Boolean);
}

export function staleSelectionIds(selectionState, categories) {
  const state = normalizeSelectionState(selectionState);
  const byCategory = new Map(array(categories).map((category) => [category.id, new Set(category.entries.map((entry) => entry.id))]));
  const missingCategoryIds = [];
  const missingEntryIds = [];
  for (const [categoryId, ids] of Object.entries(state.selections)) {
    if (!byCategory.has(categoryId)) {
      missingCategoryIds.push(categoryId);
      continue;
    }
    for (const id of ids) if (!byCategory.get(categoryId).has(id)) missingEntryIds.push(id);
  }
  return { missingCategoryIds, missingEntryIds };
}

export function buildAssembledPrompt(selectionState, componentOrder, categories = [], freeformPrompt = "") {
  const normSelection = normalizeSelectionState(selectionState, categories);
  const normOrder = normalizeComponentOrder(componentOrder, categories);
  const byCategory = new Map(array(categories).map((category) => [category.id, category]));

  const sections = [];
  for (const token of normOrder) {
    if (token === PROMPT_TOKEN) {
      const promptText = trimmed(freeformPrompt);
      if (promptText) sections.push(`Prompt:\n${promptText}`);
      continue;
    }
    const category = byCategory.get(token);
    if (!category) continue;
    const selectedIds = array(normSelection.selections?.[token]);
    if (!selectedIds.length) continue;
    const entries = array(category.entries);
    const byId = new Map(entries.map((e) => [e.id, e]));
    const prompts = selectedIds.map((id) => byId.get(id)?.prompt).filter((p) => typeof p === "string" && p.trim().length > 0);
    if (prompts.length > 0) {
      const label = categoryLabel(category);
      sections.push(`${label}:\n${prompts.join(", ")}`);
    }
  }
  return sections.join("\n\n");
}

export function filterEntriesV2(entries, { query = "", folderId = "", tag = "", favoritesOnly = false } = {}) {
  const terms = lower(query).split(/\s+/).filter(Boolean);
  const folder = trimmed(folderId);
  const wantedTag = lower(tag);
  return array(entries).filter((entry) => {
    const haystack = `${lower(entry?.name)} ${lower(entry?.prompt)} ${normalizeTags(entry?.tags).map(lower).join(" ")}`;
    return terms.every((term) => haystack.includes(term))
      && (!folder || (entry?.folder_id || "") === folder)
      && (!wantedTag || normalizeTags(entry?.tags).some((value) => lower(value) === wantedTag))
      && (!favoritesOnly || entry?.favorite === true);
  });
}

export const filterEntries = filterEntriesV2;

/** Return one clamped, zero-based page without mutating the input array. */
export function paginateEntries(items, requestedPage = 0, pageSize = 10) {
  const source = array(items);
  const size = Number.isInteger(pageSize) && pageSize > 0 ? pageSize : 10;
  const total = source.length;
  const pageCount = Math.max(1, Math.ceil(total / size));
  const requested = Number.isInteger(requestedPage) ? requestedPage : 0;
  const page = Math.min(Math.max(requested, 0), pageCount - 1);
  const start = total ? page * size : 0;
  const end = total ? Math.min(start + size, total) : 0;
  return { items: source.slice(start, end), page, pageCount, total, start, end };
}

/** Move a catalog cursor through a flat global index, optionally representing a grid. */
export function navigateCatalogIndex(currentIndex, key, itemCount, { pageSize = 10, columns = 1 } = {}) {
  const count = Number.isInteger(itemCount) && itemCount > 0 ? itemCount : 0;
  if (!count) return -1;
  const current = Number.isInteger(currentIndex) ? Math.min(Math.max(currentIndex, 0), count - 1) : 0;
  const size = Number.isInteger(pageSize) && pageSize > 0 ? pageSize : 10;
  const columnCount = Number.isInteger(columns) && columns > 0 ? columns : 1;
  const pageRows = Math.max(1, Math.ceil(size / columnCount));
  const pageDelta = pageRows * columnCount;
  let next = current;
  if (key === "ArrowLeft" || key === "ArrowUp") next = current - (key === "ArrowUp" ? columnCount : 1);
  else if (key === "ArrowRight" || key === "ArrowDown") next = current + (key === "ArrowDown" ? columnCount : 1);
  else if (key === "PageUp") next = current - pageDelta;
  else if (key === "PageDown") next = current + pageDelta;
  else if (key === "Home") next = 0;
  else if (key === "End") next = count - 1;
  return Math.min(Math.max(next, 0), count - 1);
}

export function availableTags(entries) {
  return normalizeTags(array(entries).flatMap((entry) => array(entry?.tags)));
}

export function folderOptions(category) {
  return array(category?.folders).slice().sort((a, b) => lower(a.name).localeCompare(lower(b.name)) || a.id.localeCompare(b.id));
}

export function reorderIds(ids, from, to) {
  const result = array(ids).map((id) => id);
  const source = Number(from);
  const target = Number(to);
  if (!Number.isInteger(source) || !Number.isInteger(target) || source < 0 || source >= result.length || target < 0 || target >= result.length || source === target) return result;
  const [item] = result.splice(source, 1);
  result.splice(target, 0, item);
  return result;
}

/** Move one item by a relative offset; invalid moves return a stable copy. */
export function moveByOffset(ids, index, offset) {
  const source = Number(index);
  const distance = Number(offset);
  if (!Number.isInteger(source) || !Number.isInteger(distance)) return array(ids).slice();
  return reorderIds(ids, source, source + distance);
}

export function reorderGallery(images, from, to) {
  return reorderIds(array(images), from, to);
}

export const applyGalleryReorder = reorderGallery;

export function galleryState(entry, kind = "preview") {
  const images = array(entry?.images).filter((image) => image.kind === kind);
  const primary = entry?.primary_image_id && images.some((image) => image.id === entry.primary_image_id) ? entry.primary_image_id : null;
  return { images, primary_image_id: primary };
}

export function setGalleryPrimary(entry, imageId) {
  const id = trimmed(imageId);
  if (!array(entry?.images).some((image) => image.id === id && image.kind === "preview")) return null;
  return id;
}

export function normalizeImportMapping(mapping, groups = []) {
  const source = object(mapping);
  const known = new Set(array(groups).map((group) => trimmed(group.id || group.name)).filter(Boolean));
  const result = {};
  for (const [key, value] of Object.entries(source)) {
    const sourceId = trimmed(key);
    const targetId = trimmed(value);
    if (sourceId && targetId && (known.size === 0 || known.has(sourceId))) result[sourceId] = targetId;
  }
  return result;
}

/** Selecting one import input kind clears the other kind's pending selection. */
export function selectImportSource(state, sourceId) {
  return { ...object(state), sourceId: trimmed(sourceId), files: [] };
}

export function selectImportFiles(state, files) {
  return { ...object(state), sourceId: "", files: array(files).slice() };
}

export function normalizeConflictPolicy(policy) {
  return ["skip", "rename", "replace"].includes(policy) ? policy : "skip";
}

export function importPreviewSummary(preview) {
  const source = object(preview);
  const counts = object(source.counts);
  return {
    records: Number(counts.records ?? source.record_count ?? source.records) || 0,
    groups: Number(counts.groups ?? source.group_count ?? source.groups) || 0,
    conflicts: Number(counts.conflicts ?? source.conflict_count ?? source.conflicts) || 0,
    omittedNegative: Number(counts.omitted_negative ?? counts.negative_prompt ?? source.omitted_negative) || 0,
    warnings: array(source.warnings).map((warning) => text(warning)).filter(Boolean),
  };
}

export function cleanPositivePrompt(raw) {
  const input = text(raw).trim();
  if (!input) return "";
  const lines = input.split(/\r?\n/);
  const positive = [];
  for (const line of lines) {
    const stripped = line.trim();
    if (/^Negative\s+prompt\s*:/i.test(stripped)) break;
    if (/^Steps\s*:\s*\d+/i.test(stripped)) break;
    if (/^(?:Template|Lora\s+hashes|TI\s+hashes|Version|Size|Model\s+hash|Model|Seed|Sampler|CFG\s+scale)\s*:/i.test(stripped)) break;
    positive.push(line);
  }
  return positive.join("\n").trim();
}

export function suggestEntryName(prompt, filename = "") {
  if (filename) {
    let cleanFile = filename.replace(/\.[a-zA-Z0-9]+$/, "");
    cleanFile = cleanFile.replace(/^[0-9_\-]+/, "").replace(/[_\-]+/g, " ").trim();
    if (cleanFile.length >= 3) {
      return cleanFile.slice(0, 80).replace(/\b\w/g, (c) => c.toUpperCase());
    }
  }
  if (prompt) {
    const firstLine = prompt.trim().split(/\r?\n/)[0].trim().replace(/^[A-Za-z0-9 _\-]+:\s*/, "");
    const words = firstLine.split(/\s+/).filter(Boolean);
    if (words.length) {
      const snippet = words.slice(0, 6).join(" ").replace(/[,;:.!?]+$/, "");
      if (snippet.length >= 3) {
        return snippet.charAt(0).toUpperCase() + snippet.slice(1);
      }
    }
  }
  return "Extracted Prompt";
}

export function parsePromptSections(prompt, categoryNames = []) {
  const input = text(prompt).trim();
  if (!input) return {};
  const defaultLabels = ["Style", "Character", "Action", "Background", "Camera", "Lighting", "Mood", "Prompt"];
  const known = new Set([...defaultLabels, ...array(categoryNames).map((c) => text(c).trim()).filter(Boolean)]);
  const regex = /(?:^|\n\n|\r\n\r\n)(?<label>[A-Za-z0-9 _\-]+):\s*(?<content>.*?)(?=(?:\n\n|\r\n\r\n)[A-Za-z0-9 _\-]+:|$)/gs;
  const matches = [...input.matchAll(regex)];
  const sections = {};
  for (const match of matches) {
    const label = match.groups?.label?.trim();
    const content = match.groups?.content?.trim();
    if (!label || !content) continue;
    let matched = label;
    for (const k of known) {
      if (k.toLocaleLowerCase() === label.toLocaleLowerCase()) {
        matched = k;
        break;
      }
    }
    sections[matched] = content;
  }
  return sections;
}
