/**
 * AletheiaActivityChart
 * ---------------------
 * Chart.js lifecycle for the Activity report's stacked bar chart. The <canvas>
 * lives inside the HTMX-swapped #activity-reports fragment, so this module is
 * built to re-init on every swap without leaking Chart instances, to keep the
 * By User / By Matter and Hours / Fees toggle selection across swaps, and to
 * recolour live when the theme changes.
 *
 *   render(canvasId, dataElId, opts?)  - (re)build the chart from a json_script payload
 *   update(canvasId, partialState)     - flip dimension/metric without refetching
 *   _stateFor(canvasId)                - current {dimension, metric} (used to re-seed Alpine)
 */
window.AletheiaActivityChart = (function () {
  let themeObserverStarted = false;
  // Remembers the last payload element + toggle state per canvas, so an HTMX
  // re-swap or a theme change can rebuild with the same selection.
  const registry = {};

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") || "light";
  }

  function readPayload(dataElId) {
    const el = document.getElementById(dataElId);
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  function formatValue(value, metric) {
    if (metric === "fees") {
      return "$" + Number(value).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    }
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }) + "h";
  }

  function buildDatasets(payload, state, theme) {
    const series = (payload.series && payload.series[state.dimension]) || [];
    const isMatter = state.dimension === "matter";
    const otherLast =
      isMatter && series.length > 0 && series[series.length - 1].label === "Other";
    const colors = window.AletheiaChartPalette.make(series.length, theme, { otherLast });
    return series.map((s, i) => ({
      label: s.label,
      data: s[state.metric] || [],
      backgroundColor: colors[i],
      borderWidth: 0,
      borderRadius: 2,
      stack: "activity",
    }));
  }

  function render(canvasId, dataElId, opts) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === "undefined") return;
    const payload = readPayload(dataElId);
    if (!payload) return;

    const prev = registry[canvasId] && registry[canvasId].state;
    const state = Object.assign({ dimension: "user", metric: "hours" }, prev, opts);
    registry[canvasId] = { dataElId, state };

    const theme = currentTheme();
    const themed = window.AletheiaChartPalette.axes(theme);

    // Chart.js v4: tear down any instance already bound to this canvas.
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    new Chart(canvas, {
      type: "bar",
      data: {
        labels: payload.months,
        datasets: buildDatasets(payload, state, theme),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            stacked: true,
            grid: { display: false },
            ticks: { color: themed.tick },
          },
          y: {
            stacked: true,
            beginAtZero: true,
            grid: { color: themed.grid },
            ticks: {
              color: themed.tick,
              callback: function (value) {
                return state.metric === "fees" ? "$" + value : value;
              },
            },
            title: {
              display: true,
              text: state.metric === "fees" ? "Fees ($)" : "Hours",
              color: themed.tick,
            },
          },
        },
        plugins: {
          legend: {
            position: "bottom",
            labels: { color: themed.tick, boxWidth: 12, boxHeight: 12, usePointStyle: false },
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ctx.dataset.label + ": " + formatValue(ctx.parsed.y, state.metric);
              },
            },
          },
        },
      },
    });

    startThemeObserver();
  }

  function update(canvasId, partialState) {
    const cfg = registry[canvasId];
    if (cfg) render(canvasId, cfg.dataElId, Object.assign({}, cfg.state, partialState));
  }

  function rerenderAll() {
    Object.keys(registry).forEach(function (id) {
      if (document.getElementById(id)) {
        render(id, registry[id].dataElId, registry[id].state);
      }
    });
  }

  function _stateFor(canvasId) {
    return registry[canvasId] ? registry[canvasId].state : null;
  }

  function startThemeObserver() {
    if (themeObserverStarted) return;
    themeObserverStarted = true;
    new MutationObserver(function (mutations) {
      if (mutations.some((m) => m.attributeName === "data-theme")) rerenderAll();
    }).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
  }

  // Destroy a chart whose canvas is about to be removed by an HTMX swap
  // (e.g. the user clears the date range and the no-filter message replaces it).
  document.body.addEventListener("htmx:beforeCleanupElement", function (e) {
    const node = e.target;
    if (!node || typeof Chart === "undefined") return;
    const canvases = [];
    if (node.tagName === "CANVAS") canvases.push(node);
    if (node.querySelectorAll) {
      node.querySelectorAll("canvas").forEach((c) => canvases.push(c));
    }
    canvases.forEach(function (c) {
      const inst = Chart.getChart(c);
      if (inst) inst.destroy();
    });
  });

  // Initial full-page load: the inline render script inside the report fragment
  // runs while parsing, BEFORE this (end-of-body) module is defined, so its guard
  // no-ops. Pick up any charts present at load time here. Subsequent HTMX swaps
  // re-run that inline script, by which point this module already exists.
  function autoInit() {
    document.querySelectorAll("canvas[data-chart-data]").forEach(function (c) {
      if (c.id) render(c.id, c.dataset.chartData);
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoInit);
  } else {
    autoInit();
  }

  return { render, update, _stateFor };
})();
