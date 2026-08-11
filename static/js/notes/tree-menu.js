// Context menu for the editor's tree panes. Row types: folder (New note /
// New subfolder / Rename / Delete), matter (New note / New folder), note
// incl. recents (Properties / Delete). One shared floating menu
// (#tree-context-menu, same fixed-position idiom as #highlight-ref-dropdown),
// opened by right-click on a row or a folder/matter row's hover kebab.
// Modals reuse the Notes-tab forms with ?context=editor; their success
// responses fire noteFoldersChanged, which notes-editor.js turns into a
// tree refresh.

import { refreshTree } from "./file-tree.js";
import { getCSRFToken } from "./state.js";

const ROW_SELECTOR = ".file-tree-folder, .file-tree-matter, .file-tree-note";

let menu = null;
let targetLi = null; // the row the open menu acts on

export function setupTreeMenu() {
  const container = document.getElementById("file-tree-container");
  menu = document.getElementById("tree-context-menu");
  if (!container || !menu) return;

  container.addEventListener("contextmenu", (e) => {
    const li = e.target.closest(ROW_SELECTOR);
    if (!li) return;
    e.preventDefault();
    openMenu(li, e.clientX, e.clientY);
  });

  container.addEventListener("click", (e) => {
    const btn = e.target.closest(".file-tree-menu-btn");
    if (!btn) return;
    e.stopPropagation();
    const li = btn.closest(ROW_SELECTOR);
    const rect = btn.getBoundingClientRect();
    openMenu(li, rect.left, rect.bottom + 4);
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
  showItem("properties", isNote);
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
    const folderParam = li.dataset.folderId
      ? "&folder=" + li.dataset.folderId
      : "";
    openModal(li.dataset.noteAddUrl + "?context=editor" + folderParam);
  } else if (action === "new") {
    const scope = isMatter
      ? "matter=" + li.dataset.matterId
      : "parent=" + li.dataset.folderId;
    openModal(container.dataset.folderAddUrl + "?context=editor&" + scope);
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
