/**
 * AletheiaChartPalette
 * ---------------------
 * Theme-aware *categorical* series colours for Chart.js. The earlier scheme was
 * a single accent hue + lightness ramp, which left adjacent stacked segments too
 * close to tell apart. This uses a distinct hue per series, drawn from each
 * theme's own accent family so the charts stay on-palette across all three
 * themes while reading as clearly multi-colour:
 *   - light  : the project's Tailwind accent ramps (violet brand + complements)
 *   - dark   : Gruvbox bright accents (the --gb-bright-* family)
 *   - cosmic : Nord Aurora + Frost accents (--nord*)
 *
 * make(n, theme)  -> array of n colour strings (cycles only if n exceeds the set)
 * neutral(theme)  -> muted grey for catch-all / residual ("Other" / WIP) series
 * axes(theme)     -> { grid, tick } for scales / legend
 *
 * Chart.js v4 accepts oklch(...) and hex strings directly as fill colours.
 */
window.AletheiaChartPalette = (function () {
  // Ordered for maximum contrast between adjacent stacked segments. Values are
  // the themes' own accent tokens (static/css/palette.css + colors.css) so the
  // charts stay on-palette; charts here have < 8 series, so cycling is moot.
  const CATEGORICAL = {
    light: [
      "oklch(60.6% 0.219 292.7deg)", // violet-500 (brand accent)
      "oklch(76.9% 0.165 70.1deg)", // amber-500
      "oklch(70.4% 0.123 182.5deg)", // teal-500
      "oklch(64.5% 0.215 16.4deg)", // rose-500
      "oklch(62.3% 0.188 259.8deg)", // blue-500
      "oklch(72.3% 0.192 149.6deg)", // green-500
      "oklch(66.7% 0.259 322.1deg)", // fuchsia-500
      "oklch(60.9% 0.111 221.7deg)", // cyan-600
    ],
    dark: [
      "oklch(0.756 0.108 138)", // gb-bright-aqua (signature)
      "oklch(0.731 0.182 52)", // gb-bright-orange
      "oklch(0.705 0.098 2)", // gb-bright-purple
      "oklch(0.700 0.075 233)", // gb blue (nudged off aqua for separation)
      "oklch(0.765 0.158 111)", // gb-bright-green
      "oklch(0.660 0.217 30)", // gb-bright-red
      "oklch(0.840 0.150 90)", // gb bright-yellow
    ],
    cosmic: [
      "#88c0d0", // nord8  Frost cyan (signature)
      "#d08770", // nord12 Aurora orange
      "#b48ead", // nord15 Aurora purple
      "#a3be8c", // nord14 Aurora green
      "#81a1c1", // nord9  Frost blue
      "#bf616a", // nord11 Aurora red
      "#ebcb8b", // nord13 Aurora yellow
      "#8fbcbb", // nord7  Frost teal
    ],
  };

  function make(n, theme) {
    const list = CATEGORICAL[theme] || CATEGORICAL.light;
    const out = [];
    for (let i = 0; i < n; i++) out.push(list[i % list.length]);
    return out;
  }

  const AXES = {
    light: { grid: "oklch(0.90 0 0)", tick: "oklch(0.45 0 0)" },
    dark: { grid: "oklch(0.41 0.011 52)", tick: "oklch(0.69 0.035 76)" },
    cosmic: { grid: "oklch(0.37 0.02 250)", tick: "oklch(0.78 0.03 250)" },
  };

  function axes(theme) {
    return AXES[theme] || AXES.light;
  }

  // A muted grey for catch-all / residual series ("Other" / Unbilled WIP).
  const NEUTRAL = {
    light: "oklch(0.74 0.004 286)",
    dark: "oklch(0.60 0.006 70)",
    cosmic: "oklch(0.62 0.006 250)",
  };

  function neutral(theme) {
    return NEUTRAL[theme] || NEUTRAL.light;
  }

  return { make, axes, neutral };
})();
