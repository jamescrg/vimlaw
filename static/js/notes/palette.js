// Notes search palette (Ctrl+K) — open, keyboard nav, jump-to-match
// handoff. Bound ONCE from the editor's DOMContentLoaded (never from
// setupKeyboardShortcuts, which re-binds on every note switch).

export function setupPalette() {
  const btn = document.getElementById("notes-palette-btn");
  const paletteUrl = btn ? btn.getAttribute("hx-get") : null;

  function getPalette() {
    return document.querySelector("#htmx-modal-container .notes-palette");
  }

  function openPalette() {
    if (getPalette()) {
      const input = document.getElementById("palette-input");
      if (input) input.focus();
      return;
    }
    if (paletteUrl) {
      window.htmx.ajax("GET", paletteUrl, { target: "#htmx-modal-container" });
    }
  }

  // Ctrl/Cmd+K — no contenteditable guard, so it works with the caret in
  // TipTap; preventDefault beats the browser's focus-address-bar binding
  document.addEventListener("keydown", (e) => {
    if (
      (e.ctrlKey || e.metaKey) &&
      !e.shiftKey &&
      !e.altKey &&
      e.key.toLowerCase() === "k"
    ) {
      e.preventDefault();
      openPalette();
    }
  });

  // A debounced results POST that lands after close() would swap into the
  // closing modal; kill it whenever the palette is going away
  function abortPendingResults() {
    const input = document.getElementById("palette-input");
    if (input) window.htmx.trigger(input, "htmx:abort");
  }

  // Palette-local keys: the input keeps focus throughout (no modes);
  // Escape is Alpine's own close
  document.addEventListener("keydown", (e) => {
    const palette = getPalette();
    if (!palette) return;
    if (e.key === "Escape") {
      abortPendingResults();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const rows = [...palette.querySelectorAll(".palette-row")];
      if (!rows.length) return;
      const delta = e.key === "ArrowDown" ? 1 : -1;
      const cur = rows.findIndex((r) => r.classList.contains("active"));
      const next =
        cur < 0
          ? delta === 1
            ? 0
            : rows.length - 1
          : (cur + delta + rows.length) % rows.length;
      rows.forEach((r) => r.classList.remove("active"));
      rows[next].classList.add("active");
      rows[next].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      const target =
        palette.querySelector(".palette-row.active") ||
        palette.querySelector(".palette-row");
      if (target) target.click();
    }
  });

  // Stash the query before a full-text row's note request fires; the
  // editor's initEditor tail consumes window.pendingDocSearch after the
  // re-init, which makes the jump-to-match race-free
  document.body.addEventListener("htmx:beforeRequest", (e) => {
    const elt = e.detail.elt;
    if (elt && elt.classList && elt.classList.contains("palette-row")) {
      window.pendingDocSearch = elt.dataset.searchTerm || null;
    }
  });

  // Close only after the note actually swapped in — Alpine's close wipes
  // the modal's innerHTML, which would detach an in-flight row request
  document.body.addEventListener("htmx:afterSwap", (e) => {
    if (
      e.detail.target &&
      e.detail.target.id === "note-editor-container" &&
      getPalette()
    ) {
      abortPendingResults();
      window.dispatchEvent(new CustomEvent("close-modal"));
    }
  });
}
