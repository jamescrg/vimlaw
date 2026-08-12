// Shared mutable state and helpers for the notes editor modules
// Every module imports this instead of maintaining its own references

export const state = {
  editor: null,
  autosaveTimer: null,
  lastSavedContent: "",
  searchMatches: [],
  currentMatchIndex: -1,
  langSelector: null,
  outlineTimer: null,
  // Another tab saved this note past us: editing is paused until the
  // user reloads (autosave.js enterConflict/clearConflict)
  conflict: false,
};

export function getCSRFToken() {
  const el = document.querySelector("[name=csrfmiddlewaretoken]");

  return el ? el.value : "";
}

export function bindClick(id, handler) {
  const el = document.getElementById(id);
  if (el) el.addEventListener("click", handler);

  return el;
}

export function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
