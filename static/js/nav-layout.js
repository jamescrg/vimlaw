(function () {
  // Navigation layout is a per-user preference, persisted server-side (the
  // settings radios POST it via htmx) and rendered onto <html> pre-paint by the
  // bootstrap script in base.html. This only handles the instant client-side
  // switch when the user picks a layout, so the change is visible before the
  // save round-trips. Desktop only — the horizontal CSS is gated above 768px,
  // so small screens always get the sidebar regardless of the attribute.
  window.applyNavLayout = function (setting) {
    if (setting === 'horizontal') {
      document.documentElement.setAttribute('data-nav', 'horizontal');
    } else {
      document.documentElement.removeAttribute('data-nav');
    }
  };
})();
