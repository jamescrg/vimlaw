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

  // Compact label for the per-column total drawn atop each stacked bar.
  function formatTotal(value, metric) {
    if (metric === "fees") {
      if (value >= 1e6) return "$" + (value / 1e6).toFixed(1) + "M";
      if (value >= 1e3) return "$" + (value / 1e3).toFixed(1) + "k";
      return "$" + Math.round(value);
    }
    return Math.round(value) + "h";
  }

  // Draws the stack total (across visible series) above each bar.
  const stackTotalsPlugin = {
    id: "stackTotals",
    afterDatasetsDraw(chart) {
      const opts = (chart.options.plugins && chart.options.plugins.stackTotals) || {};
      const meta0 = chart.getDatasetMeta(0);
      if (!meta0 || !meta0.data || !meta0.data.length) return;
      const { ctx, scales } = chart;
      ctx.save();
      ctx.fillStyle = opts.color || "#666";
      ctx.font = "600 12px " + ((Chart.defaults.font && Chart.defaults.font.family) || "sans-serif");
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      const n = chart.data.labels.length;
      for (let i = 0; i < n; i++) {
        let total = 0;
        chart.data.datasets.forEach(function (ds, di) {
          if (chart.isDatasetVisible(di)) total += Number(ds.data[i]) || 0;
        });
        if (!total) continue;
        const bar = meta0.data[i];
        ctx.fillText(formatTotal(total, opts.metric), bar.x, scales.y.getPixelForValue(total) - 4);
      }
      ctx.restore();
    },
  };

  function buildDatasets(payload, state, theme) {
    const series = (payload.series && payload.series[state.dimension]) || [];
    const palette = window.AletheiaChartPalette;
    const isMatter = state.dimension === "matter";
    // A series is neutral (grey) if flagged, or the matter view's trailing "Other".
    const isNeutral = (s, i) =>
      s.neutral === true ||
      (isMatter && s.label === "Other" && i === series.length - 1);
    const coloredCount = series.filter((s, i) => !isNeutral(s, i)).length || 1;
    const colors = palette.make(coloredCount, theme);
    const grey = palette.neutral(theme);
    let ci = 0;
    return series.map((s, i) => ({
      label: s.label,
      data: s[state.metric] || [],
      backgroundColor: isNeutral(s, i) ? grey : colors[ci++],
      borderWidth: 0,
      borderRadius: 2,
      stack: "activity",
    }));
  }

  // Draws the selected metric's total in the centre of a doughnut.
  const donutCenterPlugin = {
    id: "donutCenter",
    afterDatasetsDraw(chart) {
      const opts = (chart.options.plugins && chart.options.plugins.donutCenter) || {};
      const meta = chart.getDatasetMeta(0);
      if (!meta || !meta.data || !meta.data.length) return;
      const { ctx } = chart;
      const total = (chart.data.datasets[0].data || []).reduce(
        (a, v) => a + (Number(v) || 0),
        0
      );
      const cx = (chart.chartArea.left + chart.chartArea.right) / 2;
      const cy = (chart.chartArea.top + chart.chartArea.bottom) / 2;
      ctx.save();
      ctx.fillStyle = opts.color || "#666";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const fam = (Chart.defaults.font && Chart.defaults.font.family) || "sans-serif";
      ctx.font = "600 16px " + fam;
      ctx.fillText("$" + Math.round(total).toLocaleString(), cx, cy);
      if (opts.label) {
        ctx.font = "12px " + fam;
        ctx.fillStyle = opts.muted || opts.color || "#999";
        ctx.fillText(opts.label, cx, cy + 18);
      }
      ctx.restore();
    },
  };

  function renderDonut(canvasId, dataElId, opts) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === "undefined") return;
    const payload = readPayload(dataElId);
    if (!payload) return;

    const prev = registry[canvasId] && registry[canvasId].state;
    const state = Object.assign({ metric: "net" }, prev, opts);
    registry[canvasId] = { dataElId, state, kind: "donut" };

    const theme = currentTheme();
    const themed = window.AletheiaChartPalette.axes(theme);
    const palette = window.AletheiaChartPalette;

    const values = payload[state.metric] || [];
    const labels = payload.labels || [];
    const total = values.reduce((a, v) => a + (Number(v) || 0), 0);

    // Slice colours: palette for the named slices, grey for a trailing "Other".
    const coloredCount = payload.hasOther ? Math.max(labels.length - 1, 1) : labels.length;
    const colors = palette.make(coloredCount, theme);
    const sliceColors = labels.map((_, i) =>
      payload.hasOther && i === labels.length - 1 ? palette.neutral(theme) : colors[i]
    );

    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    new Chart(canvas, {
      type: "doughnut",
      plugins: [donutCenterPlugin],
      data: {
        labels: labels,
        datasets: [{ data: values, backgroundColor: sliceColors, borderWidth: 0 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        plugins: {
          legend: {
            position: "bottom",
            labels: { color: themed.tick, boxWidth: 12, boxHeight: 12 },
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                const v = Number(ctx.parsed) || 0;
                const pct = total ? (v / total) * 100 : 0;
                return (
                  ctx.label +
                  ": " +
                  formatValue(v, "fees") +
                  " (" +
                  pct.toFixed(1) +
                  "%)"
                );
              },
            },
          },
          donutCenter: { color: themed.tick, muted: themed.grid, label: state.metricLabel },
        },
      },
    });

    startThemeObserver();
  }

  function updateDonut(canvasId, partialState) {
    const cfg = registry[canvasId];
    if (cfg) renderDonut(canvasId, cfg.dataElId, Object.assign({}, cfg.state, partialState));
  }

  function _donutStateFor(canvasId) {
    return registry[canvasId] ? registry[canvasId].state : null;
  }

  function render(canvasId, dataElId, opts) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === "undefined") return;
    const payload = readPayload(dataElId);
    if (!payload) return;

    const prev = registry[canvasId] && registry[canvasId].state;
    const state = Object.assign({ dimension: "user", metric: "fees" }, prev, opts);
    registry[canvasId] = { dataElId, state, kind: "bar" };

    const theme = currentTheme();
    const themed = window.AletheiaChartPalette.axes(theme);

    // Chart.js v4: tear down any instance already bound to this canvas.
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    new Chart(canvas, {
      type: "bar",
      plugins: [stackTotalsPlugin],
      data: {
        labels: payload.months,
        datasets: buildDatasets(payload, state, theme),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        // Headroom so the per-column total labels aren't clipped at the top.
        layout: { padding: { top: 18 } },
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
              text:
                state.metricLabel ||
                (state.metric === "fees" ? "Fees ($)" : "Hours"),
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
          stackTotals: { metric: state.metric, color: themed.tick },
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
      if (!document.getElementById(id)) return;
      const cfg = registry[id];
      if (cfg.kind === "donut") {
        renderDonut(id, cfg.dataElId, cfg.state);
      } else {
        render(id, cfg.dataElId, cfg.state);
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
    document.querySelectorAll("canvas[data-donut-data]").forEach(function (c) {
      if (c.id) renderDonut(c.id, c.dataset.donutData);
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoInit);
  } else {
    autoInit();
  }

  return { render, update, _stateFor, renderDonut, updateDonut, _donutStateFor };
})();
