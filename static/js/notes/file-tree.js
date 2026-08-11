// Files tab — folder expand/collapse for the standalone notes editor.
// The tree is server-rendered once per full page load (never htmx-swapped),
// so direct binding here is safe.

import { getCSRFToken } from "./state.js";

export function setupFileTree() {
  const tree = document.querySelector(".note-sidebar .file-tree");
  if (!tree) return; // matter editor renders the flat list instead

  tree.querySelectorAll(".file-tree-folder").forEach((li) => {
    const onToggle = (e) => {
      e.stopPropagation();
      li.classList.toggle("collapsed");
      // Fire-and-forget: expand state lives in the session, shared with
      // the Notes tab's folder sidebar (endpoint returns 204).
      fetch(li.dataset.toggleUrl, {
        method: "POST",
        headers: { "X-CSRFToken": getCSRFToken() },
      });
    };
    li.querySelector(":scope > .file-tree-toggle")?.addEventListener(
      "click",
      onToggle,
    );
    li.querySelector(":scope > .file-tree-name")?.addEventListener(
      "click",
      onToggle,
    );
  });
}
