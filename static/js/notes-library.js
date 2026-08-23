// Library tab (Notes): drag-and-drop + right-click menus over the folder
// sidebar and the notes table. A library-specific layer on purpose: the
// editor's tree is a navigator (click opens), this sidebar is a filter for
// the table, so the two share server endpoints and validation
// (notes:folder-reparent, notes:note-move, notes:bulk-move) but not UI code.
//
// - Sidebar folder rows drag onto folder rows (re-parent) or the Inbox row
//   (to root); table rows drag onto folder rows / Inbox (move; a selected
//   row drags the whole selection through bulk-move).
// - Right-click on a folder row, the Inbox row or a table row opens that
//   row's own dropdown (Alpine dropdown().openAt) at the cursor, so the
//   menu IS the kebab / title menu: same items, same modals.
// - Both panes re-fetch themselves: the sidebar on noteFoldersChanged, the
//   table on notesChanged.
//
// Listeners are delegated to #note-folders and #notes (stable elements) so
// they survive the htmx innerHTML refreshes.

(function () {
  const MAX_DEPTH = 3; // 0-based; 4 levels, mirrors NoteFolder's cap
  const HOVER_EXPAND_MS = 600;
  const DROP_ERROR_MS = 1200;
  const FOLDER_ROW = "li.folder-item-container[data-folder-id]";
  const NOTE_ROW = "tr[data-note-id]";

  // dataTransfer is unreadable during dragover, so live validation works
  // off this record instead
  let drag = null; // { type: "folder"|"note", el, url, parentId, folderId, height, bulk }
  let dropTarget = null;
  let hoverTimer = null;

  function csrfToken() {
    try {
      return JSON.parse(document.body.getAttribute("hx-headers"))[
        "X-CSRFToken"
      ];
    } catch (e) {
      return "";
    }
  }

  // ─── Right-click → the row's own dropdown at the cursor ─────────────────

  function onContextMenu(e) {
    const row = e.target.closest("li.folder-item-container, " + NOTE_ROW);
    if (!row) return;
    const dropdown = row.querySelector(".dropdown");
    if (!dropdown || !window.Alpine) return; // e.g. the All Folders row
    e.preventDefault();
    window.Alpine.$data(dropdown).openAt(e.clientX, e.clientY);
  }

  // "New note" menu items: create in the editor in a new tab — a plain
  // form post with target=_blank (the browser opens the redirect there),
  // submitted inside the click so popup blockers allow it. This tab's
  // table catches up when it is next visible.
  function onPostOpenClick(e) {
    const item = e.target.closest("[data-post-open]");
    if (!item) return;
    e.preventDefault();
    const form = document.createElement("form");
    form.method = "post";
    form.action = item.dataset.postOpen;
    form.target = "_blank";
    form.style.display = "none";
    const token = document.createElement("input");
    token.type = "hidden";
    token.name = "csrfmiddlewaretoken";
    token.value = csrfToken();
    form.appendChild(token);
    document.body.appendChild(form);
    form.submit();
    form.remove();
  }

  // ─── Drag and drop ──────────────────────────────────────────────────────

  // Depth of the deepest descendant row minus the folder's own depth
  // (folder rows are a flat DFS list linked by data-parent-id)
  function subtreeHeight(row) {
    const own = +row.dataset.depth;
    let max = own;
    getNoteFolderDescendantIds(row.dataset.folderId).forEach((id) => {
      const el = document.getElementById(`note-folder-${id}`);
      if (el) max = Math.max(max, +el.dataset.depth);
    });
    return max - own;
  }

  function onDragStart(e) {
    const row = e.target.closest(FOLDER_ROW + ", " + NOTE_ROW);
    if (!row) return;
    if (row.matches(NOTE_ROW)) {
      // A selected row drags the whole selection (the table carries the
      // bulk-move URL)
      const table = row.closest("[data-bulk-move-url]");
      const bulk = !!(table && row.querySelector(".icon-square-check"));
      drag = {
        type: "note",
        el: row,
        url: bulk ? table.dataset.bulkMoveUrl : row.dataset.moveUrl,
        parentId: row.dataset.folderId || "root",
        bulk,
      };
    } else {
      drag = {
        type: "folder",
        el: row,
        url: row.dataset.reparentUrl,
        parentId: row.dataset.parentId, // "root" at the top level
        folderId: row.dataset.folderId,
        height: subtreeHeight(row),
        bulk: false,
      };
    }
    e.dataTransfer.setData("text/plain", drag.type + ":" + row.id);
    e.dataTransfer.effectAllowed = "move";
    row.classList.add("dragging");
  }

  // The sidebar row that would accept the current drag at this event's
  // position, or null. The server re-validates every move; this only
  // decides what the cursor and highlight promise.
  function resolveDropTarget(e) {
    if (!drag) return null;
    const row = e.target.closest("#note-folders li.folder-item-container");
    if (!row) return null;
    const atRoot = !drag.bulk && drag.parentId === "root";
    if (row.dataset.root) return atRoot ? null : row; // Inbox = root
    const id = row.dataset.folderId;
    if (!id) return null; // All Folders
    if (drag.type === "folder") {
      if (id === drag.folderId) return null; // itself
      if (getNoteFolderDescendantIds(drag.folderId).includes(id)) return null; // own subtree
      if (+row.dataset.depth + 1 + drag.height > MAX_DEPTH) return null;
    }
    if (!drag.bulk && drag.parentId === id) return null; // already here
    return row;
  }

  function setHighlight(target) {
    if (target === dropTarget) return;
    if (dropTarget) dropTarget.classList.remove("drop-target");
    dropTarget = target;
    if (dropTarget) dropTarget.classList.add("drop-target");
    // Dwelling over a collapsed folder opens it (through the caret, so the
    // session-kept expansion follows)
    clearTimeout(hoverTimer);
    if (!target || !target.dataset.folderId) return;
    const caret = target.querySelector(".folder-caret .icon-chevron-right");
    if (!caret) return;
    hoverTimer = setTimeout(() => {
      toggleNoteFolder(target.dataset.folderId, {
        preventDefault() {},
        stopPropagation() {},
      });
    }, HOVER_EXPAND_MS);
  }

  function onDragOver(e) {
    if (!drag) return;
    const target = resolveDropTarget(e);
    setHighlight(target);
    if (target) {
      // preventDefault only on valid targets, so the browser's no-drop
      // cursor signals invalid ones
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
    }
  }

  function onDragLeave(e) {
    if (!e.relatedTarget || !e.currentTarget.contains(e.relatedTarget)) {
      setHighlight(null);
    }
  }

  async function onDrop(e) {
    const target = resolveDropTarget(e);
    if (!target || !drag) return;
    e.preventDefault();
    const destination = target.dataset.root ? "" : target.dataset.folderId;
    const { url, type } = drag;
    setHighlight(null);

    const resp = await fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken() },
      body: new URLSearchParams({ destination }),
    });
    if (!resp.ok) return flashDropError(target, await resp.text());
    // Folder moves re-render the sidebar (and the table: a suffixed name
    // may head it); note moves re-render the table
    if (type === "folder")
      window.htmx.trigger(document.body, "noteFoldersChanged");
    window.htmx.trigger(document.body, "notesChanged");
  }

  function onDragEnd() {
    if (drag) drag.el.classList.remove("dragging");
    drag = null;
    setHighlight(null);
  }

  // Rejected drop: brief red flash on the target (the server's reason goes
  // to the console)
  function flashDropError(target, reason) {
    console.warn("Move rejected:", reason);
    target.classList.add("drop-error");
    setTimeout(() => target.classList.remove("drop-error"), DROP_ERROR_MS);
  }

  // ─── Wiring ─────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", () => {
    const sidebar = document.getElementById("note-folders");
    const table = document.getElementById("notes");
    if (!sidebar || !table) return;

    [sidebar, table].forEach((el) => {
      el.addEventListener("contextmenu", onContextMenu);
      el.addEventListener("dragstart", onDragStart);
      el.addEventListener("dragend", onDragEnd);
    });
    sidebar.addEventListener("dragover", onDragOver);
    sidebar.addEventListener("dragleave", onDragLeave);
    sidebar.addEventListener("drop", onDrop);
    document.addEventListener("click", onPostOpenClick);
  });
})();
