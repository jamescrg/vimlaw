// Tiptap ESM imports from esm.sh CDN
import { Editor, Node as TiptapNode, Extension } from "https://esm.sh/@tiptap/core@2";
import Document from "https://esm.sh/@tiptap/extension-document@2";
import Paragraph from "https://esm.sh/@tiptap/extension-paragraph@2";
import Text from "https://esm.sh/@tiptap/extension-text@2";
import Bold from "https://esm.sh/@tiptap/extension-bold@2";
import Italic from "https://esm.sh/@tiptap/extension-italic@2";
import Strike from "https://esm.sh/@tiptap/extension-strike@2";
import Heading from "https://esm.sh/@tiptap/extension-heading@2";
import BulletList from "https://esm.sh/@tiptap/extension-bullet-list@2";
import OrderedList from "https://esm.sh/@tiptap/extension-ordered-list@2";
import ListItem from "https://esm.sh/@tiptap/extension-list-item@2";
import Blockquote from "https://esm.sh/@tiptap/extension-blockquote@2";
import HardBreak from "https://esm.sh/@tiptap/extension-hard-break@2";
import History from "https://esm.sh/@tiptap/extension-history@2";
import Dropcursor from "https://esm.sh/@tiptap/extension-dropcursor@2";
import Gapcursor from "https://esm.sh/@tiptap/extension-gapcursor@2";
import { Plugin, PluginKey } from "https://esm.sh/prosemirror-state";
import { Decoration, DecorationSet } from "https://esm.sh/prosemirror-view";

// Search highlight plugin for ProseMirror decorations
const searchPluginKey = new PluginKey("search");

const SearchHighlight = Extension.create({
  name: "searchHighlight",

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: searchPluginKey,
        state: {
          init() {
            return { searchTerm: "", decorations: DecorationSet.empty, matches: [] };
          },
          apply(tr, prev, oldState, newState) {
            const meta = tr.getMeta(searchPluginKey);
            if (meta !== undefined) {
              if (!meta.searchTerm) {
                return { searchTerm: "", decorations: DecorationSet.empty, matches: [] };
              }
              const decorations = [];
              const matches = [];
              const escapedTerm = meta.searchTerm.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
              const regex = new RegExp(escapedTerm, "gi");

              newState.doc.descendants(function(node, pos) {
                if (node.isText) {
                  const text = node.text;
                  let match;
                  while ((match = regex.exec(text)) !== null) {
                    const from = pos + match.index;
                    const to = from + match[0].length;
                    matches.push({ from: from, to: to });
                    const className = meta.currentIndex === matches.length - 1
                      ? "search-match search-match-current"
                      : "search-match";
                    decorations.push(
                      Decoration.inline(from, to, { class: className })
                    );
                  }
                }
              });

              return {
                searchTerm: meta.searchTerm,
                decorations: DecorationSet.create(newState.doc, decorations),
                matches: matches,
              };
            }
            // Map decorations through document changes
            const mapped = prev.decorations.map(tr.mapping, tr.doc);
            const mappedMatches = prev.matches.map(function(m) {
              return {
                from: tr.mapping.map(m.from),
                to: tr.mapping.map(m.to),
              };
            });
            return {
              searchTerm: prev.searchTerm,
              decorations: mapped,
              matches: mappedMatches,
            };
          },
        },
        props: {
          decorations(state) {
            return this.getState(state).decorations;
          },
        },
      }),
    ];
  },
});

// Collapsible headings plugin
const collapsePluginKey = new PluginKey("collapse");

function getCollapseStorageKey() {
  return "note-collapse-" + (window.NOTE_DATA ? window.NOTE_DATA.id : "unknown");
}

function getCollapsedHeadings() {
  try {
    const stored = localStorage.getItem(getCollapseStorageKey());
    return stored ? JSON.parse(stored) : [];
  } catch (e) {
    return [];
  }
}

function saveCollapsedHeadings(collapsed) {
  try {
    localStorage.setItem(getCollapseStorageKey(), JSON.stringify(collapsed));
  } catch (e) {
    // localStorage might be full or disabled
  }
}

function getHeadingId(node, pos) {
  // Use heading text content as identifier (more stable than position)
  return node.textContent.trim().substring(0, 50);
}

function toggleHeadingCollapse(headingId) {
  const collapsed = getCollapsedHeadings();
  const index = collapsed.indexOf(headingId);
  if (index >= 0) {
    collapsed.splice(index, 1);
  } else {
    collapsed.push(headingId);
  }
  saveCollapsedHeadings(collapsed);
}

function expandAllHeadings() {
  saveCollapsedHeadings([]);
  if (editor) {
    const tr = editor.state.tr;
    tr.setMeta(collapsePluginKey, { collapsed: [] });
    editor.view.dispatch(tr);
  }
}

function collapseAllHeadings() {
  if (!editor) return;

  const headingIds = [];
  editor.state.doc.descendants(function(node, pos) {
    if (node.type.name === "heading") {
      headingIds.push(getHeadingId(node, pos));
    }
  });

  saveCollapsedHeadings(headingIds);
  const tr = editor.state.tr;
  tr.setMeta(collapsePluginKey, { collapsed: headingIds });
  editor.view.dispatch(tr);
}

const CollapseHeadings = Extension.create({
  name: "collapseHeadings",

  addProseMirrorPlugins() {
    const extension = this;
    return [
      new Plugin({
        key: collapsePluginKey,
        state: {
          init() {
            return { collapsed: getCollapsedHeadings() };
          },
          apply(tr, prev) {
            const meta = tr.getMeta(collapsePluginKey);
            if (meta !== undefined) {
              return { collapsed: meta.collapsed };
            }
            return prev;
          },
        },
        props: {
          decorations(state) {
            const pluginState = this.getState(state);
            const collapsed = pluginState.collapsed;
            const decorations = [];
            const headings = [];

            // First pass: collect all headings with their positions and levels
            state.doc.descendants(function(node, pos) {
              if (node.type.name === "heading") {
                headings.push({
                  pos: pos,
                  level: node.attrs.level,
                  id: getHeadingId(node, pos),
                  nodeSize: node.nodeSize,
                });
              }
            });

            // Second pass: create decorations
            headings.forEach(function(heading, index) {
              const isCollapsed = collapsed.indexOf(heading.id) >= 0;

              // Create chevron widget decoration (insert at start of heading content)
              const chevronWidget = document.createElement("span");
              chevronWidget.className = "heading-toggle" + (isCollapsed ? " collapsed" : "");
              chevronWidget.innerHTML = '<i class="bi bi-chevron-down"></i>';
              chevronWidget.dataset.headingId = heading.id;

              decorations.push(
                Decoration.widget(heading.pos + 1, chevronWidget, { side: -1 })
              );

              // If collapsed, hide each node until next heading of same or higher level
              if (isCollapsed) {
                const endPos = findCollapseEndPos(headings, index, state.doc);
                const startPos = heading.pos + heading.nodeSize;

                // Iterate through nodes and add decoration to each
                state.doc.nodesBetween(startPos, endPos, function(node, pos) {
                  if (pos >= startPos && pos < endPos) {
                    decorations.push(
                      Decoration.node(pos, pos + node.nodeSize, {
                        class: "collapsed-content",
                        spellcheck: "false",
                      })
                    );
                    return false; // Don't descend into children
                  }
                });
              }
            });

            return DecorationSet.create(state.doc, decorations);
          },
          handleDOMEvents: {
            mousedown: function(view, event) {
              const toggle = event.target.closest(".heading-toggle");
              if (toggle) {
                event.preventDefault();
                event.stopPropagation();
                const headingId = toggle.dataset.headingId;
                toggleHeadingCollapse(headingId);
                // Dispatch transaction to trigger decoration update
                const tr = view.state.tr;
                tr.setMeta(collapsePluginKey, { collapsed: getCollapsedHeadings() });
                view.dispatch(tr);
                return true;
              }
              return false;
            },
          },
        },
      }),
    ];
  },
});

function findCollapseEndPos(headings, currentIndex, doc) {
  const currentHeading = headings[currentIndex];
  const currentLevel = currentHeading.level;

  // Find next heading of same or higher level (lower number = higher level)
  for (let i = currentIndex + 1; i < headings.length; i++) {
    if (headings[i].level <= currentLevel) {
      return headings[i].pos;
    }
  }

  // No next heading found, collapse until end of document
  return doc.content.size;
}

// Custom extension for note references (documents and highlights)
const NoteRef = TiptapNode.create({
  name: "noteRef",
  group: "inline",
  inline: true,
  atom: true,

  addAttributes() {
    return {
      type: {
        default: "document",
      },
      id: {
        default: null,
      },
      label: {
        default: "",
      },
    };
  },

  parseHTML() {
    return [
      {
        tag: 'span.note-ref',
        getAttrs: (dom) => ({
          type: dom.getAttribute("data-type"),
          id: dom.getAttribute("data-id"),
          label: dom.textContent,
        }),
      },
    ];
  },

  renderHTML({ node }) {
    return [
      "span",
      {
        class: "note-ref",
        "data-type": node.attrs.type,
        "data-id": node.attrs.id,
      },
      node.attrs.label,
    ];
  },
});

let editor = null;
let autosaveTimer = null;
let lastSavedContent = "";
let currentRefType = "document";

// Search state
let searchMatches = [];
let currentMatchIndex = -1;

// Initialize editor
function initEditor() {
  const container = document.getElementById("note-editor");
  if (!container || !window.NOTE_DATA) return;

  // Parse initial content - convert markdown references to HTML
  let initialContent = window.NOTE_DATA.content || "";
  initialContent = markdownToHtml(initialContent);

  editor = new Editor({
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
      Dropcursor,
      Gapcursor,
      NoteRef,
      SearchHighlight,
      CollapseHeadings,
    ],
    content: initialContent,
    autofocus: true,
    onUpdate: function () {
      scheduleAutosave();
    },
  });

  lastSavedContent = getMarkdownContent();
  setupToolbar();
  setupKeyboardShortcuts();
  setupReferencePicker();
  setupReferenceClicks();
  setupTitleEdit();
  setupSearchBar();
  setupImportExport();
}

function setupReferenceClicks() {
  const container = document.getElementById("note-editor");
  if (!container) return;

  container.addEventListener("click", function (e) {
    const ref = e.target.closest(".note-ref");
    if (!ref) return;

    e.preventDefault();
    const refType = ref.getAttribute("data-type");
    const refId = ref.getAttribute("data-id");

    if (!refId) return;

    let url;
    if (refType === "document") {
      url = "/documents/view/" + refId + "/";
    } else if (refType === "highlight") {
      url = "/case/highlights/" + refId + "/";
    }

    if (url) {
      window.open(url, "_blank");
    }
  });
}

function setupTitleEdit() {
  const titleEl = document.getElementById("note-title");
  if (!titleEl) return;

  titleEl.addEventListener("click", function () {
    startTitleEdit();
  });
}

function startTitleEdit() {
  const titleEl = document.getElementById("note-title");
  if (!titleEl || titleEl.tagName === "INPUT") return;

  const currentTitle = titleEl.textContent;
  const noteId = titleEl.dataset.noteId;

  const input = document.createElement("input");
  input.type = "text";
  input.value = currentTitle;
  input.className = "note-title-input";
  input.id = "note-title";
  input.dataset.noteId = noteId;

  titleEl.replaceWith(input);
  input.focus();
  input.select();

  input.addEventListener("blur", function () {
    finishTitleEdit(input, currentTitle);
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      input.blur();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancelTitleEdit(input, currentTitle);
    }
  });
}

function finishTitleEdit(input, originalTitle) {
  const newTitle = input.value.trim();
  const noteId = input.dataset.noteId;

  if (!newTitle || newTitle === originalTitle) {
    revertToSpan(input, originalTitle);
    return;
  }

  // Save the new title
  const formData = new FormData();
  formData.append("title", newTitle);

  fetch(window.NOTE_DATA.titleUrl, {
    method: "POST",
    headers: {
      "X-CSRFToken": getCSRFToken(),
    },
    body: formData,
  })
    .then(function (response) {
      return response.json();
    })
    .then(function (data) {
      if (data.saved) {
        revertToSpan(input, data.title);
      } else {
        revertToSpan(input, originalTitle);
      }
    })
    .catch(function () {
      revertToSpan(input, originalTitle);
    });
}

function cancelTitleEdit(input, originalTitle) {
  revertToSpan(input, originalTitle);
}

function revertToSpan(input, title) {
  const span = document.createElement("span");
  span.id = "note-title";
  span.className = "note-title";
  span.dataset.noteId = input.dataset.noteId;
  span.textContent = title;

  input.replaceWith(span);

  // Re-attach click listener
  span.addEventListener("click", function () {
    startTitleEdit();
  });
}

// Convert simple markdown to HTML for editor
function markdownToHtml(md) {
  if (!md) return "<p></p>";

  // Convert reference syntax to spans
  md = md.replace(
    /\[\[doc:(\d+)\|([^\]]+)\]\]/g,
    '<span class="note-ref" data-type="document" data-id="$1">$2</span>'
  );
  md = md.replace(
    /\[\[hl:(\d+)\|([^\]]+)\]\]/g,
    '<span class="note-ref" data-type="highlight" data-id="$1">$2</span>'
  );

  function formatInline(text) {
    return text
      .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/~~(.+?)~~/g, "<s>$1</s>");
  }

  // Parse lines into list items with depth info
  // Handle both Unix (\n) and Windows (\r\n) line endings
  const lines = md.split(/\r?\n/);
  const parsed = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      parsed.push({ type: "blank" });
      continue;
    }

    // Check for headers
    const headerMatch = trimmed.match(/^(#{1,5}) (.+)$/);
    if (headerMatch) {
      parsed.push({
        type: "header",
        level: headerMatch[1].length,
        content: formatInline(headerMatch[2]),
      });
      continue;
    }

    // Check for blockquote
    if (trimmed.startsWith("> ")) {
      parsed.push({
        type: "blockquote",
        content: formatInline(trimmed.substring(2)),
      });
      continue;
    }

    // Check for unordered list item (handle tabs, empty items, windows line endings)
    const ulMatch = line.replace(/\r$/, "").match(/^([ \t]*)[-*] (.*)$/);
    if (ulMatch) {
      // Normalize: count tabs as 2 spaces each
      const indentStr = ulMatch[1].replace(/\t/g, "  ");
      const depth = Math.floor(indentStr.length / 2);
      parsed.push({
        type: "li",
        listType: "ul",
        depth: depth,
        content: formatInline(ulMatch[2] || ""),
      });
      continue;
    }

    // Check for ordered list item
    const olMatch = line.replace(/\r$/, "").match(/^([ \t]*)(\d+)\. (.*)$/);
    if (olMatch) {
      const indentStr = olMatch[1].replace(/\t/g, "  ");
      const depth = Math.floor(indentStr.length / 2);
      parsed.push({
        type: "li",
        listType: "ol",
        depth: depth,
        content: formatInline(olMatch[3] || ""),
      });
      continue;
    }

    // Regular paragraph
    parsed.push({
      type: "paragraph",
      content: formatInline(trimmed),
    });
  }

  // Build HTML with proper nesting for ProseMirror
  // ProseMirror expects: <ul><li><p>text</p><ul><li><p>nested</p></li></ul></li></ul>
  const result = [];
  let i = 0;

  function buildList(startIndex, minDepth) {
    let idx = startIndex;
    const items = [];

    while (idx < parsed.length) {
      const item = parsed[idx];

      if (item.type !== "li") {
        break;
      }

      if (item.depth < minDepth) {
        break;
      }

      if (item.depth === minDepth) {
        // This item is at our level
        const listType = item.listType;
        let liContent = "<li><p>" + item.content + "</p>";
        idx++;

        // Check if next items are nested (deeper)
        if (idx < parsed.length && parsed[idx].type === "li" && parsed[idx].depth > minDepth) {
          const nested = buildList(idx, parsed[idx].depth);
          liContent += nested.html;
          idx = nested.endIndex;
        }

        liContent += "</li>";
        items.push({ html: liContent, listType: listType });
      } else {
        // Deeper item - should be handled by recursion
        break;
      }
    }

    if (items.length === 0) {
      return { html: "", endIndex: idx };
    }

    // Group consecutive items by list type
    const listType = items[0].listType;
    const html = "<" + listType + ">" + items.map(function(it) { return it.html; }).join("") + "</" + listType + ">";

    return { html: html, endIndex: idx };
  }

  while (i < parsed.length) {
    const item = parsed[i];

    if (item.type === "blank") {
      i++;
      continue;
    }

    if (item.type === "header") {
      result.push("<h" + item.level + ">" + item.content + "</h" + item.level + ">");
      i++;
      continue;
    }

    if (item.type === "blockquote") {
      result.push("<blockquote><p>" + item.content + "</p></blockquote>");
      i++;
      continue;
    }

    if (item.type === "paragraph") {
      result.push("<p>" + item.content + "</p>");
      i++;
      continue;
    }

    if (item.type === "li") {
      const listResult = buildList(i, item.depth);
      result.push(listResult.html);
      i = listResult.endIndex;
      continue;
    }

    i++;
  }

  return result.join("") || "<p></p>";
}

// Convert editor HTML to markdown
function htmlToMarkdown(html) {
  const tempDiv = document.createElement("div");
  tempDiv.innerHTML = html;

  function processNode(node, listDepth, listType, listIndex) {
    if (node.nodeType === Node.TEXT_NODE) {
      return node.textContent;
    }

    if (node.nodeType !== Node.ELEMENT_NODE) return "";

    const tag = node.tagName.toLowerCase();

    // For most elements, process children normally
    function getChildren() {
      return Array.from(node.childNodes).map(function(child) {
        return processNode(child, listDepth, null, 0);
      }).join("");
    }

    switch (tag) {
      case "h1":
        return "# " + getChildren() + "\n\n";
      case "h2":
        return "## " + getChildren() + "\n\n";
      case "h3":
        return "### " + getChildren() + "\n\n";
      case "h4":
        return "#### " + getChildren() + "\n\n";
      case "h5":
        return "##### " + getChildren() + "\n\n";
      case "p":
        // If inside a list item, don't add extra newlines
        if (listDepth > 0) {
          return getChildren();
        }
        return getChildren() + "\n\n";
      case "strong":
        return "**" + getChildren() + "**";
      case "em":
        return "*" + getChildren() + "*";
      case "s":
        return "~~" + getChildren() + "~~";
      case "blockquote":
        return (
          getChildren()
            .trim()
            .split("\n")
            .map(function (line) {
              return "> " + line;
            })
            .join("\n") + "\n\n"
        );
      case "ul":
      case "ol":
        // Process list items with incremented depth
        let result = "";
        let idx = 1;
        Array.from(node.children).forEach(function(child) {
          if (child.tagName.toLowerCase() === "li") {
            result += processNode(child, listDepth + 1, tag, idx);
            idx++;
          }
        });
        // Add trailing newline only for top-level lists
        if (listDepth === 0) {
          result += "\n";
        }
        return result;
      case "li":
        const indent = "  ".repeat(listDepth - 1);
        let prefix;
        if (listType === "ol") {
          prefix = listIndex + ". ";
        } else {
          prefix = "- ";
        }

        // Process li children: separate text content from nested lists
        let textContent = "";
        let nestedLists = "";

        Array.from(node.childNodes).forEach(function(child) {
          if (child.nodeType === Node.ELEMENT_NODE) {
            const childTag = child.tagName.toLowerCase();
            if (childTag === "ul" || childTag === "ol") {
              nestedLists += processNode(child, listDepth, null, 0);
            } else if (childTag === "p") {
              textContent += processNode(child, listDepth, null, 0);
            } else {
              textContent += processNode(child, listDepth, null, 0);
            }
          } else {
            textContent += processNode(child, listDepth, null, 0);
          }
        });

        return indent + prefix + textContent.trim() + "\n" + nestedLists;
      case "br":
        return "\n";
      case "span":
        if (
          node.classList.contains("note-ref") ||
          node.getAttribute("data-type")
        ) {
          const refType = node.getAttribute("data-type");
          const refId = node.getAttribute("data-id");
          const label = node.textContent || getChildren();
          if (refType === "document") {
            return "[[doc:" + refId + "|" + label + "]]";
          } else if (refType === "highlight") {
            return "[[hl:" + refId + "|" + label + "]]";
          }
        }
        return getChildren();
      default:
        return getChildren();
    }
  }

  let markdown = processNode(tempDiv, 0, null, 0);
  // Clean up multiple newlines
  markdown = markdown.replace(/\n{3,}/g, "\n\n").trim();
  return markdown;
}

function getMarkdownContent() {
  if (!editor) return "";
  const html = editor.getHTML();
  return htmlToMarkdown(html);
}

// Autosave with debounce
function scheduleAutosave() {
  if (autosaveTimer) clearTimeout(autosaveTimer);
  updateSaveStatus("unsaved");
  autosaveTimer = setTimeout(performAutosave, 2000);
}

function performAutosave() {
  const content = getMarkdownContent();
  if (content === lastSavedContent) {
    updateSaveStatus("saved");
    return;
  }

  updateSaveStatus("saving");

  const formData = new FormData();
  formData.append("content", content);

  fetch(window.NOTE_DATA.autosaveUrl, {
    method: "POST",
    headers: {
      "X-CSRFToken": getCSRFToken(),
    },
    body: formData,
  })
    .then(function (response) {
      return response.json();
    })
    .then(function (data) {
      if (data.saved) {
        lastSavedContent = content;
        updateSaveStatus("saved");
      }
    })
    .catch(function () {
      updateSaveStatus("unsaved");
    });
}

function updateSaveStatus(status) {
  const btn = document.getElementById("save-status-btn");
  if (!btn) return;

  const icon = btn.querySelector("i");
  if (!icon) return;

  if (status === "unsaved") {
    btn.classList.add("active");
    btn.title = "Unsaved changes";
    icon.className = "bi bi-cloud-arrow-up";
  } else if (status === "saving") {
    btn.classList.add("active");
    btn.title = "Saving...";
    icon.className = "bi bi-cloud-arrow-up";
  } else {
    btn.classList.remove("active");
    btn.title = "Saved";
    icon.className = "bi bi-cloud-check";
  }
}

function getCSRFToken() {
  const el = document.querySelector("[name=csrfmiddlewaretoken]");
  return el ? el.value : "";
}

// Toolbar setup
function setupToolbar() {
  const btnBold = document.getElementById("btn-bold");
  const btnItalic = document.getElementById("btn-italic");
  const btnStrike = document.getElementById("btn-strike");
  const btnH1 = document.getElementById("btn-heading-1");
  const btnH2 = document.getElementById("btn-heading-2");
  const btnH3 = document.getElementById("btn-heading-3");
  const btnBullet = document.getElementById("btn-bullet-list");
  const btnOrdered = document.getElementById("btn-ordered-list");
  const btnQuote = document.getElementById("btn-blockquote");

  if (btnBold) {
    btnBold.addEventListener("click", function () {
      editor.chain().focus().toggleBold().run();
    });
  }
  if (btnItalic) {
    btnItalic.addEventListener("click", function () {
      editor.chain().focus().toggleItalic().run();
    });
  }
  if (btnStrike) {
    btnStrike.addEventListener("click", function () {
      editor.chain().focus().toggleStrike().run();
    });
  }
  if (btnH1) {
    btnH1.addEventListener("click", function () {
      editor.chain().focus().toggleHeading({ level: 1 }).run();
    });
  }
  if (btnH2) {
    btnH2.addEventListener("click", function () {
      editor.chain().focus().toggleHeading({ level: 2 }).run();
    });
  }
  if (btnH3) {
    btnH3.addEventListener("click", function () {
      editor.chain().focus().toggleHeading({ level: 3 }).run();
    });
  }
  if (btnBullet) {
    btnBullet.addEventListener("click", function () {
      editor.chain().focus().toggleBulletList().run();
    });
  }
  if (btnOrdered) {
    btnOrdered.addEventListener("click", function () {
      editor.chain().focus().toggleOrderedList().run();
    });
  }
  if (btnQuote) {
    btnQuote.addEventListener("click", function () {
      editor.chain().focus().toggleBlockquote().run();
    });
  }

  // Reference insertion buttons
  document.querySelectorAll("[data-ref-type]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      openReferencePicker(btn.dataset.refType);
    });
  });

  // Expand/Collapse all buttons
  const expandAllBtn = document.getElementById("expand-all-btn");
  const collapseAllBtn = document.getElementById("collapse-all-btn");

  if (expandAllBtn) {
    expandAllBtn.addEventListener("click", function (e) {
      e.preventDefault();
      expandAllHeadings();
    });
  }

  if (collapseAllBtn) {
    collapseAllBtn.addEventListener("click", function (e) {
      e.preventDefault();
      collapseAllHeadings();
    });
  }
}

function setupKeyboardShortcuts() {
  document.addEventListener("keydown", function (e) {
    const mod = e.ctrlKey || e.metaKey;

    // Save: Ctrl+S
    if (mod && e.key === "s") {
      e.preventDefault();
      if (autosaveTimer) clearTimeout(autosaveTimer);
      performAutosave();
      return;
    }

    // Headings: Ctrl+1 through Ctrl+5
    if (mod && !e.shiftKey && e.key === "1") {
      e.preventDefault();
      editor.chain().focus().toggleHeading({ level: 1 }).run();
      return;
    }
    if (mod && !e.shiftKey && e.key === "2") {
      e.preventDefault();
      editor.chain().focus().toggleHeading({ level: 2 }).run();
      return;
    }
    if (mod && !e.shiftKey && e.key === "3") {
      e.preventDefault();
      editor.chain().focus().toggleHeading({ level: 3 }).run();
      return;
    }
    if (mod && !e.shiftKey && e.key === "4") {
      e.preventDefault();
      editor.chain().focus().toggleHeading({ level: 4 }).run();
      return;
    }
    if (mod && !e.shiftKey && e.key === "5") {
      e.preventDefault();
      editor.chain().focus().toggleHeading({ level: 5 }).run();
      return;
    }

    // Clear formatting / convert to paragraph: Ctrl+0
    if (mod && !e.shiftKey && e.key === "0") {
      e.preventDefault();
      editor.chain().focus().setParagraph().run();
      return;
    }

    // Bullet list: Ctrl+7
    if (mod && !e.shiftKey && e.key === "7") {
      e.preventDefault();
      editor.chain().focus().toggleBulletList().run();
      return;
    }

    // Blockquote: Ctrl+8
    if (mod && !e.shiftKey && e.key === "8") {
      e.preventDefault();
      editor.chain().focus().toggleBlockquote().run();
      return;
    }

    // Move list item up: Ctrl+Up
    if (mod && e.key === "ArrowUp" && editor.isActive("listItem")) {
      e.preventDefault();
      moveListItem("up");
      return;
    }

    // Move list item down: Ctrl+Down
    if (mod && e.key === "ArrowDown" && editor.isActive("listItem")) {
      e.preventDefault();
      moveListItem("down");
      return;
    }

    // Delete block/list item: Ctrl+Delete or Ctrl+D
    if (mod && (e.key === "Delete" || e.key === "d")) {
      e.preventDefault();
      editor.chain().focus().deleteNode("paragraph").run();
      return;
    }

    // Insert reference: Ctrl+;
    if (mod && e.key === ";") {
      e.preventDefault();
      openReferencePicker("document");
      return;
    }

    // Show shortcuts: Ctrl+/ or ?
    if ((mod && e.key === "/") || e.key === "?") {
      e.preventDefault();
      showShortcutsModal();
      return;
    }

    // Search and replace: Ctrl+H
    if (mod && e.key === "h") {
      e.preventDefault();
      toggleSearchBar();
      return;
    }
  });
}

function showShortcutsModal() {
  // Trigger click on the keyboard shortcuts button to load via HTMX
  const btn = document.querySelector('[title="Keyboard shortcuts"]');
  if (btn) {
    btn.click();
  }
}

function moveListItem(direction) {
  const { state, view } = editor;
  const { selection } = state;
  const { $from } = selection;

  // Find the list item node
  let listItemPos = null;
  let listItemNode = null;
  let listItemDepth = null;

  for (let d = $from.depth; d > 0; d--) {
    const node = $from.node(d);
    if (node.type.name === "listItem") {
      listItemPos = $from.before(d);
      listItemNode = node;
      listItemDepth = d;
      break;
    }
  }

  if (!listItemNode || listItemPos === null) return;

  const parentList = $from.node(listItemDepth - 1);
  const indexInParent = $from.index(listItemDepth - 1);

  if (direction === "up" && indexInParent === 0) return;
  if (direction === "down" && indexInParent >= parentList.childCount - 1) return;

  const tr = state.tr;
  const listItemEnd = listItemPos + listItemNode.nodeSize;
  const cursorOffset = $from.pos - listItemPos;
  let newCursorPos;

  if (direction === "up") {
    const prevItemNode = parentList.child(indexInParent - 1);
    const prevItemSize = prevItemNode.nodeSize;
    // New position will be prevItemSize earlier
    newCursorPos = $from.pos - prevItemSize;
    // Move current item before previous
    const slice = tr.doc.slice(listItemPos, listItemEnd);
    tr.delete(listItemPos, listItemEnd);
    tr.insert(listItemPos - prevItemSize, slice.content);
  } else {
    const nextItemNode = parentList.child(indexInParent + 1);
    const nextItemSize = nextItemNode.nodeSize;
    // New position will be nextItemSize later
    newCursorPos = $from.pos + nextItemSize;
    // Move next item before current
    const nextItemPos = listItemEnd;
    const nextSlice = tr.doc.slice(nextItemPos, nextItemPos + nextItemSize);
    tr.delete(nextItemPos, nextItemPos + nextItemSize);
    tr.insert(listItemPos, nextSlice.content);
  }

  // Set cursor position
  tr.setSelection(state.selection.constructor.near(tr.doc.resolve(newCursorPos)));
  view.dispatch(tr.scrollIntoView());
}

// Reference picker
function setupReferencePicker() {
  const overlay = document.getElementById("reference-picker-overlay");
  const closeBtn = document.getElementById("picker-close");
  const searchInput = document.getElementById("reference-search");
  const tabs = document.querySelectorAll(".picker-tab");

  if (closeBtn) {
    closeBtn.addEventListener("click", closeReferencePicker);
  }

  if (overlay) {
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) closeReferencePicker();
    });
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      currentRefType = tab.dataset.type;
      tabs.forEach(function (t) {
        t.classList.remove("active");
      });
      tab.classList.add("active");
      if (searchInput.value) {
        searchReferences(searchInput.value);
      }
    });
  });

  if (searchInput) {
    let searchTimer;
    searchInput.addEventListener("input", function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        searchReferences(searchInput.value);
      }, 300);
    });
  }

  // Handle result clicks
  document
    .getElementById("reference-results")
    .addEventListener("click", function (e) {
      const item = e.target.closest(".reference-item");
      if (item) {
        insertReference(item.dataset.type, item.dataset.id, item.dataset.label);
      }
    });
}

function openReferencePicker(refType) {
  currentRefType = refType || "document";
  const overlay = document.getElementById("reference-picker-overlay");
  const searchInput = document.getElementById("reference-search");
  const tabs = document.querySelectorAll(".picker-tab");
  const results = document.getElementById("reference-results");

  tabs.forEach(function (t) {
    t.classList.toggle("active", t.dataset.type === currentRefType);
  });

  results.innerHTML = '<div class="reference-empty">Type to search...</div>';
  overlay.classList.add("active");
  searchInput.value = "";
  searchInput.focus();
}

function closeReferencePicker() {
  const overlay = document.getElementById("reference-picker-overlay");
  overlay.classList.remove("active");
  editor.commands.focus();
}

function searchReferences(query) {
  if (!query.trim()) {
    document.getElementById("reference-results").innerHTML =
      '<div class="reference-empty">Type to search...</div>';
    return;
  }

  const url =
    window.NOTE_DATA.searchUrl +
    "?q=" +
    encodeURIComponent(query) +
    "&type=" +
    currentRefType;

  fetch(url, {
    headers: {
      "X-CSRFToken": getCSRFToken(),
    },
  })
    .then(function (response) {
      return response.text();
    })
    .then(function (html) {
      document.getElementById("reference-results").innerHTML = html;
    });
}

function insertReference(type, id, label) {
  editor
    .chain()
    .focus()
    .insertContent([
      {
        type: "noteRef",
        attrs: { type: type, id: id, label: label },
      },
      { type: "text", text: " " },
    ])
    .run();

  closeReferencePicker();
}

// =============================================================================
// Search and Replace
// =============================================================================

function setupSearchBar() {
  const searchInput = document.getElementById("search-input");
  const replaceInput = document.getElementById("replace-input");
  const prevBtn = document.getElementById("search-prev");
  const nextBtn = document.getElementById("search-next");
  const replaceBtn = document.getElementById("replace-one");
  const replaceAllBtn = document.getElementById("replace-all");
  const closeBtn = document.getElementById("search-close");
  const toggleBtn = document.getElementById("search-toggle-btn");

  if (searchInput) {
    let searchTimer;
    searchInput.addEventListener("input", function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        performSearch(searchInput.value);
      }, 200);
    });

    searchInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        goToNextMatch();
      } else if (e.key === "Escape") {
        hideSearchBar();
      }
    });
  }

  if (replaceInput) {
    replaceInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        replaceCurrentMatch();
      } else if (e.key === "Escape") {
        hideSearchBar();
      }
    });
  }

  if (prevBtn) {
    prevBtn.addEventListener("click", goToPrevMatch);
  }

  if (nextBtn) {
    nextBtn.addEventListener("click", goToNextMatch);
  }

  if (replaceBtn) {
    replaceBtn.addEventListener("click", replaceCurrentMatch);
  }

  if (replaceAllBtn) {
    replaceAllBtn.addEventListener("click", replaceAllMatches);
  }

  if (closeBtn) {
    closeBtn.addEventListener("click", hideSearchBar);
  }

  if (toggleBtn) {
    toggleBtn.addEventListener("click", function (e) {
      e.preventDefault();
      toggleSearchBar();
    });
  }
}

function toggleSearchBar() {
  const bar = document.getElementById("search-replace-bar");
  if (bar && bar.classList.contains("visible")) {
    hideSearchBar();
  } else {
    showSearchBar();
  }
}

function showSearchBar() {
  const bar = document.getElementById("search-replace-bar");
  const searchInput = document.getElementById("search-input");
  const toggleBtn = document.getElementById("search-toggle-btn");

  if (bar) {
    bar.classList.add("visible");
  }
  if (toggleBtn) {
    toggleBtn.classList.add("active");
  }
  if (searchInput) {
    searchInput.focus();
    searchInput.select();
  }
}

function hideSearchBar() {
  const bar = document.getElementById("search-replace-bar");
  const toggleBtn = document.getElementById("search-toggle-btn");
  const searchInput = document.getElementById("search-input");
  const replaceInput = document.getElementById("replace-input");

  if (bar) {
    bar.classList.remove("visible");
  }
  if (toggleBtn) {
    toggleBtn.classList.remove("active");
  }

  clearSearchHighlights();
  searchMatches = [];
  currentMatchIndex = -1;
  updateSearchCount();

  if (searchInput) searchInput.value = "";
  if (replaceInput) replaceInput.value = "";

  if (editor) {
    editor.commands.focus();
  }
}

function performSearch(searchTerm) {
  searchMatches = [];
  currentMatchIndex = -1;

  if (!searchTerm || !editor) {
    // Clear decorations
    const tr = editor.state.tr;
    tr.setMeta(searchPluginKey, { searchTerm: "", currentIndex: -1 });
    editor.view.dispatch(tr);
    updateSearchCount();
    return;
  }

  // Dispatch transaction to update search decorations
  const tr = editor.state.tr;
  tr.setMeta(searchPluginKey, { searchTerm: searchTerm, currentIndex: 0 });
  editor.view.dispatch(tr);

  // Get matches from plugin state
  const pluginState = searchPluginKey.getState(editor.state);
  if (pluginState && pluginState.matches) {
    searchMatches = pluginState.matches;
  }

  if (searchMatches.length > 0) {
    currentMatchIndex = 0;
    scrollToCurrentMatch();
  }

  updateSearchCount();
}

function clearSearchHighlights() {
  if (!editor) return;

  // Clear decorations by dispatching empty search
  const tr = editor.state.tr;
  tr.setMeta(searchPluginKey, { searchTerm: "", currentIndex: -1 });
  editor.view.dispatch(tr);

  searchMatches = [];
  currentMatchIndex = -1;
}

function updateSearchDecorations() {
  if (!editor) return;

  const searchInput = document.getElementById("search-input");
  const searchTerm = searchInput ? searchInput.value : "";

  const tr = editor.state.tr;
  tr.setMeta(searchPluginKey, { searchTerm: searchTerm, currentIndex: currentMatchIndex });
  editor.view.dispatch(tr);
}

function scrollToCurrentMatch() {
  if (currentMatchIndex < 0 || currentMatchIndex >= searchMatches.length) return;

  const match = searchMatches[currentMatchIndex];
  if (!match) return;

  // Get the DOM position of the match and scroll to it
  const coords = editor.view.coordsAtPos(match.from);
  if (coords) {
    const container = document.getElementById("note-editor");
    if (container) {
      const rect = container.getBoundingClientRect();
      const relativeTop = coords.top - rect.top;
      const centerOffset = container.clientHeight / 2;
      container.scrollTop += relativeTop - centerOffset;
    }
  }
}

function updateSearchCount() {
  const countEl = document.getElementById("search-count");
  if (countEl) {
    if (searchMatches.length === 0) {
      countEl.textContent = "";
    } else {
      countEl.textContent = (currentMatchIndex + 1) + " of " + searchMatches.length;
    }
  }
}

function goToNextMatch() {
  if (searchMatches.length === 0) return;
  currentMatchIndex = (currentMatchIndex + 1) % searchMatches.length;
  updateSearchDecorations();
  scrollToCurrentMatch();
  updateSearchCount();
}

function goToPrevMatch() {
  if (searchMatches.length === 0) return;
  currentMatchIndex =
    (currentMatchIndex - 1 + searchMatches.length) % searchMatches.length;
  updateSearchDecorations();
  scrollToCurrentMatch();
  updateSearchCount();
}

function replaceCurrentMatch() {
  if (currentMatchIndex < 0 || currentMatchIndex >= searchMatches.length) return;

  const searchInput = document.getElementById("search-input");
  const replaceInput = document.getElementById("replace-input");
  if (!searchInput || !editor) return;

  const searchTerm = searchInput.value;
  const replaceTerm = replaceInput ? replaceInput.value : "";

  const match = searchMatches[currentMatchIndex];
  if (!match) return;

  // Replace the match using Tiptap's chain
  editor
    .chain()
    .focus()
    .setTextSelection({ from: match.from, to: match.to })
    .deleteSelection()
    .insertContent(replaceTerm)
    .run();

  // Re-run search to update matches
  performSearch(searchTerm);

  // Trigger autosave
  scheduleAutosave();
}

function replaceAllMatches() {
  const searchInput = document.getElementById("search-input");
  const replaceInput = document.getElementById("replace-input");
  if (!searchInput || !editor) return;

  const searchTerm = searchInput.value;
  const replaceTerm = replaceInput ? replaceInput.value : "";

  if (!searchTerm || searchMatches.length === 0) return;

  // Replace all matches in reverse order to preserve positions
  const matchesCopy = searchMatches.slice().reverse();

  editor.chain().focus().run();

  matchesCopy.forEach(function(match) {
    editor
      .chain()
      .setTextSelection({ from: match.from, to: match.to })
      .deleteSelection()
      .insertContent(replaceTerm)
      .run();
  });

  // Clear search state
  clearSearchHighlights();
  updateSearchCount();

  // Trigger autosave
  scheduleAutosave();
}

// =============================================================================
// Import/Export
// =============================================================================

function setupImportExport() {
  // Export button
  const exportBtn = document.getElementById("export-btn");
  if (exportBtn) {
    exportBtn.addEventListener("click", function (e) {
      e.preventDefault();
      exportToMarkdown();
    });
  }

  // Listen for HTMX content swap to set up import handlers
  document.body.addEventListener("htmx:afterSwap", function (e) {
    // Check if the import modal was just loaded
    if (document.getElementById("import-confirm-btn")) {
      setupImportModal();
    }
  });
}

function exportToMarkdown() {
  if (!editor) return;

  const markdown = getMarkdownContent();
  const title = window.NOTE_DATA.title || "note";

  // Sanitize filename
  const safeTitle = title.replace(/[^a-zA-Z0-9 \-_]/g, "").trim() || "note";
  const filename = safeTitle + ".md";

  // Create download
  const blob = new Blob([markdown], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
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

  // Handle file selection
  fileInput.addEventListener("change", function () {
    const file = fileInput.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function (e) {
      textInput.value = e.target.result;
    };
    reader.readAsText(file);
  });

  // Handle import confirmation
  confirmBtn.addEventListener("click", function () {
    const content = textInput.value.trim();
    if (!content) return;

    const replaceContent = document.getElementById("import-replace").checked;
    importMarkdown(content, replaceContent);

    // Close modal
    const modal = bootstrap.Modal.getInstance(document.getElementById("htmx-modal-container"));
    if (modal) {
      modal.hide();
    }
  });
}

function importMarkdown(markdown, replace) {
  if (!editor) return;

  // Convert markdown to HTML
  const html = markdownToHtml(markdown);

  if (replace) {
    // Replace all content
    editor.commands.setContent(html);
  } else {
    // Append to end
    editor.commands.focus("end");
    editor.commands.insertContent("<p></p>" + html);
  }

  // Trigger autosave
  scheduleAutosave();
}

// Initialize on load
document.addEventListener("DOMContentLoaded", initEditor);
