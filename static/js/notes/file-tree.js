// Files tab — folder toggle + drag-and-drop re-parenting for the standalone
// notes editor. All events are delegated to #file-tree-container (a stable
// element) so bindings survive the htmx innerHTML refresh of the tree that
// follows every move.

import { getCSRFToken } from "./state.js";

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
  if (!container || !container.querySelector(".file-tree")) return; // matter editor: flat list
  if (container.dataset.treeBound) return;
  container.dataset.treeBound = "1";

  container.addEventListener("click", onClick);
  container.addEventListener("dragstart", onDragStart);
  container.addEventListener("dragend", onDragEnd);
  container.addEventListener("dragover", onDragOver);
  container.addEventListener("dragleave", onDragLeave);
  container.addEventListener("drop", onDrop);
}

// ─── Expand/collapse ─────────────────────────────────────────────────────────

function onClick(e) {
  const handle = e.target.closest(".file-tree-toggle, .file-tree-name");
  if (!handle) return;
  const li = handle.closest(".file-tree-item");
  if (!li || !li.classList.contains("file-tree-folder")) return; // note clicks fall through to hx-get

  e.stopPropagation();
  li.classList.toggle("collapsed");
  // Fire-and-forget: expand state lives in the session, shared with the
  // Notes tab's folder sidebar (endpoint returns 204).
  fetch(li.dataset.toggleUrl, {
    method: "POST",
    headers: { "X-CSRFToken": getCSRFToken() },
  });
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
  drag = { type, el: li, height: type === "folder" ? subtreeHeight(li) : 0 };
  e.dataTransfer.setData(
    "text/plain",
    JSON.stringify({ type, id: li.dataset.folderId || li.dataset.noteId }),
  );
  e.dataTransfer.effectAllowed = "move";
  li.classList.add("dragging");
}

// Returns the folder li or root ul that would accept the current drag at
// this event's position, or null. The server re-validates every move; this
// only decides what the cursor and highlight promise.
function resolveDropTarget(e) {
  if (!drag) return null;

  const folderLi = e.target.closest(".file-tree-folder");
  if (folderLi) {
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

  const tree = e.target.closest(".file-tree");
  if (tree) {
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
  refreshTree();
}

function onDragEnd() {
  if (drag) drag.el.classList.remove("dragging");
  drag = null;
  clearDropState();
}

// No toast library loads in the editor, so rejection feedback is a brief
// red flash on the target (the server's reason goes to the console).
function flashDropError(target, reason) {
  console.warn("Move rejected:", reason);
  target.classList.add("drop-error");
  setTimeout(() => target.classList.remove("drop-error"), DROP_ERROR_MS);
}

function refreshTree() {
  const container = document.getElementById("file-tree-container");
  // htmx.ajax processes the swapped content, so the new note rows' hx-get
  // attributes keep working. NOTE_DATA is re-set on every content swap,
  // so the active pill follows the currently open note.
  window.htmx.ajax(
    "GET",
    `${container.dataset.refreshUrl}?note=${window.NOTE_DATA.id}`,
    { target: "#file-tree-container", swap: "innerHTML" },
  );
}
