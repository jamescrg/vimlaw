// Table auto-render for the notes editor.
//
// Two paths turn pipe-table markdown into a real table while editing (stored
// markdown already renders via markdownToHtml on load):
//  - Typing: a pipe row followed by a separator row (| --- | --- |) converts
//    on Enter into a table with a header row and one empty body row.
//  - Pasting: plain text containing a pipe table is treated as markdown and
//    converted wholesale (a table paste is a markdown paste in practice).

import { Extension, Plugin, PluginKey } from "../vendor/tiptap.bundle.js";
import {
  isPipeRow,
  isTableSeparator,
  splitPipeRow,
  buildTableHtml,
  markdownToHtml,
} from "./markdown.js";

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
