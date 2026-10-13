"use strict";
function spInitPriceHistory() {
  if (window.__spPriceHistory) return;
  window.__spPriceHistory = true;
  const modalEl = document.getElementById("priceAnalyticsModal");
  if (!modalEl) return;
  const body = document.getElementById("price-modal-body");
  const loading = document.getElementById("price-modal-loading");
  const content = document.getElementById("price-modal-content");
  const canvas = document.getElementById("price-modal-trend");
  const rowsEl = document.getElementById("price-modal-rows");
  const moreBtn = document.getElementById("price-modal-more");
  const errorEl = document.getElementById("price-modal-error");
  const alertBox = document.getElementById("price-modal-alert");
  const chartEmpty = document.getElementById("price-modal-chart-empty");
  const countEl = document.getElementById("pm-count");
  const nameEl = document.getElementById("price-modal-product-name");
  const subtitle = document.getElementById("price-modal-subtitle");
  const baseUrl = body.dataset.historyUrlBase || "/api/products";
  let chart = null;
  let currentId = null;
  let fullTrend = [];
  let currentRange = "30";
  let nextCursor = null;
  let currency = body.dataset.currency || "EGP";

  const money = (value, cur = currency) => {
    const n = Number(value || 0) / 100;
    return `${n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${cur}${cur === "EGP" ? " (ج.م)" : ""}`;
  };
  const pct = (n) => (n === null || n === undefined ? "N/A" : `${n > 0 ? "+" : ""}${Number(n).toFixed(2)}%`);
  const signed = (n, c) => (n > 0 ? "+" : "") + money(n, c);

  function trendForRange(range) {
    if (range === "all") return fullTrend;
    const days = Number(range) || 30;
    const cutoff = Date.now() - days * 86400000;
    return fullTrend.filter((p) => {
      const t = Date.parse(p.timestamp);
      return Number.isNaN(t) || t >= cutoff;
    });
  }

  function renderStats(summary, cur) {
    currency = cur || currency;
    const set = (id, v) => { document.getElementById(id).textContent = v; };
    const setTrend = (id, n, suffix) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (n === null || n === undefined || Number(n) === 0) { el.hidden = true; return; }
      el.hidden = false;
      el.textContent = `${Number(n) > 0 ? "▲" : "▼"} ${suffix || ""}`.trim();
      el.classList.toggle("up", Number(n) > 0);
      el.classList.toggle("down", Number(n) < 0);
    };
    set("pm-current", money(summary.current, currency));
    set("pm-cost", money(summary.current_cost ?? summary.current, currency));
    set("pm-high", money(summary.highest, currency));
    set("pm-low", money(summary.lowest, currency));
    set("pm-avg", money(summary.average, currency));
    const latest = summary.latest;
    if (latest) {
      set("pm-last", signed(latest.change_amount, latest.currency || currency));
      set("pm-pct", pct(latest.change_percentage));
      setTrend("pm-last-trend", latest.change_amount, "vs previous");
      setTrend("pm-pct-trend", latest.change_percentage, "change");
    } else {
      set("pm-last", "—");
      set("pm-pct", "N/A");
      setTrend("pm-last-trend", 0);
      setTrend("pm-pct-trend", 0);
    }
    countEl.textContent = summary.count ?? 0;
    alertBox.hidden = !summary.alert;
  }

  function renderChart() {
    const points = trendForRange(currentRange);
    chartEmpty.hidden = points.length > 0;
    if (chart) { chart.destroy(); chart = null; }
    if (!points.length) return;
    const dark = document.documentElement.dataset.bsTheme === "dark";
    const sellingLabel = "Selling Price";
    const costLabel = "Cost Price";
    chart = new Chart(canvas, {
      type: "line",
      data: {
        labels: points.map((p) => p.date),
        datasets: [
          { label: sellingLabel, data: points.map((p) => p.new_price / 100), borderColor: "#438bff", backgroundColor: "#438bff17", fill: true },
          { label: costLabel, data: points.map((p) => p.new_cost / 100), borderColor: "#35cba2", backgroundColor: "transparent", fill: false },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: matchMedia("(prefers-reduced-motion: reduce)").matches ? false : { duration: 400 },
        interaction: { mode: "index", intersect: false },
        elements: { line: { tension: 0.3, borderWidth: 2 }, point: { radius: points.length > 15 ? 2 : 3, hoverRadius: 5 } },
        plugins: {
          legend: { position: "bottom", labels: { color: dark ? "#b3c3da" : "#63799e", font: { size: 10 }, boxWidth: 7, boxHeight: 7, usePointStyle: true } },
          tooltip: { backgroundColor: "#102138", padding: 10, callbacks: { title: (items) => points[items[0].dataIndex].date, label: (item) => `${item.dataset.label}: ${money(Math.round(item.parsed.y * 100), points[item.dataIndex].currency)}` } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: dark ? "#a2b4ce" : "#63799e", maxTicksLimit: 6, maxRotation: 0, font: { size: 9 } }, border: { display: false } },
          y: { grid: { color: dark ? "#29394e" : "#e8edf5" }, border: { display: false }, ticks: { color: dark ? "#a2b4ce" : "#63799e", maxTicksLimit: 5, font: { size: 9 }, callback: (v) => Number(v).toLocaleString("en-GB", { notation: "compact" }) } },
        },
      },
    });
  }

  function appendRows(items) {
    for (const row of items) {
      const tr = document.createElement("tr");
      const cells = [
        [row.date, row.source || ""],
        [money(row.old_price, row.currency), `Cost: ${money(row.old_cost, row.currency)}`],
        [money(row.new_price, row.currency), `Cost: ${money(row.new_cost, row.currency)}`],
        [`${row.change_amount > 0 ? "+" : ""}${money(row.change_amount, row.currency)} (${pct(row.change_percentage)})`, `Cost: ${pct(row.cost_change_percentage)}`],
        [row.changed_by || "—", row.product_name || ""],
      ];
      cells.forEach((v, i) => {
        const td = document.createElement("td");
        td.textContent = v[0];
        const small = document.createElement("small");
        small.textContent = v[1];
        td.append(small);
        if (i === 3) td.className = row.change_amount > 0 ? "ph-up" : row.change_amount < 0 ? "ph-down" : "";
        tr.append(td);
      });
      rowsEl.append(tr);
    }
  }

  async function loadHistoryPage(url) {
    const res = await fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    const data = await res.json();
    if (!res.ok) throw Error(data.error || "Unable to load price history.");
    return data;
  }

  let currentName = "";
  let currentSummary = null;

  function hideAdjustDrawer() {
    const drawer = document.getElementById("pm-adjust-drawer");
    if (drawer) drawer.hidden = true;
    const err = document.getElementById("pm-adjust-error");
    if (err) err.hidden = true;
  }

  function showAdjustDrawer() {
    const drawer = document.getElementById("pm-adjust-drawer");
    if (!drawer) return;
    drawer.hidden = false;
    const err = document.getElementById("pm-adjust-error");
    if (err) err.hidden = true;
    const priceIn = document.getElementById("pm-adjust-price");
    const costIn = document.getElementById("pm-adjust-cost");
    if (priceIn && currentSummary && currentSummary.current_price !== undefined) {
      priceIn.value = (Number(currentSummary.current_price || 0) / 100).toFixed(2);
    }
    if (costIn && currentSummary && currentSummary.current_cost !== undefined) {
      costIn.value = (Number(currentSummary.current_cost || 0) / 100).toFixed(2);
    }
    if (priceIn) priceIn.focus();
  }

  const adjustToggle = document.getElementById("pm-adjust-toggle");
  if (adjustToggle) adjustToggle.onclick = showAdjustDrawer;

  const adjustClose = document.getElementById("pm-adjust-close");
  if (adjustClose) adjustClose.onclick = hideAdjustDrawer;

  const adjustCancel = document.getElementById("pm-adjust-cancel");
  if (adjustCancel) adjustCancel.onclick = hideAdjustDrawer;

  const adjustSubmit = document.getElementById("pm-adjust-submit");
  if (adjustSubmit) {
    adjustSubmit.onclick = async () => {
      const priceIn = document.getElementById("pm-adjust-price");
      const costIn = document.getElementById("pm-adjust-cost");
      const err = document.getElementById("pm-adjust-error");
      if (!priceIn || !currentId) return;
      const priceVal = priceIn.value.trim();
      if (!priceVal) {
        if (err) {
          err.textContent = "Please enter a valid selling price.";
          err.hidden = false;
        }
        return;
      }
      adjustSubmit.disabled = true;
      try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
        const res = await fetch(`/api/products/${currentId}/adjust-price`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-CSRFToken": csrfToken,
          },
          credentials: "same-origin",
          body: JSON.stringify({
            price: priceVal,
            cost: costIn ? costIn.value.trim() : undefined,
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || "Failed to update price.");
        hideAdjustDrawer();
        await openModal(currentId, currentName);
      } catch (e) {
        if (err) {
          err.textContent = e.message;
          err.hidden = false;
        }
      } finally {
        adjustSubmit.disabled = false;
      }
    };
  }

  async function openModal(pid, pname) {
    currentId = pid;
    currentName = pname || "";
    hideAdjustDrawer();
    currentRange = "30";
    modalEl.querySelectorAll(".price-range a").forEach((a) => a.classList.toggle("active", a.dataset.range === "30"));
    nameEl.textContent = pname || "";
    subtitle.textContent = `Price History · Price Trend`;
    document.getElementById("pm-export-xlsx").href = `/products/${pid}/price-history/export/xlsx`;
    document.getElementById("pm-export-pdf").href = `/products/${pid}/price-history/export/pdf`;
    document.getElementById("pm-export-history").href = `/products/${pid}/price-history/export/xlsx`;
    const countBadge = document.getElementById("pm-image-count");
    if (countBadge) countBadge.textContent = "…";
    const galleryBtn = document.getElementById("pm-view-gallery");
    if (galleryBtn) {
      galleryBtn.onclick = () => {
        if (window.StoreProGallery) window.StoreProGallery.open(pid, pname || "Product Gallery");
      };
    }
    loading.hidden = false;
    content.hidden = true;
    errorEl.hidden = true;
    rowsEl.innerHTML = "";
    nextCursor = null;
    if (window.bootstrap?.Modal) bootstrap.Modal.getOrCreateInstance(modalEl).show();
    try {
      const [main, allTrend] = await Promise.all([
        loadHistoryPage(`${baseUrl}/${pid}/price-history`),
        loadHistoryPage(`${baseUrl}/${pid}/price-history?range=all`).catch(() => null),
      ]);
      currentSummary = main.summary;
      // Gallery count for the Product Images card (non-blocking on failure).
      fetch(`/api/products/${pid}/preview`, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then((r) => r.json())
        .then((preview) => {
          if (countBadge && Array.isArray(preview.images)) countBadge.textContent = String(preview.images.length);
        })
        .catch(() => { if (countBadge) countBadge.textContent = "0"; });
      currency = main.currency || currency;
      fullTrend = (allTrend && allTrend.summary && allTrend.summary.trend && allTrend.summary.trend.length ? allTrend.summary.trend : main.summary.trend) || [];
      renderStats(main.summary, main.currency);
      appendRows(main.items);
      nextCursor = main.next_cursor;
      moreBtn.hidden = !nextCursor;
      if (nextCursor) moreBtn.dataset.cursor = nextCursor;
      loading.hidden = true;
      content.hidden = false;
      renderChart();
      if (window.lucide) lucide.createIcons();
    } catch (e) {
      loading.hidden = true;
      content.hidden = true;
      errorEl.textContent = e.message;
      errorEl.hidden = false;
      content.hidden = false;
    }
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-price-analytics]");
    if (!btn) return;
    e.preventDefault();
    openModal(btn.getAttribute("data-price-analytics"), btn.getAttribute("data-product-name") || "");
  });

  modalEl.querySelectorAll(".price-range a").forEach((a) =>
    a.addEventListener("click", (e) => {
      e.preventDefault();
      currentRange = a.dataset.range;
      modalEl.querySelectorAll(".price-range a").forEach((x) => x.classList.toggle("active", x === a));
      renderChart();
    })
  );

  moreBtn.addEventListener("click", async () => {
    if (moreBtn.disabled || !nextCursor || !currentId) return;
    moreBtn.disabled = true;
    errorEl.hidden = true;
    try {
      const data = await loadHistoryPage(`${baseUrl}/${currentId}/price-history?before=${encodeURIComponent(nextCursor)}`);
      appendRows(data.items);
      nextCursor = data.next_cursor;
      moreBtn.hidden = !nextCursor;
      if (nextCursor) moreBtn.dataset.cursor = nextCursor;
    } catch (e) {
      errorEl.textContent = e.message;
      errorEl.hidden = false;
    } finally {
      moreBtn.disabled = false;
    }
  });

  // Delete confirms are handled centrally in row-menu.js via a delegated
  // submit listener, so cloned floating-menu forms are covered too.
}
document.addEventListener("DOMContentLoaded", spInitPriceHistory);
document.addEventListener("storepro:content", spInitPriceHistory);
