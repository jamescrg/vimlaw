/* AI chat history panel: bottom collapse toggle + drag-to-resize.
   Shared by the case AI, agenda, and intake chat windows, which render the
   same .ai-chat-sidebar markup. Mirrors the notes editor's panel: the
   toggle glyph tracks state (an open panel shows the close glyph), and the
   resizer drags to resize with double-click to reset. */
(function () {
  const sidebar = document.getElementById("historySidebar");
  if (!sidebar) return;

  const WIDTH_KEY = "ai-history-panel-width";
  const MIN_WIDTH = 180;
  const MAX_WIDTH = 480;

  function syncIcon() {
    const icon = sidebar.querySelector(".ai-sidebar-toggle i");
    if (icon)
      icon.className =
        "icon-panel-left-" +
        (sidebar.classList.contains("collapsed") ? "open" : "close");
  }

  // Global: the toggle button wires up via an onclick attribute.
  window.toggleSidebar = function () {
    sidebar.classList.toggle("collapsed");
    syncIcon();
  };

  const resizer = sidebar.querySelector(".ai-sidebar-resizer");
  if (resizer) {
    const stored = parseInt(localStorage.getItem(WIDTH_KEY), 10);
    if (stored) sidebar.style.setProperty("--ai-sidebar-width", stored + "px");

    resizer.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      resizer.setPointerCapture(e.pointerId);
      sidebar.classList.add("resizing");
      const startX = e.clientX;
      const startWidth = sidebar.offsetWidth;

      const onMove = (ev) => {
        const width = Math.min(
          MAX_WIDTH,
          Math.max(MIN_WIDTH, startWidth + ev.clientX - startX),
        );
        sidebar.style.setProperty("--ai-sidebar-width", width + "px");
      };
      const onUp = () => {
        resizer.removeEventListener("pointermove", onMove);
        resizer.removeEventListener("pointerup", onUp);
        sidebar.classList.remove("resizing");
        localStorage.setItem(WIDTH_KEY, String(sidebar.offsetWidth));
      };
      resizer.addEventListener("pointermove", onMove);
      resizer.addEventListener("pointerup", onUp);
    });

    resizer.addEventListener("dblclick", () => {
      sidebar.style.removeProperty("--ai-sidebar-width");
      localStorage.removeItem(WIDTH_KEY);
    });
  }

  syncIcon();
})();
