/**
 * Toast Notification System
 * Works with HTMX via response headers or direct JavaScript calls
 * No external dependencies (vanilla JS)
 */

const Toast = (function () {
  const ICONS = {
    success: "icon-circle-check",
    error: "icon-alert-circle",
    warning: "icon-alert-triangle",
    info: "icon-info",
  };

  const COLORS = {
    success: "var(--success)",
    error: "var(--error)",
    warning: "var(--warning)",
    info: "var(--sky-600)",
  };

  const DEFAULTS = {
    duration: 5000, // Auto-dismiss after 5 seconds (0 = no auto-dismiss)
  };

  let container = null;

  function getContainer() {
    if (!container) {
      container = document.getElementById("toast-container");
      if (!container) {
        container = document.createElement("div");
        container.id = "toast-container";
        container.className = "toast-container position-fixed top-0 end-0 p-3";
        container.style.zIndex = "9999";
        document.body.appendChild(container);
      }
    }
    return container;
  }

  function createToastElement(options) {
    const { type, title, message, duration, link } = {
      ...DEFAULTS,
      ...options,
    };

    const toast = document.createElement("div");
    toast.className = "toast";
    toast.setAttribute("role", "alert");
    toast.setAttribute("aria-live", "assertive");
    toast.setAttribute("aria-atomic", "true");

    const icon = ICONS[type] || ICONS.info;
    const color = COLORS[type] || COLORS.info;

    let bodyContent = escapeHtml(message);
    if (link && link.url && link.text) {
      bodyContent += ` <a href="${escapeHtml(link.url)}" class="toast-link" hx-boost="false">${escapeHtml(link.text)}</a>`;
    }

    toast.innerHTML = `
      <div class="toast-header">
        <i class="bi ${icon} me-2" style="color: ${color};"></i>
        <strong class="me-auto">${escapeHtml(title || capitalize(type))}</strong>
        <button type="button" class="toast-close" aria-label="Close">
          <i class="icon-x"></i>
        </button>
      </div>
      <div class="toast-body">
        ${bodyContent}
      </div>
    `;

    return { element: toast, duration };
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  function hideToast(element) {
    element.classList.remove("show");
    element.classList.add("hiding");
    // Remove after transition
    setTimeout(() => {
      element.remove();
    }, 150);
  }

  /**
   * Show a toast notification
   * @param {Object} options - Toast options
   * @param {string} options.type - Toast type: success, error, warning, info
   * @param {string} options.title - Optional title (defaults to type name)
   * @param {string} options.message - Toast message
   * @param {number} options.duration - Auto-dismiss duration in ms (0 = no auto-dismiss)
   */
  function show(options) {
    const toastContainer = getContainer();
    const { element, duration } = createToastElement(options);
    toastContainer.appendChild(element);

    // Close button handler
    const closeBtn = element.querySelector(".toast-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => hideToast(element));
    }

    // Show with animation (use requestAnimationFrame for proper transition)
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        element.classList.add("show");
      });
    });

    // Auto-hide after duration
    if (duration > 0) {
      setTimeout(() => {
        if (element.parentElement) {
          hideToast(element);
        }
      }, duration);
    }

    return element;
  }

  // Convenience methods
  function success(message, title = "Success", duration = DEFAULTS.duration) {
    return show({ type: "success", message, title, duration });
  }

  function error(message, title = "Error", duration = 0) {
    // Errors don't auto-dismiss by default
    return show({ type: "error", message, title, duration });
  }

  function warning(message, title = "Warning", duration = DEFAULTS.duration) {
    return show({ type: "warning", message, title, duration });
  }

  function info(message, title = "Info", duration = DEFAULTS.duration) {
    return show({ type: "info", message, title, duration });
  }

  // Clear all toasts
  function clearAll() {
    const toastContainer = getContainer();
    const toasts = toastContainer.querySelectorAll(".toast");
    toasts.forEach((el) => hideToast(el));
  }

  return {
    show,
    success,
    error,
    warning,
    info,
    clearAll,
  };
})();

// HTMX Integration - Listen for HX-Toast header in responses
function handleToastHeaders(xhr) {
  if (!xhr) return;

  const toastHeader = xhr.getResponseHeader("HX-Toast");
  if (toastHeader) {
    try {
      const toastData = JSON.parse(toastHeader);
      Toast.show(toastData);
    } catch (e) {
      console.error("Failed to parse HX-Toast header:", e);
    }
  }

  const toastsHeader = xhr.getResponseHeader("HX-Toasts");
  if (toastsHeader) {
    try {
      const toasts = JSON.parse(toastsHeader);
      if (Array.isArray(toasts)) {
        toasts.forEach((t) => Toast.show(t));
      }
    } catch (e) {
      console.error("Failed to parse HX-Toasts header:", e);
    }
  }
}

document.addEventListener("htmx:beforeSwap", function (event) {
  handleToastHeaders(event.detail.xhr);
});
