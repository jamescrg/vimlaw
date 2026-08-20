/**
 * Prompt Editor - Lightweight TipTap editor for AI prompts
 * A simplified version of notes-editor.js focused on prompt composition
 */

// TipTap imports from local bundle (built with: npm run build)
import {
  Editor,
  Document,
  Paragraph,
  Text,
  Bold,
  Italic,
  Strike,
  Heading,
  BulletList,
  OrderedList,
  ListItem,
  Blockquote,
  HardBreak,
  History,
  Placeholder,
  Table,
  TableRow,
} from "./vendor/tiptap.bundle.js";

import { connectFormatToolbar } from "./format-toolbar.js";
import { HighlightMark } from "./highlight-mark.js";
import {
  NoteTableCell,
  NoteTableHeader,
  TableAutoRender,
} from "./notes/tables.js";
import { htmlToMarkdown } from "./notes/markdown.js";

let promptEditor = null;

/**
 * Initialize the prompt editor in the given container
 */
export function initPromptEditor(container) {
  if (promptEditor) {
    promptEditor.destroy();
  }

  promptEditor = new Editor({
    element: container,
    extensions: [
      Document,
      Paragraph,
      Text,
      Bold,
      Italic,
      Strike,
      Heading.configure({ levels: [1, 2, 3, 4, 5] }),
      BulletList,
      OrderedList,
      ListItem,
      Blockquote,
      HardBreak,
      History,
      HighlightMark.configure({ multicolor: true }),
      // Same table anatomy as the notes editor: no resizing or merging
      // (pipe markdown can't express either), column alignment rides the
      // extended cell types, and pasted pipe tables auto-render. The
      // serialized prompt reaches the model as a GFM pipe table.
      Table,
      TableRow,
      NoteTableHeader,
      NoteTableCell,
      TableAutoRender,
      Placeholder.configure({
        placeholder: "Compose your prompt here...",
      }),
    ],
    content: "",
  });

  // Wire the shared formatting toolbar to this editor instance
  const toolbar = document.querySelector(
    ".prompt-editor-toolbar .format-toolbar",
  );
  connectFormatToolbar(toolbar, promptEditor);

  // No table sub-toolbar here (that bar is the notes editor's); the table
  // button inserts directly. Tab walks the cells and grows the table at
  // the end (TipTap's Table keymap), which covers prompt-sized tables.
  const tableBtn = toolbar && toolbar.querySelector("[data-table-toggle]");
  if (tableBtn) {
    tableBtn.onclick = () =>
      promptEditor
        .chain()
        .focus()
        .insertTable({ rows: 3, cols: 3, withHeaderRow: true })
        .run();
    const syncTableBtn = () => {
      // No nested tables: insert flips off inside one
      tableBtn.disabled = promptEditor.isActive("table");
    };
    promptEditor.on("selectionUpdate", syncTableBtn);
    promptEditor.on("update", syncTableBtn);
    syncTableBtn();
  }

  return promptEditor;
}

/**
 * Get the current editor content as markdown
 */
export function getMarkdownContent() {
  if (!promptEditor) return "";
  const html = promptEditor.getHTML();
  return htmlToMarkdown(html);
}

/**
 * Get the current editor content as HTML
 */
export function getHtmlContent() {
  if (!promptEditor) return "";
  return promptEditor.getHTML();
}

/**
 * Set the editor content from HTML
 */
export function setHtmlContent(html) {
  if (!promptEditor) return;
  promptEditor.commands.setContent(html);
}

/**
 * Clear all editor content
 */
export function clearContent() {
  if (!promptEditor) return;
  promptEditor.commands.clearContent();
}

/**
 * Destroy the editor instance and clean up
 */
export function destroyPromptEditor() {
  if (promptEditor) {
    promptEditor.destroy();
    promptEditor = null;
  }
}

/**
 * Check if editor has content
 */
export function hasContent() {
  if (!promptEditor) return false;
  return !promptEditor.isEmpty;
}
