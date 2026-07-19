(function () {
  var STORAGE_KEY = 'theme';
  var media = window.matchMedia('(prefers-color-scheme: dark)');

  // Legacy: retired themes map to their nearest survivor — sky and kosmos
  // to light (Matcha), kosmos-dark to dark (Gruvbox).
  var LEGACY = { sky: 'light', kosmos: 'light', 'kosmos-dark': 'dark' };
  var stored = localStorage.getItem(STORAGE_KEY);
  if (LEGACY[stored]) {
    localStorage.setItem(STORAGE_KEY, LEGACY[stored]);
  }

  function resolve(setting) {
    if (setting === 'auto') {
      return media.matches ? 'dark' : 'light';
    }
    return setting;
  }

  function apply(setting) {
    document.documentElement.setAttribute('data-theme', resolve(setting));
  }

  function current() {
    return localStorage.getItem(STORAGE_KEY) || 'auto';
  }

  window.setTheme = function (setting) {
    localStorage.setItem(STORAGE_KEY, setting);
    apply(setting);
  };

  window.getThemeSetting = current;

  // Reflect the stored setting onto the settings-page radios. Runs on load and
  // after every htmx swap, since the settings content arrives via a boosted
  // swap where an inline script would not reliably re-run.
  function syncRadios() {
    var input = document.querySelector(
      '.theme-options input[value="' + current() + '"]'
    );
    if (input) input.checked = true;
  }

  syncRadios();
  document.body.addEventListener('htmx:afterSwap', syncRadios);

  media.addEventListener('change', function () {
    if (current() === 'auto') {
      apply('auto');
    }
  });
})();
