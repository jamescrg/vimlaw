(function () {
  const sidebar = document.getElementById("sidebar");
  const toggle = document.getElementById("sidebar-toggle");
  const overlay = document.getElementById("sidebar-overlay");

  const STORAGE_KEY = "sidebar-collapsed";
  const APP_ALIASES = { case: "matters", events: "events" };
  const envClass = document.body.classList.contains("env-dev") ? "env-dev" : "";

  function openMobile() {
    sidebar.classList.add("mobile-open");
    overlay.classList.add("visible");
  }

  function closeMobile() {
    sidebar.classList.remove("mobile-open");
    overlay.classList.remove("visible");
  }

  function updateSidebarActive() {
    const segment = window.location.pathname.split("/")[1] || "tasks";

    const app = APP_ALIASES[segment] || segment;
    sidebar.querySelectorAll(".sidebar-nav li").forEach(function (li) {
      li.classList.remove("active");
    });

    const activeLink = sidebar.querySelector("#nav-" + app);
    if (activeLink) activeLink.closest("li").classList.add("active");
  }

  // Desktop collapse toggle
  toggle.addEventListener("click", function () {
    const collapsed =
      document.documentElement.classList.toggle("sidebar-collapsed");

    localStorage.setItem(STORAGE_KEY, collapsed);
  });

  document.addEventListener("click", function (e) {
    if (e.target.closest("#sidebar-mobile-trigger")) openMobile();
  });
  overlay.addEventListener("click", closeMobile);

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && sidebar.classList.contains("mobile-open")) {
      closeMobile();
    }
  });

  // Close mobile sidebar on any nav link click
  sidebar.addEventListener("click", function (e) {
    if (e.target.closest("a") && window.innerWidth <= 768) closeMobile();
  });

  // Cancel HTMX request if navigating to the current page
  sidebar.addEventListener("htmx:beforeRequest", function (e) {
    if (e.detail.elt.closest("li.active")) e.preventDefault();
  });

  // Sync body class and sidebar active state after HTMX content swap
  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target && e.detail.target.id === "main-content") {
      updateSidebarActive();

      const match = e.detail.xhr.response.match(/<body[^>]*class="([^"]*)"/);
      const newClasses = match ? match[1] : "";
      const preserved = envClass ? envClass + " " : "";

      document.body.className = (preserved + newClasses).trim();
    }
  });
})();
