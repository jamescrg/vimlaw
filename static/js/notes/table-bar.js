// Table sub-toolbar — a search-and-replace-style bar under the note toolbar,
// toggled by the format toolbar's table icon. Houses insert, row/column
// operations, per-column alignment, header toggle and delete. The bar
// element lives in editor.html and survives note switches; onclick
// assignment keeps rebinding idempotent when the editor rebuilds.

import { state } from "./state.js";
import {
  setColumnAlign,
  getColumnAlign,
  normalizeTableAligns,
} from "./tables.js";

const ALIGN_OPS = { alignLeft: "left", alignCenter: "center", alignRight: "right" };

const OPS = {
  insert: (e) =>
    e.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(),
  rowAbove: (e) => {
    e.chain().focus().addRowBefore().run();
    normalizeTableAligns(e);
  },
  rowBelow: (e) => {
    e.chain().focus().addRowAfter().run();
    normalizeTableAligns(e);
  },
  rowDelete: (e) => e.chain().focus().deleteRow().run(),
  colLeft: (e) => e.chain().focus().addColumnBefore().run(),
  colRight: (e) => e.chain().focus().addColumnAfter().run(),
  colDelete: (e) => e.chain().focus().deleteColumn().run(),
  headerRow: (e) => e.chain().focus().toggleHeaderRow().run(),
  deleteTable: (e) => e.chain().focus().deleteTable().run(),
};

function bar() {
  return document.getElementById("table-bar");
}

function toggleBtn() {
  return document.querySelector(".note-toolbar [data-table-toggle]");
}

function sync() {
  const el = bar();
  const editor = state.editor;
  if (!el || !editor) return;
  const inTable = editor.isActive("table");
  const align = inTable ? getColumnAlign(editor) : null;
  for (const btn of el.querySelectorAll("[data-tb]")) {
    const op = btn.dataset.tb;
    // No nested tables: insert flips off inside one, everything else on
    btn.disabled = op === "insert" ? inTable : !inTable;
    if (op in ALIGN_OPS) {
      btn.classList.toggle("active", inTable && align === ALIGN_OPS[op]);
    }
  }
}

export function toggleTableBar() {
  const el = bar();
  if (!el) return;
  const visible = el.classList.toggle("visible");
  const btn = toggleBtn();
  if (btn) btn.classList.toggle("active", visible);
  if (visible) sync();
}

export function hideTableBar() {
  const el = bar();
  if (el) el.classList.remove("visible");
  const btn = toggleBtn();
  if (btn) btn.classList.remove("active");
}

export function setupTableBar() {
  const el = bar();
  const btn = toggleBtn();
  if (!el || !btn) return;

  if (window.NOTE_DATA && window.NOTE_DATA.readOnly) {
    hideTableBar();
    return;
  }

  btn.onclick = () => toggleTableBar();

  for (const opBtn of el.querySelectorAll("[data-tb]")) {
    opBtn.onclick = () => {
      const editor = state.editor;
      if (!editor) return;
      const op = opBtn.dataset.tb;
      if (op in ALIGN_OPS) {
        // Alignment buttons toggle: clicking the active one clears back
        // to default (plain --- in the separator row)
        const next =
          getColumnAlign(editor) === ALIGN_OPS[op] ? null : ALIGN_OPS[op];
        setColumnAlign(editor, next);
        editor.commands.focus();
      } else if (OPS[op]) {
        OPS[op](editor);
      }
      sync();
    };
  }

  const closeBtn = document.getElementById("table-bar-close");
  if (closeBtn) closeBtn.onclick = () => hideTableBar();

  state.editor.on("selectionUpdate", sync);
  state.editor.on("update", sync);
  sync();
}
