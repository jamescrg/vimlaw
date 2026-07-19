/**
 * KosmosChartPalette
 * ---------------------
 * Generates muted, theme-aware series colours for Chart.js so charts blend with
 * the project's monochrome + two-accent aesthetic instead of reading as a loud
 * rainbow. Colours are built in OKLCH at low, constant chroma, anchored on each
 * theme's accent hue (violet / gruvbox aqua / Nord frost / Kosmos amber); a gentle hue arc plus
 * a lightness ramp keeps adjacent stacked segments distinguishable. Chart.js v4
 * accepts oklch(...) strings directly as fill / grid / tick colours.
 *
 * make(n, theme)  -> array of n oklch() strings
 * axes(theme)     -> { grid, tick } oklch() strings for scales / legend
 * neutral(theme)  -> muted grey for catch-all / residual ("Other" / WIP) series
 * border(theme)   -> table-border colour (--border-medium) for outlining slices/bars
 */
window.KosmosChartPalette = (function () {
  const THEME = {
    // otherL = lightness of the near-neutral "Other" bucket. In light it sits
    // well above the series ramp so it recedes toward the page; in dark/cosmic
    // it stays mid so it recedes toward the dark surface.
    light: {
      // Violet family anchored on the --violet ramp (hue ~293, the app's
      // selection accent). Soft chroma so it reads as muted violet, not loud.
      hue: 293, hueSpan: 42, chroma: 0.07, lMin: 0.6, lMax: 0.82, otherL: 0.88,
      grid: "oklch(0.90 0 0)", tick: "oklch(0.45 0 0)",
    },
    kosmos: {
      // Same muted violet family as Matcha (violet is the emphasis accent
      // here too); neutral stone axes.
      hue: 293, hueSpan: 42, chroma: 0.07, lMin: 0.6, lMax: 0.82, otherL: 0.88,
      grid: "oklch(0.90 0 0)", tick: "oklch(0.45 0 0)",
    },
    dark: {
      hue: 142, hueSpan: 80, chroma: 0.06, lMin: 0.52, lMax: 0.76, otherL: 0.52,
      grid: "oklch(0.41 0.011 52)", tick: "oklch(0.69 0.035 76)",
    },
    cosmic: {
      hue: 210, hueSpan: 90, chroma: 0.055, lMin: 0.55, lMax: 0.8, otherL: 0.55,
      grid: "oklch(0.37 0.02 250)", tick: "oklch(0.78 0.03 250)",
    },
    "nord-light": {
      // Cosmic's frost arc at light-theme lightness; cool polar axes.
      hue: 210, hueSpan: 90, chroma: 0.055, lMin: 0.6, lMax: 0.82, otherL: 0.88,
      grid: "oklch(0.90 0.008 250)", tick: "oklch(0.45 0.02 250)",
    },
    "kosmos-dark": {
      // Warm arc around the brand amber (hue ~77): sienna through gold to
      // olive, low chroma so it reads as embers on the night, not neon.
      hue: 77, hueSpan: 80, chroma: 0.06, lMin: 0.52, lMax: 0.76, otherL: 0.52,
      grid: "#37322e", tick: "#a8a29e",
    },
  };

  function params(theme) {
    return THEME[theme] || THEME.light;
  }

  function make(n, theme, opts) {
    const t = params(theme);
    const otherLast = opts && opts.otherLast;
    const colored = otherLast ? Math.max(n - 1, 1) : n;
    const out = [];
    for (let i = 0; i < n; i++) {
      // The trailing "Other" bucket reads as a light, near-neutral residual.
      if (otherLast && i === n - 1) {
        out.push(`oklch(${t.otherL.toFixed(3)} 0.012 ${t.hue.toFixed(1)})`);
        continue;
      }
      const f = colored === 1 ? 0.5 : i / (colored - 1);
      const hue = t.hue - t.hueSpan / 2 + f * t.hueSpan;
      const l = t.lMin + f * (t.lMax - t.lMin);
      out.push(`oklch(${l.toFixed(3)} ${t.chroma} ${hue.toFixed(1)})`);
    }
    return out;
  }

  function axes(theme) {
    const t = params(theme);
    return { grid: t.grid, tick: t.tick };
  }

  // Catch-all / residual series ("Other"). Light is stone-250 — one step below
  // the table-header grey (stone-200), to offset the chart's lighter surround so
  // it reads the same. Dark/cosmic keep a mid-grey visible on the dark surface.
  const NEUTRAL = {
    light: "oklch(88.5% 0 none)",
    kosmos: "oklch(88.5% 0 none)",
    dark: "oklch(0.60 0.006 70)",
    cosmic: "oklch(0.62 0.006 250)",
    "nord-light": "oklch(88.5% 0.008 250)",
    "kosmos-dark": "#57534e",
  };

  function neutral(theme) {
    return NEUTRAL[theme] || NEUTRAL.light;
  }

  // One step darker than the table cell border (--border-medium-dark: stone-350
  // / gb-dark3 / nord3) so the outline separates cleanly against the light
  // 'Other' grey. Outlines donut slices and bar segments.
  const BORDER = {
    light: "oklch(83.5% 0 none)",
    kosmos: "oklch(83.5% 0 none)",
    dark: "oklch(0.482 0.018 61)",
    cosmic: "#4c566a",
    "nord-light": "oklch(0.815 0.015 250)",
    "kosmos-dark": "#44403c",
  };

  function border(theme) {
    return BORDER[theme] || BORDER.light;
  }

  return { make, axes, neutral, border };
})();
