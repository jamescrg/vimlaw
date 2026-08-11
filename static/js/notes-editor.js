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
} from "./vendor/tiptap.bundle.js";

import { HighlightMark } from "./highlight-mark.js";
import { PlainCopy } from "./plain-copy.js";

import { state, getCSRFToken, bindClick } from "./notes/state.js";
import { setupFileTree } from "./notes/file-tree.js";
import { connectFormatToolbar } from "./format-toolbar.js";
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
  updateOutlineActive,
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
    editable: !(window.NOTE_DATA && window.NOTE_DATA.readOnly),
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
      HighlightMark.configure({ multicolor: true }),
      Code,
      CodeBlockLowlight.configure({ lowlight: createLowlight(lowlightAll) }),
      HorizontalRule,
      NoteRef,
      SearchHighlight,
      PlainCopy,
    ],
    content: initialContent,
    onUpdate() {
      scheduleAutosave();
      scheduleOutlineUpdate();
    },
    onSelectionUpdate() {
      updateCodeBlockLangSelector();
      updateOutlineActive();
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
  if (window.NOTE_DATA && window.NOTE_DATA.readOnly) return;

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
          document.body.dispatchEvent(new Event("noteSaved"));
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
  const cluster = document.querySelector(".note-toolbar .format-toolbar");
  if (!cluster) return;

  // Synced notes are read-only, but TipTap still applies programmatic
  // commands to a non-editable editor — hide the format cluster (the rest
  // of the bar stays useful). The element survives note switches, so
  // re-show it when an editable note loads.
  const readOnly = !!(window.NOTE_DATA && window.NOTE_DATA.readOnly);
  cluster.style.display = readOnly ? "none" : "";
  if (readOnly) return;

  connectFormatToolbar(cluster, state.editor);
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
  const pane = document.querySelector(".files-pane");
  if (!pane) return;

  pane
    .querySelectorAll("[data-note-id]")
    .forEach((item) => item.classList.remove("active"));

  const activeItem = pane.querySelector('[data-note-id="' + noteId + '"]');
  if (!activeItem) return;
  activeItem.classList.add("active");

  // Reveal a note sitting inside collapsed folders (tree only). DOM-only,
  // mirroring the server's render-time ancestor union without persisting
  // the expansion to the session.
  let folder = activeItem.parentElement.closest(".file-tree-folder");
  while (folder) {
    folder.classList.remove("collapsed");
    folder = folder.parentElement.closest(".file-tree-folder");
  }
  activeItem.scrollIntoView({ block: "nearest" });
}

// ─── Panel Collapse + Tabs ───────────────────────────────────────────────────

const PANEL_STATE_KEY = "notes-editor-note-panel";
const PANEL_TAB_KEY = "notes-editor-panel-tab";
const PANEL_WIDTH_KEY = "notes-editor-panel-width";
// Collapsed leaves a 3rem rail (so the bottom toggle stays reachable) —
// only widths beyond it count as "open".
const PANEL_RAIL_PX = 64;
const PANEL_MIN_WIDTH = 180;
const PANEL_MAX_WIDTH = 560;

// Point the toggle's icon at the action it will perform: an open panel
// gets the "close" glyph, a collapsed one the "open" glyph.
function syncPanelIcon(isOpen) {
  const icon = document.querySelector("#panel-toggle-btn i");
  if (icon) icon.className = "icon-panel-left-" + (isOpen ? "close" : "open");
}

// Measured width is the ground truth (media queries collapse the panel
// without touching the classes), so re-sync from it on load and resize.
function syncPanelIcons() {
  const panel = document.querySelector(".note-panel");
  if (panel) syncPanelIcon(panel.offsetWidth > PANEL_RAIL_PX);
}

function togglePanel() {
  const panel = document.querySelector(".note-panel");
  if (!panel) return;

  const isVisible = panel.offsetWidth > PANEL_RAIL_PX;
  panel.classList.toggle("collapsed", isVisible);
  panel.classList.toggle("expanded", !isVisible);
  localStorage.setItem(PANEL_STATE_KEY, isVisible ? "collapsed" : "expanded");
  syncPanelIcon(!isVisible);
}

function openPanel() {
  const panel = document.querySelector(".note-panel");
  if (!panel) return;

  panel.classList.remove("collapsed");
  panel.classList.add("expanded");
  localStorage.setItem(PANEL_STATE_KEY, "expanded");
  syncPanelIcon(true);
}

function setPanelTab(tab) {
  const panel = document.querySelector(".note-panel");
  if (!panel) return;

  panel.classList.toggle("tab-outline", tab === "outline");
  panel
    .querySelectorAll(".panel-tab, .rail-tab")
    .forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));
  localStorage.setItem(PANEL_TAB_KEY, tab);
}

function setupPanelTabs() {
  document.querySelectorAll(".note-panel .panel-tab").forEach((btn) => {
    btn.addEventListener("click", () => setPanelTab(btn.dataset.tab));
  });

  // Rail icons expand the collapsed panel straight onto their tab
  document.querySelectorAll(".note-panel .rail-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      setPanelTab(btn.dataset.tab);
      openPanel();
    });
  });
}

function setupPanelResize() {
  const panel = document.querySelector(".note-panel");
  const resizer = panel && panel.querySelector(".panel-resizer");
  if (!resizer) return;

  const storedWidth = parseInt(localStorage.getItem(PANEL_WIDTH_KEY), 10);
  if (storedWidth) panel.style.setProperty("--panel-width", storedWidth + "px");

  resizer.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    resizer.setPointerCapture(e.pointerId);
    panel.classList.add("resizing");
    const startX = e.clientX;
    const startWidth = panel.offsetWidth;

    const onMove = (ev) => {
      const width = Math.min(
        PANEL_MAX_WIDTH,
        Math.max(PANEL_MIN_WIDTH, startWidth + ev.clientX - startX),
      );
      panel.style.setProperty("--panel-width", width + "px");
    };
    const onUp = () => {
      resizer.removeEventListener("pointermove", onMove);
      resizer.removeEventListener("pointerup", onUp);
      panel.classList.remove("resizing");
      localStorage.setItem(PANEL_WIDTH_KEY, String(panel.offsetWidth));
    };
    resizer.addEventListener("pointermove", onMove);
    resizer.addEventListener("pointerup", onUp);
  });

  resizer.addEventListener("dblclick", () => {
    panel.style.removeProperty("--panel-width");
    localStorage.removeItem(PANEL_WIDTH_KEY);
  });
}

function restorePanelStates() {
  const panel = document.querySelector(".note-panel");
  if (panel) {
    const stored = localStorage.getItem(PANEL_STATE_KEY);
    if (stored === "collapsed") panel.classList.add("collapsed");
    else if (stored === "expanded" && window.innerWidth >= 1200)
      panel.classList.add("expanded");
  }
  setPanelTab(localStorage.getItem(PANEL_TAB_KEY) || "files");
}

window.togglePanel = togglePanel;

// ─── Init ────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  restorePanelStates();
  setupPanelTabs();
  setupPanelResize();
  syncPanelIcons();
  setupFileTree();
  initEditor();
  setupHtmxHandlers();
  setupOutlineCollapseAll();
});

window.addEventListener("resize", syncPanelIcons);
