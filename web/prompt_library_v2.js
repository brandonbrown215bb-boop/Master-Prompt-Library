import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import {
  CORE_CATEGORY_IDS,
  PROMPT_TOKEN,
  availableTags,
  buildAssembledPrompt,
  categoryLabel,
  cleanPositivePrompt,
  applyExtractionResponse,
  filterEntriesV2,
  folderOptions,
  galleryState,
  importPreviewSummary,
  extractionRequestToken,
  extractionCategoryForField,
  extractionFieldOptions,
  extractionSavePlan,
  moveByOffset,
  navigateCatalogIndex,
  normalizeComponentOrder,
  normalizeImportMapping,
  normalizeLibraryPayload,
  normalizeSelectionState,
  paginateEntries,
  normalizeTags,
  parsePromptSections,
  reorderIds,
  serializeComponentOrder,
  serializeSelectionState,
  selectImportFiles,
  selectImportSource,
  selectExtractionField,
  selectedExtractionFields,
  setGalleryPrimary,
  runIfCurrentExtractionRequest,
  selectedExtractionDraft,
  staleSelectionIds,
  suggestEntryName,
  updateExtractionFieldDraft,
  toggleExtractionFieldSelection,
  visionExtractionRequestFields,
} from "./library_v2_logic.mjs?v=2.1.0-lora1";
import { installQuickPicker } from "./prompt_library_quick_picker.mjs?v=2.1.0-lora1";
import {
  clampLayoutGeometry,
  layoutCSSVariables,
  loadLayoutState,
  nextTabIndex,
  resetLayoutState,
  saveLayoutState,
  viewportSize,
} from "./modal_ui_state.mjs?v=2.1.0-uiux1";
import {
  VISION_PROVIDERS,
  connectionForProvider,
  forgetVisionConnection,
  loadVisionConnection,
  normalizeVisionModels,
  saveVisionConnection,
  visionProvider,
} from "./vision_connection_state.mjs?v=2.1.0-vision1";

const EXTENSION_NAME = "PromptLibrary.MasterPromptLibraryV2";
const API_BASE = "/master_prompt_library/v2";
const MAX_ERROR_LENGTH = 600;
const MAX_TAG_LENGTH = 80;
const CATALOG_PAGE_SIZE = 10;

function element(tag, attributes = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "textContent") node.textContent = String(value);
    else if (key === "className") node.className = String(value);
    else if (key === "dataset" && value && typeof value === "object") {
      for (const [dataKey, dataValue] of Object.entries(value)) node.dataset[dataKey] = String(dataValue);
    } else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key in node && typeof value !== "object") {
      try { node[key] = value; } catch { node.setAttribute(key, String(value)); }
    } else node.setAttribute(key, String(value));
  }
  for (const child of children) if (child) node.appendChild(child);
  return node;
}

function clear(node) {
  while (node?.firstChild) node.removeChild(node.firstChild);
}

function text(value) {
  return typeof value === "string" ? value : "";
}

function trimError(error) {
  const message = error instanceof Error ? error.message : String(error || "Unexpected library error.");
  return message.trim().slice(0, MAX_ERROR_LENGTH) || "Unexpected library error.";
}

function confirmAction(message) {
  return typeof window === "undefined" || typeof window.confirm !== "function" ? true : window.confirm(message);
}

function mergeImportFiles(existing, incoming) {
  const result = [...(existing || [])];
  const seen = new Set(result.map((file) => `${file.webkitRelativePath || file.name}:${file.size}:${file.lastModified}`));
  for (const file of incoming || []) {
    const key = `${file.webkitRelativePath || file.name}:${file.size}:${file.lastModified}`;
    if (!seen.has(key)) { seen.add(key); result.push(file); }
  }
  return result;
}

function chooseNamedItem(items, prompt, emptyMessage) {
  if (!items.length) return null;
  const lines = items.map((item, index) => `${index + 1}. ${item.name}`).join("\n");
  const answer = text(ask(`${prompt}\n${lines}\nEnter a number or display name:`, "1")).trim();
  if (!answer) return null;
  const number = Number(answer);
  if (Number.isInteger(number) && number >= 1 && number <= items.length) return items[number - 1];
  const wanted = answer.toLocaleLowerCase();
  const match = items.find((item) => item.name.toLocaleLowerCase() === wanted);
  if (match) return match;
  if (emptyMessage) modalInstance?.setError?.(emptyMessage);
  return null;
}

function ask(message, fallback = "") {
  return typeof window === "undefined" || typeof window.prompt !== "function" ? fallback : window.prompt(message, fallback);
}

async function responsePayload(response) {
  if (!response) throw new Error("The library server returned no response.");
  let bodyText = "";
  if (typeof response.text === "function") {
    try { bodyText = await response.text(); } catch { bodyText = ""; }
  }
  let data = null;
  if (bodyText) {
    try { data = JSON.parse(bodyText); } catch { data = null; }
  } else if (typeof response.json === "function") {
    try { data = await response.json(); } catch { data = null; }
  }
  const failed = response.ok === false || (Number.isFinite(response.status) && response.status >= 400);
  if (failed) {
    const message = data && typeof data === "object" ? (data.error || data.message || data.detail) : bodyText;
    throw new Error(message || `Library request failed (${response.status || "unknown status"}).`);
  }
  return data;
}

async function requestJSON(path, options = {}) {
  return responsePayload(await api.fetchApi(path, options));
}

function requestOptions(method, body) {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function entryFromPayload(payload) {
  return payload?.entry && typeof payload.entry === "object" ? payload.entry : payload;
}

function ensureStyles() {
  for (const href of [
    new URL("./prompt_library_v2.css?v=2.1.0-lora1", import.meta.url).href,
    new URL("./prompt_library_quick_picker.css", import.meta.url).href,
  ]) {
    if (document.querySelector(`link[data-mpl2-styles="${href}"]`)) continue;
    document.head.appendChild(element("link", { rel: "stylesheet", href, "data-mpl2-styles": href }));
  }
}

function nodesInOpenGraph() {
  const graph = app?.graph;
  const nodes = graph?._nodes || graph?.nodes;
  return Array.isArray(nodes) ? nodes : [];
}

function isV2NodeData(nodeData) {
  return nodeData?.name === "MasterPromptLibraryV2" || nodeData?.display_name === "Master Prompt Library v2";
}

function isV2Node(node) {
  if (!node) return false;
  if (node.comfyClass === "MasterPromptLibraryV2" || node.type === "MasterPromptLibraryV2" || node.constructor?.comfyClass === "MasterPromptLibraryV2") return true;
  if (node.title !== "Master Prompt Library v2" && node.title !== "Master Prompt Library V2") return false;
  const names = new Set((node.widgets || []).map((widget) => widget?.name));
  return names.has("selection_state") && names.has("component_order");
}

function widget(node, name) {
  return node?.widgets?.find((candidate) => candidate?.name === name) || null;
}

function parseDraftFromNode(node, categories = []) {
  const state = normalizeSelectionState(widget(node, "selection_state")?.value, categories);
  const rawOrder = widget(node, "component_order")?.value;
  const order = normalizeComponentOrder(rawOrder, categories, { includeUnknown: true });
  return { selection: state, order };
}

function hideSerializedWidget(candidate) {
  if (!candidate) return;
  candidate.serialize = true;
  candidate.hidden = true;
  candidate.options = { ...(candidate.options || {}), serialize: true };
  candidate.computeSize = () => [0, -4];
}

function summaryForNode(node, library) {
  const categories = library?.categories || [];
  const draft = parseDraftFromNode(node, categories);
  const stale = staleSelectionIds(draft.selection, categories);
  const pieces = [];
  for (const category of categories) {
    const ids = draft.selection.selections[category.id] || [];
    if (!ids.length) continue;
    const names = ids.map((id) => category.entries.find((entry) => entry.id === id)?.name || `missing:${id}`).slice(0, 3);
    pieces.push(`${categoryLabel(category)} ${ids.length}: ${names.join(", ")}${ids.length > names.length ? "…" : ""}`);
  }
  const warnings = stale.missingCategoryIds.length || stale.missingEntryIds.length
    ? ` · stale ${stale.missingCategoryIds.length + stale.missingEntryIds.length}`
    : "";
  return pieces.length ? `${pieces.join(" · ")}${warnings}` : `No components selected${warnings}`;
}

function updateNodeSummaries(library) {
  for (const node of nodesInOpenGraph()) {
    if (!isV2Node(node)) continue;
    const summary = summaryForNode(node, library);
    if (node.__mpl2SummaryWidget) {
      node.__mpl2SummaryWidget.value = summary;
      node.__mpl2SummaryWidget.label = summary;
    }
    node.__mpl2QuickPicker?.syncFromNode?.(library);
    node.setDirtyCanvas?.(true, true);
  }
}

class MasterPromptLibraryV2Modal {
  constructor() {
    this.root = element("div", { className: "mpl2-modal", hidden: true });
    this.backdrop = element("div", { className: "mpl2-backdrop", "aria-hidden": "true" });
    this.dialog = element("section", { className: "mpl2-dialog", role: "dialog", "aria-modal": "true", "aria-labelledby": "mpl2-title" });
    this.root.append(this.backdrop, this.dialog);
    document.body.appendChild(this.root);
    this.library = null;
    this.fingerprint = "";
    this.activeNode = null;
    this.activeCategory = "style";
    this.selectedId = null;
    this.cursorEntryId = null;
    this.catalogPage = 0;
    this.pendingCatalogFocusId = null;
    this.mode = "browse";
    this.editorDraft = null;
    this.editorOriginal = null;
    this.selection = null;
    this.order = [];
    this.draftNodeKey = null;
    this.query = "";
    this.folderId = "";
    this.tag = "";
    this.favoritesOnly = false;
    this.galleryKind = "preview";
    this.galleryBusy = false;
    this.galleryStatuses = new Map();
    this.availableLoras = [];
    this.lorasLoaded = false;
    this.importState = { preview: null, mapping: {}, policy: "skip", files: [], sources: [], sourceId: "" };
    const visionConnection = loadVisionConnection();
    this.extractState = {
      file: null,
      previewUrl: "",
      prompt: "",
      suggestedName: "",
      targetCategory: "style",
      folderId: "",
      tags: "",
      source: "",
      sections: {},
      structured: null,
      selectedExtractedField: "positive_prompt",
      selectedExtractionFields: ["positive_prompt"],
      extractedFieldDrafts: { positive_prompt: "" },
      busy: false,
      ...visionConnection,
      visionModels: normalizeVisionModels([], visionConnection.apiModel),
      visionModelsLoading: false,
      visionModelsError: "",
      customModel: false,
    };
    this.busy = false;
    this.statusMessage = "";
    this.errorMessage = "";
    this.previousFocus = null;
    this.imageRevision = 0;
    this.activeSubdialog = null;
    this.closeActiveSubdialog = null;
    this.subdialogSequence = 0;
    this.focusRestore = null;
    this.mobilePane = "catalog";
    this.layout = loadLayoutState();
    this.layoutObserver = null;
    this.splitterDrag = null;
    this.showPromptPreview = false;
    this.build();
    this.applyLayout();
    this.boundKeydown = (event) => this.handleKeydown(event);
  }

  build() {
    const header = element("header", { className: "mpl2-header" });
    const heading = element("div", {}, [
      element("p", { className: "mpl2-kicker", textContent: "Prompt catalog / working archive" }),
      element("h2", { className: "mpl2-title", id: "mpl2-title", textContent: "Master Prompt Library v2" }),
      element("p", { className: "mpl2-subtitle", textContent: "Select ordered components, keep the archive local, and apply one deterministic state to the node." }),
    ]);
    this.context = element("p", { className: "mpl2-context" });
    this.closeButton = this.setFocusKey(element("button", { className: "mpl2-close", type: "button", "aria-label": "Close library", title: "Close library", textContent: "×" }), "close");
    this.closeButton.addEventListener("click", () => void this.close());
    header.append(heading, this.context, this.closeButton);

    const toolbar = element("div", { className: "mpl2-toolbar" });
    const searchWrap = element("label", { className: "mpl2-toolbar-search" }, [
      element("span", { className: "mpl2-label", textContent: "Find in archive" }),
    ]);
    this.searchInput = element("input", { className: "mpl2-input", type: "search", placeholder: "Search names, prompts, tags…", "aria-label": "Search library entries", autocomplete: "off" });
    this.searchInput.addEventListener("input", () => { this.query = this.searchInput.value; this.resetCatalogPage(); this.render(); });
    searchWrap.appendChild(this.searchInput);
    this.folderSelect = element("select", { className: "mpl2-select", "aria-label": "Filter by folder" });
    this.folderSelect.addEventListener("change", () => { this.folderId = this.folderSelect.value; this.resetCatalogPage(); this.render(); });
    this.tagSelect = element("select", { className: "mpl2-select", "aria-label": "Filter by tag" });
    this.tagSelect.addEventListener("change", () => { this.tag = this.tagSelect.value; this.resetCatalogPage(); this.render(); });
    const favoriteLabel = element("label", { className: "mpl2-check-label" });
    this.favoriteInput = element("input", { type: "checkbox", "aria-label": "Favorites only" });
    this.favoriteInput.addEventListener("change", () => { this.favoritesOnly = this.favoriteInput.checked; this.resetCatalogPage(); this.render(); });
    favoriteLabel.append(this.favoriteInput, document.createTextNode(" Favorites"));
    this.clearFiltersButton = this.actionButton("Clear filters", "", () => { this.query = ""; this.folderId = ""; this.tag = ""; this.favoritesOnly = false; this.resetCatalogPage(); this.render(); });
    this.importButton = this.actionButton("Import…", "", () => { this.mode = "import"; this.clearError(); this.loadImportSources(); this.render(); });
    this.extractButton = this.actionButton("Extract Image…", "", () => {
      this.mode = "extract_image";
      this.clearError();
      this.initExtractImageState();
      this.render();
      void this.refreshVisionModels({ silent: true });
    });
    this.exportButton = this.actionButton("Export JSON", "", () => this.exportLibrary());
    this.layoutControls = element("div", { className: "mpl2-layout-controls", "aria-label": "Layout controls" });
    this.resetLayoutButton = this.actionButton("Reset layout", "", () => this.resetLayout());
    this.layoutControls.appendChild(this.resetLayoutButton);
    toolbar.append(searchWrap, this.folderSelect, this.tagSelect, favoriteLabel, this.clearFiltersButton, this.importButton, this.extractButton, this.exportButton, this.layoutControls);

    this.error = element("div", { className: "mpl2-error", role: "alert", hidden: true });
    this.body = element("div", { className: "mpl2-body" });
    this.rail = element("aside", { className: "mpl2-rail", "aria-label": "Prompt categories" });
    this.paneTabs = element("div", { className: "mpl2-pane-tabs", role: "tablist", "aria-label": "Prompt panes" });
    this.main = element("main", { className: "mpl2-main" });
    this.listPane = element("section", { className: "mpl2-list-pane", id: "mpl2-catalog-pane", role: "tabpanel", "aria-labelledby": "mpl2-pane-tab-catalog", "aria-label": "Prompt catalog" });
    this.detailPane = element("section", { className: "mpl2-detail-pane", id: "mpl2-detail-pane", role: "tabpanel", "aria-labelledby": "mpl2-pane-tab-detail", "aria-label": "Selection and entry details" });
    this.mainSplitter = element("div", {
      className: "mpl2-main-splitter",
      role: "separator",
      tabindex: "0",
      "aria-orientation": "vertical",
      "aria-label": "Resize catalog and details panes",
    });
    this.main.append(this.listPane, this.mainSplitter, this.detailPane);
    this.body.append(this.rail, this.paneTabs, this.main);
    this.installSplitterHandlers();
    this.footer = element("footer", { className: "mpl2-footer" });
    this.applyButton = this.actionButton("Apply to Node", "primary", () => this.applyToNode());
    this.footer.append(element("span", { className: "mpl2-footer-note", textContent: "Closing keeps the node's prior state." }), this.applyButton);
    this.dialog.append(header, toolbar, this.error, this.body, this.footer);
    this.backdrop.addEventListener("click", () => void this.close());
  }

  actionButton(label, variant, callback) {
    return element("button", {
      className: `mpl2-button${variant === "primary" ? " mpl2-button-primary" : ""}${variant === "danger" ? " mpl2-button-danger" : ""}`,
      type: "button", textContent: label, onclick: callback,
    });
  }

  currentViewport() {
    let gutter = 8;
    try {
      const rootStyle = getComputedStyle(this.root);
      // Padding is a resolved CSS length even when the custom property itself
      // contains a clamp() expression.
      const rawGutter = rootStyle.paddingLeft || rootStyle.getPropertyValue("--mpl2-modal-gutter");
      const parsedGutter = Number.parseFloat(rawGutter);
      if (Number.isFinite(parsedGutter)) gutter = parsedGutter;
      return { ...viewportSize({ width: window.innerWidth, height: window.innerHeight }), gutter };
    } catch {
      return { ...viewportSize(), gutter };
    }
  }

  applyLayout() {
    this.layout = clampLayoutGeometry(this.layout, this.currentViewport());
    const variables = layoutCSSVariables(this.layout, this.currentViewport());
    // Native CSS resize writes direct width/height properties.  The persisted
    // CSS variables are the single geometry source, so clear those overrides
    // after capturing a resize (and on Reset) before reapplying the variables.
    this.dialog.style.removeProperty("width");
    this.dialog.style.removeProperty("height");
    for (const [name, value] of Object.entries(variables)) this.dialog.style.setProperty(name, value);
    this.main?.style.setProperty("--mpl2-list-width", variables["--mpl2-list-width"]);
    if (this.mainSplitter) {
      const maxList = Math.max(220, this.layout.dialogWidth - 320);
      this.mainSplitter.setAttribute("aria-valuemin", "220");
      this.mainSplitter.setAttribute("aria-valuemax", String(Math.round(maxList)));
      this.mainSplitter.setAttribute("aria-valuenow", String(this.layout.listWidth));
    }
  }

  persistLayout() {
    saveLayoutState(this.layout, undefined, this.currentViewport());
    this.applyLayout();
  }

  resetLayout() {
    this.layout = resetLayoutState(undefined, this.currentViewport());
    this.applyLayout();
    this.setStatus("Layout reset to defaults.");
    if (!this.root.hidden) this.render();
  }

  setListWidth(value, { persist = true } = {}) {
    const next = clampLayoutGeometry({ ...this.layout, listWidth: value }, this.currentViewport());
    this.layout = next;
    this.applyLayout();
    if (persist) saveLayoutState(this.layout, undefined, this.currentViewport());
  }

  installSplitterHandlers() {
    this.mainSplitter.addEventListener("pointerdown", (event) => {
      if (event.button !== undefined && event.button !== 0) return;
      event.preventDefault();
      this.splitterDrag = { startX: event.clientX, startListWidth: this.layout.listWidth, pointerId: event.pointerId };
      this.mainSplitter.setPointerCapture?.(event.pointerId);
    });
    this.mainSplitter.addEventListener("pointermove", (event) => {
      if (!this.splitterDrag) return;
      event.preventDefault();
      this.setListWidth(this.splitterDrag.startListWidth + (event.clientX - this.splitterDrag.startX));
    });
    const stopDrag = (event) => {
      if (!this.splitterDrag) return;
      if (event?.pointerId === undefined || event.pointerId === this.splitterDrag.pointerId) this.splitterDrag = null;
    };
    this.mainSplitter.addEventListener("pointerup", stopDrag);
    this.mainSplitter.addEventListener("pointercancel", stopDrag);
    this.mainSplitter.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const viewport = this.currentViewport();
      const maxList = Math.max(220, this.layout.dialogWidth - 320);
      const next = event.key === "Home"
        ? 220
        : event.key === "End"
          ? maxList
          : this.layout.listWidth + (event.key === "ArrowRight" ? 16 : -16);
      this.setListWidth(next);
    });
    const ResizeObserverCtor = globalThis.ResizeObserver;
    if (typeof ResizeObserverCtor === "function") {
      this.layoutObserver = new ResizeObserverCtor(() => {
        if (this.root.hidden) return;
        const viewport = this.currentViewport();
        const measured = this.dialog.getBoundingClientRect?.();
        if (!measured?.width || !measured?.height) return;
        const hasDirectWidth = Boolean(this.dialog.style.width);
        const hasDirectHeight = Boolean(this.dialog.style.height);
        if (!hasDirectWidth && !hasDirectHeight) {
          const restored = loadLayoutState(undefined, viewport);
          if (JSON.stringify(restored) !== JSON.stringify(this.layout)) {
            this.layout = restored;
            this.applyLayout();
          }
          return;
        }
        // A viewport cap is not a user resize.  Keep the larger preference so
        // reopening on a larger monitor can restore it.
        const raw = { ...this.layout };
        const maxWidth = viewport.width - (2 * viewport.gutter);
        const maxHeight = viewport.height - (2 * viewport.gutter);
        const userResizedWidth = measured.width < maxWidth - 2;
        const userResizedHeight = measured.height < maxHeight - 2;
        // A window/monitor change can make the rendered box smaller without
        // changing the user's preference. Keep the larger stored value so it
        // can be restored when the viewport grows again.
        if (!userResizedWidth && !userResizedHeight) {
          this.applyLayout();
          return;
        }
        if (userResizedWidth) raw.dialogWidth = measured.width;
        if (userResizedHeight) raw.dialogHeight = measured.height;
        const clamped = clampLayoutGeometry(raw, viewport);
        if (Math.abs(clamped.dialogWidth - this.layout.dialogWidth) >= 2
          || Math.abs(clamped.dialogHeight - this.layout.dialogHeight) >= 2
          || Math.abs(clamped.listWidth - this.layout.listWidth) >= 2) {
          this.layout = clamped;
          this.applyLayout();
          saveLayoutState(this.layout, undefined, viewport);
        }
      });
      this.layoutObserver.observe(this.dialog);
    }
  }

  setFocusKey(node, key) {
    if (node && key) node.dataset.mpl2FocusKey = key;
    return node;
  }

  focusByKey(key) {
    if (!key) return null;
    const target = [...this.dialog.querySelectorAll("[data-mpl2-focus-key]")]
      .find((candidate) => candidate.dataset.mpl2FocusKey === key
        && !candidate.disabled
        && !candidate.hidden
        && !candidate.closest("[hidden]"));
    target?.focus?.();
    return target || null;
  }

  captureRenderFocus() {
    const active = document.activeElement;
    if (!active || active === document.body || !this.dialog.contains(active)) return;
    const key = active.dataset?.mpl2FocusKey;
    if (key) this.focusRestore = { key };
  }

  restoreRenderFocus() {
    const request = this.focusRestore;
    this.focusRestore = null;
    if (!request?.key) return;
    const active = document.activeElement;
    if (active && active !== document.body && this.dialog.contains(active) && active.isConnected !== false) return;
    queueMicrotask(() => {
      const current = document.activeElement;
      if (current && current !== document.body && this.dialog.contains(current) && current.isConnected !== false) return;
      if (this.focusByKey(request.key)) return;
      const key = request.key;
      const fallbackKeys = [];
      if (key.startsWith("order-entry-remove:")) {
        const [, categoryId, entryId] = key.split(":");
        fallbackKeys.push(`order-entry-up:${categoryId}:${entryId}`, `order-entry-down:${categoryId}:${entryId}`);
      }
      if (key.startsWith("detail-delete:")) {
        const [, entryId] = key.split(":");
        fallbackKeys.push(`catalog-card:${entryId}`, "catalog-page:next", "catalog-page:previous");
      }
      fallbackKeys.push(`category:${this.activeCategory}`, `pane-tab:${this.mobilePane}`, "close");
      for (const fallback of fallbackKeys) if (this.focusByKey(fallback)) return;
    });
  }

  renderPaneTabs() {
    this.body.dataset.mobilePane = this.mobilePane;
    this.main.dataset.mobilePane = this.mobilePane;
    clear(this.paneTabs);
    const panes = [
      { key: "catalog", label: "Catalog", controls: this.listPane.id },
      { key: "detail", label: "Details", controls: this.detailPane.id },
    ];
    for (const pane of panes) {
      const tab = this.setFocusKey(element("button", {
        className: `mpl2-pane-tab${pane.key === this.mobilePane ? " is-active" : ""}`,
        type: "button",
        role: "tab",
        id: `mpl2-pane-tab-${pane.key}`,
        "aria-selected": String(pane.key === this.mobilePane),
        "aria-controls": pane.controls,
        tabindex: pane.key === this.mobilePane ? "0" : "-1",
        textContent: pane.label,
      }), `pane-tab:${pane.key}`);
      tab.addEventListener("click", () => this.setMobilePane(pane.key));
      this.paneTabs.appendChild(tab);
    }
  }

  setMobilePane(pane, focus = true) {
    if (pane !== "catalog" && pane !== "detail") return;
    this.mobilePane = pane;
    this.render();
    if (focus) queueMicrotask(() => this.focusByKey(`pane-tab:${pane}`));
  }

  handlePaneTabKeydown(event) {
    if (event.defaultPrevented) return false;
    const target = event.target?.closest?.(".mpl2-pane-tab");
    if (!target) return false;
    const panes = ["catalog", "detail"];
    const current = panes.indexOf(target.id.replace("mpl2-pane-tab-", ""));
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return false;
    event.preventDefault();
    const next = nextTabIndex(current, event.key, panes.length);
    this.setMobilePane(panes[next]);
    return true;
  }

  showSubdialog({ title, content, actions = [], onDismiss = null }) {
    if (this.activeSubdialog) {
      this.closeActiveSubdialog?.();
    }
    const previousFocus = document.activeElement;
    const backdrop = element("div", { className: "mpl2-subdialog-backdrop" });
    const titleId = `mpl2-subdialog-title-${++this.subdialogSequence}`;
    const dialog = element("div", { className: "mpl2-subdialog", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId });
    const header = element("div", { className: "mpl2-subdialog-header" }, [
      element("h4", { className: "mpl2-subdialog-title", id: titleId, textContent: title }),
    ]);
    const body = element("div", { className: "mpl2-subdialog-body" });
    if (Array.isArray(content)) body.append(...content.filter(Boolean));
    else if (content) body.appendChild(content);

    const actionRow = element("div", { className: "mpl2-subdialog-actions" });
    for (const action of actions) {
      const btn = this.actionButton(action.label, action.variant || (action.primary ? "primary" : ""), () => {
        action.onClick?.();
      });
      actionRow.appendChild(btn);
    }

    dialog.append(header, body, actionRow);
    backdrop.appendChild(dialog);
    this.dialog.appendChild(backdrop);
    this.activeSubdialog = backdrop;

    const close = () => {
      if (this.activeSubdialog === backdrop) {
        backdrop.remove();
        this.activeSubdialog = null;
        this.closeActiveSubdialog = null;
        previousFocus?.focus?.();
      }
    };
    const dismiss = () => {
      const wasActive = this.activeSubdialog === backdrop;
      close();
      if (wasActive) onDismiss?.();
    };
    this.closeActiveSubdialog = dismiss;

    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) dismiss();
    });

    const firstInput = dialog.querySelector("input, select, textarea, button.mpl2-button-primary, button");
    queueMicrotask(() => firstInput?.focus?.());

    return { backdrop, dialog, close, dismiss };
  }

  promptDialog({ title, message, defaultValue = "", placeholder = "", confirmLabel = "Save" }) {
    return new Promise((resolve) => {
      const input = element("input", {
        className: "mpl2-input",
        type: "text",
        value: defaultValue,
        placeholder: placeholder || "",
      });
      let sub;
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          e.stopPropagation();
          sub.close();
          resolve(input.value);
        } else if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          sub.dismiss();
        }
      });
      sub = this.showSubdialog({
        title,
        content: [
          message ? element("p", { style: "margin: 0 0 8px;", textContent: message }) : null,
          input,
        ],
        actions: [
          { label: "Cancel", onClick: () => { sub.close(); resolve(null); } },
          { label: confirmLabel, primary: true, onClick: () => { sub.close(); resolve(input.value); } },
        ],
        onDismiss: () => resolve(null),
      });
    });
  }

  confirmDialog({ title, message, confirmLabel = "Confirm", variant = "danger" }) {
    return new Promise((resolve) => {
      const sub = this.showSubdialog({
        title,
        content: element("p", { style: "margin: 0; line-height: 1.5;", textContent: message }),
        actions: [
          { label: "Cancel", onClick: () => { sub.close(); resolve(false); } },
          { label: confirmLabel, variant, primary: variant === "primary", onClick: () => { sub.close(); resolve(true); } },
        ],
        onDismiss: () => resolve(false),
      });
    });
  }

  choiceDialog({ title, message, choices = [] }) {
    return new Promise((resolve) => {
      const menu = element("div", { className: "mpl2-subdialog-menu" });
      const sub = this.showSubdialog({
        title,
        content: [
          message ? element("p", { style: "margin: 0 0 10px;", textContent: message }) : null,
          menu,
        ],
        actions: [
          { label: "Cancel", onClick: () => { sub.close(); resolve(null); } },
        ],
        onDismiss: () => resolve(null),
      });
      for (const choice of choices) {
        const btn = element("button", {
          className: `mpl2-button${choice.variant === "danger" ? " mpl2-button-danger" : ""}${choice.variant === "primary" ? " mpl2-button-primary" : ""}`,
          type: "button",
          textContent: choice.label,
          onclick: () => {
            sub.close();
            resolve(choice.value);
          },
        });
        menu.appendChild(btn);
      }
    });
  }

  chooseFolderDialog(category, title) {
    return new Promise((resolve) => {
      const folders = folderOptions(category);
      if (!folders.length) { resolve(null); return; }
      const select = element("select", { className: "mpl2-select" });
      for (const f of folders) select.appendChild(element("option", { value: f.id, textContent: f.name }));
      const sub = this.showSubdialog({
        title,
        content: select,
        actions: [
          { label: "Cancel", onClick: () => { sub.close(); resolve(null); } },
          { label: "Select", primary: true, onClick: () => {
            const chosen = folders.find((f) => f.id === select.value) || folders[0];
            sub.close();
            resolve(chosen);
          } },
        ],
        onDismiss: () => resolve(null),
      });
    });
  }

  chooseCategoryDialog(categories, title, confirmText = "Select Category") {
    return new Promise((resolve) => {
      const select = element("select", { className: "mpl2-select" });
      for (const c of categories) select.appendChild(element("option", { value: c.id, textContent: categoryLabel(c) }));
      const sub = this.showSubdialog({
        title,
        content: select,
        actions: [
          { label: "Cancel", onClick: () => { sub.close(); resolve(null); } },
          { label: confirmText, primary: true, onClick: () => {
            const chosen = categories.find((c) => c.id === select.value) || categories[0];
            sub.close();
            resolve(chosen);
          } },
        ],
        onDismiss: () => resolve(null),
      });
    });
  }

  open(node) {
    if (!isV2Node(node)) return;
    const newNode = this.activeNode !== node;
    this.activeNode = node;
    this.layout = loadLayoutState(undefined, this.currentViewport());
    this.applyLayout();
    this.previousFocus = document.activeElement;
    this.mode = "browse";
    this.errorMessage = "";
    this.statusMessage = "";
    if (newNode || !this.selection) {
      this.draftNodeKey = node;
      this.selection = normalizeSelectionState(widget(node, "selection_state")?.value);
      this.order = normalizeComponentOrder(widget(node, "component_order")?.value, [], { includeUnknown: true });
      this.selectedId = null;
      this.resetCatalogPage();
    }
    this.root.hidden = false;
    document.addEventListener("keydown", this.boundKeydown);
    this.renderLoading();
    Promise.all([this.refreshLibrary(), this.refreshLoras()]).then(() => {
      this.render();
      queueMicrotask(() => this.searchInput.focus());
    });
  }

  async close() {
    if (this.hasEditorChanges()) {
      const confirmed = await this.confirmDialog({
        title: "Discard Changes?",
        message: "Discard unsaved entry changes?",
        confirmLabel: "Discard Changes",
        variant: "danger",
      });
      if (!confirmed) return;
    }
    if (this.activeSubdialog) {
      this.closeActiveSubdialog?.();
    }
    this.invalidateExtractRequests();
    this.root.hidden = true;
    document.removeEventListener("keydown", this.boundKeydown);
    this.previousFocus?.focus?.();
  }

  handleKeydown(event) {
    if (this.root.hidden) return;
    if (this.activeSubdialog) {
      if (event.key === "Escape") {
        event.preventDefault();
        this.closeActiveSubdialog?.();
        return;
      }
      if (event.key === "Tab") {
        const focusable = [...this.activeSubdialog.querySelectorAll("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")].filter((item) => !item.hidden);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
      return;
    }
    if (this.handlePaneTabKeydown(event)) return;
    if (event.key === "Escape") { event.preventDefault(); void this.close(); return; }
    if (this.handleCatalogKeydown(event)) return;
    if (event.key !== "Tab") return;
    const focusable = [...this.dialog.querySelectorAll("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")].filter((item) => !item.hidden);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  isCatalogNavigationTarget(target) {
    const card = target?.closest?.(".mpl2-entry-card");
    if (!card) return null;
    if (target === card) return card;
    const tagName = String(target?.tagName || "").toUpperCase();
    if (["INPUT", "TEXTAREA", "SELECT", "BUTTON", "A"].includes(tagName) || target?.isContentEditable) return null;
    return card;
  }

  handleCatalogKeydown(event) {
    const card = this.isCatalogNavigationTarget(event.target);
    if (!card) return false;
    const entryId = card.dataset.entryId || null;
    const visible = this.visibleEntries();
    const currentIndex = visible.findIndex((entry) => entry.id === (this.cursorEntryId || entryId));
    const navigationKeys = new Set(["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End"]);
    if (event.key === "Enter") {
      const entry = visible.find((candidate) => candidate.id === entryId);
      if (!entry) return false;
      event.preventDefault();
      this.cursorEntryId = entry.id;
      this.selectedId = entry.id;
      this.mode = "browse";
      this.pendingCatalogFocusId = entry.id;
      this.render();
      return true;
    }
    if (event.key === " ") {
      const entry = visible.find((candidate) => candidate.id === entryId);
      if (!entry) return false;
      event.preventDefault();
      this.cursorEntryId = entry.id;
      this.pendingCatalogFocusId = entry.id;
      this.toggleSelection(entry.id, !this.isSelected(entry.id));
      return true;
    }
    if (!navigationKeys.has(event.key)) return false;
    event.preventDefault();
    const nextIndex = navigateCatalogIndex(currentIndex < 0 ? 0 : currentIndex, event.key, visible.length, { pageSize: CATALOG_PAGE_SIZE, columns: 1 });
    if (nextIndex < 0) return true;
    const nextEntry = visible[nextIndex];
    this.cursorEntryId = nextEntry.id;
    this.catalogPage = Math.floor(nextIndex / CATALOG_PAGE_SIZE);
    this.pendingCatalogFocusId = nextEntry.id;
    this.render();
    return true;
  }

  renderLoading() {
    // Keep the body/rail/main/list/detail structure mounted.  Clearing the
    // body itself detaches the containers that the normal render pass owns.
    if (!this.body.contains(this.rail)) this.body.appendChild(this.rail);
    if (!this.body.contains(this.main)) this.body.appendChild(this.main);
    if (!this.main.contains(this.listPane)) this.main.appendChild(this.listPane);
    if (!this.main.contains(this.detailPane)) this.main.appendChild(this.detailPane);
    clear(this.rail);
    clear(this.listPane);
    clear(this.detailPane);
    this.listPane.appendChild(element("p", { className: "mpl2-loading", textContent: "Loading the local archive…" }));
  }

  async refreshLibrary() {
    try {
      const payload = await requestJSON(`${API_BASE}/library`);
      const normalized = normalizeLibraryPayload(payload);
      this.library = normalized.library;
      this.fingerprint = normalized.fingerprint;
      if (!this.selection) this.selection = normalizeSelectionState(null, this.library.categories);
      else this.selection = normalizeSelectionState(this.selection, this.library.categories);
      this.order = normalizeComponentOrder(this.order, this.library.categories, { includeUnknown: true });
      updateNodeSummaries(this.library);
      return this.library;
    } catch (error) {
      this.setError(error);
      return null;
    }
  }

  async refreshLoras() {
    try {
      const payload = await requestJSON(`${API_BASE}/loras`);
      this.availableLoras = [...new Set((Array.isArray(payload?.loras) ? payload.loras : [])
        .map((name) => text(name).trim()).filter(Boolean))].sort((left, right) => left.localeCompare(right));
      this.lorasLoaded = true;
      return this.availableLoras;
    } catch {
      // Manual names remain usable when ComfyUI cannot enumerate its LoRA folder.
      this.availableLoras = [];
      this.lorasLoaded = false;
      return [];
    }
  }

  setError(error) {
    this.errorMessage = trimError(error);
    if (this.error) { this.error.hidden = false; this.error.textContent = this.errorMessage; }
  }

  clearError() {
    this.errorMessage = "";
    if (this.error) { this.error.hidden = true; this.error.textContent = ""; }
  }

  setStatus(message) {
    this.statusMessage = text(message);
  }

  setBusy(value) {
    this.busy = Boolean(value);
    this.applyButton.disabled = this.busy;
    this.dialog.setAttribute("aria-busy", String(this.busy));
  }

  categories() {
    return this.library?.categories || [];
  }

  activeCategoryObject() {
    return this.categories().find((category) => category.id === this.activeCategory) || this.categories()[0] || null;
  }

  activeEntries() {
    return this.activeCategoryObject()?.entries || [];
  }

  selectedIds(categoryId = this.activeCategory) {
    return this.selection?.selections?.[categoryId] || [];
  }

  isSelected(id, categoryId = this.activeCategory) {
    return this.selectedIds(categoryId).includes(id);
  }

  findEntry(categoryId = this.activeCategory, id = this.selectedId) {
    return this.categories().find((category) => category.id === categoryId)?.entries.find((entry) => entry.id === id) || null;
  }

  visibleEntries() {
    return filterEntriesV2(this.activeEntries(), { query: this.query, folderId: this.folderId, tag: this.tag, favoritesOnly: this.favoritesOnly });
  }

  resetCatalogPage() {
    this.catalogPage = 0;
    this.cursorEntryId = null;
    this.pendingCatalogFocusId = null;
  }

  focusCatalogEntry(entryId) {
    if (!entryId) return;
    const card = [...this.listPane.querySelectorAll(".mpl2-entry-card")].find((candidate) => candidate.dataset.entryId === entryId);
    card?.focus?.();
  }

  goToCatalogPage(page) {
    const pagination = paginateEntries(this.visibleEntries(), page, CATALOG_PAGE_SIZE);
    const entry = pagination.items[0] || null;
    this.catalogPage = pagination.page;
    this.cursorEntryId = entry?.id || null;
    this.pendingCatalogFocusId = entry?.id || null;
    this.render();
  }

  render() {
    this.captureRenderFocus();
    if (!this.library) { this.renderLoading(); this.restoreRenderFocus(); return; }
    if (!this.categories().some((category) => category.id === this.activeCategory)) {
      this.activeCategory = this.categories()[0]?.id || "style";
      this.resetCatalogPage();
    }
    const stale = staleSelectionIds(this.selection, this.categories());
    this.context.textContent = this.activeNode
      ? `Node draft · ${stale.missingCategoryIds.length + stale.missingEntryIds.length ? `${stale.missingCategoryIds.length + stale.missingEntryIds.length} stale ID(s)` : "selection ready"}`
      : "Local library";
    this.error.hidden = !this.errorMessage;
    this.error.textContent = this.errorMessage;
    this.searchInput.value = this.query;
    this.favoriteInput.checked = this.favoritesOnly;
    this.renderPaneTabs();
    this.renderRail();
    this.renderFilters();
    if (this.mode === "import") this.renderImportPane();
    else if (this.mode === "extract_image") this.renderExtractImagePane();
    else { this.renderCatalog(); this.renderDetail(); }
    this.renderFooter(stale);
    this.restoreRenderFocus();
  }

  renderRail() {
    clear(this.rail);
    this.rail.appendChild(element("div", { className: "mpl2-rail-heading" }, [
      element("span", { textContent: "Components" }),
      this.actionButton("＋ Category", "", () => this.createCategory()),
    ]));
    for (const [index, category] of this.categories().entries()) {
      const item = element("div", { className: `mpl2-rail-item${category.id === this.activeCategory ? " is-active" : ""}`, draggable: true, dataset: { categoryId: category.id } });
      item.addEventListener("dragstart", (event) => { event.dataTransfer.setData("text/mpl2-category", category.id); });
      item.addEventListener("dragover", (event) => event.preventDefault());
      item.addEventListener("drop", (event) => { event.preventDefault(); const from = this.categories().findIndex((candidate) => candidate.id === event.dataTransfer.getData("text/mpl2-category")); this.reorderCategories(from, index); });
      const browse = this.setFocusKey(element("button", { className: "mpl2-category", type: "button", "aria-current": category.id === this.activeCategory ? "page" : "false" }, [
        element("span", { className: "mpl2-drag-handle", textContent: "⋮⋮", "aria-hidden": "true" }),
        element("span", { className: "mpl2-category-name", textContent: categoryLabel(category) }),
        element("span", { className: "mpl2-category-count", textContent: String(category.entries.length) }),
      ]), `category:${category.id}`);
      browse.addEventListener("click", () => this.selectCategory(category.id));
      const menu = this.setFocusKey(element("button", { className: "mpl2-icon-button", type: "button", title: `Manage ${categoryLabel(category)}`, "aria-label": `Manage ${categoryLabel(category)}`, textContent: "⋯" }), `category-menu:${category.id}`);
      menu.addEventListener("click", (event) => { event.stopPropagation(); this.categoryMenu(category); });
      const moveUp = this.setFocusKey(element("button", { className: "mpl2-icon-button", type: "button", title: `Move ${categoryLabel(category)} up`, "aria-label": `Move ${categoryLabel(category)} up`, textContent: "↑", disabled: index === 0 }), `category-up:${category.id}`);
      moveUp.addEventListener("click", (event) => { event.stopPropagation(); this.reorderCategories(index, index - 1); });
      const moveDown = this.setFocusKey(element("button", { className: "mpl2-icon-button", type: "button", title: `Move ${categoryLabel(category)} down`, "aria-label": `Move ${categoryLabel(category)} down`, textContent: "↓", disabled: index === this.categories().length - 1 }), `category-down:${category.id}`);
      moveDown.addEventListener("click", (event) => { event.stopPropagation(); this.reorderCategories(index, index + 1); });
      item.append(browse, moveUp, moveDown, menu);
      this.rail.appendChild(item);
    }
  }

  renderFilters() {
    const category = this.activeCategoryObject();
    clear(this.folderSelect);
    this.folderSelect.appendChild(element("option", { value: "", textContent: "All folders" }));
    for (const folder of folderOptions(category)) this.folderSelect.appendChild(element("option", { value: folder.id, textContent: folder.name }));
    this.folderSelect.value = this.folderId;
    clear(this.tagSelect);
    this.tagSelect.appendChild(element("option", { value: "", textContent: "All tags" }));
    for (const tag of availableTags(this.activeEntries())) this.tagSelect.appendChild(element("option", { value: tag, textContent: `#${tag}` }));
    this.tagSelect.value = this.tag;
  }

  renderCatalog() {
    const visible = this.visibleEntries();
    let pagination = paginateEntries(visible, this.catalogPage, CATALOG_PAGE_SIZE);
    const cursorIndex = visible.findIndex((entry) => entry.id === this.cursorEntryId);
    if (cursorIndex >= 0 && (cursorIndex < pagination.start || cursorIndex >= pagination.end)) {
      this.catalogPage = Math.floor(cursorIndex / CATALOG_PAGE_SIZE);
      pagination = paginateEntries(visible, this.catalogPage, CATALOG_PAGE_SIZE);
    }
    this.catalogPage = pagination.page;
    if (!pagination.items.some((entry) => entry.id === this.cursorEntryId)) this.cursorEntryId = pagination.items[0]?.id || null;
    clear(this.listPane);
    const heading = element("div", { className: "mpl2-list-heading" }, [
      element("strong", { textContent: `${categoryLabel(this.activeCategoryObject())} catalog` }),
      element("span", { textContent: `${pagination.total} / ${this.activeEntries().length}` }),
      this.actionButton("＋ Add entry", "primary", () => this.startAdd()),
    ]);
    const previous = this.setFocusKey(this.actionButton("Previous", "", () => this.goToCatalogPage(pagination.page - 1)), "catalog-page:previous");
    previous.disabled = pagination.page <= 0;
    const next = this.setFocusKey(this.actionButton("Next", "", () => this.goToCatalogPage(pagination.page + 1)), "catalog-page:next");
    next.disabled = pagination.page >= pagination.pageCount - 1;
    const status = element("span", {
      className: "mpl2-page-status",
      "aria-live": "polite",
      textContent: `Page ${pagination.page + 1} of ${pagination.pageCount} · ${pagination.total} match${pagination.total === 1 ? "" : "es"}`,
    });
    const pager = element("div", { className: "mpl2-pager", "aria-label": "Catalog pages" }, [previous, status, next]);
    const list = element("div", { className: "mpl2-entry-list", role: "list" });
    if (!pagination.total) {
      list.appendChild(element("p", { className: "mpl2-empty", textContent: this.query || this.folderId || this.tag || this.favoritesOnly ? "Nothing matches these filters." : "This category is empty." }));
      list.appendChild(this.actionButton("＋ Add entry", "primary", () => this.startAdd()));
    }
    for (const entry of pagination.items) list.appendChild(this.entryCard(entry));
    this.listPane.append(heading, pager, list);
    const focusId = this.pendingCatalogFocusId;
    this.pendingCatalogFocusId = null;
    if (focusId) {
      // Explicit catalog navigation has a more useful target than restoring
      // the button that caused the page render.
      this.focusRestore = null;
      queueMicrotask(() => this.focusCatalogEntry(focusId));
    }
  }

  imageUrl(entry, image) {
    if (!entry?.id || !image?.id) return "";
    return `${API_BASE}/entries/${encodeURIComponent(entry.id)}/images/${encodeURIComponent(image.id)}?cache=${this.imageRevision}`;
  }

  primaryImage(entry) {
    return entry?.images?.find((image) => image.id === entry.primary_image_id && image.kind === "preview") || entry?.images?.find((image) => image.kind === "preview") || null;
  }

  imageOrPlaceholder(entry, image, className = "mpl2-thumbnail") {
    if (image) return element("img", { className, src: this.imageUrl(entry, image), alt: image.caption || `Preview of ${entry.name}`, loading: "lazy" });
    return element("span", { className: `${className} mpl2-placeholder`, role: "img", "aria-label": `No preview for ${entry.name}`, textContent: "✦" });
  }

  entryCard(entry) {
    const card = this.setFocusKey(element("article", {
      className: `mpl2-entry-card${entry.id === this.cursorEntryId ? " is-focused" : ""}`,
      tabindex: entry.id === this.cursorEntryId ? "0" : "-1",
      role: "listitem",
      "aria-current": entry.id === this.selectedId ? "true" : "false",
      dataset: { entryId: entry.id },
    }), `catalog-card:${entry.id}`);
    const check = this.setFocusKey(element("input", { type: "checkbox", checked: this.isSelected(entry.id), "aria-label": `Select ${entry.name}` }), `catalog-checkbox:${entry.id}`);
    check.addEventListener("click", (event) => event.stopPropagation());
    check.addEventListener("change", () => { this.cursorEntryId = entry.id; this.toggleSelection(entry.id, check.checked); });
    const favorite = this.setFocusKey(element("button", { className: `mpl2-favorite${entry.favorite ? " is-favorite" : ""}`, type: "button", title: entry.favorite ? "Favorite" : "Add favorite", "aria-label": entry.favorite ? `Remove ${entry.name} from favorites` : `Add ${entry.name} to favorites`, textContent: entry.favorite ? "★" : "☆" }), `catalog-favorite:${entry.id}`);
    favorite.addEventListener("click", (event) => { event.stopPropagation(); this.updateEntryFavorite(entry, !entry.favorite); });
    const visual = this.imageOrPlaceholder(entry, this.primaryImage(entry));
    const copy = element("div", { className: "mpl2-entry-copy" }, [
      element("strong", { className: "mpl2-entry-name", textContent: entry.name }),
      element("span", { className: "mpl2-entry-snippet", textContent: entry.prompt }),
      element("span", { className: "mpl2-entry-tags", textContent: entry.tags.length ? entry.tags.map((tag) => `#${tag}`).join(" ") : "" }),
    ]);
    card.append(check, visual, copy, favorite);
    card.addEventListener("click", () => { this.selectedId = entry.id; this.cursorEntryId = entry.id; this.mode = "browse"; this.pendingCatalogFocusId = entry.id; this.render(); });
    return card;
  }

  renderDetail() {
    clear(this.detailPane);
    const entry = this.findEntry();
    this.renderSelectedTray();
    const detail = element("div", { className: "mpl2-entry-detail" });
    if (this.mode === "edit") this.renderEditor(detail);
    else if (entry) this.renderEntryDetail(detail, entry);
    else detail.append(element("p", { className: "mpl2-empty", textContent: "Choose an entry to inspect it, or use the checkboxes to build a selection." }), this.actionButton("＋ Add entry", "primary", () => this.startAdd()));
    this.detailPane.appendChild(detail);
    if (this.statusMessage) this.detailPane.appendChild(element("p", { className: "mpl2-status", "aria-live": "polite", textContent: this.statusMessage }));
  }

  renderSelectedTray() {
    const tray = element("section", { className: "mpl2-tray", "aria-label": "Selected components" });
    tray.appendChild(element("div", { className: "mpl2-section-heading" }, [element("strong", { textContent: "Selected order" }), element("span", { textContent: "Drag groups and entries" })]));
    const groups = element("div", { className: "mpl2-tray-groups" });
    const order = this.order.length ? this.order : normalizeComponentOrder([], this.categories());
    for (const token of order) {
      if (token === PROMPT_TOKEN) {
        groups.appendChild(this.trayGroup(PROMPT_TOKEN, "Prompt", [], true));
        continue;
      }
      const category = this.categories().find((candidate) => candidate.id === token);
      if (!category) continue;
      const entries = this.selectedIds(category.id).map((id) => category.entries.find((entry) => entry.id === id) || { id, name: `Missing ${id}`, missing: true });
      groups.appendChild(this.trayGroup(category.id, categoryLabel(category), entries, false));
    }
    tray.appendChild(groups);

    const nodePrompt = widget(this.activeNode, "prompt")?.value || "";
    const assembledText = buildAssembledPrompt(this.selection, this.order, this.categories(), nodePrompt);
    if (assembledText) {
      const previewWrap = element("div", { className: "mpl2-assembled-preview" });
      const toggle = element("button", {
        className: "mpl2-assembled-toggle",
        type: "button",
        "aria-expanded": String(this.showPromptPreview || false),
        textContent: this.showPromptPreview ? "▾ Hide Assembled Prompt Preview" : "▸ Show Assembled Prompt Preview",
      });
      toggle.addEventListener("click", () => {
        this.showPromptPreview = !this.showPromptPreview;
        this.render();
      });
      previewWrap.appendChild(toggle);
      if (this.showPromptPreview) {
        previewWrap.appendChild(element("pre", { className: "mpl2-assembled-box", textContent: assembledText }));
      }
      tray.appendChild(previewWrap);
    }

    this.detailPane.appendChild(tray);
  }

  trayGroup(token, label, entries, isPrompt) {
    const group = element("div", { className: `mpl2-tray-group${isPrompt ? " is-prompt" : ""}`, draggable: "true", dataset: { token } });
    group.addEventListener("dragstart", (event) => { event.dataTransfer.setData("text/mpl2-tray-group", token); });
    group.addEventListener("dragover", (event) => event.preventDefault());
    group.addEventListener("drop", (event) => { event.preventDefault(); const fromToken = event.dataTransfer.getData("text/mpl2-tray-group"); const from = this.order.indexOf(fromToken); const to = this.order.indexOf(token); if (from >= 0 && to >= 0) { this.order = reorderIds(this.order, from, to); this.render(); } });
    const groupIndex = this.order.indexOf(token);
    const heading = element("div", { className: "mpl2-tray-group-heading" }, [element("span", { className: "mpl2-drag-handle", textContent: "⋮⋮", "aria-hidden": "true" }), element("strong", { textContent: label }), element("span", { className: "mpl2-tray-count", textContent: isPrompt ? "freeform" : String(entries.length) })]);
    const groupUp = this.setFocusKey(element("button", { className: "mpl2-order-button", type: "button", title: `Move ${label} earlier`, "aria-label": `Move ${label} earlier`, textContent: "↑", disabled: groupIndex <= 0 }), `order-group-up:${token}`);
    groupUp.addEventListener("click", (event) => { event.stopPropagation(); this.moveGroup(token, -1); });
    const groupDown = this.setFocusKey(element("button", { className: "mpl2-order-button", type: "button", title: `Move ${label} later`, "aria-label": `Move ${label} later`, textContent: "↓", disabled: groupIndex < 0 || groupIndex >= this.order.length - 1 }), `order-group-down:${token}`);
    groupDown.addEventListener("click", (event) => { event.stopPropagation(); this.moveGroup(token, 1); });
    heading.append(groupUp, groupDown);
    group.appendChild(heading);
    if (!isPrompt) {
      const list = element("div", { className: "mpl2-tray-entries" });
      for (const entry of entries) {
        const chip = element("span", { className: `mpl2-tray-entry${entry.missing ? " is-missing" : ""}`, draggable: "true", dataset: { categoryId: token, entryId: entry.id } }, [document.createTextNode(entry.name)]);
        chip.addEventListener("dragstart", (event) => { event.stopPropagation(); event.dataTransfer.setData("text/mpl2-tray-entry", JSON.stringify({ categoryId: token, entryId: entry.id })); });
        chip.addEventListener("dragover", (event) => event.preventDefault());
        chip.addEventListener("drop", (event) => { event.preventDefault(); const data = JSON.parse(event.dataTransfer.getData("text/mpl2-tray-entry") || "{}"); if (data.categoryId !== token) return; const ids = this.selectedIds(token); const from = ids.indexOf(data.entryId); const to = ids.indexOf(entry.id); if (from >= 0 && to >= 0) { this.selection.selections[token] = reorderIds(ids, from, to); this.render(); } });
        const entryIndex = this.selectedIds(token).indexOf(entry.id);
        const entryUp = this.setFocusKey(element("button", { className: "mpl2-order-button", type: "button", title: `Move ${entry.name} earlier`, "aria-label": `Move ${entry.name} earlier`, textContent: "↑", disabled: entryIndex <= 0 }), `order-entry-up:${token}:${entry.id}`);
        entryUp.addEventListener("click", (event) => { event.stopPropagation(); this.moveEntry(token, entry.id, -1); });
        const entryDown = this.setFocusKey(element("button", { className: "mpl2-order-button", type: "button", title: `Move ${entry.name} later`, "aria-label": `Move ${entry.name} later`, textContent: "↓", disabled: entryIndex < 0 || entryIndex >= this.selectedIds(token).length - 1 }), `order-entry-down:${token}:${entry.id}`);
        entryDown.addEventListener("click", (event) => { event.stopPropagation(); this.moveEntry(token, entry.id, 1); });
        const remove = this.setFocusKey(element("button", { className: "mpl2-chip-remove", type: "button", "aria-label": `Remove ${entry.name}`, textContent: "×" }), `order-entry-remove:${token}:${entry.id}`);
        chip.append(entryUp, entryDown);
        remove.addEventListener("click", (event) => { event.stopPropagation(); this.selection.selections[token] = this.selectedIds(token).filter((id) => id !== entry.id); this.render(); });
        chip.appendChild(remove);
        list.appendChild(chip);
      }
      if (!entries.length) list.appendChild(element("span", { className: "mpl2-tray-empty", textContent: "No selections" }));
      group.appendChild(list);
    } else group.appendChild(element("p", { className: "mpl2-tray-note", textContent: "The node's freeform prompt stays visible on canvas." }));
    return group;
  }

  renderEntryDetail(container, entry) {
    const heading = element("div", { className: "mpl2-detail-heading" }, [
      element("div", {}, [element("h3", { className: "mpl2-detail-title", textContent: entry.name }), element("p", { className: "mpl2-detail-meta", textContent: `${categoryLabel(this.activeCategoryObject())}${entry.folder_id ? " · filed" : " · unfiled"}` })]),
      this.setFocusKey(this.actionButton(entry.favorite ? "★ Favorite" : "☆ Favorite", entry.favorite ? "primary" : "", () => this.updateEntryFavorite(entry, !entry.favorite)), `detail-favorite:${entry.id}`),
    ]);
    const prompt = element("p", { className: "mpl2-prompt", textContent: entry.prompt });
    const tags = element("div", { className: "mpl2-tag-row" }, entry.tags.map((tag) => element("span", { className: "mpl2-tag", textContent: `#${tag}` })));
    const loras = element("div", { className: "mpl2-lora-summary", "aria-label": "Attached LoRAs" }, (entry.loras || []).map((lora) => element("span", {
      className: "mpl2-lora-chip",
      textContent: `${lora.name} · M ${lora.strength_model} / C ${lora.strength_clip}`,
      title: `${lora.name} · model ${lora.strength_model} · CLIP ${lora.strength_clip}`,
    })));
    const actions = element("div", { className: "mpl2-detail-actions" }, [
      this.setFocusKey(this.actionButton(this.isSelected(entry.id) ? "Selected" : "Select", this.isSelected(entry.id) ? "primary" : "", () => this.toggleSelection(entry.id, !this.isSelected(entry.id))), `detail-select:${entry.id}`),
      this.setFocusKey(this.actionButton("Edit", "", () => this.startEdit(entry)), `detail-edit:${entry.id}`),
      this.setFocusKey(this.actionButton("Duplicate", "", () => this.startDuplicate(entry)), `detail-duplicate:${entry.id}`),
      this.setFocusKey(this.actionButton("Delete", "danger", () => this.deleteEntry(entry)), `detail-delete:${entry.id}`),
    ]);
    container.append(heading, tags, loras, prompt, actions, this.renderGallery(entry));
  }

  renderGallery(entry) {
    const section = element("section", { className: "mpl2-gallery", "aria-label": "Entry image gallery" });
    const tabs = element("div", { className: "mpl2-gallery-tabs", role: "tablist" });
    const safeEntryId = String(entry.id || "entry").replace(/[^A-Za-z0-9_-]/g, "-");
    for (const kind of ["preview", "generated"]) {
      const tabId = `mpl2-gallery-tab-${safeEntryId}-${kind}`;
      const panelId = `mpl2-gallery-panel-${safeEntryId}-${kind}`;
      const tab = this.setFocusKey(element("button", {
        className: `mpl2-tab${this.galleryKind === kind ? " is-active" : ""}`,
        type: "button",
        role: "tab",
        id: tabId,
        "aria-controls": panelId,
        "aria-selected": String(this.galleryKind === kind),
        tabindex: this.galleryKind === kind ? "0" : "-1",
        textContent: kind === "preview" ? "Previews" : "Generated",
      }), `gallery-tab:${kind}`);
      tab.addEventListener("click", () => { this.galleryKind = kind; this.render(); });
      tab.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const kinds = ["preview", "generated"];
        const next = nextTabIndex(kinds.indexOf(kind), event.key, kinds.length);
        this.galleryKind = kinds[next];
        this.render();
        queueMicrotask(() => this.focusByKey(`gallery-tab:${this.galleryKind}`));
      });
      tabs.appendChild(tab);
    }
    section.append(tabs);
    for (const kind of ["preview", "generated"]) {
      section.append(this.renderGalleryPanel(entry, kind, safeEntryId));
    }
    return section;
  }

  renderGalleryPanel(entry, kind, safeEntryId = String(entry.id || "entry").replace(/[^A-Za-z0-9_-]/g, "-")) {
    const panelId = `mpl2-gallery-panel-${safeEntryId}-${kind}`;
    const tabId = `mpl2-gallery-tab-${safeEntryId}-${kind}`;
    const panel = element("div", {
      className: "mpl2-gallery-panel",
      id: panelId,
      role: "tabpanel",
      "aria-labelledby": tabId,
      tabindex: "0",
      hidden: this.galleryKind !== kind,
    });
    const fileInput = element("input", { className: "mpl2-hidden-file", type: "file", multiple: true, accept: "image/jpeg,image/png,image/webp", "aria-label": `Attach ${kind} images` });
    const fileLabel = element("label", { className: "mpl2-button" }, [fileInput, document.createTextNode(`＋ Add ${kind === "preview" ? "previews" : "generated images"}`)]);
    fileInput.addEventListener("change", (event) => this.uploadImages(entry, event.target.files, kind));
    const state = galleryState(entry, kind);
    const grid = element("div", { className: "mpl2-gallery-grid" });
    if (!state.images.length) grid.appendChild(element("p", { className: "mpl2-gallery-empty", textContent: `No ${kind} images attached.` }));
    for (const [index, image] of state.images.entries()) grid.appendChild(this.galleryCard(entry, image, index, state.images, kind));
    const statuses = [...this.galleryStatuses.entries()].filter(([key]) => key.startsWith(`${kind}:`));
    const statusList = element("div", { className: "mpl2-upload-statuses", "aria-live": "polite" }, statuses.map(([, status]) => element("p", { className: `mpl2-image-status ${status.kind === "error" ? "is-error" : ""}`, textContent: status.message })));
    panel.append(element("div", { className: "mpl2-gallery-actions" }, [fileLabel, element("span", { className: "mpl2-image-note", textContent: "JPEG, PNG, or WebP · 8 MiB each · up to 20 total" })]), statusList, grid);
    return panel;
  }

  galleryCard(entry, image, index, images, kind = this.galleryKind) {
    const card = element("article", { className: "mpl2-gallery-card", draggable: true });
    card.addEventListener("dragstart", (event) => { event.dataTransfer.setData("text/mpl2-gallery-index", String(index)); });
    card.addEventListener("dragover", (event) => event.preventDefault());
    card.addEventListener("drop", (event) => { event.preventDefault(); const from = Number(event.dataTransfer.getData("text/mpl2-gallery-index")); if (Number.isInteger(from)) this.reorderImages(entry, images, from, index, kind); });
    card.appendChild(element("img", { className: "mpl2-gallery-image", src: this.imageUrl(entry, image), alt: image.caption || `${image.kind} image ${index + 1}` }));
    const captionWrap = element("div", { style: "display: flex; align-items: center; gap: 4px;" });
    const caption = element("input", { className: "mpl2-input", type: "text", maxlength: "240", value: image.caption || "", placeholder: "Caption", "aria-label": `Caption for image ${index + 1}` });
    const savedTick = element("span", { className: "mpl2-caption-saved", textContent: "" });
    caption.addEventListener("change", async () => {
      await this.saveImageMetadata(entry, { [image.id]: { caption: caption.value } });
      savedTick.textContent = "Saved ✓";
      setTimeout(() => { savedTick.textContent = ""; }, 2500);
    });
    captionWrap.append(caption, savedTick);
    const controls = element("div", { className: "mpl2-gallery-card-actions" }, [
      this.setFocusKey(this.actionButton("↑", "", () => this.reorderImages(entry, images, index, Math.max(0, index - 1), kind)), `gallery-up:${kind}:${image.id}`),
      this.setFocusKey(this.actionButton("↓", "", () => this.reorderImages(entry, images, index, Math.min(images.length - 1, index + 1), kind)), `gallery-down:${kind}:${image.id}`),
      this.setFocusKey(this.actionButton("Delete", "danger", () => void this.deleteImage(entry, image)), `gallery-delete:${kind}:${image.id}`),
    ]);
    if (image.kind === "preview") controls.insertBefore(this.setFocusKey(this.actionButton(entry.primary_image_id === image.id ? "Primary" : "Set primary", entry.primary_image_id === image.id ? "primary" : "", () => this.setPrimary(entry, image)), `gallery-primary:${image.id}`), controls.firstChild);
    const status = this.galleryStatuses.get(image.id);
    card.append(captionWrap, controls);
    if (status) card.appendChild(element("p", { className: `mpl2-image-status ${status.kind === "error" ? "is-error" : ""}`, textContent: status.message }));
    return card;
  }

  renderLoraEditor(draft) {
    if (!Array.isArray(draft.loras)) draft.loras = [];
    const section = element("fieldset", { className: "mpl2-lora-editor" });
    section.appendChild(element("legend", { textContent: "LoRAs activated by this concept" }));
    const datalistId = "mpl2-installed-loras";
    const datalist = element("datalist", { id: datalistId }, this.availableLoras.map((name) => element("option", { value: name })));
    section.appendChild(datalist);
    const rows = element("div", { className: "mpl2-lora-rows" });
    for (const [index, lora] of draft.loras.entries()) {
      const name = element("input", {
        className: "mpl2-input",
        type: "text",
        list: datalistId,
        value: lora.name || "",
        maxlength: "512",
        placeholder: "LoRA filename or subfolder/path.safetensors",
        "aria-label": `LoRA ${index + 1} filename`,
      });
      const modelStrength = element("input", { className: "mpl2-input", type: "number", min: "-100", max: "100", step: "0.05", value: lora.strength_model ?? 1, "aria-label": `LoRA ${index + 1} model strength` });
      const clipStrength = element("input", { className: "mpl2-input", type: "number", min: "-100", max: "100", step: "0.05", value: lora.strength_clip ?? 1, "aria-label": `LoRA ${index + 1} CLIP strength` });
      name.addEventListener("input", () => { lora.name = name.value; });
      modelStrength.addEventListener("input", () => { lora.strength_model = modelStrength.value; });
      clipStrength.addEventListener("input", () => { lora.strength_clip = clipStrength.value; });
      const remove = this.actionButton("Remove", "danger", () => { draft.loras.splice(index, 1); this.render(); });
      rows.appendChild(element("div", { className: "mpl2-lora-row" }, [
        element("label", { className: "mpl2-lora-name" }, [element("span", { textContent: "LoRA" }), name]),
        element("label", {}, [element("span", { textContent: "Model" }), modelStrength]),
        element("label", {}, [element("span", { textContent: "CLIP" }), clipStrength]),
        remove,
      ]));
    }
    if (!draft.loras.length) rows.appendChild(element("p", { className: "mpl2-tray-note", textContent: "No LoRA attached. This concept only contributes prompt text." }));
    const add = this.actionButton("＋ Attach LoRA", "", () => {
      if (draft.loras.length >= 16) return;
      draft.loras.push({ name: "", strength_model: 1, strength_clip: 1 });
      this.render();
    });
    add.disabled = draft.loras.length >= 16;
    section.append(rows, element("div", { className: "mpl2-lora-footer" }, [
      add,
      element("span", { className: "mpl2-tray-note", textContent: this.lorasLoaded ? `${this.availableLoras.length} installed LoRA${this.availableLoras.length === 1 ? "" : "s"} available.` : "Installed LoRAs could not be listed; a manual relative name still works." }),
    ]));
    return section;
  }

  renderEditor(container) {
    const draft = this.editorDraft || { name: "", prompt: "", tags: "", loras: [], folder_id: "", favorite: false };
    const category = this.activeCategoryObject();
    const form = element("div", { className: "mpl2-editor" });
    const name = element("input", { className: "mpl2-input", type: "text", maxlength: "120", value: draft.name, "aria-label": "Entry name" });
    const prompt = element("textarea", { className: "mpl2-textarea", maxlength: "20000", "aria-label": "Entry prompt", placeholder: "Prompt text this component contributes…" });
    prompt.value = draft.prompt;
    const tags = element("input", { className: "mpl2-input", type: "text", value: draft.tags, placeholder: "ink, portrait, cinematic", "aria-label": "Entry tags" });
    const folder = element("select", { className: "mpl2-select", "aria-label": "Entry folder" });
    folder.appendChild(element("option", { value: "", textContent: "Unfiled" }));
    for (const option of folderOptions(category)) folder.appendChild(element("option", { value: option.id, textContent: option.name }));
    folder.value = draft.folder_id || "";
    const newFolder = this.actionButton("＋ New folder", "", () => this.createFolder(category));
    const favorite = element("input", { type: "checkbox", checked: draft.favorite, "aria-label": "Favorite entry" });
    name.addEventListener("input", () => { draft.name = name.value; });
    prompt.addEventListener("input", () => { draft.prompt = prompt.value; });
    tags.addEventListener("input", () => { draft.tags = tags.value; });
    folder.addEventListener("change", () => { draft.folder_id = folder.value; });
    favorite.addEventListener("change", () => { draft.favorite = favorite.checked; });
    form.append(element("label", { className: "mpl2-field-label", textContent: "Name" }), name, element("label", { className: "mpl2-field-label", textContent: "Prompt text" }), prompt, element("label", { className: "mpl2-field-label", textContent: "Tags · comma separated" }), tags, this.renderLoraEditor(draft), element("label", { className: "mpl2-field-label", textContent: "Folder" }), element("div", { className: "mpl2-inline-field" }, [folder, newFolder]), element("label", { className: "mpl2-check-label" }, [favorite, document.createTextNode(" Favorite")]), element("div", { className: "mpl2-editor-actions" }, [this.actionButton("Save entry", "primary", () => this.saveEditor()), this.actionButton("Cancel", "", () => this.cancelEditor())]));
    container.append(element("div", { className: "mpl2-detail-heading" }, [element("h3", { className: "mpl2-detail-title", textContent: this.editorOriginal ? "Edit entry" : "New entry" })]), form);
    queueMicrotask(() => name.focus());
  }

  renderFooter(stale) {
    const count = Object.values(this.selection?.selections || {}).reduce((total, ids) => total + ids.length, 0);
    const staleCount = stale.missingCategoryIds.length + stale.missingEntryIds.length;
    this.footer.querySelector(".mpl2-footer-note").textContent = `${count} selected${staleCount ? ` · ${staleCount} stale ID(s) will be reported` : ""}${this.statusMessage ? ` · ${this.statusMessage}` : ""}`;
  }

  async selectCategory(categoryId) {
    if (this.hasEditorChanges()) {
      const confirmed = await this.confirmDialog({
        title: "Discard Changes?",
        message: "Discard unsaved entry changes?",
        confirmLabel: "Discard Changes",
        variant: "danger",
      });
      if (!confirmed) return;
    }
    this.activeCategory = categoryId;
    this.selectedId = null;
    this.mode = "browse";
    this.editorDraft = null;
    this.editorOriginal = null;
    this.folderId = "";
    this.tag = "";
    this.resetCatalogPage();
    this.render();
  }

  moveGroup(categoryId, offset) {
    const index = this.order.indexOf(categoryId);
    if (index < 0) return;
    this.order = moveByOffset(this.order, index, offset);
    this.render();
  }

  moveEntry(categoryId, entryId, offset) {
    const ids = this.selectedIds(categoryId);
    const index = ids.indexOf(entryId);
    if (index < 0) return;
    this.selection.selections[categoryId] = moveByOffset(ids, index, offset);
    this.render();
  }

  toggleSelection(id, selected) {
    const ids = this.selectedIds(this.activeCategory).slice();
    if (selected && !ids.includes(id)) ids.push(id);
    if (!selected) {
      const index = ids.indexOf(id);
      if (index >= 0) ids.splice(index, 1);
    }
    this.selection.selections[this.activeCategory] = ids;
    this.render();
  }

  hasEditorChanges() {
    if (!this.editorDraft) return false;
    return JSON.stringify(this.editorDraft) !== JSON.stringify(this.editorOriginal || {});
  }

  startEdit(entry) {
    this.editorOriginal = { id: entry.id, name: entry.name, prompt: entry.prompt, tags: entry.tags.join(", "), loras: (entry.loras || []).map((lora) => ({ ...lora })), folder_id: entry.folder_id || "", favorite: entry.favorite };
    this.editorDraft = { ...this.editorOriginal, loras: this.editorOriginal.loras.map((lora) => ({ ...lora })) };
    this.mode = "edit";
    this.clearError();
    this.render();
  }

  startDuplicate(entry) {
    const names = new Set(this.activeEntries().map((candidate) => candidate.name.toLocaleLowerCase()));
    let name = `Copy of ${entry.name}`;
    let suffix = 2;
    while (names.has(name.toLocaleLowerCase())) name = `Copy of ${entry.name} (${suffix++})`;
    this.editorOriginal = null;
    this.editorDraft = { name, prompt: entry.prompt, tags: entry.tags.join(", "), loras: (entry.loras || []).map((lora) => ({ ...lora })), folder_id: entry.folder_id || "", favorite: false };
    this.mode = "edit";
    this.render();
  }

  startAdd() {
    this.editorOriginal = null;
    this.editorDraft = { name: "", prompt: "", tags: "", loras: [], folder_id: "", favorite: false };
    this.mode = "edit";
    this.render();
  }

  async cancelEditor() {
    if (this.hasEditorChanges()) {
      const confirmed = await this.confirmDialog({
        title: "Discard Changes?",
        message: "Discard unsaved entry changes?",
        confirmLabel: "Discard Changes",
        variant: "danger",
      });
      if (!confirmed) return;
    }
    this.editorOriginal = null;
    this.editorDraft = null;
    this.mode = "browse";
    this.render();
  }

  async saveEditor() {
    if (this.busy) return;
    const draft = this.editorDraft || {};
    const name = text(draft.name).trim();
    const prompt = text(draft.prompt).trim();
    if (!name || !prompt) { this.setError("Name and prompt text are required."); return; }
    if (name.length > 120 || prompt.length > 20000) { this.setError("Name must be 120 characters or fewer and prompt text 20,000 characters or fewer."); return; }
    const tags = normalizeTags(text(draft.tags).split(",").map((tag) => tag.slice(0, MAX_TAG_LENGTH)));
    const loras = (Array.isArray(draft.loras) ? draft.loras : []).map((lora) => ({
      name: text(lora?.name).trim(),
      strength_model: Number(lora?.strength_model),
      strength_clip: Number(lora?.strength_clip),
    }));
    if (loras.some((lora) => !lora.name)) { this.setError("Each attached LoRA needs a filename."); return; }
    if (new Set(loras.map((lora) => lora.name.toLocaleLowerCase())).size !== loras.length) { this.setError("A concept cannot attach the same LoRA more than once."); return; }
    if (loras.some((lora) => !Number.isFinite(lora.strength_model) || !Number.isFinite(lora.strength_clip) || Math.abs(lora.strength_model) > 100 || Math.abs(lora.strength_clip) > 100)) { this.setError("LoRA strengths must be numbers from -100 to 100."); return; }
    this.setBusy(true);
    try {
      const body = { category: this.activeCategory, name, prompt, tags, loras, favorite: draft.favorite === true, folder_id: draft.folder_id || null };
      const payload = draft.id ? await requestJSON(`${API_BASE}/entries/${encodeURIComponent(draft.id)}`, requestOptions("PUT", body)) : await requestJSON(`${API_BASE}/entries`, requestOptions("POST", body));
      const saved = entryFromPayload(payload);
      await this.refreshLibrary();
      this.selectedId = saved?.id || this.library.categories.find((category) => category.id === this.activeCategory)?.entries.find((entry) => entry.name === name)?.id || null;
      this.editorDraft = null;
      this.editorOriginal = null;
      this.mode = "browse";
      this.setStatus("Entry saved.");
    } catch (error) { this.setError(error); }
    finally { this.setBusy(false); this.render(); }
  }

  async updateEntryFavorite(entry, favorite) {
    if (this.busy) return;
    this.setBusy(true);
    try { await requestJSON(`${API_BASE}/entries/${encodeURIComponent(entry.id)}`, requestOptions("PUT", { favorite })); await this.refreshLibrary(); this.setStatus(favorite ? "Added to favorites." : "Removed from favorites."); }
    catch (error) { this.setError(error); }
    finally { this.setBusy(false); this.render(); }
  }

  async deleteEntry(entry) {
    if (this.busy) return;
    const confirmed = await this.confirmDialog({
      title: "Delete Entry",
      message: `Permanently delete "${entry.name}" and its attached images?`,
      confirmLabel: "Delete Entry",
      variant: "danger",
    });
    if (!confirmed) return;
    const visibleBeforeDelete = this.visibleEntries();
    const deletedIndex = visibleBeforeDelete.findIndex((candidate) => candidate.id === entry.id);
    this.pendingCatalogFocusId = visibleBeforeDelete[deletedIndex + 1]?.id
      || visibleBeforeDelete[deletedIndex - 1]?.id
      || null;
    this.setBusy(true);
    try {
      await requestJSON(`${API_BASE}/entries/${encodeURIComponent(entry.id)}`, { method: "DELETE" });
      this.selection.selections[this.activeCategory] = this.selectedIds().filter((id) => id !== entry.id);
      this.selectedId = null;
      await this.refreshLibrary();
      this.setStatus("Entry deleted.");
    } catch (error) { this.setError(error); }
    finally { this.setBusy(false); this.render(); }
  }

  async createCategory() {
    if (this.busy) return;
    const name = text(await this.promptDialog({
      title: "New Category",
      message: "Enter name for the new component category:",
      placeholder: "e.g. Composition, Lighting…",
      confirmLabel: "Create Category",
    })).trim();
    if (!name || this.busy) return;
    this.setBusy(true);
    try {
      const payload = await requestJSON(`${API_BASE}/categories`, requestOptions("POST", { name }));
      const created = payload?.category || payload;
      await this.refreshLibrary();
      this.activeCategory = created?.id || this.categories().at(-1)?.id || this.activeCategory;
      this.resetCatalogPage();
      this.setStatus("Category created.");
    } catch (error) { this.setError(error); }
    finally { this.setBusy(false); this.render(); }
  }

  async renameCategory(category) {
    if (this.busy) return;
    const name = text(await this.promptDialog({
      title: "Rename Category",
      message: `Rename category "${categoryLabel(category)}":`,
      defaultValue: category.name,
      confirmLabel: "Rename",
    })).trim();
    if (!name || name === category.name || this.busy) return;
    this.setBusy(true);
    try {
      await requestJSON(`${API_BASE}/categories/${encodeURIComponent(category.id)}`, requestOptions("PUT", { name }));
      await this.refreshLibrary();
      this.setStatus("Category renamed.");
    } catch (error) { this.setError(error); }
    finally { this.setBusy(false); this.render(); }
  }

  async reorderCategories(from, to) {
    if (from < 0 || to < 0 || from === to || this.busy) return;
    const ids = reorderIds(this.categories().map((category) => category.id), from, to);
    this.setBusy(true);
    try {
      await requestJSON(`${API_BASE}/categories/order`, requestOptions("PUT", { order: ids, category_ids: ids }));
      await this.refreshLibrary();
      this.order = normalizeComponentOrder(this.order, this.categories(), { includeUnknown: true });
      this.setStatus("Category order saved.");
    } catch (error) { this.setError(error); }
    finally { this.setBusy(false); this.render(); }
  }

  async deleteCategory(category) {
    if (category.protected) {
      this.setError("Core categories are protected and cannot be deleted.");
      return;
    }
    if (this.busy) return;
    const otherCategories = this.categories().filter((candidate) => candidate.id !== category.id);
    const body = {};

    if (category.entries.length) {
      const choices = [
        { label: `Permanently delete category and all ${category.entries.length} entries`, value: "delete_all", variant: "danger" },
      ];
      if (otherCategories.length > 0) {
        choices.unshift({ label: `Move ${category.entries.length} entries to another category…`, value: "move", variant: "primary" });
      }
      const action = await this.choiceDialog({
        title: `Delete Category "${category.name}"`,
        message: `Category "${category.name}" contains ${category.entries.length} entries. What would you like to do?`,
        choices,
      });
      if (!action) return;

      if (action === "delete_all") {
        const doubleConfirm = await this.confirmDialog({
          title: "Confirm Deletion",
          message: `Permanently delete all ${category.entries.length} entries and images in "${category.name}"? This cannot be undone.`,
          confirmLabel: "Permanently Delete",
          variant: "danger",
        });
        if (!doubleConfirm) return;
        body.delete_entries = true;
      } else if (action === "move") {
        const target = await this.chooseCategoryDialog(otherCategories, "Move entries to which category?", "Move & Delete Category");
        if (!target) return;
        body.move_to_category_id = target.id;
      }
    } else {
      const confirmed = await this.confirmDialog({
        title: "Delete Category",
        message: `Delete empty category "${category.name}"?`,
        confirmLabel: "Delete Category",
        variant: "danger",
      });
      if (!confirmed) return;
    }

    this.setBusy(true);
    try {
      await requestJSON(`${API_BASE}/categories/${encodeURIComponent(category.id)}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      delete this.selection.selections[category.id];
      this.order = this.order.filter((id) => id !== category.id);
      await this.refreshLibrary();
      this.activeCategory = this.categories()[0]?.id || "style";
      this.resetCatalogPage();
      this.setStatus("Category deleted.");
    } catch (error) { this.setError(error); }
    finally { this.setBusy(false); this.render(); }
  }

  async categoryMenu(category) {
    const choices = [
      { label: `Rename "${categoryLabel(category)}"`, value: "rename" },
      { label: `Manage Folders in "${categoryLabel(category)}"…`, value: "folder" },
    ];
    if (!category.protected) {
      choices.push({ label: `Delete "${categoryLabel(category)}"`, value: "delete", variant: "danger" });
    }
    const choice = await this.choiceDialog({
      title: `Category: ${categoryLabel(category)}`,
      choices,
    });
    if (choice === "rename") await this.renameCategory(category);
    else if (choice === "folder") await this.folderMenu(category);
    else if (choice === "delete") await this.deleteCategory(category);
  }

  async folderMenu(category) {
    const folders = folderOptions(category);
    const choices = [
      { label: "＋ New Folder", value: "create", variant: "primary" },
    ];
    if (folders.length > 0) {
      choices.push({ label: "Rename Folder…", value: "rename" });
      choices.push({ label: "Delete Folder…", value: "delete", variant: "danger" });
    }
    const choice = await this.choiceDialog({
      title: `Folders in ${categoryLabel(category)}`,
      choices,
    });
    if (choice === "create") await this.createFolder(category);
    else if (choice === "rename") {
      const folder = await this.chooseFolderDialog(category, "Rename which folder?");
      if (folder) await this.renameFolder(category, folder);
    } else if (choice === "delete") {
      const folder = await this.chooseFolderDialog(category, "Delete which folder? (Entries become unfiled)");
      if (folder) await this.deleteFolder(category, folder);
    }
  }

  async createFolder(category) {
    if (this.busy) return;
    const name = text(await this.promptDialog({
      title: `New Folder in ${categoryLabel(category)}`,
      message: "Enter folder name:",
      placeholder: "e.g. Anime, Realistic, Minimalist…",
      confirmLabel: "Create Folder",
    })).trim();
    if (!name || this.busy) return;
    this.setBusy(true);
    try {
      await requestJSON(`${API_BASE}/categories/${encodeURIComponent(category.id)}/folders`, requestOptions("POST", { name }));
      await this.refreshLibrary();
      this.setStatus("Folder created.");
    } catch (error) { this.setError(error); }
    finally { this.setBusy(false); this.render(); }
  }

  async renameFolder(category, folder) {
    if (this.busy) return;
    const name = text(await this.promptDialog({
      title: "Rename Folder",
      message: `Enter new name for folder "${folder.name}":`,
      defaultValue: folder.name,
      confirmLabel: "Save",
    })).trim();
    if (!name || name === folder.name || this.busy) return;
    this.setBusy(true);
    try {
      await requestJSON(`${API_BASE}/categories/${encodeURIComponent(category.id)}/folders/${encodeURIComponent(folder.id)}`, requestOptions("PUT", { name }));
      await this.refreshLibrary();
      this.setStatus("Folder renamed.");
    } catch (error) { this.setError(error); }
    finally { this.setBusy(false); this.render(); }
  }

  async deleteFolder(category, folder) {
    if (this.busy) return;
    const confirmed = await this.confirmDialog({
      title: "Delete Folder",
      message: `Delete folder "${folder.name}"? Existing entries will become unfiled.`,
      confirmLabel: "Delete Folder",
      variant: "danger",
    });
    if (!confirmed || this.busy) return;
    this.setBusy(true);
    try {
      await requestJSON(`${API_BASE}/categories/${encodeURIComponent(category.id)}/folders/${encodeURIComponent(folder.id)}`, { method: "DELETE" });
      await this.refreshLibrary();
      this.setStatus("Folder deleted; entries remain unfiled.");
    } catch (error) { this.setError(error); }
    finally { this.setBusy(false); this.render(); }
  }

  async saveImageMetadata(entry, updates = {}, orderedImages = null, primaryImageId = entry.primary_image_id || null) {
    if (this.galleryBusy) return;
    const source = orderedImages || entry.images;
    const images = source.map((image) => ({ ...image, ...(updates[image.id] || {}) }));
    this.galleryBusy = true;
    try { await requestJSON(`${API_BASE}/entries/${encodeURIComponent(entry.id)}/images`, requestOptions("PUT", { images, primary_image_id: primaryImageId })); await this.refreshLibrary(); this.imageRevision += 1; }
    catch (error) { this.setError(error); }
    finally { this.galleryBusy = false; this.render(); }
  }

  async reorderImages(entry, visibleImages, from, to, kind = this.galleryKind) {
    if (from === to || from < 0 || to < 0 || from >= visibleImages.length || to >= visibleImages.length) return;
    const visibleIds = reorderIds(visibleImages.map((image) => image.id), from, to);
    const positions = new Map(visibleIds.map((id, index) => [id, index]));
    const byId = new Map(entry.images.map((image) => [image.id, image]));
    let nextVisible = 0;
    const reordered = entry.images.map((image) => image.kind === kind ? byId.get(visibleIds[nextVisible++]) : image);
    await this.saveImageMetadata(entry, {}, reordered);
  }

  async setPrimary(entry, image) {
    const primary = setGalleryPrimary(entry, image.id);
    if (!primary) { this.setError("Only preview images can be primary."); return; }
    try { await requestJSON(`${API_BASE}/entries/${encodeURIComponent(entry.id)}/images`, requestOptions("PUT", { images: entry.images, primary_image_id: primary })); await this.refreshLibrary(); this.imageRevision += 1; this.setStatus("Primary preview updated."); }
    catch (error) { this.setError(error); }
    finally { this.render(); }
  }

  async deleteImage(entry, image) {
    if (this.galleryBusy) return;
    const confirmed = await this.confirmDialog({
      title: "Delete Image",
      message: `Delete this ${image.kind} image?`,
      confirmLabel: "Delete Image",
      variant: "danger",
    });
    if (!confirmed) return;
    this.galleryBusy = true;
    try { await requestJSON(`${API_BASE}/entries/${encodeURIComponent(entry.id)}/images/${encodeURIComponent(image.id)}`, { method: "DELETE" }); await this.refreshLibrary(); this.imageRevision += 1; this.setStatus("Image deleted."); }
    catch (error) { this.setError(error); }
    finally { this.galleryBusy = false; this.render(); }
  }

  async uploadImages(entry, fileList, kind) {
    const files = [...(fileList || [])];
    if (!files.length || this.galleryBusy) return;
    this.galleryBusy = true;
    for (const file of files) {
      const statusKey = `${kind}:${file.name}`;
      this.galleryStatuses.set(statusKey, { kind: "busy", message: `${file.name}: uploading…` });
      this.render();
      try {
        const form = new FormData(); form.append("kind", kind); form.append("file", file, file.name);
        await requestJSON(`${API_BASE}/entries/${encodeURIComponent(entry.id)}/images`, { method: "POST", body: form });
        this.galleryStatuses.set(statusKey, { kind: "ok", message: `${file.name}: uploaded` });
      } catch (error) { this.galleryStatuses.set(statusKey, { kind: "error", message: `${file.name}: ${trimError(error)}` }); }
      await this.refreshLibrary();
    }
    this.galleryBusy = false;
    this.imageRevision += 1;
    this.setStatus("Upload batch finished; individual failures remain visible.");
    this.render();
  }

  async loadImportSources() {
    try { const payload = await requestJSON(`${API_BASE}/imports/sources`); this.importState.sources = payload?.sources || (Array.isArray(payload) ? payload : []); this.render(); }
    catch (error) { this.setError(error); }
  }

  renderImportPane() {
    clear(this.listPane); clear(this.detailPane);
    this.listPane.appendChild(element("div", { className: "mpl2-list-heading" }, [element("strong", { textContent: "Import source" }), element("span", { textContent: "Preview first" })]));
    const sourceSelect = element("select", { className: "mpl2-select", "aria-label": "Installed import source" });
    sourceSelect.append(element("option", { value: "", textContent: "Choose an installed source…" }));
    for (const source of this.importState.sources) sourceSelect.appendChild(element("option", { value: source.id || source.path || source.name, textContent: source.name || source.path || source.id }));
    sourceSelect.value = this.importState.sourceId;
    sourceSelect.addEventListener("change", () => { this.importState = selectImportSource(this.importState, sourceSelect.value); this.render(); });
    const files = element("input", { className: "mpl2-hidden-file", type: "file", multiple: true, accept: ".txt,.json,.csv, text/plain, application/json, text/csv", "aria-label": "Choose prompt files" });
    files.addEventListener("change", () => { this.importState = selectImportFiles(this.importState, mergeImportFiles(this.importState.files, files.files)); this.render(); });
    const fileLabel = element("label", { className: "mpl2-button" }, [files, document.createTextNode("Choose files")]);
    const directory = element("input", { className: "mpl2-hidden-file", type: "file", multiple: true, accept: ".txt,.json,.csv, text/plain, application/json, text/csv", webkitdirectory: true, "aria-label": "Choose an import directory" });
    directory.addEventListener("change", () => { this.importState = selectImportFiles(this.importState, mergeImportFiles(this.importState.files, directory.files)); this.render(); });
    const directoryLabel = element("label", { className: "mpl2-button" }, [directory, document.createTextNode("Choose directory")]);
    const clearFiles = this.actionButton("Clear files", "", () => { this.importState.files = []; this.render(); });
    const previewButton = this.actionButton("Preview import", "primary", () => this.previewImport());
    const backButton = this.actionButton("Back to archive", "", () => { this.mode = "browse"; this.render(); });
    this.listPane.appendChild(element("div", { className: "mpl2-import-form" }, [element("p", { className: "mpl2-import-note", textContent: "Nothing is written until Apply import. Installed sources are read-only discovery results." }), sourceSelect, element("div", { className: "mpl2-editor-actions" }, [fileLabel, directoryLabel, clearFiles]), element("p", { className: "mpl2-import-note", textContent: `${this.importState.files.length} local file(s) selected; file and directory choices are merged.` }), element("div", { className: "mpl2-editor-actions" }, [previewButton, backButton])]));
    const preview = this.importState.preview;
    if (!preview) { this.detailPane.appendChild(element("p", { className: "mpl2-empty", textContent: "Choose a local file, directory, or installed source, then preview it." })); return; }
    const summary = importPreviewSummary(preview);
    const groups = preview.groups || preview.inferred_groups || [];
    const mapping = element("div", { className: "mpl2-import-mapping" });
    for (const group of groups) {
      const sourceId = text(group.id || group.name);
      const select = element("select", { className: "mpl2-select", "aria-label": `Map ${sourceId}` });
      for (const category of this.categories()) select.appendChild(element("option", { value: category.id, textContent: categoryLabel(category) }));
      select.value = this.importState.mapping[sourceId] || this.categories()[0]?.id || "";
      select.addEventListener("change", () => { this.importState.mapping[sourceId] = select.value; });
      mapping.appendChild(element("label", { className: "mpl2-import-map-row" }, [element("span", { textContent: sourceId || "Uncategorized" }), select]));
    }
    const policy = element("select", { className: "mpl2-select", "aria-label": "Import conflict policy" }, [element("option", { value: "skip", textContent: "Skip conflicts (default)" }), element("option", { value: "rename", textContent: "Rename imported" }), element("option", { value: "replace", textContent: "Replace matching name" })]);
    policy.value = this.importState.policy; policy.addEventListener("change", () => { this.importState.policy = policy.value; });
    const warningList = element("ul", { className: "mpl2-import-warnings" }, summary.warnings.map((warning) => element("li", { textContent: warning })));
    const apply = this.actionButton("Apply import", "primary", () => this.applyImport());
    this.detailPane.append(element("div", { className: "mpl2-detail-heading" }, [element("h3", { className: "mpl2-detail-title", textContent: "Import preview" })]), element("p", { className: "mpl2-import-summary", textContent: `${summary.records} record(s) · ${summary.groups} group(s) · ${summary.conflicts} conflict(s) · ${summary.omittedNegative} negative prompt field(s) omitted` }), mapping, element("label", { className: "mpl2-field-label", textContent: "Conflict policy" }), policy, warningList, apply);
  }

  async previewImport() {
    if (this.busy || (!this.importState.files.length && !this.importState.sourceId)) { this.setError("Choose a local file/directory or an installed source first."); return; }
    this.setBusy(true);
    try {
      const form = new FormData();
      if (this.importState.sourceId) form.append("source_id", this.importState.sourceId);
      for (const file of this.importState.files) form.append("files", file, file.webkitRelativePath || file.name);
      const payload = await requestJSON(`${API_BASE}/imports/preview`, { method: "POST", body: form });
      this.importState.preview = payload?.preview || payload;
      const groups = this.importState.preview?.groups || this.importState.preview?.inferred_groups || [];
      this.importState.mapping = normalizeImportMapping(this.importState.mapping, groups);
      this.setStatus("Preview loaded; no library changes made.");
    } catch (error) { this.setError(error); }
    finally { this.setBusy(false); this.render(); }
  }

  async applyImport() {
    const preview = this.importState.preview;
    if (!preview || this.busy) return;
    if (this.importState.policy === "replace") {
      const confirmed = await this.confirmDialog({
        title: "Confirm Replacement",
        message: "Replace matching entry names in the library with items from this import?",
        confirmLabel: "Replace Matching",
        variant: "danger",
      });
      if (!confirmed) return;
    }
    this.setBusy(true);
    try {
      const body = { preview_id: preview.id || preview.preview_id || null, records: preview.records || undefined, mapping: this.importState.mapping, conflict_policy: this.importState.policy };
      const result = await requestJSON(`${API_BASE}/imports/apply`, requestOptions("POST", body));
      const stats = result?.stats && typeof result.stats === "object" ? result.stats : (result || {});
      await this.refreshLibrary();
      this.importState.preview = null;
      this.setStatus(`Import applied · ${Number(stats.imported) || 0} imported · ${Number(stats.skipped) || 0} skipped · ${Number(stats.renamed) || 0} renamed · ${Number(stats.replaced) || 0} replaced · ${Number(stats.omitted_negative ?? stats.omittedNegative) || 0} negative prompts omitted.`);
      this.mode = "browse";
    } catch (error) { this.setError(error); }
    finally { this.setBusy(false); this.render(); }
  }

  initExtractImageState() {
    if (this.extractState?.previewUrl) URL.revokeObjectURL(this.extractState.previewUrl);
    this.extractState = {
      file: null,
      previewUrl: "",
      prompt: "",
      suggestedName: "",
      targetCategory: this.activeCategory || this.categories()[0]?.id || "style",
      folderId: "",
      tags: "",
      source: "",
      sections: {},
      structured: null,
      selectedExtractedField: "positive_prompt",
      selectedExtractionFields: ["positive_prompt"],
      extractedFieldDrafts: { positive_prompt: "" },
      busy: false,
      provider: this.extractState?.provider || "ollama",
      apiEndpoint: this.extractState?.apiEndpoint || "http://127.0.0.1:11434/v1",
      apiKey: this.extractState?.apiKey || "",
      apiModel: this.extractState?.apiModel || "llava",
      rememberApiKey: this.extractState?.rememberApiKey !== false,
      visionModels: normalizeVisionModels(this.extractState?.visionModels, this.extractState?.apiModel),
      visionModelsLoading: false,
      visionModelsError: "",
      customModel: Boolean(this.extractState?.customModel),
    };
  }

  persistVisionConnection() {
    return saveVisionConnection(this.extractState);
  }

  setVisionProvider(providerId) {
    const next = connectionForProvider(providerId, this.extractState);
    Object.assign(this.extractState, next, {
      visionModels: normalizeVisionModels([], next.apiModel),
      visionModelsError: "",
      customModel: false,
    });
    this.persistVisionConnection();
    this.render();
    void this.refreshVisionModels({ silent: true });
  }

  forgetVisionSettings() {
    forgetVisionConnection();
    const next = connectionForProvider("ollama", { rememberApiKey: true });
    Object.assign(this.extractState, next, {
      visionModels: normalizeVisionModels([], next.apiModel),
      visionModelsLoading: false,
      visionModelsError: "",
      customModel: false,
    });
    this.setStatus("Forgot the saved Vision API connection on this browser.");
    this.render();
  }

  async refreshVisionModels({ silent = false } = {}) {
    const state = this.extractState;
    const endpoint = text(state?.apiEndpoint).trim();
    const apiKey = text(state?.apiKey).trim();
    if (!endpoint || state?.visionModelsLoading) return;
    state.visionModelsLoading = true;
    state.visionModelsError = "";
    this.render();
    try {
      const response = await requestJSON(`${API_BASE}/vision/models`, requestOptions("POST", {
        api_endpoint: endpoint,
        api_key: apiKey,
      }));
      if (this.extractState !== state || text(state.apiEndpoint).trim() !== endpoint || text(state.apiKey).trim() !== apiKey) return;
      const models = normalizeVisionModels(response?.models, state.apiModel);
      state.visionModels = models;
      if (!state.apiModel && models.length) state.apiModel = models[0];
      state.customModel = false;
      this.persistVisionConnection();
      this.setStatus(models.length ? `Loaded ${models.length} model${models.length === 1 ? "" : "s"} from the Vision API.` : "The Vision API returned no models; use Custom model.");
    } catch (error) {
      if (this.extractState !== state) return;
      state.visionModelsError = trimError(error);
      if (!silent) this.setError(error);
    } finally {
      if (this.extractState === state) {
        state.visionModelsLoading = false;
        this.render();
      }
    }
  }

  invalidateExtractRequests() {
    const previous = this.extractState;
    if (!previous || typeof previous !== "object") return;
    if (previous.previewUrl) URL.revokeObjectURL(previous.previewUrl);
    this.extractState = {
      ...previous,
      file: null,
      previewUrl: "",
      prompt: "",
      suggestedName: "",
      source: "",
      sections: {},
      structured: null,
      selectedExtractedField: "positive_prompt",
      selectedExtractionFields: ["positive_prompt"],
      extractedFieldDrafts: { positive_prompt: "" },
      busy: false,
    };
  }

  async processExtractFile(file) {
    const state = this.extractState;
    if (!file || state.busy) return;
    const requestToken = extractionRequestToken(state);
    this.clearError();
    state.file = file;
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    state.previewUrl = URL.createObjectURL(file);
    state.busy = true;
    state.prompt = "";
    state.source = "";
    state.sections = {};
    state.structured = null;
    state.selectedExtractedField = "positive_prompt";
    state.selectedExtractionFields = ["positive_prompt"];
    state.extractedFieldDrafts = { positive_prompt: "" };
    this.render();

    try {
      const form = new FormData();
      form.append("image", file, file.name);
      const response = await requestJSON(`${API_BASE}/extract_image`, { method: "POST", body: form });
      if (!runIfCurrentExtractionRequest(this.extractState, requestToken, () => {
        Object.assign(state, applyExtractionResponse(state, response, { filename: file.name, categoryNames: this.categories().map(c => c.name), categories: this.categories() }));
        this.setStatus(state.prompt ? `Extracted positive prompt (${state.source}).` : "No prompt metadata found in this image.");
      })) return;
    } catch (error) {
      runIfCurrentExtractionRequest(this.extractState, requestToken, () => this.setError(error));
    } finally {
      runIfCurrentExtractionRequest(this.extractState, requestToken, () => {
        state.busy = false;
        this.render();
      });
    }
  }

  async runVisionExtraction() {
    const state = this.extractState;
    if (!state.file || state.busy) {
      this.setError("Choose an image file first.");
      return;
    }
    if (!state.apiEndpoint) {
      this.setError("Please enter a Vision API endpoint (e.g. http://localhost:11434/v1 or OpenAI URL).");
      return;
    }
    if (!state.apiModel) {
      this.setError("Choose a discovered model or enter a custom model ID.");
      return;
    }
    this.persistVisionConnection();
    const requestToken = extractionRequestToken(state);
    const file = state.file;
    this.clearError();
    state.busy = true;
    this.render();
    try {
      const form = new FormData();
      form.append("image", file, file.name);
      const fields = visionExtractionRequestFields(state);
      for (const [key, value] of Object.entries(fields)) {
        if (value || key === "force_vision") form.append(key, value);
      }
      const response = await requestJSON(`${API_BASE}/extract_image`, { method: "POST", body: form });
      if (!runIfCurrentExtractionRequest(this.extractState, requestToken, () => {
        Object.assign(state, applyExtractionResponse(state, response, { filename: file.name, categoryNames: this.categories().map(c => c.name), categories: this.categories(), requirePrompt: true }));
        this.setStatus(`Vision interrogation completed (${state.source}).`);
      })) return;
    } catch (error) {
      runIfCurrentExtractionRequest(this.extractState, requestToken, () => this.setError(error));
    } finally {
      runIfCurrentExtractionRequest(this.extractState, requestToken, () => {
        state.busy = false;
        this.render();
      });
    }
  }

  renderExtractImagePane() {
    clear(this.listPane);
    clear(this.detailPane);

    this.listPane.appendChild(element("div", { className: "mpl2-list-heading" }, [
      element("strong", { textContent: "Extract Image Prompt" }),
      element("span", { textContent: "Metadata & Vision" }),
    ]));

    const dropzone = element("label", { className: "mpl2-dropzone", for: "mpl2-extract-file", "aria-label": "Drop image here or click to browse" }, [
      element("span", { className: "mpl2-dropzone-icon", textContent: "📷", "aria-hidden": "true" }),
      element("span", { className: "mpl2-dropzone-text", textContent: "Drop PNG, WebP, or JPEG image here" }),
      element("span", { className: "mpl2-dropzone-hint", textContent: "or click to select file from disk" }),
    ]);

    const hiddenFile = element("input", {
      className: "mpl2-hidden-file",
      type: "file",
      id: "mpl2-extract-file",
      tabindex: "0",
      accept: "image/png,image/webp,image/jpeg,.png,.webp,.jpg,.jpeg",
      "aria-label": "Drop image here or click to browse",
    });
    hiddenFile.addEventListener("change", () => {
      if (hiddenFile.files?.length) this.processExtractFile(hiddenFile.files[0]);
    });

    dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("is-dragover"); });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("is-dragover"));
    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzone.classList.remove("is-dragover");
      if (e.dataTransfer?.files?.length) this.processExtractFile(e.dataTransfer.files[0]);
    });

    const provider = visionProvider(this.extractState.provider);
    const providerSelect = element("select", { id: "mpl2-vision-provider", className: "mpl2-select" },
      VISION_PROVIDERS.map((candidate) => element("option", { value: candidate.id, textContent: candidate.label })));
    providerSelect.value = provider.id;
    providerSelect.addEventListener("change", () => this.setVisionProvider(providerSelect.value));

    const keyInput = element("input", {
      id: "mpl2-vision-key",
      className: "mpl2-input",
      type: "password",
      autocomplete: "off",
      placeholder: provider.keyRequired ? "API key" : "Optional",
      value: this.extractState.apiKey || "",
      oninput: (event) => { this.extractState.apiKey = event.target.value; },
      onchange: () => { this.persistVisionConnection(); void this.refreshVisionModels({ silent: true }); },
    });

    const modelValues = normalizeVisionModels(this.extractState.visionModels, this.extractState.apiModel);
    const modelSelect = element("select", {
      id: "mpl2-vision-model",
      className: "mpl2-select",
      disabled: this.extractState.visionModelsLoading,
      "aria-describedby": "mpl2-vision-model-status",
    }, [
      ...modelValues.map((model) => element("option", { value: model, textContent: model })),
      element("option", { value: "__custom__", textContent: "Custom model…" }),
    ]);
    modelSelect.value = this.extractState.customModel || !modelValues.length ? "__custom__" : this.extractState.apiModel;
    modelSelect.addEventListener("change", () => {
      if (modelSelect.value === "__custom__") {
        this.extractState.customModel = true;
        this.render();
        return;
      }
      this.extractState.customModel = false;
      this.extractState.apiModel = modelSelect.value;
      this.persistVisionConnection();
    });
    const modelRefresh = this.actionButton(this.extractState.visionModelsLoading ? "Loading…" : "Refresh", "", () => this.refreshVisionModels());
    modelRefresh.disabled = this.extractState.visionModelsLoading || !this.extractState.apiEndpoint;
    const modelControls = element("div", { className: "mpl2-vision-model-controls" }, [modelSelect, modelRefresh]);

    const customModelInput = element("input", {
      className: "mpl2-input",
      placeholder: "Enter a custom model ID",
      value: this.extractState.apiModel || "",
      oninput: (event) => { this.extractState.apiModel = event.target.value; },
      onchange: () => this.persistVisionConnection(),
      "aria-label": "Custom Vision API model ID",
    });

    const endpointInput = element("input", {
      id: "mpl2-vision-endpoint",
      className: "mpl2-input",
      placeholder: "OpenAI-compatible base URL",
      value: this.extractState.apiEndpoint || "",
      oninput: (event) => { this.extractState.apiEndpoint = event.target.value; },
      onchange: () => { this.persistVisionConnection(); void this.refreshVisionModels({ silent: true }); },
    });

    const rememberKey = element("input", { type: "checkbox", checked: this.extractState.rememberApiKey !== false });
    rememberKey.addEventListener("change", () => {
      this.extractState.rememberApiKey = rememberKey.checked;
      this.persistVisionConnection();
    });

    const modelStatus = this.extractState.visionModelsLoading
      ? "Contacting the provider…"
      : this.extractState.visionModelsError
        ? `Model discovery unavailable: ${this.extractState.visionModelsError}`
        : modelValues.length
          ? `${modelValues.length} model${modelValues.length === 1 ? "" : "s"} available.`
          : "Choose Refresh, or use a custom model ID.";

    const visionActions = element("div", { className: "mpl2-vision-actions" }, [
      this.actionButton("Run Vision Interrogation", "primary", () => this.runVisionExtraction()),
      this.actionButton("Forget saved connection", "", () => this.forgetVisionSettings()),
    ]);

    const connectionDetails = element("details", { className: "mpl2-vision-advanced", open: provider.id === "custom" }, [
      element("summary", { textContent: "Connection details" }),
      element("div", { className: "mpl2-vision-advanced-fields" }, [
        element("label", { className: "mpl2-field-label", for: "mpl2-vision-endpoint", textContent: "API Endpoint" }),
        endpointInput,
        element("label", { className: "mpl2-vision-remember" }, [
          rememberKey,
          element("span", { textContent: "Remember API key in this browser profile" }),
        ]),
        element("p", { className: "mpl2-vision-storage-note", textContent: "The endpoint, model, and provider are saved locally. Uncheck this before leaving a shared browser." }),
      ]),
    ]);

    const visionDetails = element("details", { className: "mpl2-vision-config" }, [
      element("summary", { textContent: `Vision API · ${provider.label}` }),
      element("div", { className: "mpl2-vision-fields" }, [
        element("div", { className: "mpl2-vision-field" }, [
          element("label", { className: "mpl2-field-label", for: "mpl2-vision-provider", textContent: "Provider" }),
          providerSelect,
        ]),
        element("div", { className: "mpl2-vision-field" }, [
          element("label", { className: "mpl2-field-label", for: "mpl2-vision-key", textContent: provider.keyRequired ? "API Key" : "API Key (optional)" }),
          keyInput,
        ]),
        element("div", { className: "mpl2-vision-field mpl2-vision-model-field" }, [
          element("label", { className: "mpl2-field-label", for: "mpl2-vision-model", textContent: "Model" }),
          modelControls,
          (this.extractState.customModel || !modelValues.length) ? customModelInput : null,
          element("p", { id: "mpl2-vision-model-status", className: "mpl2-vision-model-status", textContent: modelStatus, role: "status", "aria-live": "polite" }),
        ]),
        connectionDetails,
        visionActions,
      ]),
    ]);

    const backButton = this.actionButton("Back to archive", "", () => {
      this.invalidateExtractRequests();
      this.mode = "browse";
      this.render();
    });

    const formWrap = element("div", { className: "mpl2-extract-form" }, [
      hiddenFile,
      dropzone,
      element("p", { className: "mpl2-import-note", textContent: "Reads embedded ComfyUI, A1111/Forge metadata, or queries vision models." }),
      visionDetails,
      element("div", { className: "mpl2-editor-actions" }, [backButton]),
    ]);
    this.listPane.appendChild(formWrap);

    if (this.extractState.busy) {
      this.detailPane.appendChild(element("p", { className: "mpl2-loading", textContent: "Extracting image prompt…" }));
      return;
    }

    const extractedFields = extractionFieldOptions(this.extractState);
    const activeField = extractedFields.find((field) => field.key === this.extractState.selectedExtractedField)
      || extractedFields[0]
      || { key: "positive_prompt", label: "Positive Prompt", value: selectedExtractionDraft(this.extractState) };
    if (extractedFields.length && activeField.key !== this.extractState.selectedExtractedField) {
      Object.assign(this.extractState, selectExtractionField(this.extractState, activeField.key));
    }

    if (!this.extractState.file && !activeField.value.trim()) {
      this.detailPane.appendChild(element("p", { className: "mpl2-empty", textContent: "Drop or select an image on the left to extract prompt metadata or run vision interrogation." }));
      return;
    }

    const detailHeader = element("div", { className: "mpl2-detail-heading" }, [
      element("h3", { className: "mpl2-detail-title", textContent: "Extracted Result" }),
    ]);

    const previewRow = element("div", { className: "mpl2-extract-preview" });
    if (this.extractState.previewUrl) {
      previewRow.appendChild(element("img", { className: "mpl2-extract-thumb", src: this.extractState.previewUrl, alt: "Extracted image thumbnail" }));
    }

    const badgeKind = this.extractState.source === "metadata" ? "metadata" : this.extractState.source === "vision" ? "vision" : "none";
    const badgeLabel = this.extractState.source === "metadata" ? "Metadata Found" : this.extractState.source === "vision" ? "Vision Interrogation" : "No Source Metadata";
    const badge = element("span", { className: `mpl2-badge mpl2-badge-${badgeKind}`, textContent: badgeLabel });

    const previewMeta = element("div", {}, [
      badge,
      element("p", { className: "mpl2-tray-note", textContent: this.extractState.file ? `${this.extractState.file.name} (${(this.extractState.file.size / 1024).toFixed(1)} KB)` : "" }),
    ]);
    const confidence = this.extractState.structured?.confidence;
    if (typeof confidence === "number" && Number.isFinite(confidence)) {
      previewMeta.appendChild(element("p", { className: "mpl2-tray-note", textContent: `Confidence: ${confidence}` }));
    }
    previewRow.appendChild(previewMeta);

    const extractedFieldControls = [];
    if (extractedFields.length > 1) {
      const fieldLabel = element("label", { className: "mpl2-field-label", textContent: "Field to Edit" });
      const extractedFieldSelect = this.setFocusKey(element("select", { className: "mpl2-select", "aria-label": "Field to edit" }), "extracted-field");
      for (const field of extractedFields) {
        extractedFieldSelect.appendChild(element("option", { value: field.key, textContent: field.label }));
      }
      extractedFieldSelect.value = activeField.key;
      extractedFieldSelect.addEventListener("change", () => {
        Object.assign(this.extractState, selectExtractionField(this.extractState, extractedFieldSelect.value));
        this.render();
      });
      extractedFieldControls.push(fieldLabel, extractedFieldSelect);
    }

    const selectedForSave = new Set(selectedExtractionFields(this.extractState));
    const selectionRows = [];
    for (const field of extractedFields) {
      const destination = extractionCategoryForField(field.key, this.categories(), this.extractState.targetCategory);
      const canSave = Boolean(field.value.trim() && destination);
      if (!canSave && selectedForSave.has(field.key)) {
        Object.assign(this.extractState, toggleExtractionFieldSelection(this.extractState, field.key, false));
        selectedForSave.delete(field.key);
      }
      const checkbox = element("input", {
        type: "checkbox",
        checked: selectedForSave.has(field.key),
        disabled: !canSave,
        "aria-label": `Add ${field.label} to library`,
      });
      checkbox.addEventListener("change", () => {
        Object.assign(this.extractState, toggleExtractionFieldSelection(this.extractState, field.key, checkbox.checked));
        this.renderExtractImagePane();
      });
      selectionRows.push(element("label", { className: `mpl2-extraction-choice${canSave ? "" : " is-unavailable"}` }, [
        checkbox,
        element("span", { className: "mpl2-extraction-choice-name", textContent: field.label }),
        element("span", {
          className: "mpl2-extraction-choice-target",
          textContent: destination ? `→ ${categoryLabel(destination)}` : "No matching category",
        }),
      ]));
    }
    const selectionFieldset = extractedFields.length > 1
      ? element("fieldset", { className: "mpl2-extraction-selection" }, [
        element("legend", { textContent: "Fields to Add" }),
        element("div", { className: "mpl2-extraction-choices" }, selectionRows),
        element("p", { className: "mpl2-extraction-selection-note", textContent: "Each checked field becomes its own library entry. Unmatched fields need a category with the same name." }),
      ])
      : null;

    const promptLabel = element("label", { className: "mpl2-field-label", textContent: `Extracted ${activeField.label}` });
    const promptTextarea = element("textarea", {
      className: "mpl2-textarea",
      rows: "6",
      "aria-label": "Extracted prompt text",
    });
    promptTextarea.value = selectedExtractionDraft(this.extractState);
    promptTextarea.addEventListener("input", () => {
      Object.assign(this.extractState, updateExtractionFieldDraft(this.extractState, promptTextarea.value));
      if (!this.extractState.structured) {
        this.extractState.sections = parsePromptSections(this.extractState.prompt, this.categories().map(c => c.name));
      }
    });

    const sectionKeys = Object.keys(this.extractState.sections || {});
    const sectionWrap = element("div");
    if (sectionKeys.length) {
      const tagList = element("div", { className: "mpl2-section-tags" });
      for (const k of sectionKeys) {
        const sectionText = String(this.extractState.sections[k] || "").trim();
        tagList.appendChild(element("span", {
          className: "mpl2-section-tag",
          textContent: `${k}: ${sectionText}`,
        }));
      }
      sectionWrap.append(element("label", { className: "mpl2-field-label", textContent: "Detected Sections" }), tagList);
    }

    const categoryLabelEl = element("label", { className: "mpl2-field-label", textContent: extractedFields.length > 1 ? "Positive Prompt Target Category" : "Target Category" });
    const categorySelect = element("select", { className: "mpl2-select", "aria-label": "Target library category" });
    for (const cat of this.categories()) {
      categorySelect.appendChild(element("option", { value: cat.id, textContent: categoryLabel(cat) }));
    }
    categorySelect.value = this.extractState.targetCategory || this.categories()[0]?.id || "style";
    categorySelect.addEventListener("change", () => {
      this.extractState.targetCategory = categorySelect.value;
      this.renderExtractImagePane();
    });

    const nameLabel = element("label", { className: "mpl2-field-label", textContent: extractedFields.length > 1 ? "Base Entry Name" : "Entry Name" });
    const nameInput = element("input", {
      className: "mpl2-input",
      value: this.extractState.suggestedName,
      placeholder: "Entry name…",
      "aria-label": "Entry name",
    });
    nameInput.addEventListener("input", () => {
      this.extractState.suggestedName = nameInput.value;
    });

    const targetCatObj = this.categories().find(c => c.id === this.extractState.targetCategory);
    const folders = folderOptions(targetCatObj);
    const folderSelect = element("select", { className: "mpl2-select", "aria-label": "Folder (optional)" });
    folderSelect.appendChild(element("option", { value: "", textContent: "No folder (unfiled)" }));
    for (const f of folders) {
      folderSelect.appendChild(element("option", { value: f.id, textContent: f.name }));
    }
    folderSelect.value = this.extractState.folderId || "";
    folderSelect.addEventListener("change", () => {
      this.extractState.folderId = folderSelect.value;
    });

    const tagsLabel = element("label", { className: "mpl2-field-label", textContent: "Tags (comma-separated)" });
    const tagsInput = element("input", {
      className: "mpl2-input",
      value: this.extractState.tags,
      placeholder: "e.g. sci-fi, detailed, lighting",
      "aria-label": "Entry tags",
    });
    tagsInput.addEventListener("input", () => {
      this.extractState.tags = tagsInput.value;
    });

    const savePlan = extractionSavePlan(this.extractState, this.categories());
    const addLabel = savePlan.entries.length > 1 ? `＋ Add ${savePlan.entries.length} Fields to Library` : "＋ Add to Library";
    const addToLibraryBtn = this.actionButton(addLabel, "primary", () => this.saveExtractedToLibrary());
    addToLibraryBtn.disabled = savePlan.entries.length === 0;
    const applyToNodeBtn = this.actionButton("Apply to Active Node", "", () => this.applyExtractedToNode());
    const copyBtn = this.actionButton("Copy Prompt", "", () => this.copyExtractedPrompt());

    const actions = element("div", { className: "mpl2-detail-actions" }, [
      addToLibraryBtn,
      applyToNodeBtn,
      copyBtn,
    ]);

    this.detailPane.append(
      detailHeader,
      previewRow,
      ...extractedFieldControls,
      selectionFieldset,
      promptLabel,
      promptTextarea,
      sectionWrap,
      categoryLabelEl,
      categorySelect,
      nameLabel,
      nameInput,
      element("label", { className: "mpl2-field-label", textContent: "Folder (optional)" }),
      folderSelect,
      tagsLabel,
      tagsInput,
      actions
    );
  }

  async saveExtractedToLibrary() {
    const plan = extractionSavePlan(this.extractState, this.categories());
    if (plan.unmatched.length) {
      this.setError(`No matching library category for: ${plan.unmatched.map((field) => field.label).join(", ")}.`);
      return;
    }
    if (plan.empty.length) {
      this.setError(`Selected fields cannot be empty: ${plan.empty.map((field) => field.label).join(", ")}.`);
      return;
    }
    if (!plan.entries.length) {
      this.setError("Choose at least one extracted field to add.");
      return;
    }

    const conflicts = plan.entries.filter((operation) => {
      const category = this.categories().find((candidate) => candidate.id === operation.category);
      const wanted = operation.name.trim().toLocaleLowerCase();
      return category?.entries.some((entry) => text(entry.name).trim().toLocaleLowerCase() === wanted);
    });
    if (conflicts.length) {
      this.setError(`Entry name already exists: ${conflicts.map((operation) => operation.name).join(", ")}.`);
      return;
    }
    if (this.busy) return;
    this.setBusy(true);
    const createdEntries = [];

    try {
      const tagList = normalizeTags(this.extractState.tags.split(","));
      for (const operation of plan.entries) {
        const payload = await requestJSON(`${API_BASE}/entries`, requestOptions("POST", {
          name: operation.name,
          prompt: operation.prompt,
          category: operation.category,
          folder_id: operation.folder_id,
          tags: tagList,
        }));
        const entry = payload?.entry || payload;
        createdEntries.push({ ...operation, entry });

        if (this.extractState.file && entry?.id) {
          try {
            const form = new FormData();
            form.append("kind", "preview");
            form.append("file", this.extractState.file, this.extractState.file.name);
            await requestJSON(`${API_BASE}/entries/${encodeURIComponent(entry.id)}/images`, { method: "POST", body: form });
          } catch {
            // Non-fatal image upload error
          }
        }
      }

      await this.refreshLibrary();
      this.activeCategory = createdEntries[0]?.category || this.activeCategory;
      this.selectedId = createdEntries[0]?.entry?.id || null;
      this.mode = "browse";
      this.setStatus(createdEntries.length === 1
        ? `Added “${createdEntries[0].name}” to ${categoryLabel(this.activeCategoryObject())}.`
        : `Added ${createdEntries.length} extracted fields to the library.`);
    } catch (error) {
      if (createdEntries.length) {
        await this.refreshLibrary();
        this.setError(`Added ${createdEntries.length} field${createdEntries.length === 1 ? "" : "s"}, then stopped: ${trimError(error)}`);
      } else {
        this.setError(error);
      }
    } finally {
      this.setBusy(false);
      this.render();
    }
  }

  applyExtractedToNode() {
    const promptText = selectedExtractionDraft(this.extractState).trim();
    if (!promptText) {
      this.setError("No extracted prompt to apply.");
      return;
    }
    if (!this.activeNode) {
      this.setError("No active node selected.");
      return;
    }
    const promptWidget = widget(this.activeNode, "prompt");
    if (promptWidget) {
      promptWidget.value = promptText;
      promptWidget.callback?.(promptText);
      this.activeNode.setDirtyCanvas?.(true, true);
      this.setStatus("Applied extracted prompt to active node.");
    } else {
      this.setError("Active node has no prompt input widget.");
    }
    this.render();
  }

  async copyExtractedPrompt() {
    const promptText = selectedExtractionDraft(this.extractState).trim();
    if (!promptText) return;
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(promptText);
        this.setStatus("Copied prompt to clipboard.");
      } else {
        this.setStatus("Clipboard not available in this environment.");
      }
    } catch {
      this.setStatus("Failed to copy to clipboard.");
    }
    this.render();
  }

  async exportLibrary() {
    if (this.busy) return;
    try {
      const payload = await requestJSON(`${API_BASE}/library`);
      const blob = new Blob([JSON.stringify(payload?.library || payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob); const link = element("a", { href: url, download: "prompt_library_v2.json" }); document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url); this.setStatus("Library exported."); this.render();
    } catch (error) { this.setError(error); }
  }

  async applyToNode() {
    if (!this.activeNode || this.busy) return;
    const selectionWidget = widget(this.activeNode, "selection_state");
    const orderWidget = widget(this.activeNode, "component_order");
    if (!selectionWidget || !orderWidget) { this.setError("The active node does not expose the v2 serialized selection widgets."); return; }
    const nextSelection = serializeSelectionState(this.selection, this.categories());
    const nextOrder = serializeComponentOrder(this.order, this.categories());
    const prior = { selection: selectionWidget.value, order: orderWidget.value };
    try {
      selectionWidget.value = nextSelection;
      orderWidget.value = nextOrder;
      selectionWidget.callback?.(nextSelection);
      orderWidget.callback?.(nextOrder);
      this.activeNode.setDirtyCanvas?.(true, true);
      updateNodeSummaries(this.library);
      this.setStatus("Applied to node.");
      this.close();
    } catch (error) {
      selectionWidget.value = prior.selection;
      orderWidget.value = prior.order;
      this.setError(error);
    }
  }
}

let modalInstance = null;

function getModal() {
  if (!modalInstance) modalInstance = new MasterPromptLibraryV2Modal();
  return modalInstance;
}

function addBrowseButton(node, knownV2 = false) {
  if (!knownV2 && !isV2Node(node)) return false;
  const attachedButton = node.__masterPromptLibraryV2Button;
  if (attachedButton && node.widgets?.includes(attachedButton)) return true;
  if (attachedButton) delete node.__masterPromptLibraryV2Button;
  const selectionWidget = widget(node, "selection_state");
  const orderWidget = widget(node, "component_order");
  if (!selectionWidget || !orderWidget || typeof node.addWidget !== "function") return false;
  hideSerializedWidget(selectionWidget);
  hideSerializedWidget(orderWidget);
  const button = node.addWidget?.("button", "Choose Components", null, () => getModal().open(node), { serialize: false });
  if (button) {
    button.serialize = false;
    button.serializeValue = () => null;
    button.label = "Choose Components";
    button.callback = () => getModal().open(node);
    node.__masterPromptLibraryV2Button = button;
  }
  const summaryWidget = node.addWidget?.("text", "selection_summary", "No components selected", () => {}, { serialize: false });
  if (summaryWidget) {
    summaryWidget.serialize = false;
    summaryWidget.disabled = true;
    summaryWidget.computeSize = () => [Math.max(160, Number(node.size?.[0]) || 160), 28];
    node.__mpl2SummaryWidget = summaryWidget;
  }
  installQuickPicker(node, {
    apiBase: API_BASE,
    fetchLibrary: () => requestJSON(`${API_BASE}/library`),
    onSelectionChange: (library) => updateNodeSummaries(library),
  });
  node.setDirtyCanvas?.(true, true);
  return Boolean(button);
}

function scheduleBrowseButton(node, knownV2 = false) {
  for (const delay of [0, 50, 250, 1000]) {
    setTimeout(() => {
      if (!node?.__masterPromptLibraryV2Button) addBrowseButton(node, knownV2);
    }, delay);
  }
}

function hookV2Node(nodeType, nodeData) {
  if (nodeType?.comfyClass !== "MasterPromptLibraryV2" && !isV2NodeData(nodeData)) return;
  const prototype = nodeType?.prototype;
  if (!prototype || prototype.__masterPromptLibraryV2CreationHook) return;
  const original = prototype.onNodeCreated;
  prototype.onNodeCreated = function masterPromptLibraryV2OnNodeCreated(...args) {
    const result = typeof original === "function" ? original.apply(this, args) : undefined;
    const defer = () => scheduleBrowseButton(this, true);
    if (result && typeof result.then === "function") return result.then((value) => { defer(); return value; });
    defer(); return result;
  };
  Object.defineProperty(prototype, "__masterPromptLibraryV2CreationHook", { configurable: false, enumerable: false, value: true, writable: false });
}

app.registerExtension({
  name: EXTENSION_NAME,
  init() { ensureStyles(); },
  afterConfigureGraph() { nodesInOpenGraph().forEach((node) => scheduleBrowseButton(node)); },
  beforeRegisterNodeDef(nodeType, nodeData) { hookV2Node(nodeType, nodeData); },
  nodeCreated(node) { scheduleBrowseButton(node); },
  loadedGraphNode(node) { scheduleBrowseButton(node); },
});
