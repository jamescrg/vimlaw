// Per-browser-tab navigation state for the notes editor.
//
// Tree expansion, the active left pane, and outline collapse are
// deliberately sessionStorage: each tab owns its navigation, so working
// in one tab never moves the tree under another (the server renders
// every node collapsed and knows nothing about expansion). A duplicated
// tab inherits a copy of the state; a fresh tab starts collapsed with
// the open note's ancestors revealed. Shared *preferences* (panel
// widths, collapsed panels) stay in localStorage elsewhere.

const KEY = "notes-tab-state";

function loadState() {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) {
      const s = JSON.parse(raw);
      return {
        expandedFolders: Array.isArray(s.expandedFolders)
          ? s.expandedFolders
          : [],
        expandedMatters: Array.isArray(s.expandedMatters)
          ? s.expandedMatters
          : [],
        pane: s.pane || null,
      };
    }
  } catch (e) {
    // fall through to a fresh default
  }
  return { expandedFolders: [], expandedMatters: [], pane: null };
}

function saveState(s) {
  sessionStorage.setItem(KEY, JSON.stringify(s));
}

function setInList(list, id, on) {
  const i = list.indexOf(id);
  if (on && i < 0) list.push(id);
  if (!on && i >= 0) list.splice(i, 1);
}

export function setFolderExpanded(id, on) {
  const s = loadState();
  setInList(s.expandedFolders, Number(id), on);
  saveState(s);
}

export function setMatterExpanded(id, on) {
  const s = loadState();
  setInList(s.expandedMatters, Number(id), on);
  saveState(s);
}

// Collapse/expand-all for one pane: bulk-write the pane's ids
export function setPaneExpansion(folderIds, matterIds, expand) {
  const s = loadState();
  folderIds.forEach((id) => setInList(s.expandedFolders, Number(id), expand));
  matterIds.forEach((id) => setInList(s.expandedMatters, Number(id), expand));
  saveState(s);
}

export function getPane() {
  return loadState().pane;
}

export function setPane(pane) {
  const s = loadState();
  s.pane = pane;
  saveState(s);
}

// Un-collapse the active note row's ancestor chain (DOM) and, when
// persist is set, remember those ids so the next tree refresh keeps the
// open note's path visible in this tab.
export function revealActiveNote(persist = true) {
  const container = document.getElementById("file-tree-container");
  if (!container) return;
  const s = persist ? loadState() : null;
  container.querySelectorAll(".file-tree-note.active").forEach((row) => {
    let node = row.parentElement.closest(
      ".file-tree-folder, .file-tree-matter",
    );
    while (node) {
      node.classList.remove("collapsed");
      if (s) {
        if (node.classList.contains("file-tree-matter")) {
          setInList(s.expandedMatters, Number(node.dataset.matterId), true);
        } else {
          setInList(s.expandedFolders, Number(node.dataset.folderId), true);
        }
      }
      node = node.parentElement.closest(".file-tree-folder, .file-tree-matter");
    }
  });
  if (s) saveState(s);
}

// Dress a freshly rendered (all-collapsed) tree in this tab's expansion
// state. Runs on load and synchronously inside the tree's htmx:afterSwap
// (before refreshTree's scroll restore, which needs final heights).
export function applyTreeState() {
  const container = document.getElementById("file-tree-container");
  if (!container) return;
  const s = loadState();
  const folders = new Set(s.expandedFolders);
  const matters = new Set(s.expandedMatters);
  container.querySelectorAll(".file-tree-folder").forEach((li) => {
    li.classList.toggle("collapsed", !folders.has(Number(li.dataset.folderId)));
  });
  container.querySelectorAll(".file-tree-matter").forEach((li) => {
    li.classList.toggle("collapsed", !matters.has(Number(li.dataset.matterId)));
  });
  revealActiveNote();
}
