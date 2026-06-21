/**
 * AletheiaChartPalette
 * ---------------------
 * Generates muted, theme-aware series colours for Chart.js so charts blend with
 * the project's monochrome + two-accent aesthetic instead of reading as a loud
 * rainbow. Colours are built in OKLCH at low, constant chroma, anchored on each
 * theme's accent hue (lime / gruvbox aqua / Nord frost); a gentle hue arc plus a
 * lightness ramp keeps adjacent stacked segments distinguishable. Chart.js v4
 * accepts oklch(...) strings directly as fill / grid / tick colours.
 *
 * make(n, theme)  -> array of n oklch() strings
 * axes(theme)     -> { grid, tick } oklch() strings for scales / legend
 */
window.AletheiaChartPalette = (function () {
  const THEME = {
    light: {
      // Violet family anchored on the --violet ramp (hue ~293, the app's
      // selection accent). Mid chroma so it reads clearly violet, not gray.
      hue: 293, hueSpan: 42, chroma: 0.11, lMin: 0.6, lMax: 0.82,
      grid: "oklch(0.90 0 0)", tick: "oklch(0.45 0 0)",
    },
    dark: {
      hue: 142, hueSpan: 80, chroma: 0.06, lMin: 0.52, lMax: 0.76,
      grid: "oklch(0.41 0.011 52)", tick: "oklch(0.69 0.035 76)",
    },
    cosmic: {
      hue: 210, hueSpan: 90, chroma: 0.055, lMin: 0.55, lMax: 0.8,
      grid: "oklch(0.37 0.02 250)", tick: "oklch(0.78 0.03 250)",
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
      // The trailing "Other" bucket reads as near-neutral residual.
      if (otherLast && i === n - 1) {
        out.push(`oklch(${t.lMin.toFixed(3)} 0.012 ${t.hue.toFixed(1)})`);
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

  return { make, axes };
})();
