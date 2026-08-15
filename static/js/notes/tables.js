// Table auto-render for the notes editor.
//
// Two paths turn pipe-table markdown into a real table while editing (stored
// markdown already renders via markdownToHtml on load):
//  - Typing: a pipe row followed by a separator row (| --- | --- |) converts
//    on Enter into a table with a header row and one empty body row.
//  - Pasting: plain text containing a pipe table is treated as markdown and
//    converted wholesale (a table paste is a markdown paste in practice).

import {
  Extension,
  Plugin,
  PluginKey,
  TableCell,
  TableHeader,
  TableMap,
} from "../vendor/tiptap.bundle.js";
import {
  isPipeRow,
  isTableSeparator,
  splitPipeRow,
  buildTableHtml,
  markdownToHtml,
} from "./markdown.js";

// Per-cell alignment attribute. It renders as an inline text-align and
// serializes to the separator row's colons — alignment is per COLUMN in
// pipe markdown, so setColumnAlign below always stamps a full column.
const alignAttribute = {
  align: {
    default: null,
    parseHTML: (el) => el.style.textAlign || null,
    renderHTML: (attrs) =>
      attrs.align ? { style: "text-align: " + attrs.align } : {},
  },
};

export const NoteTableCell = TableCell.extend({
  addAttributes() {
    return { ...this.parent?.(), ...alignAttribute };
  },
});

export const NoteTableHeader = TableHeader.extend({
  addAttributes() {
    return { ...this.parent?.(), ...alignAttribute };
  },
});

// Locate the table and current column from the selection; null outside one
function currentColumn(state) {
  const { $from } = state.selection;
  for (let d = $from.depth; d > 0; d--) {
    const name = $from.node(d).type.name;
    if (name === "tableCell" || name === "tableHeader") {
      const table = $from.node(d - 2);
      const tableStart = $from.start(d - 2);
      const map = TableMap.get(table);
      const rect = map.findCell($from.before(d) - tableStart);
      return { table, tableStart, map, col: rect.left };
    }
  }
  return null;
}

// Stamp align onto every cell of the caret's column (null clears)
export function setColumnAlign(editor, align) {
  const loc = currentColumn(editor.state);
  if (!loc) return false;
  const { table, tableStart, map, col } = loc;
  let tr = editor.state.tr;
  for (let row = 0; row < map.height; row++) {
    const pos = map.map[row * map.width + col];
    const cell = table.nodeAt(pos);
    tr = tr.setNodeMarkup(tableStart + pos, null, {
      ...cell.attrs,
      align: align || null,
    });
  }
  editor.view.dispatch(tr);
  return true;
}

// Re-stamp every column's alignment from its header cell — freshly added
// rows are born with null cells, and pipe markdown treats alignment as a
// column property, so the header is the source of truth.
export function normalizeTableAligns(editor) {
  const loc = currentColumn(editor.state);
  if (!loc) return;
  const { table, tableStart, map } = loc;
  let tr = editor.state.tr;
  let changed = false;
  for (let col = 0; col < map.width; col++) {
    const align = table.nodeAt(map.map[col]).attrs.align || null;
    for (let row = 1; row < map.height; row++) {
      const pos = map.map[row * map.width + col];
      const cell = table.nodeAt(pos);
      if ((cell.attrs.align || null) !== align) {
        tr = tr.setNodeMarkup(tableStart + pos, null, {
          ...cell.attrs,
          align,
        });
        changed = true;
      }
    }
  }
  if (changed) editor.view.dispatch(tr);
}

export function getColumnAlign(editor) {
  const loc = currentColumn(editor.state);
  if (!loc) return null;
  const { table, map, col } = loc;
  return table.nodeAt(map.map[col]).attrs.align || null;
}

function textHasPipeTable(text) {
  const lines = text.split(/\r?\n/);
  for (let i = 0; i + 1 < lines.length; i++) {
    if (isPipeRow(lines[i].trim()) && isTableSeparator(lines[i + 1].trim())) {
      return true;
    }
  }
  return false;
}

export const TableAutoRender = Extension.create({
  name: "tableAutoRender",

  addKeyboardShortcuts() {
    return {
      Enter: () => {
        const editor = this.editor;
        if (editor.isActive("table") || editor.isActive("codeBlock")) {
          return false;
        }
        const { $from, empty } = editor.state.selection;
        if (!empty || $from.parent.type.name !== "paragraph") return false;
        // Only convert when the separator row is complete (caret at its end)
        if ($from.parentOffset !== $from.parent.content.size) return false;
        if (!isTableSeparator($from.parent.textContent.trim())) return false;

        const depth = $from.depth;
        const index = $from.index(depth - 1);
        if (index === 0) return false;
        const prev = $from.node(depth - 1).child(index - 1);
        if (prev.type.name !== "paragraph") return false;
        const headText = prev.textContent.trim();
        if (!isPipeRow(headText)) return false;

        const header = splitPipeRow(headText);
        const html = buildTableHtml(header, [header.map(() => "")]);
        const from = $from.before(depth) - prev.nodeSize;
        const to = $from.after(depth);
        editor
          .chain()
          .deleteRange({ from, to })
          .insertContentAt(from, html)
          .run();

        // Drop the caret into the first body cell
        const table = editor.state.doc.nodeAt(from);
        if (table && table.type.name === "table" && table.childCount > 1) {
          editor.commands.setTextSelection(from + table.child(0).nodeSize + 4);
        }
        editor.commands.focus();
        return true;
      },
    };
  },

  addProseMirrorPlugins() {
    const editor = this.editor;
    return [
      new Plugin({
        key: new PluginKey("tableMarkdownPaste"),
        props: {
          handlePaste(view, event) {
            const clipboard = event.clipboardData;
            if (!clipboard) return false;
            // Rich pastes (real HTML tables included) already work natively
            if (clipboard.getData("text/html")) return false;
            if (editor.isActive("table") || editor.isActive("codeBlock")) {
              return false;
            }
            const text = clipboard.getData("text/plain") || "";
            if (!textHasPipeTable(text)) return false;
            editor.commands.insertContent(markdownToHtml(text));
            return true;
          },
        },
      }),
    ];
  },
});
