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
    // Hues track the app's highlight set (--hl-violet/orange/blue/green/red/
    // yellow), at a slightly deeper-than-the-pale-fills, even-and-soft level
    // (chroma ~0.09) so bars read on a near-white page while staying on-aesthetic.
    // Ordered so the highlight set's warm cluster (red/orange/yellow) isn't
    // adjacent in the stack; teal is the one non-highlight hue, added for a 7th.
    // The Tailwind 150 level — one step up from the app's highlight fills (the
    // *-100 family): still soft and on-aesthetic, a touch more presence so
    // adjacent bars separate. Hues track the highlight set.
    light: [
      "oklch(91.9% 0.041 294.0deg)", // violet-150 (hl-violet family)
      "oklch(92.8% 0.055 73.0deg)", // orange-150
      "oklch(90.7% 0.045 254.9deg)", // blue-150
      "oklch(94.4% 0.062 156.4deg)", // green-150
      "oklch(91.1% 0.045 18.0deg)", // red-150
      "oklch(93.0% 0.060 181.0deg)", // teal (~150; complement for a 7th hue)
      "oklch(95.9% 0.097 102.4deg)", // yellow-150 (hl-yellow family)
    ],
    // Muted Gruvbox family: same hues as the bright accents but chroma pulled
    // down (~0.08, was up to 0.22) so they're soft on the dark surface, distinct
    // by hue rather than intensity.
    dark: [
      "oklch(0.72 0.075 165)", // muted aqua (signature)
      "oklch(0.73 0.085 60)", // muted orange
      "oklch(0.70 0.078 350)", // muted purple
      "oklch(0.70 0.068 240)", // muted blue
      "oklch(0.75 0.080 130)", // muted green
      "oklch(0.66 0.090 28)", // muted red
      "oklch(0.81 0.080 92)", // muted yellow
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
