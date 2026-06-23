// Contacts: Clients & Folders off-canvas drawer (mobile only).
//
// The #folders sidebar is the left column on desktop; at <=768px it becomes a
// right-hand drawer opened by the floating folder button (#folders-fab). Mirrors
// the nav drawer in sidebar.js: event delegation off `document`, so it keeps
// working after htmx re-renders the contacts content.
(function () {
  function drawer() {
    return document.getElementById("folders");
  }

  function overlay() {
    return document.getElementById("folders-overlay");
  }

  function open() {
    drawer()?.classList.add("drawer-open");
    overlay()?.classList.add("visible");
  }

  function close() {
    drawer()?.classList.remove("drawer-open");
    overlay()?.classList.remove("visible");
  }

  document.addEventListener("click", function (e) {
    if (e.target.closest("#folders-fab")) {
      open();
      return;
    }
    if (e.target.closest("#folders-overlay")) {
      close();
      return;
    }
    // Tapping a client/folder link inside the drawer navigates — close it.
    if (e.target.closest("#folders a") && window.innerWidth <= 768) {
      close();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") close();
  });
})();
