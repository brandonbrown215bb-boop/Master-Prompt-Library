# UI/UX Remediation Plan

## Objective

Make the Master Prompt Library v2 manager and quick picker keyboard-complete,
responsive at practical ComfyUI window sizes, legible without wasting large
displays, and predictable about which interface state survives closing or
reloading.

The outer Comfy Desktop window remains host-owned. This work owns the library
modal, its nested dialogs, the embedded quick picker, and their local UI state.

## Required outcomes

### 1. Keyboard and assistive-technology correctness

- Enter and Space activate the image-extraction dropzone.
- Escape closes only the active nested dialog; a second Escape may close the
  manager.
- Nested dialogs expose their visible title as the accessible dialog name.
- Catalog selection, favorite, ordering, removal, and paging updates preserve a
  useful keyboard focus target instead of dropping focus onto `body`.
- File-upload controls have a visible keyboard focus indicator.
- Gallery tabs expose complete tab semantics and Left/Right/Home/End keyboard
  navigation.
- The quick-picker listbox declares multi-selection and retains roving focus.

### 2. Legible use of available pixels

- The manager defaults near the usable viewport rather than stopping at
  1260x840 on large displays.
- At 700x720, no catalog/detail content is clipped behind the footer.
- The narrow layout provides an explicit Catalog/Details switch rather than
  stacking two minimum-height panes inside an overflow-hidden parent.
- Body and control copy stays at or above 12px in the modal. Quick-picker
  labels and previews stay at or above 11px.
- Touch/click targets are at least 24x24 CSS pixels.
- Quick-picker results are paged or virtualized; a 281-entry category must not
  create a 12,000px scrolling DOM surface.

### 3. Persistence contract

- Modal width, height, and catalog/detail split are user-adjustable and stored
  in namespaced local storage.
- Restored geometry is clamped to the current viewport so monitor or window
  changes cannot strand content off-screen.
- A visible reset action returns geometry and density to defaults.
- Existing browser-session persistence for manager filters, active category,
  and draft selection remains intact.
- Quick-picker expansion, query, category, page, and cursor remain transient and
  are not added to workflow serialization.
- Only **Apply to Node** commits modal selection/order to workflow state.

## Implementation boundaries

- Preserve current uncommitted image-extraction and route work.
- Do not change backend persistence or import semantics for UI-state storage.
- Do not serialize UI geometry into ComfyUI workflows.
- Keep drag-and-drop as an enhancement; every ordering action must retain a
  keyboard button path.
- Avoid introducing a UI framework or a new build pipeline.

## Acceptance evidence

### Automated

- `node --test tests/*.mjs`
- `python -m unittest discover -s tests -v`
- Tests exercise behavior rather than only searching source text for selectors.
- Geometry helpers cover clamping and malformed/unavailable storage.
- Keyboard helpers cover nested Escape, dropzone activation, focus restoration,
  tabs, and quick-picker paging/virtualization.

### Installed host

- Workspace and installed frontend files have matching hashes before the host
  smoke.
- 1280x720: the modal remains legible and all primary actions are visible.
- 700x720: Catalog and Details are independently reachable with no clipped
  content behind the footer.
- 2560x1440: the modal uses substantially more than 1260x840 by default or
  restores the user's larger size.
- Keyboard-only: open manager, traverse categories and catalog, toggle and
  reorder selection, open/cancel nested dialogs, use image extraction, and
  return focus to the invoking control.
- Close/reopen restores session state; page reload restores only namespaced UI
  geometry and applied workflow state.

## Delegated slices

1. **Modal behavior:** nested dialogs, focus continuity, keyboard upload paths,
   tab semantics, geometry storage and controls.
2. **Responsive presentation:** large-screen sizing, narrow Catalog/Details
   layout, legible type, visible file focus, minimum target sizes.
3. **Quick picker:** bounded rendering, paging/navigation, multi-select ARIA,
   legible density, and transient-state invariants.

The orchestrator owns integration review, cross-slice fixes, complete automated
verification, installed parity, and the real-host acceptance pass.
