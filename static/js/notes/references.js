// Reference picker, citations, and NoteRef node for the notes editor

import { Node as TiptapNode } from "../vendor/tiptap.bundle.js";

import { state, getCSRFToken } from "./state.js";
import { scheduleAutosave } from "./autosave.js";

// ─── NoteRef Node Extension ──────────────────────────────────────────────────

export const NoteRef = TiptapNode.create({
  name: "noteRef",
  group: "inline",
  inline: true,
  atom: true,

  addAttributes() {
    return {
      type: { default: "document" },
      id: { default: null },
      label: { default: "" },
    };
  },

  parseHTML() {
    return [
      {
        tag: "span.note-ref",
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

// ─── Reference Clicks ────────────────────────────────────────────────────────

export function setupReferenceClicks() {
  const container = document.getElementById("note-editor");
  if (!container) return;

  const dropdown = document.getElementById("highlight-ref-dropdown");
  const detailLink = document.getElementById("highlight-ref-detail");
  const sourceLink = document.getElementById("highlight-ref-source");

  let currentHighlightId = null;

  document.addEventListener("click", (e) => {
    if (
      dropdown &&
      !dropdown.contains(e.target) &&
      !e.target.closest(".note-ref")
    ) {
      dropdown.classList.remove("show");
    }
  });

  if (detailLink) {
    detailLink.addEventListener("click", (e) => {
      e.preventDefault();
      dropdown.classList.remove("show");
      if (currentHighlightId) {
        htmx.ajax(
          "GET",
          "/case/highlights/" + currentHighlightId + "/detail/",
          {
            target: document.getElementById("htmx-modal-container"),
            swap: "innerHTML",
          },
        );
      }
    });
  }

  if (sourceLink) {
    sourceLink.addEventListener("click", (e) => {
      e.preventDefault();
      dropdown.classList.remove("show");

      if (currentHighlightId) {
        window.open(
          "/case/highlights/" + currentHighlightId + "/link/",
          "_blank",
        );
      }
    });
  }

  container.addEventListener("click", (e) => {
    const ref = e.target.closest(".note-ref");
    if (!ref) return;

    e.preventDefault();
    e.stopPropagation();

    const refType = ref.getAttribute("data-type");
    const refId = ref.getAttribute("data-id");

    if (!refId) return;

    if (refType === "document") {
      window.open("/documents/view/" + refId + "/", "_blank");
    } else if (refType === "highlight" && dropdown) {
      currentHighlightId = refId;
      const rect = ref.getBoundingClientRect();
      dropdown.style.position = "fixed";
      dropdown.style.left = rect.left + "px";
      dropdown.style.top = rect.bottom + 4 + "px";
      dropdown.classList.add("show");
    }
  });
}

// ─── Reference Citations ─────────────────────────────────────────────────────

function collectReferenceIds() {
  const docIds = [];
  const hlIds = [];

  state.editor.state.doc.descendants((node) => {
    if (node.type.name !== "noteRef") return;
    if (node.attrs.type === "document" && node.attrs.id)
      docIds.push(node.attrs.id);
    else if (node.attrs.type === "highlight" && node.attrs.id)
      hlIds.push(node.attrs.id);
  });

  return { docIds, hlIds };
}

export function refreshReferenceCitations() {
  if (!state.editor || !window.NOTE_DATA.citationsUrl) return;

  const refs = collectReferenceIds();
  if (refs.docIds.length === 0 && refs.hlIds.length === 0) return;

  const params = new URLSearchParams();
  refs.docIds.forEach((id) => params.append("doc", id));
  refs.hlIds.forEach((id) => params.append("hl", id));

  fetch(window.NOTE_DATA.citationsUrl + "?" + params.toString(), {
    headers: { "X-CSRFToken": getCSRFToken() },
  })
    .then((r) => r.json())
    .then((citations) => {
      const updates = [];
      state.editor.state.doc.descendants((node, pos) => {
        if (node.type.name !== "noteRef") return;
        const key =
          (node.attrs.type === "document" ? "doc:" : "hl:") + node.attrs.id;
        const newLabel = citations[key];

        if (newLabel && newLabel !== node.attrs.label) {
          updates.push({ pos, node, newLabel });
        }
      });

      updates.reverse().forEach((u) => {
        state.editor
          .chain()
          .setNodeMarkup(u.pos, null, {
            type: u.node.attrs.type,
            id: u.node.attrs.id,
            label: u.newLabel,
          })
          .run();
      });

      if (updates.length > 0) scheduleAutosave();
    })
    .catch((err) => console.error("Failed to refresh citations:", err));
}

// ─── Reference Picker ────────────────────────────────────────────────────────

export function setupReferencePicker() {
  const picker = document.getElementById("reference-picker");
  const searchInput = document.getElementById("reference-search");

  if (searchInput) {
    let searchTimer;

    searchInput.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => searchReferences(searchInput.value), 300);
    });

    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeReferencePicker();
    });
  }

  document
    .getElementById("reference-results")
    .addEventListener("click", (e) => {
      const tab = e.target.closest(".sources-tab");
      if (tab) {
        e.preventDefault();
        document
          .querySelectorAll("#reference-results .sources-tab")
          .forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        const tabName = tab.dataset.tab;
        document
          .querySelectorAll("#reference-results .sources-tab-content")
          .forEach((c) =>
            c.classList.toggle("hidden", c.dataset.tab !== tabName),
          );

        return;
      }

      const link = e.target.closest("a[data-type]");

      if (link) {
        e.preventDefault();

        insertReference(link.dataset.type, link.dataset.id, link.dataset.label);
      }
    });

  document.addEventListener("mousedown", (e) => {
    if (!picker || !picker.classList.contains("active")) return;
    if (picker.contains(e.target) || e.target.closest("#insert-source-btn"))
      return;

    closeReferencePicker();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && picker && picker.classList.contains("active")) {
      closeReferencePicker();
    }
  });
}

export function openReferencePicker() {
  const picker = document.getElementById("reference-picker");
  const searchInput = document.getElementById("reference-search");
  const results = document.getElementById("reference-results");

  if (state.editor && picker) {
    const { from } = state.editor.state.selection;
    const coords = state.editor.view.coordsAtPos(from);

    let top, left;
    if (coords && coords.bottom > 0) {
      top = coords.bottom + 8;
      left = coords.left;
    } else {
      const editorRect = document
        .getElementById("note-editor")
        .getBoundingClientRect();
      top = editorRect.top + 100;
      left = editorRect.left + 50;
    }

    const pickerWidth = 320;
    if (left + pickerWidth > window.innerWidth - 16) {
      left = window.innerWidth - pickerWidth - 16;
    }

    const pickerHeight = 400;
    if (top + pickerHeight > window.innerHeight - 16) {
      top = Math.max(100, coords ? coords.top - pickerHeight - 8 : 100);
    }

    picker.style.top = top + "px";
    picker.style.left = Math.max(16, left) + "px";
  }

  // Server-rendered HTML from trusted endpoint
  results.innerHTML =
    '<div class="sources-empty-state"><i class="icon-search"></i><p>Search for highlights and documents to insert</p></div>';
  picker.classList.add("active");
  searchInput.value = "";

  setTimeout(() => searchInput.focus({ preventScroll: true }), 10);
}

function closeReferencePicker() {
  const picker = document.getElementById("reference-picker");
  if (picker) picker.classList.remove("active");
  if (state.editor) state.editor.commands.focus();
}

function searchReferences(query) {
  if (!query.trim()) {
    // Static trusted HTML for empty state
    document.getElementById("reference-results").innerHTML =
      '<div class="sources-empty-state"><i class="icon-search"></i><p>Search for highlights and documents to insert</p></div>';
    return;
  }

  fetch(window.NOTE_DATA.searchUrl + "?q=" + encodeURIComponent(query), {
    headers: { "X-CSRFToken": getCSRFToken() },
  })
    .then((r) => r.text())
    .then((html) => {
      // Server-rendered HTML from trusted internal endpoint
      document.getElementById("reference-results").innerHTML = html;
    });
}

function insertReference(type, id, label) {
  state.editor
    .chain()
    .focus()
    .insertContent([
      { type: "noteRef", attrs: { type, id, label } },
      { type: "text", text: " " },
    ])
    .run();
  closeReferencePicker();
}
