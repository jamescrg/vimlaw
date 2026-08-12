// Autosave, save status, and multi-tab conflict handling for the editor
//
// Every save carries base_version — the exact updated_at string this tab
// last received — and the server 409s if another tab saved since. A 409
// (or a broadcast save landing while we're dirty) pauses editing behind
// a banner until the user reloads; a clean tab just reloads silently.

import { state, getCSRFToken } from "./state.js";
import { htmlToMarkdown } from "./markdown.js";
import { broadcast } from "./broadcast.js";

export function getMarkdownContent() {
  if (!state.editor) return "";

  return htmlToMarkdown(state.editor.getHTML());
}

// Clean = the buffer matches what this tab last saved (during the swap
// gap state.editor is null and this correctly reports clean)
export function isClean() {
  return getMarkdownContent() === state.lastSavedContent;
}

export function scheduleAutosave() {
  if (window.NOTE_DATA && window.NOTE_DATA.readOnly) return;
  if (state.conflict) return;
  if (state.autosaveTimer) clearTimeout(state.autosaveTimer);
  updateSaveStatus("unsaved");

  state.autosaveTimer = setTimeout(performAutosave, 2000);
}

export function performAutosave() {
  if (state.conflict) return;
  const content = getMarkdownContent();

  if (content === state.lastSavedContent) {
    updateSaveStatus("saved");

    return;
  }

  updateSaveStatus("saving");

  const formData = new FormData();
  formData.append("content", content);
  formData.append("base_version", window.NOTE_DATA.updatedAt || "");

  fetch(window.NOTE_DATA.autosaveUrl, {
    method: "POST",
    headers: { "X-CSRFToken": getCSRFToken() },
    body: formData,
  })
    .then((r) => {
      if (r.status === 409) {
        enterConflict();
        return null;
      }
      if (r.status === 404) {
        // The note was deleted from another tab (e.g. a folder-cascade
        // delete, which has no per-note broadcast); land on launch like
        // a direct delete would
        const container = document.getElementById("file-tree-container");
        if (container) window.location.assign(container.dataset.launchUrl);
        return null;
      }
      return r.json();
    })
    .then((data) => {
      if (data && data.saved) {
        state.lastSavedContent = content;
        window.NOTE_DATA.updatedAt = data.updated_at;
        updateSaveStatus("saved");
        document.body.dispatchEvent(new Event("noteSaved"));
        broadcast({
          type: "note-saved",
          noteId: window.NOTE_DATA.id,
          updatedAt: data.updated_at,
        });
      }
    })
    .catch(() => updateSaveStatus("unsaved"));
}

// ─── Conflict state ──────────────────────────────────────────────────────────

export function enterConflict() {
  if (state.conflict) return;
  state.conflict = true;
  if (state.autosaveTimer) clearTimeout(state.autosaveTimer);
  const banner = document.getElementById("note-conflict-banner");
  if (banner) banner.hidden = false;
  updateSaveStatus("conflict");
}

export function clearConflict() {
  state.conflict = false;
  const banner = document.getElementById("note-conflict-banner");
  if (banner) banner.hidden = true;
}

// Re-fetch the open note through the normal swap pipeline (editor
// rebuild + fresh NOTE_DATA); ?sync=1 keeps background reloads out of
// the recency trail
export function reloadNoteContent() {
  window.htmx.ajax(
    "GET",
    `${window.NOTE_DATA.contentPartialUrl}?sync=1`,
    { target: "#note-editor-container", swap: "innerHTML" },
  );
}

function updateSaveStatus(status) {
  const btn = document.getElementById("save-status-btn");
  if (!btn) return;

  const icon = btn.querySelector("i");
  if (!icon) return;

  if (status === "conflict") {
    icon.className = "icon-triangle-alert";
    btn.classList.add("active");
    btn.title = "Changed in another tab — reload to continue";
    return;
  }

  // Same disk glyph either way — the .active urgent tint signals unsaved
  icon.className = "icon-save";
  if (status === "saved") {
    btn.classList.remove("active");
    btn.title = "Saved";
  } else {
    btn.classList.add("active");
    btn.title = status === "saving" ? "Saving..." : "Unsaved changes";
  }
}

// ─── Unload flush ────────────────────────────────────────────────────────────

// Closing a tab inside the 2s debounce window would lose the edit;
// keepalive lets the request outlive the page (sendBeacon can't carry
// the CSRF header). base_version keeps a closing stale tab from
// stomping newer work. Bodies over ~64KB may be dropped by the browser;
// the regular debounced saves make that loss window tiny.
window.addEventListener("pagehide", () => {
  if (state.conflict || !state.editor) return;
  if (window.NOTE_DATA && window.NOTE_DATA.readOnly) return;
  const content = getMarkdownContent();
  if (content === state.lastSavedContent) return;
  const formData = new FormData();
  formData.append("content", content);
  formData.append("base_version", window.NOTE_DATA.updatedAt || "");
  fetch(window.NOTE_DATA.autosaveUrl, {
    method: "POST",
    headers: { "X-CSRFToken": getCSRFToken() },
    body: formData,
    keepalive: true,
  });
});
