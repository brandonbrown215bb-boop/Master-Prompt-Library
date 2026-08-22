import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import {
  API_BASE,
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  NONE_VALUE,
  filterEntries,
  hasDuplicateName,
  imageState,
  rebuildComboValues,
  validateImageFile,
} from "./library_logic.mjs";

const EXTENSION_NAME = "PromptLibrary.MasterPromptLibrary";
const MAX_ERROR_LENGTH = 500;

function element(tag, attributes = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "textContent") {
      node.textContent = String(value);
    } else if (key === "className") {
      node.className = String(value);
    } else if (key === "dataset" && value && typeof value === "object") {
      for (const [dataKey, dataValue] of Object.entries(value)) {
        node.dataset[dataKey] = String(dataValue);
      }
    } else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2), value);
    } else if (key in node && typeof value !== "object") {
      try {
        node[key] = value;
      } catch {
        node.setAttribute(key, String(value));
      }
    } else {
      node.setAttribute(key, String(value));
    }
  }
  for (const child of children) {
    if (child) node.appendChild(child);
  }
  return node;
}

function clearChildren(node) {
  while (node?.firstChild) node.removeChild(node.firstChild);
}

function trimError(error) {
  const message = error instanceof Error ? error.message : String(error || "Unexpected library error.");
  return message.trim().slice(0, MAX_ERROR_LENGTH) || "Unexpected library error.";
}

function categoryFromNode(node) {
  for (const category of CATEGORY_ORDER) {
    const widget = node?.widgets?.find((candidate) => candidate?.name === category);
    if (widget && widget.value && widget.value !== NONE_VALUE) return category;
  }
  return "style";
}

function isMasterPromptNodeData(nodeData) {
  return nodeData?.name === "MasterPromptLibrary"
    || nodeData?.display_name === "Master Prompt Library";
}

function isMasterPromptNode(node) {
  if (!node) return false;
  if (node.comfyClass === "MasterPromptLibrary"
    || node.type === "MasterPromptLibrary"
    || node.constructor?.comfyClass === "MasterPromptLibrary") {
    return true;
  }
  if (node.title !== "Master Prompt Library") return false;
  const widgetNames = new Set((node.widgets || []).map((widget) => widget?.name));
  return ["style", "character", "action", "background", "component_order"]
    .every((name) => widgetNames.has(name));
}

function nodesInOpenGraph() {
  const graph = app?.graph;
  const nodes = graph?._nodes || graph?.nodes;
  return Array.isArray(nodes) ? nodes : [];
}

function updateNodeCombos(library) {
  for (const node of nodesInOpenGraph()) {
    if (!isMasterPromptNode(node)) continue;
    for (const category of CATEGORY_ORDER) {
      const widget = node.widgets?.find((candidate) => candidate?.name === category);
      if (!widget) continue;
      const previousValue = widget.value;
      const rebuilt = rebuildComboValues(library?.categories?.[category], previousValue);
      widget.options = widget.options || {};
      widget.options.values = rebuilt.values;
      widget.value = rebuilt.value;
      if (rebuilt.value !== previousValue) widget.callback?.(rebuilt.value);
    }
    node.setDirtyCanvas?.(true, true);
  }
}

function normalizeLibraryPayload(payload) {
  const source = payload?.library && typeof payload.library === "object"
    ? payload.library
    : payload;
  if (!source || typeof source !== "object" || !source.categories || typeof source.categories !== "object") {
    throw new Error("The library response was not a valid prompt library.");
  }
  const categories = {};
  for (const category of CATEGORY_ORDER) {
    if (!Array.isArray(source.categories[category])) {
      throw new Error(`The library response is missing the ${CATEGORY_LABELS[category]} category.`);
    }
    categories[category] = source.categories[category]
      .filter((entry) => entry && typeof entry === "object" && typeof entry.id === "string")
      .map((entry) => ({
        id: entry.id,
        name: typeof entry.name === "string" ? entry.name : "",
        prompt: typeof entry.prompt === "string" ? entry.prompt : "",
        image: entry.image && typeof entry.image === "object" ? { ...entry.image } : null,
      }));
  }
  return { version: Number(source.version) || 1, categories };
}

async function responsePayload(response) {
  if (!response) throw new Error("The library server returned no response.");
  let bodyText = "";
  if (typeof response.text === "function") {
    try {
      bodyText = await response.text();
    } catch {
      bodyText = "";
    }
  }
  let data = null;
  if (bodyText) {
    try {
      data = JSON.parse(bodyText);
    } catch {
      data = null;
    }
  } else if (typeof response.json === "function") {
    try {
      data = await response.json();
    } catch {
      data = null;
    }
  }
  const failed = response.ok === false || (Number.isFinite(response.status) && response.status >= 400);
  if (failed) {
    const message = data && typeof data === "object"
      ? (data.error || data.message || data.detail)
      : bodyText;
    throw new Error(message || `Library request failed (${response.status || "unknown status"}).`);
  }
  return data;
}

async function requestJSON(path, options = {}) {
  const response = await api.fetchApi(path, options);
  return responsePayload(response);
}

function requestOptions(method, body) {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

function entryFromPayload(payload) {
  return payload?.entry && typeof payload.entry === "object" ? payload.entry : payload;
}

function uniqueCopyName(entries, sourceName) {
  const base = `Copy of ${sourceName}`;
  let candidate = base;
  let suffix = 2;
  while (hasDuplicateName(entries, candidate)) {
    candidate = `${base} (${suffix})`;
    suffix += 1;
  }
  return candidate;
}

function ensureStyles() {
  const href = new URL("./prompt_library.css", import.meta.url).href;
  if (document.querySelector(`link[data-mpl-styles="${href}"]`)) return;
  const link = element("link", { rel: "stylesheet", href, "data-mpl-styles": href });
  document.head.appendChild(link);
}

class PromptLibraryModal {
  constructor() {
    this.root = element("div", { className: "mpl-modal", hidden: true });
    this.backdrop = element("div", { className: "mpl-backdrop", "aria-hidden": "true" });
    this.dialog = element("section", {
      className: "mpl-dialog",
      role: "dialog",
      "aria-modal": "true",
      "aria-labelledby": "mpl-title",
    });
    this.root.appendChild(this.backdrop);
    this.root.appendChild(this.dialog);

    this.library = null;
    this.activeNode = null;
    this.activeCategory = "style";
    this.selectedId = null;
    this.editingId = null;
    this.mode = "view";
    this.draft = null;
    this.query = "";
    this.busy = false;
    this.statusMessage = "";
    this.imageRevision = 0;
    this.previousFocus = null;
    this.boundKeydown = (event) => this.handleKeydown(event);
    this.objectUrls = new Set();
    this.categoryButtons = new Map();
    this.build();
    document.body.appendChild(this.root);
  }

  build() {
    const header = element("header", { className: "mpl-header" });
    const heading = element("div", {}, [
      element("p", { className: "mpl-kicker", textContent: "Prompt catalog / local archive" }),
      element("h2", { className: "mpl-title", id: "mpl-title", textContent: "Master Prompt Library" }),
      element("p", {
        className: "mpl-subtitle",
        textContent: "Keep the pieces visible. Browse by category, recognize them by image, and send only the selected text back to the node.",
      }),
    ]);
    this.context = element("p", { className: "mpl-context" });
    this.closeButton = element("button", {
      className: "mpl-close",
      type: "button",
      title: "Close library",
      "aria-label": "Close library",
      textContent: "×",
    });
    this.closeButton.addEventListener("click", () => this.close());
    header.append(heading, this.context, this.closeButton);

    const toolbar = element("div", { className: "mpl-toolbar" });
    const searchWrap = element("div", { className: "mpl-toolbar-search" });
    this.searchInput = element("input", {
      className: "mpl-input",
      type: "search",
      placeholder: "Search names and prompt text…",
      "aria-label": "Search library entries",
      autocomplete: "off",
    });
    this.searchInput.addEventListener("input", () => {
      this.clearError();
      this.query = this.searchInput.value;
      this.ensureSelectedVisible();
      this.render();
    });
    searchWrap.append(
      element("label", { className: "mpl-label", for: "mpl-search", textContent: "Find in archive" }),
      this.searchInput,
    );
    this.searchInput.id = "mpl-search";
    this.count = element("span", { className: "mpl-count", "aria-live": "polite" });
    this.importButton = element("button", { className: "mpl-button", type: "button", textContent: "Import JSON" });
    this.exportButton = element("button", { className: "mpl-button", type: "button", textContent: "Export JSON" });
    this.importButton.addEventListener("click", () => this.importInput.click());
    this.exportButton.addEventListener("click", () => this.exportLibrary());
    this.importInput = element("input", {
      className: "mpl-hidden-file",
      type: "file",
      accept: "application/json,.json",
      tabindex: "-1",
      "aria-label": "Choose a prompt library JSON file",
    });
    this.importInput.addEventListener("change", (event) => this.handleImportFile(event.target.files?.[0]));
    toolbar.append(searchWrap, this.count, this.importButton, this.exportButton, this.importInput);

    this.error = element("div", { className: "mpl-error", role: "alert", hidden: true });
    const body = element("div", { className: "mpl-body" });
    this.rail = element("aside", { className: "mpl-category-rail", "aria-label": "Prompt categories" });
    this.rail.appendChild(element("p", { className: "mpl-rail-caption", textContent: "Components" }));
    for (const category of CATEGORY_ORDER) {
      const button = element("button", {
        className: "mpl-category",
        type: "button",
        dataset: { category },
        "aria-label": `Browse ${CATEGORY_LABELS[category]} entries`,
      });
      button.addEventListener("click", () => {
        this.clearError();
        this.activeCategory = category;
        this.selectedId = this.findNodeSelectionId(category) || this.library?.categories?.[category]?.[0]?.id || null;
        this.query = "";
        this.searchInput.value = "";
        this.render();
      });
      this.categoryButtons.set(category, button);
      this.rail.appendChild(button);
    }

    this.main = element("div", { className: "mpl-main" });
    this.listPane = element("section", { className: "mpl-list-pane", "aria-label": "Library entries" });
    this.listHeading = element("div", { className: "mpl-list-heading" });
    this.entryList = element("div", { className: "mpl-entry-list", role: "listbox", "aria-label": "Prompt entries" });
    this.listPane.append(this.listHeading, this.entryList);
    this.detailPane = element("section", { className: "mpl-detail-pane", "aria-label": "Entry details" });
    this.main.append(this.listPane, this.detailPane);
    body.append(this.rail, this.main);
    this.dialog.append(header, toolbar, this.error, body);
    this.backdrop.addEventListener("click", () => this.close());
  }

  async open(node) {
    this.activeNode = node;
    this.activeCategory = categoryFromNode(node);
    this.previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    this.root.hidden = false;
    this.query = "";
    this.searchInput.value = "";
    this.selectedId = null;
    this.mode = "view";
    this.editingId = null;
    this.draft = null;
    this.statusMessage = "";
    this.clearError();
    this.bindKeyboard();
    this.setBusy(true);
    try {
      await this.refreshLibrary(false);
      this.selectedId = this.findNodeSelectionId(this.activeCategory)
        || this.currentEntries()[0]?.id
        || null;
      this.searchInput.focus();
    } catch (error) {
      this.setError(error);
      this.searchInput.focus();
    } finally {
      this.setBusy(false);
      this.render();
    }
  }

  close() {
    if (this.root.hidden) return;
    this.root.hidden = true;
    this.unbindKeyboard();
    this.cleanupObjectUrls();
    const focusTarget = this.previousFocus;
    this.previousFocus = null;
    this.activeNode = null;
    if (focusTarget && typeof focusTarget.focus === "function" && document.contains(focusTarget)) focusTarget.focus();
  }

  bindKeyboard() {
    document.addEventListener("keydown", this.boundKeydown);
  }

  unbindKeyboard() {
    document.removeEventListener("keydown", this.boundKeydown);
  }

  handleKeydown(event) {
    if (this.root.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      if (this.mode === "edit") {
        this.cancelEdit();
      } else {
        this.close();
      }
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...this.dialog.querySelectorAll("button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex=\"-1\"])")]
      .filter((candidate) => !candidate.hidden && candidate.offsetParent !== null);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  clearError() {
    this.error.hidden = true;
    this.error.textContent = "";
  }

  setError(error) {
    this.error.textContent = trimError(error);
    this.error.hidden = false;
  }

  setStatus(message) {
    this.statusMessage = message || "";
  }

  setBusy(value) {
    this.busy = Boolean(value);
    this.dialog.setAttribute("aria-busy", String(this.busy));
    this.applyBusyState();
  }

  applyBusyState() {
    for (const button of this.dialog.querySelectorAll("button")) {
      if (button === this.closeButton) continue;
      button.disabled = this.busy;
    }
  }

  async refreshLibrary(updateNodes = true) {
    const payload = await requestJSON(`${API_BASE}/library`);
    this.library = normalizeLibraryPayload(payload);
    this.imageRevision = Date.now();
    this.ensureSelectedVisible();
    if (updateNodes) updateNodeCombos(this.library);
    this.render();
    return this.library;
  }

  currentEntries() {
    return this.library?.categories?.[this.activeCategory] || [];
  }

  visibleEntries() {
    return filterEntries(this.currentEntries(), this.query);
  }

  ensureSelectedVisible() {
    const visible = this.visibleEntries();
    if (!visible.some((entry) => entry.id === this.selectedId)) {
      this.selectedId = visible[0]?.id || null;
    }
  }

  findEntry(category = this.activeCategory, id = this.selectedId) {
    return this.library?.categories?.[category]?.find((entry) => entry.id === id) || null;
  }

  findNodeSelectionId(category) {
    const widget = this.activeNode?.widgets?.find((candidate) => candidate?.name === category);
    const value = widget?.value;
    if (!value || value === NONE_VALUE) return null;
    return this.library?.categories?.[category]?.find((entry) => entry.name === value)?.id || null;
  }

  render() {
    if (!this.library) {
      this.listHeading.textContent = "Loading archive…";
      return;
    }
    const entries = this.currentEntries();
    const visible = this.visibleEntries();
    this.context.textContent = this.activeNode
      ? `Opened from a Master Prompt Library node · ${CATEGORY_LABELS[this.activeCategory]} is active`
      : "Local library";
    for (const category of CATEGORY_ORDER) {
      const button = this.categoryButtons.get(category);
      const count = this.library.categories[category].length;
      clearChildren(button);
      button.append(
        document.createTextNode(CATEGORY_LABELS[category]),
        element("span", { className: "mpl-category-count", textContent: String(count) }),
      );
      button.classList.toggle("is-active", category === this.activeCategory);
      button.setAttribute("aria-current", category === this.activeCategory ? "page" : "false");
    }
    this.count.textContent = `${visible.length} / ${entries.length} entries`;
    this.listHeading.textContent = `${CATEGORY_LABELS[this.activeCategory]} archive`;
    this.searchInput.value = this.query;
    this.renderList(visible);
    this.renderDetail();
    this.applyBusyState();
  }

  renderList(entries) {
    clearChildren(this.entryList);
    if (!entries.length) {
      this.entryList.appendChild(element("p", {
        className: "mpl-empty",
        textContent: this.query ? "Nothing matches that search." : "This shelf is empty. Add the first entry.",
      }));
      return;
    }
    for (const entry of entries) {
      const state = imageState(entry, this.imageRevision);
      const row = element("button", {
        className: `mpl-entry-row${entry.id === this.selectedId ? " is-selected" : ""}`,
        type: "button",
        role: "option",
        "aria-selected": String(entry.id === this.selectedId),
        "aria-label": `${entry.name}, ${CATEGORY_LABELS[this.activeCategory]} entry`,
      });
      const visual = state.kind === "image"
        ? element("img", { className: "mpl-thumbnail", src: state.url, alt: state.alt, loading: "lazy" })
        : element("span", { className: "mpl-placeholder", role: "img", "aria-label": state.alt, textContent: "✦" });
      const copy = element("span", {}, [
        element("span", { className: "mpl-entry-name", textContent: entry.name }),
        element("span", { className: "mpl-entry-snippet", textContent: entry.prompt }),
      ]);
      row.append(visual, copy);
      row.addEventListener("click", () => {
        this.clearError();
        this.selectedId = entry.id;
        this.mode = "view";
        this.editingId = null;
        this.draft = null;
        this.render();
      });
      row.addEventListener("keydown", (event) => {
        const rows = [...this.entryList.querySelectorAll(".mpl-entry-row")];
        const index = rows.indexOf(row);
        if (event.key === "ArrowDown" || event.key === "ArrowRight") {
          event.preventDefault();
          rows[Math.min(index + 1, rows.length - 1)]?.focus();
        } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
          event.preventDefault();
          rows[Math.max(index - 1, 0)]?.focus();
        } else if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          row.click();
        }
      });
      this.entryList.appendChild(row);
    }
  }

  renderDetail() {
    clearChildren(this.detailPane);
    const status = element("div", { className: "mpl-status", "aria-live": "polite", textContent: this.statusMessage });
    if (this.mode === "edit") {
      this.renderEditor(status);
      this.detailPane.appendChild(status);
      return;
    }
    const entry = this.findEntry();
    if (!entry) {
      this.detailPane.append(
        element("p", { className: "mpl-empty", textContent: "Choose an entry, or add one to this shelf." }),
        element("div", { className: "mpl-detail-actions" }, [
          this.actionButton("＋ Add entry", "primary", () => this.startAdd()),
        ]),
        status,
      );
      return;
    }
    const state = imageState(entry, this.imageRevision);
    const preview = element("div", { className: "mpl-detail-preview" });
    if (state.kind === "image") {
      const img = element("img", { src: state.url, alt: state.alt });
      img.addEventListener("error", () => {
        clearChildren(preview);
        preview.appendChild(element("span", { className: "mpl-placeholder", role: "img", "aria-label": state.alt, textContent: "✦" }));
      });
      preview.appendChild(img);
    } else {
      preview.appendChild(element("span", { className: "mpl-placeholder", role: "img", "aria-label": state.alt, textContent: "✦" }));
    }
    const heading = element("div", { className: "mpl-detail-heading" }, [
      element("h3", { className: "mpl-detail-title", textContent: entry.name }),
      element("span", { className: "mpl-detail-category", textContent: CATEGORY_LABELS[this.activeCategory] }),
    ]);
    const prompt = element("p", { className: "mpl-prompt-readonly", textContent: entry.prompt });
    const detailActions = element("div", { className: "mpl-detail-actions" });
    detailActions.append(
      this.actionButton("Use selection", "primary", () => this.useSelection()),
      this.actionButton("Edit", "", () => this.startEdit()),
      this.actionButton("Duplicate", "", () => this.startDuplicate()),
      this.actionButton("Delete", "danger", () => this.deleteSelected()),
    );
    const imageControl = element("div", { className: "mpl-image-control" });
    const fileInput = element("input", {
      className: "mpl-hidden-file",
      type: "file",
      accept: "image/jpeg,image/png,image/webp",
      "aria-label": entry.image ? `Replace preview for ${entry.name}` : `Attach preview for ${entry.name}`,
    });
    fileInput.addEventListener("change", (event) => this.handleImageFile(event.target.files?.[0], Boolean(entry.image)));
    const fileLabel = element("label", { className: "mpl-button" }, [
      fileInput,
      document.createTextNode(entry.image ? "Replace preview" : "Attach preview"),
    ]);
    const imageActions = element("div", { className: "mpl-image-actions" }, [fileLabel]);
    if (entry.image) imageActions.appendChild(this.actionButton("Remove preview", "danger", () => this.removeImage(entry)));
    imageControl.append(
      element("p", { className: "mpl-image-note", textContent: "Preview image · JPEG, PNG, or WebP · 8 MiB maximum" }),
      imageActions,
    );
    this.detailPane.append(preview, heading, prompt, detailActions, imageControl, status);
  }

  renderEditor(status) {
    const draft = this.draft || { name: "", prompt: "" };
    const heading = element("div", { className: "mpl-detail-heading" }, [
      element("h3", { className: "mpl-detail-title", textContent: this.editingId ? "Edit entry" : "New entry" }),
      element("span", { className: "mpl-detail-category", textContent: CATEGORY_LABELS[this.activeCategory] }),
    ]);
    const editor = element("div", { className: "mpl-editor" });
    const nameInput = element("input", {
      className: "mpl-input",
      type: "text",
      maxlength: "120",
      value: draft.name,
      "aria-label": "Entry name",
      "data-mpl-editor-name": "true",
    });
    const promptInput = element("textarea", {
      className: "mpl-textarea",
      maxlength: "20000",
      "aria-label": "Entry prompt",
      placeholder: "Write the prompt text this component should contribute…",
    });
    promptInput.value = draft.prompt;
    nameInput.addEventListener("input", () => { this.draft.name = nameInput.value; });
    promptInput.addEventListener("input", () => { this.draft.prompt = promptInput.value; });
    editor.append(
      element("label", { className: "mpl-field-label", for: "mpl-entry-name", textContent: "Name" }),
      nameInput,
      element("label", { className: "mpl-field-label", for: "mpl-entry-prompt", textContent: "Prompt text" }),
      promptInput,
    );
    nameInput.id = "mpl-entry-name";
    promptInput.id = "mpl-entry-prompt";
    const actions = element("div", { className: "mpl-editor-actions" }, [
      this.actionButton("Save entry", "primary", () => this.saveDraft()),
      this.actionButton("Cancel", "", () => this.cancelEdit()),
    ]);
    this.detailPane.append(heading, editor, actions);
    queueMicrotask(() => nameInput.focus());
  }

  actionButton(label, variant, callback) {
    return element("button", {
      className: `mpl-button${variant === "primary" ? " mpl-button-primary" : ""}${variant === "danger" ? " mpl-button-danger" : ""}`,
      type: "button",
      textContent: label,
      onclick: callback,
    });
  }

  startAdd() {
    this.clearError();
    this.setStatus("");
    this.selectedId = null;
    this.editingId = null;
    this.mode = "edit";
    this.draft = { name: "", prompt: "" };
    this.render();
  }

  startEdit() {
    const entry = this.findEntry();
    if (!entry) return;
    this.clearError();
    this.setStatus("");
    this.editingId = entry.id;
    this.mode = "edit";
    this.draft = { name: entry.name, prompt: entry.prompt };
    this.render();
  }

  startDuplicate() {
    const entry = this.findEntry();
    if (!entry) return;
    this.clearError();
    this.setStatus("");
    this.selectedId = null;
    this.editingId = null;
    this.mode = "edit";
    this.draft = {
      name: uniqueCopyName(this.currentEntries(), entry.name),
      prompt: entry.prompt,
    };
    this.render();
  }

  cancelEdit() {
    this.clearError();
    this.editingId = null;
    this.draft = null;
    this.mode = "view";
    this.ensureSelectedVisible();
    this.render();
  }

  async saveDraft() {
    if (this.busy) return;
    this.clearError();
    this.setStatus("");
    const name = String(this.draft?.name || "").trim();
    const prompt = String(this.draft?.prompt || "").trim();
    const entries = this.currentEntries();
    if (!name || !prompt) {
      this.setError("Name and prompt text are required.");
      return;
    }
    if (name.length > 120 || prompt.length > 20000) {
      this.setError("Name must be 120 characters or fewer and prompt text 20,000 characters or fewer.");
      return;
    }
    if (hasDuplicateName(entries, name, this.editingId)) {
      this.setError("An entry with that name already exists in this category.");
      return;
    }
    this.setBusy(true);
    try {
      const body = { category: this.activeCategory, name, prompt };
      const payload = this.editingId
        ? await requestJSON(`${API_BASE}/entries/${encodeURIComponent(this.editingId)}`, requestOptions("PUT", body))
        : await requestJSON(`${API_BASE}/entries`, requestOptions("POST", body));
      const saved = entryFromPayload(payload);
      await this.refreshLibrary(true);
      this.selectedId = saved?.id || this.library.categories[this.activeCategory].find((entry) => entry.name === name)?.id || null;
      this.editingId = null;
      this.draft = null;
      this.mode = "view";
      this.setStatus("Entry saved.");
    } catch (error) {
      this.setError(error);
    } finally {
      this.setBusy(false);
      this.render();
    }
  }

  async deleteSelected() {
    const entry = this.findEntry();
    if (!entry || this.busy) return;
    this.clearError();
    this.setStatus("");
    if (!confirmAction(`Delete “${entry.name}”? This cannot be undone.`)) return;
    this.setBusy(true);
    try {
      await requestJSON(`${API_BASE}/entries/${encodeURIComponent(entry.id)}`, { method: "DELETE" });
      this.selectedId = null;
      await this.refreshLibrary(true);
      this.setStatus("Entry deleted.");
    } catch (error) {
      this.setError(error);
    } finally {
      this.setBusy(false);
      this.render();
    }
  }

  useSelection() {
    const entry = this.findEntry();
    if (!entry || !this.activeNode || this.mode === "edit") return;
    this.clearError();
    const widget = this.activeNode.widgets?.find((candidate) => candidate?.name === this.activeCategory);
    if (!widget) {
      this.setError(`The active node has no ${CATEGORY_LABELS[this.activeCategory]} combo.`);
      return;
    }
    widget.value = entry.name;
    widget.callback?.(entry.name);
    this.activeNode.setDirtyCanvas?.(true, true);
    this.close();
  }

  async handleImageFile(file, replacing) {
    if (!file || this.busy) return;
    this.clearError();
    this.setStatus("");
    const validation = validateImageFile(file);
    if (!validation.valid) {
      this.setError(validation.error);
      return;
    }
    const entry = this.findEntry();
    if (!entry) {
      this.setError("Save the entry before attaching a preview image.");
      return;
    }
    if (replacing && !confirmAction(`Replace the preview for “${entry.name}”?`)) return;
    this.setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file, file.name || "preview");
      await requestJSON(`${API_BASE}/entries/${encodeURIComponent(entry.id)}/image`, { method: "POST", body: form });
      await this.refreshLibrary(true);
      this.setStatus("Preview image saved.");
    } catch (error) {
      this.setError(error);
    } finally {
      this.setBusy(false);
      this.render();
    }
  }

  async removeImage(entry) {
    if (!entry || this.busy) return;
    this.clearError();
    this.setStatus("");
    if (!confirmAction(`Remove the preview for “${entry.name}”?`)) return;
    this.setBusy(true);
    try {
      await requestJSON(`${API_BASE}/entries/${encodeURIComponent(entry.id)}/image`, { method: "DELETE" });
      await this.refreshLibrary(true);
      this.setStatus("Preview removed.");
    } catch (error) {
      this.setError(error);
    } finally {
      this.setBusy(false);
      this.render();
    }
  }

  async handleImportFile(file) {
    this.importInput.value = "";
    if (!file || this.busy) return;
    this.clearError();
    this.setStatus("");
    let parsed;
    try {
      parsed = JSON.parse(await file.text());
      normalizeLibraryPayload(parsed);
    } catch (error) {
      this.setError(error instanceof SyntaxError ? "The selected file is not valid JSON." : error);
      return;
    }
    if (!confirmAction("Replace the complete prompt library with this JSON file?")) return;
    this.setBusy(true);
    try {
      await requestJSON(`${API_BASE}/library`, requestOptions("PUT", parsed));
      await this.refreshLibrary(true);
      this.setStatus("Library imported.");
    } catch (error) {
      this.setError(error);
    } finally {
      this.setBusy(false);
      this.render();
    }
  }

  exportLibrary() {
    if (!this.library || this.busy) return;
    this.clearError();
    this.setStatus("");
    try {
      const blob = new Blob([JSON.stringify(this.library, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      this.objectUrls.add(url);
      const link = element("a", { href: url, download: "prompt_library.json" });
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      this.objectUrls.delete(url);
      this.setStatus("Library exported.");
      this.render();
    } catch (error) {
      this.setError(error);
    }
  }

  cleanupObjectUrls() {
    for (const url of this.objectUrls) URL.revokeObjectURL(url);
    this.objectUrls.clear();
  }
}

function confirmAction(message) {
  return typeof window === "undefined" || typeof window.confirm !== "function" ? true : window.confirm(message);
}

let modalInstance = null;

function getModal() {
  if (!modalInstance) modalInstance = new PromptLibraryModal();
  return modalInstance;
}

function addBrowseButton(node, knownMasterPromptNode = false) {
  if ((!knownMasterPromptNode && !isMasterPromptNode(node)) || node.__masterPromptLibraryButton) return;
  const button = node.addWidget?.(
    "button",
    "Browse & Manage Library",
    null,
    () => getModal().open(node),
    { serialize: false },
  );
  if (!button) return;
  button.serialize = false;
  button.serializeValue = () => null;
  button.label = "Browse & Manage Library";
  button.callback = () => getModal().open(node);
  node.__masterPromptLibraryButton = button;

  // Adding a widget does not always invalidate LiteGraph's cached node
  // geometry. Expand to the measured size without shrinking a user's
  // deliberately resized node, then request a canvas repaint.
  const currentWidth = Number(node.size?.[0]);
  const currentHeight = Number(node.size?.[1]);
  const measured = typeof node.computeSize === "function" ? node.computeSize() : null;
  const measuredWidth = Number(measured?.[0]);
  const measuredHeight = Number(measured?.[1]);
  if (typeof node.setSize === "function" && (measuredWidth > 0 || measuredHeight > 0)) {
    const width = Math.max(
      Number.isFinite(currentWidth) ? currentWidth : 0,
      Number.isFinite(measuredWidth) ? measuredWidth : 0,
    );
    const height = Math.max(
      Number.isFinite(currentHeight) ? currentHeight : 0,
      Number.isFinite(measuredHeight) ? measuredHeight : 0,
    );
    node.setSize([width, height]);
  }
  node.setDirtyCanvas?.(true, true);
}

function addButtonsToOpenNodes() {
  for (const node of nodesInOpenGraph()) addBrowseButton(node);
}

function hookMasterPromptNode(nodeType, nodeData) {
  if (nodeType?.comfyClass !== "MasterPromptLibrary" && !isMasterPromptNodeData(nodeData)) return;
  const prototype = nodeType?.prototype;
  if (!prototype || prototype.__masterPromptLibraryCreationHook) return;

  const originalOnNodeCreated = prototype.onNodeCreated;
  prototype.onNodeCreated = function masterPromptLibraryOnNodeCreated(...args) {
    const result = typeof originalOnNodeCreated === "function"
      ? originalOnNodeCreated.apply(this, args)
      : undefined;
    const deferButton = () => queueMicrotask(() => addBrowseButton(this, true));

    // ComfyUI currently uses a synchronous hook, but preserve a future
    // async implementation's return value and attach after it resolves.
    if (result && typeof result.then === "function") {
      return result.then((value) => {
        deferButton();
        return value;
      });
    }
    deferButton();
    return result;
  };
  Object.defineProperty(prototype, "__masterPromptLibraryCreationHook", {
    configurable: false,
    enumerable: false,
    value: true,
    writable: false,
  });
}

app.registerExtension({
  name: EXTENSION_NAME,

  init() {
    ensureStyles();
  },

  afterConfigureGraph() {
    queueMicrotask(addButtonsToOpenNodes);
  },

  beforeRegisterNodeDef(nodeType, nodeData) {
    hookMasterPromptNode(nodeType, nodeData);
  },

  nodeCreated(node) {
    queueMicrotask(() => {
      if (isMasterPromptNode(node)) addBrowseButton(node);
    });
  },

  loadedGraphNode(node) {
    queueMicrotask(() => {
      if (isMasterPromptNode(node)) addBrowseButton(node);
    });
  },
});
