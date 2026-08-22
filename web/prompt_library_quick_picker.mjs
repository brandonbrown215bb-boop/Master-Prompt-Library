import {
  categoryLabel,
  filterEntriesV2,
  navigateCatalogIndex,
  normalizeLibraryPayload,
  normalizeSelectionState,
  paginateEntries,
  serializeSelectionState,
} from "./library_v2_logic.mjs";

export const QUICK_PICKER_PAGE_SIZE = 6;
export const QUICK_PICKER_GRID_COLUMNS = 3;

/** A fresh library request starts at each collapsed-to-expanded transition. */
export function shouldRefreshQuickPickerOnExpand(wasExpanded, isExpanded) {
  return !Boolean(wasExpanded) && Boolean(isExpanded);
}

function array(value) {
  return Array.isArray(value) ? value : [];
}

function text(value) {
  return typeof value === "string" ? value : "";
}

function trim(value) {
  return text(value).trim();
}

function errorText(error) {
  const message = error instanceof Error ? error.message : String(error || "Unexpected library error.");
  return message.trim().slice(0, 240) || "Unexpected library error.";
}

/** Return the selected category's entries after query filtering. */
export function quickPickerEntries(library, categoryId, query = "") {
  const categories = array(library?.categories);
  const category = categories.find((candidate) => candidate?.id === categoryId) || null;
  return {
    category,
    entries: filterEntriesV2(category?.entries || [], { query }),
  };
}

/** Return one clamped quick-picker page (kept for backwards compatibility). */
export function paginateQuickPicker(entries, requestedPage = 0) {
  return paginateEntries(entries, requestedPage, QUICK_PICKER_PAGE_SIZE);
}

/** Navigate a 2D tile grid or linear index with column awareness and boundary wrapping. */
export function navigateQuickPickerIndex(currentIndex, key, itemCount, { columns = QUICK_PICKER_GRID_COLUMNS, pageSize = 6 } = {}) {
  return navigateCatalogIndex(currentIndex, key, itemCount, { pageSize, columns });
}

/** Resolve the primary or first preview image for an entry. */
export function primaryImageForEntry(entry) {
  if (!entry || !Array.isArray(entry.images)) return null;
  if (entry.primary_image_id) {
    const match = entry.images.find((image) => image && image.id === entry.primary_image_id && image.kind === "preview");
    if (match) return match;
  }
  return entry.images.find((image) => image && image.kind === "preview") || null;
}

/** Build an entry image URL. */
export function entryImageUrl(apiBase = "/master_prompt_library/v2", entry = null, image = null) {
  if (!entry?.id || !image?.id) return "";
  const base = text(apiBase).replace(/\/+$/, "") || "/master_prompt_library/v2";
  return `${base}/entries/${encodeURIComponent(entry.id)}/images/${encodeURIComponent(image.id)}`;
}

/** Toggle one category ID while preserving every other category and selection order. */
export function toggleQuickPickerSelection(selectionState, categoryId, entryId, selected) {
  const normalized = normalizeSelectionState(selectionState);
  const category = trim(categoryId);
  const id = trim(entryId);
  if (!category || !id) return normalized;

  const selections = Object.fromEntries(Object.entries(normalized.selections).map(([key, ids]) => [key, array(ids).slice()]));
  const ids = array(selections[category]);
  const shouldSelect = selected === undefined ? !ids.includes(id) : Boolean(selected);
  selections[category] = shouldSelect
    ? (ids.includes(id) ? ids : [...ids, id])
    : ids.filter((candidate) => candidate !== id);
  return { version: normalized.version, selections };
}

function domElement(tag, attributes = {}) {
  const item = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === null) continue;
    if (key === "className") item.className = String(value);
    else if (key === "textContent") item.textContent = String(value);
    else if (key in item && typeof value !== "object") {
      try { item[key] = value; } catch { item.setAttribute(key, String(value)); }
    } else item.setAttribute(key, String(value));
  }
  return item;
}

function clear(item) {
  while (item?.firstChild) item.removeChild(item.firstChild);
}

function selectedForCategory(selection, categoryId) {
  return array(selection?.selections?.[categoryId]);
}

function selectionWidget(node) {
  return node?.widgets?.find((candidate) => candidate?.name === "selection_state") || null;
}

/**
 * Transient DOM controller for the on-node quick picker. It intentionally owns no
 * serialized widget value; the hidden selection_state widget remains the
 * sole source of truth.
 */
export class QuickPickerController {
  constructor(node, { fetchLibrary, onSelectionChange, apiBase = "/master_prompt_library/v2" } = {}) {
    this.node = node;
    this.fetchLibrary = fetchLibrary;
    this.onSelectionChange = onSelectionChange;
    this.apiBase = apiBase;
    this.library = null;
    this.selection = normalizeSelectionState(selectionWidget(node)?.value);
    this.expanded = false;
    this.loading = false;
    this.errorMessage = "";
    this.activeCategory = "";
    this.query = "";
    this.cursor = 0;

    this.root = domElement("div", { className: "mpl2-quick-root" });
    this.toggle = domElement("button", { className: "mpl2-quick-toggle", type: "button", textContent: "Quick pick components" });
    this.toggle.setAttribute("aria-expanded", "false");
    this.toggle.addEventListener("click", () => { void this.setExpanded(!this.expanded); });

    this.panel = domElement("div", { className: "mpl2-quick-panel" });
    this.controls = domElement("div", { className: "mpl2-quick-controls" });
    this.categoryLabel = domElement("label", { className: "mpl2-quick-label", textContent: "Category" });
    this.categorySelect = domElement("select", { className: "mpl2-quick-select", "aria-label": "Quick picker category" });
    this.categoryLabel.appendChild(this.categorySelect);

    this.searchLabel = domElement("label", { className: "mpl2-quick-label", textContent: "Search" });
    this.searchWrap = domElement("div", { className: "mpl2-quick-search-wrap" });
    this.searchInput = domElement("input", { className: "mpl2-quick-input", type: "search", placeholder: "Filter components…", "aria-label": "Search components" });
    this.clearSearchBtn = domElement("button", { className: "mpl2-quick-clear-search", type: "button", title: "Clear search", "aria-label": "Clear search", textContent: "×" });
    this.searchWrap.append(this.searchInput, this.clearSearchBtn);
    this.searchLabel.appendChild(this.searchWrap);
    this.controls.append(this.categoryLabel, this.searchLabel);

    this.state = domElement("div", { className: "mpl2-quick-state", role: "status", "aria-live": "polite" });
    this.tiles = domElement("div", { className: "mpl2-quick-tiles", role: "listbox", "aria-label": "Component tiles" });
    this.snippet = domElement("div", { className: "mpl2-quick-snippet", "aria-live": "polite", textContent: "Hover or focus a component to inspect prompt" });

    // Isolate mousewheel scrolling so LiteGraph does not zoom the canvas while browsing tiles
    this.tiles.addEventListener("wheel", (event) => {
      event.stopPropagation();
    }, { passive: true });

    this.panel.append(this.controls, this.state, this.tiles, this.snippet);
    this.root.append(this.toggle, this.panel);

    this.categorySelect.addEventListener("change", () => {
      this.activeCategory = this.categorySelect.value;
      this.cursor = 0;
      this.renderResults();
    });
    this.searchInput.addEventListener("input", () => {
      this.query = this.searchInput.value;
      this.cursor = 0;
      this.renderResults();
    });
    this.clearSearchBtn.addEventListener("click", () => {
      this.searchInput.value = "";
      this.query = "";
      this.cursor = 0;
      this.renderResults();
      this.searchInput.focus();
    });

    this.render();
  }

  layoutSize() {
    return {
      minWidth: 180,
      minHeight: this.expanded ? 280 : 34,
      maxWidth: 10000,
      maxHeight: 10000,
    };
  }

  markLayoutDirty() {
    this.node?.setDirtyCanvas?.(true, true);
  }

  categories() {
    return array(this.library?.categories);
  }

  readSelection() {
    const categories = this.categories();
    return normalizeSelectionState(selectionWidget(this.node)?.value, categories);
  }

  syncFromNode(library) {
    if (library) this.library = normalizeLibraryPayload(library).library;
    this.selection = this.readSelection();
    const categories = this.categories();
    if (!categories.some((category) => category.id === this.activeCategory)) this.activeCategory = categories[0]?.id || "";
    this.clampView();
    if (this.expanded && !this.loading) this.render();
  }

  async setExpanded(value) {
    const wasExpanded = this.expanded;
    this.expanded = Boolean(value);
    this.errorMessage = "";
    this.render();
    this.markLayoutDirty();
    if (shouldRefreshQuickPickerOnExpand(wasExpanded, this.expanded)) {
      await this.loadLibrary();
    }
  }

  async loadLibrary() {
    if (this.loading) return;
    this.loading = true;
    this.errorMessage = "";
    this.render();
    try {
      if (typeof this.fetchLibrary !== "function") throw new Error("Library request is unavailable.");
      this.library = normalizeLibraryPayload(await this.fetchLibrary()).library;
      this.selection = this.readSelection();
      const categories = this.categories();
      this.activeCategory = categories.some((category) => category.id === this.activeCategory) ? this.activeCategory : (categories[0]?.id || "");
      this.cursor = 0;
    } catch (error) {
      this.errorMessage = errorText(error);
    } finally {
      this.loading = false;
      this.render();
      this.markLayoutDirty();
    }
  }

  clampView() {
    const { entries } = quickPickerEntries(this.library, this.activeCategory, this.query);
    if (!entries.length) this.cursor = 0;
    else this.cursor = Math.min(Math.max(Number(this.cursor) || 0, 0), entries.length - 1);
  }

  computeGridColumns() {
    const width = this.tiles?.clientWidth || 0;
    if (width > 0) return Math.max(1, Math.floor((width + 6) / 82));
    return QUICK_PICKER_GRID_COLUMNS;
  }

  focusCursor() {
    const focus = () => {
      const target = this.tiles.querySelector(`[data-mpl2-quick-index="${this.cursor}"]`);
      if (target) {
        target.scrollIntoView({ block: "nearest", inline: "nearest" });
        target.focus();
      }
    };
    if (typeof globalThis.requestAnimationFrame === "function") globalThis.requestAnimationFrame(focus);
    else if (typeof queueMicrotask === "function") queueMicrotask(focus);
    else setTimeout(focus, 0);
  }

  handleTileKeydown(event, globalIndex) {
    const key = event.key;
    if (key === "Enter" || key === " ") {
      event.preventDefault();
      this.cursor = globalIndex;
      const { entries } = quickPickerEntries(this.library, this.activeCategory, this.query);
      const entry = entries[globalIndex];
      if (entry) this.toggleEntry(entry.id);
      return;
    }
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End"].includes(key)) return;
    const { entries } = quickPickerEntries(this.library, this.activeCategory, this.query);
    const columns = this.computeGridColumns();
    const nextIndex = navigateQuickPickerIndex(globalIndex, key, entries.length, { columns, pageSize: columns * 2 });
    if (nextIndex < 0) return;
    event.preventDefault();
    this.cursor = nextIndex;
    this.renderResults();
    this.focusCursor();
  }

  toggleEntry(entryId) {
    const widget = selectionWidget(this.node);
    if (!widget || !this.library || !this.activeCategory) return;
    const current = this.readSelection();
    const selected = selectedForCategory(current, this.activeCategory).includes(entryId);
    const next = toggleQuickPickerSelection(current, this.activeCategory, entryId, !selected);
    const serialized = serializeSelectionState(next, this.categories());
    try {
      widget.value = serialized;
      widget.callback?.(serialized);
      this.selection = normalizeSelectionState(serialized, this.categories());
      this.markLayoutDirty();
      this.onSelectionChange?.(this.library);
      this.renderResults();
      this.focusCursor();
    } catch (error) {
      this.errorMessage = errorText(error);
      this.render();
    }
  }

  renderCategoryOptions() {
    const categories = this.categories();
    const current = this.activeCategory;
    clear(this.categorySelect);
    for (const category of categories) {
      this.categorySelect.appendChild(domElement("option", { value: category.id, textContent: categoryLabel(category) }));
    }
    this.categorySelect.value = categories.some((category) => category.id === current) ? current : (categories[0]?.id || "");
    this.activeCategory = this.categorySelect.value;
    this.searchInput.value = this.query;
    this.categorySelect.disabled = this.loading || !categories.length;
    this.searchInput.disabled = this.loading || !this.library;
    this.clearSearchBtn.disabled = this.loading || !this.library;
  }

  renderResults() {
    if (!this.expanded) return;
    this.renderCategoryOptions();
    clear(this.tiles);
    if (this.loading) {
      this.state.textContent = "Loading library…";
      this.snippet.textContent = "";
      return;
    }
    if (this.errorMessage) {
      this.state.textContent = `Unable to load library: ${this.errorMessage}`;
      this.snippet.textContent = "";
      return;
    }
    if (!this.library) {
      this.state.textContent = "Expand to load the library.";
      this.snippet.textContent = "";
      return;
    }

    const { entries } = quickPickerEntries(this.library, this.activeCategory, this.query);
    this.cursor = entries.length ? Math.min(Math.max(this.cursor, 0), entries.length - 1) : 0;
    const selected = new Set(selectedForCategory(this.selection, this.activeCategory));

    for (const [globalIndex, entry] of entries.entries()) {
      const isSelected = selected.has(entry.id);
      const tile = domElement("button", {
        className: "mpl2-quick-tile",
        type: "button",
        role: "option",
        "aria-selected": String(isSelected),
        "aria-label": `${entry.name || entry.id}${isSelected ? " (selected)" : ""}`,
      });
      tile.setAttribute("tabindex", globalIndex === this.cursor ? "0" : "-1");
      tile.dataset.mpl2QuickIndex = String(globalIndex);
      tile.dataset.mpl2QuickEntry = String(entry.id);

      const image = primaryImageForEntry(entry);
      if (image) {
        const img = domElement("img", {
          className: "mpl2-quick-tile-thumb",
          src: entryImageUrl(this.apiBase, entry, image),
          alt: image.caption || entry.name || "Preview",
          loading: "lazy",
        });
        tile.appendChild(img);
      } else {
        const placeholder = domElement("span", {
          className: "mpl2-quick-tile-thumb mpl2-quick-tile-placeholder",
          textContent: entry.name ? entry.name.trim().slice(0, 2).toUpperCase() : "✦",
        });
        tile.appendChild(placeholder);
      }

      const badge = domElement("span", { className: "mpl2-quick-tile-badge", textContent: "✓" });
      const label = domElement("span", {
        className: "mpl2-quick-tile-label",
        textContent: entry.name || entry.id,
        title: entry.name || entry.id,
      });
      tile.append(badge, label);

      const updateSnippet = () => {
        this.snippet.textContent = entry.prompt ? `Prompt: ${entry.prompt}` : `Component: ${entry.name || entry.id}`;
        this.snippet.title = entry.prompt || entry.name || "";
      };

      tile.addEventListener("mouseenter", updateSnippet);
      tile.addEventListener("focus", updateSnippet);
      tile.addEventListener("mouseleave", () => {
        this.snippet.textContent = "Hover or focus a component to inspect prompt";
        this.snippet.title = "";
      });
      tile.addEventListener("blur", () => {
        this.snippet.textContent = "Hover or focus a component to inspect prompt";
        this.snippet.title = "";
      });

      tile.addEventListener("click", () => {
        this.cursor = globalIndex;
        this.toggleEntry(entry.id);
      });
      tile.addEventListener("keydown", (event) => this.handleTileKeydown(event, globalIndex));

      this.tiles.appendChild(tile);
    }

    this.state.textContent = entries.length ? `${entries.length} component${entries.length === 1 ? "" : "s"}` : "No matches.";
    if (!entries.length) this.snippet.textContent = "";
  }

  render() {
    this.toggle.textContent = this.expanded ? "Collapse quick picker" : "Quick pick components";
    this.toggle.setAttribute("aria-expanded", String(this.expanded));
    this.panel.hidden = !this.expanded;
    if (this.expanded) this.renderResults();
  }
}

/** Install once, and fail closed when the host has no usable DOM widget API. */
export function installQuickPicker(node, options = {}) {
  if (!node || node.__mpl2QuickPicker) return node?.__mpl2QuickPicker || null;
  if (typeof node.addDOMWidget !== "function") return null;
  try {
    const controller = new QuickPickerController(node, options);
    const widget = node.addDOMWidget("mpl2_quick_picker", "div", controller.root, {
      serialize: false,
      hideOnZoom: false,
      computeLayoutSize: () => controller.layoutSize(),
    });
    if (!widget) return null;
    widget.serialize = false;
    widget.computeLayoutSize = () => controller.layoutSize();
    node.__mpl2QuickPicker = controller;
    return controller;
  } catch {
    return null;
  }
}

