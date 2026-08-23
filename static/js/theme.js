(function () {
  var STORAGE_KEY = 'theme';
  var media = window.matchMedia('(prefers-color-scheme: dark)');

  // Legacy: retired themes map to their nearest survivor — sky, kosmos,
  // latte, and everforest-light to light (Matcha); kosmos-dark and mocha
  // to dark (Gruvbox). oxford was renamed basic.
  var LEGACY = {
    sky: 'light',
    kosmos: 'light',
    latte: 'light',
    'everforest-light': 'light',
    'kosmos-dark': 'dark',
    mocha: 'dark',
    oxford: 'basic',
  };
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

  // Kappa mark path from static/images/kosmos-mark.svg (100x100 viewBox).
  var MARK_PATH =
    'M38.59 21.00Q37.47 25.35 37.47 48.80Q43.13 42.87 48.13 37.86Q56.37 29.62 ' +
    '57.95 27.76Q61.19 23.96 61.38 21.00H79.44Q76.76 23.13 70.64 29.52Q64.81 ' +
    '35.45 61.84 38.56Q58.88 41.66 58.60 41.94Q57.39 43.14 55.68 44.81Q53.97 ' +
    '46.48 51.83 48.61Q57.76 53.52 61.56 56.95Q75.09 69.64 81.02 79.00H64.44Q63.14 ' +
    '75.20 60.17 71.40Q58.88 69.83 56.47 67.37Q54.06 64.92 50.54 61.40Q42.48 ' +
    '53.43 37.47 50.09V66.96Q37.57 71.31 37.80 74.27Q38.03 77.24 38.49 79.00H24.78Q25.80 ' +
    '75.48 25.89 67.14Q25.89 49.91 25.89 40.36Q25.89 30.82 25.80 28.69Q25.71 ' +
    '26.56 25.48 24.66Q25.24 22.76 24.78 21.00Z';

  // Lucide "sparkles" (stroked), the AI chat windows' favicon.
  var SPARKLES_PATHS =
    '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 ' +
    '0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 ' +
    '0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 ' +
    '14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>' +
    '<path d="M20 3v4"/><path d="M22 5h-4"/><path d="M4 17v2"/><path d="M5 18H3"/>';

  // The favicon is its own document: it can see prefers-color-scheme but not
  // data-theme or the page's tokens. So themed icons are repainted here from
  // the resolved theme and handed over as a data URI. Only icons marked
  // data-favicon opt in: "brand" is the Kosmos mark (ground = --brand-ink,
  // what the sidebar mark wears; glyph = --background-body) and "ai" is the
  // sparkles the AI chat windows carry, stroked in --brand-ink. The dev mark
  // and the other per-app icons (notes, viewer) keep their fixed colours.
  function faviconSvg(kind, ink, ground) {
    if (kind === 'brand') {
      return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' +
        '<rect width="100" height="100" rx="18" style="fill:' + ink + '"/>' +
        '<path d="' + MARK_PATH + '" style="fill:' + ground + '"/></svg>'
      );
    }
    if (kind === 'ai') {
      return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" ' +
        'fill="none" stroke-width="2" stroke-linecap="round" ' +
        'stroke-linejoin="round" style="stroke:' + ink + '">' +
        SPARKLES_PATHS + '</svg>'
      );
    }
    return null;
  }

  function paintFavicon() {
    var link = document.querySelector('link[rel="icon"][data-favicon]');
    if (!link) return;
    var style = getComputedStyle(document.documentElement);
    var ink = style.getPropertyValue('--brand-ink').trim();
    var ground = style.getPropertyValue('--background-body').trim();
    if (!ink || !ground) return;
    var svg = faviconSvg(link.getAttribute('data-favicon'), ink, ground);
    if (!svg) return;
    link.setAttribute('href', 'data:image/svg+xml,' + encodeURIComponent(svg));
  }

  function apply(setting) {
    document.documentElement.setAttribute('data-theme', resolve(setting));
    paintFavicon();
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
  paintFavicon();
  document.body.addEventListener('htmx:afterSwap', syncRadios);

  media.addEventListener('change', function () {
    if (current() === 'auto') {
      apply('auto');
    }
  });
})();
