// Files tab — folder toggle + drag-and-drop re-parenting for the standalone
// notes editor. All events are delegated to #file-tree-container (a stable
// element) so bindings survive the htmx innerHTML refresh of the tree that
// follows every move.

import { getCSRFToken } from "./state.js";
import { broadcast } from "./broadcast.js";
import {
  applyTreeState,
  setFolderExpanded,
  setMatterExpanded,
  setPaneExpansion,
} from "./tab-state.js";

const MAX_DEPTH = 3; // 0-based; 4 levels, mirrors NoteFolder's cap
const HOVER_EXPAND_MS = 600;
const DROP_ERROR_MS = 1200;

// dataTransfer is unreadable during dragover, so live validation works off
// this module-level record instead. height is the dragged folder's subtree
// height, computed once at dragstart.
let drag = null; // { type: "note"|"folder", el, height }
let dropTarget = null; // currently highlighted folder li or root ul
let hoverEl = null;
let hoverTimer = null;

export function setupFileTree() {
  const container = document.getElementById("file-tree-container");
  if (!container) return;
  if (container.dataset.treeBound) return;
  container.dataset.treeBound = "1";

  container.addEventListener("click", onClick);
  container.addEventListener("dragstart", onDragStart);
  container.addEventListener("dragend", onDragEnd);
  container.addEventListener("dragover", onDragOver);
  container.addEventListener("dragleave", onDragLeave);
  container.addEventListener("drop", onDrop);

  setupTreeCollapseAll(container);
  // Order matters: the swapped-in tree is all-collapsed; dress it in this
  // tab's expansion state synchronously (before refreshTree's promise
  // restores scroll positions against the final heights), then sync the
  // collapse-all icon off the resulting DOM.
  container.addEventListener("htmx:afterSwap", () => {
    applyTreeState();
    updateTreeCollapseIcon();
  });
  applyTreeState();
}

// ─── Collapse/expand all (header button, active pane only) ───────────────────

function activePane() {
  const panel = document.querySelector(".note-panel-left");
  if (!panel) return null;
  const pane = panel.dataset.activePane;
  if (pane === "recent") return null; // nothing to collapse there
  return document.querySelector(
    pane === "matters" ? ".tree-pane-matters" : ".tree-pane-files",
  );
}

// All-or-nothing, like the outline's collapse-all: any expanded node means
// the button collapses everything. The icon shows the action it will take.
export function updateTreeCollapseIcon() {
  const btn = document.getElementById("tree-collapse-btn");
  const pane = activePane();
  if (!btn || !pane) return;
  const anyExpanded = pane.querySelector(
    ".file-tree-folder:not(.collapsed), .file-tree-matter:not(.collapsed)",
  );
  btn.querySelector("i").className = anyExpanded
    ? "icon-chevrons-down-up"
    : "icon-chevrons-up-down";
}

function setupTreeCollapseAll(container) {
  const btn = document.getElementById("tree-collapse-btn");
  if (!btn) return;

  btn.addEventListener("click", () => {
    const pane = activePane();
    if (!pane) return;
    const expand = !pane.querySelector(
      ".file-tree-folder:not(.collapsed), .file-tree-matter:not(.collapsed)",
    );
    pane
      .querySelectorAll(".file-tree-folder, .file-tree-matter")
      .forEach((li) => li.classList.toggle("collapsed", !expand));
    // Persist the whole pane's expansion state (this tab only)
    setPaneExpansion(
      [...pane.querySelectorAll(".file-tree-folder")].map(
        (li) => li.dataset.folderId,
      ),
      [...pane.querySelectorAll(".file-tree-matter")].map(
        (li) => li.dataset.matterId,
      ),
      expand,
    );
    updateTreeCollapseIcon();
  });

  updateTreeCollapseIcon();
}

// ─── Inline folder rename ────────────────────────────────────────────────────

// Obsidian-style: the folder's name swaps to a focused input with the
// text selected, so typing replaces it. Enter/blur commit through the
// rename endpoint (htmx.ajax, so the 204's noteFoldersChanged trigger
// refreshes the trees + broadcasts); Escape keeps the current name.
export function startFolderRename(li) {
  const nameSpan = li.querySelector(":scope > .file-tree-name");
  if (!nameSpan || li.querySelector(":scope > .file-tree-rename-input")) return;

  const input = document.createElement("input");
  input.type = "text";
  input.className = "file-tree-rename-input";
  input.value = nameSpan.textContent.trim();
  nameSpan.style.display = "none";
  nameSpan.after(input);
  li.draggable = false; // a text-selection drag must not start a DnD move
  li.scrollIntoView({ block: "nearest" });
  input.focus();
  input.select();

  let done = false;
  const finish = (commit) => {
    if (done) return;
    done = true;
    const name = input.value.trim();
    input.remove();
    nameSpan.style.display = "";
    li.draggable = true;
    if (commit && name && name !== nameSpan.textContent.trim()) {
      nameSpan.textContent = name; // optimistic; the refresh re-sorts
      window.htmx.ajax("POST", li.dataset.renameUrl, {
        swap: "none",
        values: { name },
      });
    }
  };

  // Clicks inside the input must not reach the container's toggle handler
  input.addEventListener("click", (e) => e.stopPropagation());
  input.addEventListener("dblclick", (e) => e.stopPropagation());
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") {
      e.preventDefault();
      finish(true);
    } else if (e.key === "Escape") {
      e.preventDefault();
      finish(false);
    }
  });
  input.addEventListener("blur", () => finish(true));
}

// ─── Expand/collapse ─────────────────────────────────────────────────────────

function onClick(e) {
  const handle = e.target.closest(".file-tree-toggle, .file-tree-name");
  if (!handle) return;
  const li = handle.closest(".file-tree-item");
  // Folder and matter nodes toggle; note clicks fall through to hx-get
  if (
    !li ||
    !(
      li.classList.contains("file-tree-folder") ||
      li.classList.contains("file-tree-matter")
    )
  )
    return;

  e.stopPropagation();
  const nowExpanded = !li.classList.toggle("collapsed");
  if (li.classList.contains("file-tree-matter")) {
    setMatterExpanded(li.dataset.matterId, nowExpanded);
  } else {
    setFolderExpanded(li.dataset.folderId, nowExpanded);
  }
  updateTreeCollapseIcon();
}

// ─── Drag and drop ───────────────────────────────────────────────────────────

function subtreeHeight(folderLi) {
  let max = +folderLi.dataset.depth;
  folderLi.querySelectorAll(".file-tree-folder").forEach((el) => {
    max = Math.max(max, +el.dataset.depth);
  });
  return max - +folderLi.dataset.depth;
}

function onDragStart(e) {
  const li = e.target.closest(".file-tree-note, .file-tree-folder");
  if (!li) return;
  const type = li.classList.contains("file-tree-folder") ? "folder" : "note";
  drag = {
    type,
    el: li,
    height: type === "folder" ? subtreeHeight(li) : 0,
    // "" = general tree; anything else = that matter's tree. Drops never
    // cross scopes (the server re-validates).
    matterId: li.dataset.matterId || "",
  };
  e.dataTransfer.setData(
    "text/plain",
    JSON.stringify({ type, id: li.dataset.folderId || li.dataset.noteId }),
  );
  e.dataTransfer.effectAllowed = "move";
  li.classList.add("dragging");
  // Reveal the pinned root dropzones for the duration of the drag
  document.getElementById("file-tree-container").classList.add("tree-dragging");
}

// Returns the folder li or root ul that would accept the current drag at
// this event's position, or null. The server re-validates every move; this
// only decides what the cursor and highlight promise.
function resolveDropTarget(e) {
  if (!drag) return null;

  const folderLi = e.target.closest(".file-tree-folder");
  if (folderLi) {
    if ((folderLi.dataset.matterId || "") !== drag.matterId) return null; // other tree
    if (drag.el === folderLi || drag.el.contains(folderLi)) return null; // self or own subtree
    if (drag.el.parentElement.closest(".file-tree-folder") === folderLi)
      return null; // current parent — a no-op move
    if (
      drag.type === "folder" &&
      +folderLi.dataset.depth + 1 + drag.height > MAX_DEPTH
    )
      return null;
    return folderLi;
  }

  // The pinned dropzone = the root of the dragged item's own scope
  // (general root for general items, its matter's root for matter items)
  const rootBar = e.target.closest(".tree-root-dropzone");
  if (rootBar) {
    if (!drag.el.parentElement.closest(".file-tree-folder")) return null; // already at its root
    return rootBar;
  }

  // A matter node = that matter's root (folder=None), same-matter items only
  const matterLi = e.target.closest(".file-tree-matter");
  if (matterLi) {
    if (matterLi.dataset.matterId !== drag.matterId) return null;
    if (
      drag.el.parentElement.closest(".file-tree-folder, .file-tree-matter") ===
      matterLi
    )
      return null; // already at this matter's root
    return matterLi;
  }

  const tree = e.target.closest(".file-tree");
  if (tree) {
    if (tree.classList.contains("matters-tree")) return null; // background isn't a target
    if (drag.matterId !== "") return null; // general root takes general items only
    if (drag.el.parentElement === tree) return null; // already at root
    return tree;
  }
  return null;
}

function highlightClass(target) {
  return target.classList.contains("file-tree") ? "drop-target-root" : "drop-target";
}

function setHighlight(target) {
  if (target === dropTarget) return;
  if (dropTarget) dropTarget.classList.remove(highlightClass(dropTarget));
  dropTarget = target;
  if (dropTarget) dropTarget.classList.add(highlightClass(dropTarget));

  // Dwelling over a collapsed folder reveals it (DOM-only: transient travel
  // expansion isn't persisted; the drop destination persists server-side).
  clearTimeout(hoverTimer);
  hoverEl = null;
  if (target && drag && target !== drag.el && target.classList.contains("collapsed")) {
    hoverEl = target;
    hoverTimer = setTimeout(() => hoverEl.classList.remove("collapsed"), HOVER_EXPAND_MS);
  }
}

function clearDropState() {
  setHighlight(null);
}

function onDragOver(e) {
  if (!drag) return;
  const target = resolveDropTarget(e);
  setHighlight(target);
  if (target) {
    // preventDefault only on valid targets, so the browser's no-drop cursor
    // signals invalid ones.
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }
}

function onDragLeave(e) {
  if (!e.relatedTarget || !e.currentTarget.contains(e.relatedTarget)) {
    clearDropState();
  }
}

async function onDrop(e) {
  const target = resolveDropTarget(e);
  if (!target || !drag) return;
  e.preventDefault();

  const isFolderTarget = target.classList.contains("file-tree-folder");
  const destination = isFolderTarget ? target.dataset.folderId : "";
  const url =
    drag.type === "note" ? drag.el.dataset.moveUrl : drag.el.dataset.reparentUrl;
  clearDropState();

  const resp = await fetch(url, {
    method: "POST",
    headers: { "X-CSRFToken": getCSRFToken() },
    body: new URLSearchParams({ destination }),
  });
  if (!resp.ok) return flashDropError(target, await resp.text());
  // Keep the destination open in this tab so the dropped item is visible
  // after the refresh (the server no longer tracks expansion)
  if (isFolderTarget) {
    setFolderExpanded(destination, true);
  } else if (target.classList.contains("file-tree-matter")) {
    setMatterExpanded(target.dataset.matterId, true);
  }
  refreshTree();
  broadcast({ type: "tree-changed" });
}

function onDragEnd() {
  if (drag) drag.el.classList.remove("dragging");
  drag = null;
  clearDropState();
  const container = document.getElementById("file-tree-container");
  if (container) container.classList.remove("tree-dragging");
}

// No toast library loads in the editor, so rejection feedback is a brief
// red flash on the target (the server's reason goes to the console).
function flashDropError(target, reason) {
  console.warn("Move rejected:", reason);
  target.classList.add("drop-error");
  setTimeout(() => target.classList.remove("drop-error"), DROP_ERROR_MS);
}

export function refreshTree() {
  const container = document.getElementById("file-tree-container");
  // The innerHTML swap resets every list's scroll; capture and restore so
  // a rename/create/delete doesn't bounce the panel to the top. List order
  // is stable (files tree, matter trees, recents). Restore on the swap
  // EVENT, not the ajax promise: when refreshTree is called from inside
  // an htmx trigger handler (noteCreated), the request gets queued behind
  // the busy body element and htmx resolves its promise immediately —
  // before any swap. The afterSwap listener registered at bind time
  // (applyTreeState) runs first, so heights are final when this restores.
  const scrolls = Array.from(container.querySelectorAll(".file-tree")).map(
    (el) => el.scrollTop,
  );
  container.addEventListener(
    "htmx:afterSwap",
    () => {
      container.querySelectorAll(".file-tree").forEach((el, i) => {
        if (scrolls[i]) el.scrollTop = scrolls[i];
      });
    },
    { once: true },
  );
  // htmx.ajax processes the swapped content, so the new note rows' hx-get
  // attributes keep working. NOTE_DATA is re-set on every content swap,
  // so the active pill follows the currently open note.
  window.htmx.ajax(
    "GET",
    `${container.dataset.refreshUrl}?note=${window.NOTE_DATA.id}`,
    { target: "#file-tree-container", swap: "innerHTML" },
  );
}
