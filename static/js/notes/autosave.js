// Autosave and save status for the notes editor

import { state, getCSRFToken } from "./state.js";
import { htmlToMarkdown } from "./markdown.js";

export function getMarkdownContent() {
  if (!state.editor) return "";

  return htmlToMarkdown(state.editor.getHTML());
}

export function scheduleAutosave() {
  if (state.autosaveTimer) clearTimeout(state.autosaveTimer);
  updateSaveStatus("unsaved");

  state.autosaveTimer = setTimeout(performAutosave, 2000);
}

export function performAutosave() {
  const content = getMarkdownContent();

  if (content === state.lastSavedContent) {
    updateSaveStatus("saved");

    return;
  }

  updateSaveStatus("saving");

  const formData = new FormData();
  formData.append("content", content);

  fetch(window.NOTE_DATA.autosaveUrl, {
    method: "POST",
    headers: { "X-CSRFToken": getCSRFToken() },
    body: formData,
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.saved) {
        state.lastSavedContent = content;
        updateSaveStatus("saved");
      }
    })
    .catch(() => updateSaveStatus("unsaved"));
}

function updateSaveStatus(status) {
  const btn = document.getElementById("save-status-btn");
  if (!btn) return;

  const icon = btn.querySelector("i");
  if (!icon) return;

  if (status === "saved") {
    btn.classList.remove("active");
    btn.title = "Saved";
    icon.className = "icon-cloud";
  } else {
    btn.classList.add("active");
    btn.title = status === "saving" ? "Saving..." : "Unsaved changes";
    icon.className = "icon-cloud-upload";
  }
}
