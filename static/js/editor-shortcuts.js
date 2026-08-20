// Shared keyboard shortcuts for the TipTap editing surfaces (notes editor,
// AI compose-prompt modal) — the formatting half of the shortcut map lives
// here so both surfaces speak it identically. Surface-specific actions
// (save, search, reference picker, shortcuts modal) arrive as callbacks;
// a shortcut whose action is absent falls through to the browser
// untouched. The caller owns the binding scope: the notes editor binds on
// document (its editor is the whole page), the prompt modal binds on the
// modal root so the listener dies with the modal.

const HEADING_KEYS = { 1: 1, 2: 2, 3: 3, 4: 4, 5: 5 };
const FKEY_HEADINGS = { F2: 2, F3: 3, F4: 4 };
// Letters are mnemonic; Alt+1-6 mirror the highlight menu's chip order
// left to right (Alt+` clears, matching the row's leftmost chip).
const HIGHLIGHT_COLORS = {
  y: null,
  g: "mark-green",
  r: "mark-red",
  p: "mark-purple",
  o: "mark-orange",
  a: "mark-gray",
  1: "mark-gray",
  2: null,
  3: "mark-green",
  4: "mark-red",
  5: "mark-purple",
  6: "mark-orange",
};

// Returns true when the event was handled (and defaultPrevented).
export function handleEditorShortcut(editor, e, actions = {}) {
  const mod = e.ctrlKey || e.metaKey;

  // Tab inside code blocks
  if (e.key === "Tab" && !mod && editor.isActive("codeBlock")) {
    e.preventDefault();
    if (e.shiftKey) {
      const { $from } = editor.state.selection;
      const lineStart = $from.pos - $from.parentOffset;
      const textBefore = editor.state.doc.textBetween(lineStart, $from.pos);
      let spacesToRemove = 0;
      for (let si = 0; si < 4 && si < textBefore.length; si++) {
        if (textBefore[textBefore.length - 1 - si] === " ") spacesToRemove++;
        else break;
      }
      if (spacesToRemove) {
        editor
          .chain()
          .focus()
          .deleteRange({ from: $from.pos - spacesToRemove, to: $from.pos })
          .run();
      }
    } else {
      editor.chain().focus().insertContent("    ").run();
    }
    return true;
  }

  // Save: Ctrl+S
  if (mod && e.key === "s" && actions.save) {
    e.preventDefault();
    actions.save();
    return true;
  }

  // Headings: Ctrl+1 through Ctrl+5
  if (mod && !e.shiftKey && HEADING_KEYS[e.key]) {
    e.preventDefault();
    editor.chain().focus().toggleHeading({ level: HEADING_KEYS[e.key] }).run();
    return true;
  }

  // Clear formatting: Ctrl+0
  if (mod && !e.shiftKey && e.key === "0") {
    e.preventDefault();
    editor.chain().focus().setParagraph().run();
    return true;
  }

  // F-key headings: F2, F3, F4
  if (FKEY_HEADINGS[e.key]) {
    e.preventDefault();
    editor.chain().focus().toggleHeading({ level: FKEY_HEADINGS[e.key] }).run();
    return true;
  }

  // F7 for bullet list
  if (e.key === "F7") {
    e.preventDefault();
    editor.chain().focus().toggleBulletList().run();
    return true;
  }

  // Bullet list: Ctrl+7
  if (mod && !e.shiftKey && e.key === "7") {
    e.preventDefault();
    editor.chain().focus().toggleBulletList().run();
    return true;
  }

  // Blockquote: Ctrl+8
  if (mod && !e.shiftKey && e.key === "8") {
    e.preventDefault();
    editor.chain().focus().toggleBlockquote().run();
    return true;
  }

  // Move list items: Ctrl+Up/Down
  if (mod && e.key === "ArrowUp" && editor.isActive("listItem")) {
    e.preventDefault();
    moveListItem(editor, "up");
    return true;
  }
  if (mod && e.key === "ArrowDown" && editor.isActive("listItem")) {
    e.preventDefault();
    moveListItem(editor, "down");
    return true;
  }

  // Delete block: Ctrl+Delete or Ctrl+D
  if (mod && (e.key === "Delete" || e.key === "d")) {
    e.preventDefault();
    editor.chain().focus().deleteNode("paragraph").run();
    return true;
  }

  // Insert source: Ctrl+;
  if (mod && e.key === ";" && actions.openReferences) {
    e.preventDefault();
    actions.openReferences();
    return true;
  }

  // Show shortcuts: Ctrl+?
  if (mod && e.key === "?" && actions.showShortcuts) {
    e.preventDefault();
    actions.showShortcuts();
    return true;
  }

  // Highlight shortcuts: Alt+key
  const lowerKey = e.key.toLowerCase();
  if (e.altKey && !mod && lowerKey in HIGHLIGHT_COLORS) {
    e.preventDefault();
    const color = HIGHLIGHT_COLORS[lowerKey];
    if (color) {
      editor.chain().focus().toggleHighlight({ color }).run();
    } else {
      editor.chain().focus().toggleHighlight().run();
    }
    return true;
  }

  // Remove highlight: Alt+C or Alt+`
  if (e.altKey && !mod && (lowerKey === "c" || e.key === "`")) {
    e.preventDefault();
    editor.chain().focus().unsetHighlight().run();
    return true;
  }

  // Search and replace: Ctrl+H
  if (mod && e.key === "h" && actions.toggleSearch) {
    e.preventDefault();
    actions.toggleSearch();
    return true;
  }

  return false;
}

// ─── List Item Reordering ────────────────────────────────────────────────────

export function moveListItem(editor, direction) {
  const { state: editorState, view } = editor;
  const { $from } = editorState.selection;

  let listItemPos = null;
  let listItemNode = null;
  let listItemDepth = null;

  for (let d = $from.depth; d > 0; d--) {
    if ($from.node(d).type.name === "listItem") {
      listItemPos = $from.before(d);
      listItemNode = $from.node(d);
      listItemDepth = d;
      break;
    }
  }

  if (!listItemNode || listItemPos === null) return;

  const parentList = $from.node(listItemDepth - 1);
  const indexInParent = $from.index(listItemDepth - 1);

  if (direction === "up" && indexInParent === 0) return;
  if (direction === "down" && indexInParent >= parentList.childCount - 1)
    return;

  const tr = editorState.tr;
  const listItemEnd = listItemPos + listItemNode.nodeSize;
  let newCursorPos;

  if (direction === "up") {
    const prevItemSize = parentList.child(indexInParent - 1).nodeSize;
    newCursorPos = $from.pos - prevItemSize;
    const slice = tr.doc.slice(listItemPos, listItemEnd);
    tr.delete(listItemPos, listItemEnd);
    tr.insert(listItemPos - prevItemSize, slice.content);
  } else {
    const nextItemSize = parentList.child(indexInParent + 1).nodeSize;
    newCursorPos = $from.pos + nextItemSize;
    const nextItemPos = listItemEnd;
    const nextSlice = tr.doc.slice(nextItemPos, nextItemPos + nextItemSize);
    tr.delete(nextItemPos, nextItemPos + nextItemSize);
    tr.insert(listItemPos, nextSlice.content);
  }

  tr.setSelection(
    editorState.selection.constructor.near(tr.doc.resolve(newCursorPos)),
  );
  view.dispatch(tr.scrollIntoView());
}
