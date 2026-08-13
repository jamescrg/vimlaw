// Context menu for the editor's tree panes. Row types: folder (New note /
// New subfolder / Rename / Delete), matter (New note / New folder), note
// incl. recents (Properties / Delete). One shared floating menu
// (#tree-context-menu, same fixed-position idiom as #highlight-ref-dropdown),
// opened by right-click on a row or a folder/matter row's hover kebab.
// Modals reuse the Notes-tab forms with ?context=editor; their success
// responses fire noteFoldersChanged, which notes-editor.js turns into a
// tree refresh.

import { refreshTree } from "./file-tree.js";
import { broadcast } from "./broadcast.js";
import { getCSRFToken } from "./state.js";
import { setFolderExpanded, setMatterExpanded } from "./tab-state.js";

const ROW_SELECTOR = ".file-tree-folder, .file-tree-matter, .file-tree-note";

let menu = null;
let targetLi = null; // the row the open menu acts on

export function setupTreeMenu() {
  const container = document.getElementById("file-tree-container");
  menu = document.getElementById("tree-context-menu");
  if (!container || !menu) return;

  // Right-click is the sole trigger (no hover kebabs)
  container.addEventListener("contextmenu", (e) => {
    const li = e.target.closest(ROW_SELECTOR);
    if (!li) return;
    e.preventDefault();
    openMenu(li, e.clientX, e.clientY);
  });

  menu.addEventListener("click", (e) => {
    const item = e.target.closest("[data-action]");
    if (!item) return;
    e.preventDefault();
    runAction(item.dataset.action);
    closeMenu();
  });

  document.addEventListener("click", (e) => {
    if (!menu.contains(e.target)) closeMenu();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeMenu();
  });
  document.addEventListener("scroll", closeMenu, true);
}

function showItem(action, visible) {
  menu.querySelector(`[data-action=${action}]`).parentElement.style.display =
    visible ? "" : "none";
}

function openMenu(li, x, y) {
  targetLi = li;
  const isMatter = li.classList.contains("file-tree-matter");
  const isFolder = li.classList.contains("file-tree-folder");
  const isNote = !isMatter && !isFolder;
  const atDepthCap = isFolder && +li.dataset.depth >= 3;

  showItem("new-note", !isNote);
  showItem("new", !isNote && !atDepthCap);
  if (!isNote) {
    menu.querySelector("[data-action=new] [data-label]").textContent = isMatter
      ? "New folder"
      : "New subfolder";
  }
  // Properties = matter re-assignment, so matter notes only
  showItem("properties", isNote && !!li.dataset.propertiesUrl);
  showItem("rename", isFolder);
  showItem("delete", isFolder);
  showItem("delete-note", isNote);

  menu.style.position = "fixed";
  menu.style.left = x + "px";
  menu.style.top = y + "px";
  menu.classList.add("show");
}

function closeMenu() {
  if (menu) menu.classList.remove("show");
  targetLi = null;
}

function openModal(url) {
  window.htmx.ajax("GET", url, {
    target: "#htmx-modal-container",
    swap: "innerHTML",
  });
}

function deleteNote(li) {
  if (!confirm("Delete this note?")) return;
  const container = document.getElementById("file-tree-container");
  const deletedOpenNote = li.dataset.noteId === String(window.NOTE_DATA.id);
  fetch(li.dataset.deleteUrl, {
    method: "POST",
    headers: { "X-CSRFToken": getCSRFToken() },
  }).then((resp) => {
    if (!resp.ok) return;
    broadcast({ type: "note-deleted", noteId: Number(li.dataset.noteId) });
    broadcast({ type: "tree-changed" });
    if (deletedOpenNote) {
      // The open document is gone; land on the most recent surviving note
      window.location.assign(container.dataset.launchUrl);
    } else {
      refreshTree();
    }
  });
}

function runAction(action) {
  if (!targetLi) return;
  const li = targetLi;
  const container = document.getElementById("file-tree-container");
  const noteParam = "&note=" + window.NOTE_DATA.id;
  const isMatter = li.classList.contains("file-tree-matter");

  if (action === "new-note") {
    // Instant creation: an Untitled note in this folder/matter root; the
    // noteCreated trigger opens it in place. Persist the target's
    // expansion FIRST so the refreshed tree shows the new note's home.
    if (li.dataset.folderId) setFolderExpanded(li.dataset.folderId, true);
    if (isMatter) setMatterExpanded(li.dataset.matterId, true);
    const folderParam = li.dataset.folderId
      ? "?folder=" + li.dataset.folderId
      : "";
    window.htmx.ajax("POST", li.dataset.noteAddUrl + folderParam, {
      swap: "none",
    });
  } else if (action === "new") {
    // Instant creation: an Untitled folder here; rename via this menu.
    // Keep the parent open so the new child is visible after the refresh.
    if (isMatter) {
      setMatterExpanded(li.dataset.matterId, true);
    } else {
      setFolderExpanded(li.dataset.folderId, true);
    }
    const scope = isMatter
      ? "matter=" + li.dataset.matterId
      : "parent=" + li.dataset.folderId;
    window.htmx.ajax("POST", container.dataset.folderAddUrl + "?" + scope, {
      swap: "none",
    });
  } else if (action === "properties") {
    openModal(li.dataset.propertiesUrl);
  } else if (action === "rename") {
    openModal(li.dataset.editUrl + "?context=editor" + noteParam);
  } else if (action === "delete") {
    openModal(li.dataset.deleteUrl + "?context=editor" + noteParam);
  } else if (action === "delete-note") {
    deleteNote(li);
  }
}
