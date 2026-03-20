// Notes editor — main entry point
// Orchestrates init, toolbar, keyboard shortcuts, panels, HTMX, and import/export

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
  Code,
  CodeBlockLowlight,
  HorizontalRule,
  lowlightAll,
  createLowlight,
  HardBreak,
  History,
  Dropcursor,
  Gapcursor,
  Highlight,
} from "./vendor/tiptap.bundle.js";

import { state, getCSRFToken, bindClick } from "./notes/state.js";
import { markdownToHtml } from "./notes/markdown.js";
import {
  getMarkdownContent,
  scheduleAutosave,
  performAutosave,
} from "./notes/autosave.js";
import {
  SearchHighlight,
  setupSearchBar,
  toggleSearchBar,
} from "./notes/search.js";
import {
  NoteRef,
  setupReferenceClicks,
  refreshReferenceCitations,
  setupReferencePicker,
  openReferencePicker,
} from "./notes/references.js";
import {
  buildOutline,
  scheduleOutlineUpdate,
  setupOutlineCollapseAll,
} from "./notes/outline.js";

// ─── Code Block Language Selector ────────────────────────────────────────────

const CODE_LANGUAGES = [
  "bash",
  "css",
  "go",
  "html",
  "java",
  "javascript",
  "json",
  "markdown",
  "python",
  "rust",
  "sql",
  "typescript",
  "xml",
  "yaml",
];

function setupCodeBlockLangSelector() {
  state.langSelector = document.createElement("select");
  state.langSelector.id = "code-lang-selector";

  const autoOpt = document.createElement("option");
  autoOpt.value = "";
  autoOpt.textContent = "auto";
  state.langSelector.appendChild(autoOpt);

  for (const lang of CODE_LANGUAGES) {
    const opt = document.createElement("option");
    opt.value = lang;
    opt.textContent = lang;
    state.langSelector.appendChild(opt);
  }

  state.langSelector.addEventListener("change", () => {
    state.editor
      .chain()
      .focus()
      .updateAttributes("codeBlock", {
        language: state.langSelector.value || null,
      })
      .run();
  });

  state.langSelector.addEventListener("mousedown", (e) => e.stopPropagation());

  const container = document.querySelector(".note-page");
  if (container) {
    container.style.position = "relative";
    container.appendChild(state.langSelector);
  }
}

function updateCodeBlockLangSelector() {
  if (!state.langSelector) return;

  const { $from } = state.editor.state.selection;
  let codeBlockNode = null;
  let codeBlockPos = null;

  for (let depth = $from.depth; depth >= 0; depth--) {
    const node = $from.node(depth);
    if (node.type.name === "codeBlock") {
      codeBlockNode = node;
      codeBlockPos = $from.start(depth) - 1;
      break;
    }
  }

  if (!codeBlockNode) {
    state.langSelector.style.display = "none";
    return;
  }

  const dom = state.editor.view.nodeDOM(codeBlockPos);
  if (!dom || dom.tagName !== "PRE") {
    state.langSelector.style.display = "none";
    return;
  }

  const container = state.langSelector.parentElement;
  if (!container) return;

  const containerRect = container.getBoundingClientRect();
  const preRect = dom.getBoundingClientRect();

  state.langSelector.style.display = "block";
  state.langSelector.style.top =
    preRect.top - containerRect.top + container.scrollTop + 6 + "px";
  state.langSelector.style.right =
    containerRect.right - preRect.right + 8 + "px";
  state.langSelector.value = codeBlockNode.attrs.language || "";
}

// ─── Editor Init ─────────────────────────────────────────────────────────────

function initEditor() {
  const container = document.getElementById("note-editor");
  if (!container || !window.NOTE_DATA) return;

  const initialContent = markdownToHtml(window.NOTE_DATA.content || "");

  state.editor = new Editor({
    element: container,
    extensions: [
      Document,
      Paragraph,
      Text,
      Bold,
      Italic.extend({
        addKeyboardShortcuts() {
          return {
            "Mod-i": ({ editor: ed, event }) => {
              if (event && event.shiftKey) return false;
              return ed.commands.toggleItalic();
            },
          };
        },
      }),
      Strike,
      Heading.configure({ levels: [1, 2, 3, 4, 5] }),
      BulletList,
      OrderedList,
      ListItem,
      Blockquote,
      HardBreak,
      History,
      Dropcursor,
      Gapcursor,
      Highlight.configure({ multicolor: true }),
      Code,
      CodeBlockLowlight.configure({ lowlight: createLowlight(lowlightAll) }),
      HorizontalRule,
      NoteRef,
      SearchHighlight,
    ],
    content: initialContent,
    autofocus: true,
    onUpdate() {
      scheduleAutosave();
      scheduleOutlineUpdate();
    },
    onSelectionUpdate() {
      updateCodeBlockLangSelector();
    },
  });

  state.lastSavedContent = getMarkdownContent();
  setupCodeBlockLangSelector();
  setupToolbar();
  setupKeyboardShortcuts();
  setupReferencePicker();
  setupReferenceClicks();
  setupTitleEdit();
  setupSearchBar();
  setupImportExport();
  refreshReferenceCitations();
  buildOutline();
}

// ─── Title Edit ──────────────────────────────────────────────────────────────

function setupTitleEdit() {
  const input = document.getElementById("note-title");
  if (!input) return;

  let originalTitle = input.value;

  input.addEventListener("blur", () => {
    const newTitle = input.value.trim();
    if (!newTitle) {
      input.value = originalTitle;
      return;
    }
    if (newTitle === originalTitle) return;

    const formData = new FormData();
    formData.append("title", newTitle);

    fetch(window.NOTE_DATA.titleUrl, {
      method: "POST",
      headers: { "X-CSRFToken": getCSRFToken() },
      body: formData,
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.saved) {
          originalTitle = data.title;
          input.value = data.title;
        } else {
          input.value = originalTitle;
        }
      })
      .catch(() => {
        input.value = originalTitle;
      });
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      input.blur();
    } else if (e.key === "Escape") {
      e.preventDefault();
      input.value = originalTitle;
      input.blur();
    }
  });
}

// ─── Toolbar ─────────────────────────────────────────────────────────────────

function setupToolbar() {
  const toolbarActions = {
    "btn-bold": () => state.editor.chain().focus().toggleBold().run(),
    "btn-italic": () => state.editor.chain().focus().toggleItalic().run(),
    "btn-strike": () => state.editor.chain().focus().toggleStrike().run(),
    "btn-heading-1": () =>
      state.editor.chain().focus().toggleHeading({ level: 1 }).run(),
    "btn-heading-2": () =>
      state.editor.chain().focus().toggleHeading({ level: 2 }).run(),
    "btn-heading-3": () =>
      state.editor.chain().focus().toggleHeading({ level: 3 }).run(),
    "btn-bullet-list": () =>
      state.editor.chain().focus().toggleBulletList().run(),
    "btn-ordered-list": () =>
      state.editor.chain().focus().toggleOrderedList().run(),
    "btn-blockquote": () =>
      state.editor.chain().focus().toggleBlockquote().run(),
  };

  for (const [id, handler] of Object.entries(toolbarActions)) {
    bindClick(id, handler);
  }

  bindClick("insert-source-btn", (e) => {
    e.preventDefault();
    openReferencePicker();
  });
}

// ─── Keyboard Shortcuts ──────────────────────────────────────────────────────

function setupKeyboardShortcuts() {
  const HEADING_KEYS = { 1: 1, 2: 2, 3: 3, 4: 4, 5: 5 };
  const FKEY_HEADINGS = { F2: 2, F3: 3, F4: 4 };
  const HIGHLIGHT_COLORS = {
    y: null,
    g: "mark-green",
    r: "mark-red",
    p: "mark-purple",
    o: "mark-orange",
    a: "mark-gray",
  };

  document.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;

    // Tab inside code blocks
    if (e.key === "Tab" && !mod && state.editor.isActive("codeBlock")) {
      e.preventDefault();
      if (e.shiftKey) {
        const { $from } = state.editor.state.selection;
        const lineStart = $from.pos - $from.parentOffset;
        const textBefore = state.editor.state.doc.textBetween(
          lineStart,
          $from.pos,
        );
        let spacesToRemove = 0;
        for (let si = 0; si < 4 && si < textBefore.length; si++) {
          if (textBefore[textBefore.length - 1 - si] === " ") spacesToRemove++;
          else break;
        }
        if (spacesToRemove) {
          state.editor
            .chain()
            .focus()
            .deleteRange({ from: $from.pos - spacesToRemove, to: $from.pos })
            .run();
        }
      } else {
        state.editor.chain().focus().insertContent("    ").run();
      }
      return;
    }

    // Save: Ctrl+S
    if (mod && e.key === "s") {
      e.preventDefault();
      if (state.autosaveTimer) clearTimeout(state.autosaveTimer);
      performAutosave();
      return;
    }

    // Headings: Ctrl+1 through Ctrl+5
    if (mod && !e.shiftKey && HEADING_KEYS[e.key]) {
      e.preventDefault();
      state.editor
        .chain()
        .focus()
        .toggleHeading({ level: HEADING_KEYS[e.key] })
        .run();
      return;
    }

    // Clear formatting: Ctrl+0
    if (mod && !e.shiftKey && e.key === "0") {
      e.preventDefault();
      state.editor.chain().focus().setParagraph().run();
      return;
    }

    // F-key headings: F2, F3, F4
    if (FKEY_HEADINGS[e.key]) {
      e.preventDefault();
      state.editor
        .chain()
        .focus()
        .toggleHeading({ level: FKEY_HEADINGS[e.key] })
        .run();
      return;
    }

    // F7 for bullet list
    if (e.key === "F7") {
      e.preventDefault();
      state.editor.chain().focus().toggleBulletList().run();
      return;
    }

    // Bullet list: Ctrl+7
    if (mod && !e.shiftKey && e.key === "7") {
      e.preventDefault();
      state.editor.chain().focus().toggleBulletList().run();
      return;
    }

    // Blockquote: Ctrl+8
    if (mod && !e.shiftKey && e.key === "8") {
      e.preventDefault();
      state.editor.chain().focus().toggleBlockquote().run();
      return;
    }

    // Move list items: Ctrl+Up/Down
    if (mod && e.key === "ArrowUp" && state.editor.isActive("listItem")) {
      e.preventDefault();
      moveListItem("up");
      return;
    }
    if (mod && e.key === "ArrowDown" && state.editor.isActive("listItem")) {
      e.preventDefault();
      moveListItem("down");
      return;
    }

    // Delete block: Ctrl+Delete or Ctrl+D
    if (mod && (e.key === "Delete" || e.key === "d")) {
      e.preventDefault();
      state.editor.chain().focus().deleteNode("paragraph").run();
      return;
    }

    // Insert source: Ctrl+;
    if (mod && e.key === ";") {
      e.preventDefault();
      openReferencePicker();
      return;
    }

    // Show shortcuts: Ctrl+?
    if (mod && e.key === "?") {
      e.preventDefault();
      const btn = document.querySelector('[title="Keyboard shortcuts"]');
      if (btn) btn.click();
      return;
    }

    // Highlight shortcuts: Alt+key
    const lowerKey = e.key.toLowerCase();
    if (e.altKey && !mod && lowerKey in HIGHLIGHT_COLORS) {
      e.preventDefault();
      const color = HIGHLIGHT_COLORS[lowerKey];
      if (color) {
        state.editor.chain().focus().toggleHighlight({ color }).run();
      } else {
        state.editor.chain().focus().toggleHighlight().run();
      }
      return;
    }

    // Remove highlight: Alt+C
    if (e.altKey && !mod && lowerKey === "c") {
      e.preventDefault();
      state.editor.chain().focus().unsetHighlight().run();
      return;
    }

    // Search and replace: Ctrl+H
    if (mod && e.key === "h") {
      e.preventDefault();
      toggleSearchBar();
    }
  });
}

// ─── List Item Reordering ────────────────────────────────────────────────────

function moveListItem(direction) {
  const { state: editorState, view } = state.editor;
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

// ─── Import/Export ───────────────────────────────────────────────────────────

function setupImportExport() {
  bindClick("export-btn", (e) => {
    e.preventDefault();
    exportToMarkdown();
  });

  document.body.addEventListener("htmx:afterSwap", () => {
    if (document.getElementById("import-confirm-btn")) setupImportModal();
  });
}

function exportToMarkdown() {
  if (!state.editor) return;

  const markdown = getMarkdownContent();
  const title = window.NOTE_DATA.title || "note";
  const safeTitle = title.replace(/[^a-zA-Z0-9 \-_]/g, "").trim() || "note";

  const blob = new Blob([markdown], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = safeTitle + ".md";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function setupImportModal() {
  const fileInput = document.getElementById("import-file");
  const textInput = document.getElementById("import-text");
  const confirmBtn = document.getElementById("import-confirm-btn");
  if (!fileInput || !textInput || !confirmBtn) return;

  fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      textInput.value = e.target.result;
    };
    reader.readAsText(file);
  });

  confirmBtn.addEventListener("click", () => {
    const content = textInput.value.trim();
    if (!content) return;

    const replaceContent = document.getElementById("import-replace").checked;
    importMarkdown(content, replaceContent);
    window.dispatchEvent(new CustomEvent("close-modal"));
  });
}

function importMarkdown(markdown, replace) {
  if (!state.editor) return;
  const html = markdownToHtml(markdown);

  if (replace) {
    state.editor.commands.setContent(html);
  } else {
    state.editor.commands.focus("end");
    state.editor.commands.insertContent("<p></p>" + html);
  }

  scheduleAutosave();
}

// ─── HTMX Integration ───────────────────────────────────────────────────────

function setupHtmxHandlers() {
  document.body.addEventListener("htmx:beforeRequest", (e) => {
    if (e.detail.target && e.detail.target.id === "note-editor-container") {
      if (state.autosaveTimer) clearTimeout(state.autosaveTimer);
      performAutosave();

      const clickedItem = e.detail.elt;
      if (clickedItem && clickedItem.dataset.noteId) {
        updateSidebarActive(clickedItem.dataset.noteId);
      }
    }
  });

  document.body.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target && e.detail.target.id === "note-editor-container") {
      if (state.editor) {
        state.editor.destroy();
        state.editor = null;
      }

      state.lastSavedContent = "";
      state.searchMatches = [];
      state.currentMatchIndex = -1;

      setTimeout(initEditor, 50);
    }
  });
}

function updateSidebarActive(noteId) {
  const sidebar = document.querySelector(".sidebar-notes-list");
  if (!sidebar) return;

  sidebar
    .querySelectorAll("li")
    .forEach((item) => item.classList.remove("active"));

  const activeItem = sidebar.querySelector('li[data-note-id="' + noteId + '"]');
  if (activeItem) activeItem.classList.add("active");
}

// ─── Panel Collapse ──────────────────────────────────────────────────────────

function togglePanel(panelClass) {
  const panel = document.querySelector("." + panelClass);
  if (!panel) return;

  const isVisible = panel.offsetWidth > 0;
  if (isVisible) {
    panel.classList.add("collapsed");
    panel.classList.remove("expanded");
    localStorage.setItem("notes-editor-" + panelClass, "collapsed");
  } else {
    panel.classList.remove("collapsed");
    panel.classList.add("expanded");
    localStorage.setItem("notes-editor-" + panelClass, "expanded");
  }
}

function restorePanelStates() {
  const screenWidth = window.innerWidth;

  const sidebarState = localStorage.getItem("notes-editor-note-sidebar");
  const sidebar = document.querySelector(".note-sidebar");
  if (sidebar) {
    if (sidebarState === "collapsed") sidebar.classList.add("collapsed");
    else if (sidebarState === "expanded" && screenWidth >= 1200)
      sidebar.classList.add("expanded");
  }

  const outlineState = localStorage.getItem("notes-editor-note-outline");
  const outline = document.querySelector(".note-outline");
  if (outline) {
    if (outlineState === "collapsed") outline.classList.add("collapsed");
    else if (outlineState === "expanded" && screenWidth >= 768)
      outline.classList.add("expanded");
  }
}

window.togglePanel = togglePanel;

// ─── Init ────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  restorePanelStates();
  initEditor();
  setupHtmxHandlers();
  setupOutlineCollapseAll();
});
