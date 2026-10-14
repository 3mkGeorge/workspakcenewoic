"use strict";
document.addEventListener("DOMContentLoaded", () => {
  const icons = () => window.lucide?.createIcons();
  const root = document.documentElement;
  try {
    const preference = localStorage.getItem("storepro-theme");
    if (preference) root.dataset.bsTheme = preference;
  } catch {}
  const syncThemeIcon = () => {
    document.querySelectorAll('[data-action="theme"]').forEach((button) => {
      const dark = root.dataset.bsTheme === "dark";
      button.setAttribute("aria-pressed", String(dark));
      button.innerHTML = `<i data-lucide="${dark ? "sun" : "moon"}"></i>`;
    });
  };
  syncThemeIcon();
  icons();
  const toast = (message) => {
    const el = document.getElementById("app-toast");
    if (el) {
      el.querySelector(".toast-body").textContent = message;
      bootstrap.Toast.getOrCreateInstance(el).show();
    }
  };
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-action]");
    if (!el) return;
    if (el.dataset.action === "theme") {
      root.dataset.bsTheme = root.dataset.bsTheme === "dark" ? "light" : "dark";
      try {
        localStorage.setItem("storepro-theme", root.dataset.bsTheme);
      } catch {}
      syncThemeIcon();
      icons();
      redrawCharts();
      document.dispatchEvent(new CustomEvent("storepro:theme"));
    }
    if (el.dataset.action === "sidebar")
      document.getElementById("sidebar").classList.toggle("is-open");
    if (el.dataset.action === "print") window.print();
    if (el.dataset.action === "back")
      window.history.length > 1 ? history.back() : location.assign("/");
  });
  document.addEventListener("click", (e) => {
    const bar = document.getElementById("sidebar");
    if (
      bar?.classList.contains("is-open") &&
      !bar.contains(e.target) &&
      !e.target.closest('[data-action="sidebar"]')
    )
      bar.classList.remove("is-open");
  });
  document.addEventListener("keydown", (e) => {
    if (
      e.key === "/" &&
      !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)
    ) {
      e.preventDefault();
      document.querySelector(".global-search input")?.focus();
    }
  });
  function bindConfirms(scope) {
    scope.querySelectorAll("form[data-confirm]:not([data-sp-confirm])").forEach((form) => {
      form.dataset.spConfirm = "1";
      form.addEventListener("submit", (event) => {
        if (!confirm(form.dataset.confirm)) event.preventDefault();
      });
    });
  }
  const SERIES = ["#2563eb", "#8b5cf6", "#10b981", "#f59e0b", "#06b6d4", "#ef4444"];
  const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
  const ISO_MONTH = /^\d{4}-\d{2}$/;
  function shortLabel(label) {
    const text = String(label ?? "");
    const locale = root.lang === "ar" ? "ar-EG" : "en-GB";
    if (ISO_DAY.test(text))
      return new Date(`${text}T00:00:00`).toLocaleDateString(locale, { day: "2-digit", month: "short" });
    if (ISO_MONTH.test(text))
      return new Date(`${text}-01T00:00:00`).toLocaleDateString(locale, { month: "short", year: "2-digit" });
    return text.length > 14 ? `${text.slice(0, 13)}…` : text;
  }
  const compact = (v) => {
    const n = Math.abs(v);
    if (n >= 1e6) return `${+(v / 1e6).toFixed(1)}M`;
    if (n >= 1e3) return `${+(v / 1e3).toFixed(1)}k`;
    return v;
  };
  function initCharts(scope) {
    scope.querySelectorAll("canvas[data-chart]:not([data-sp-chart])").forEach((canvas) => {
      if (!window.Chart) return;
      canvas.dataset.spChart = "1";
      window.Chart.getChart?.(canvas)?.destroy();
      const data = JSON.parse(canvas.dataset.chart);
      const type = canvas.dataset.type || "line";
      const horizontal = canvas.dataset.indexAxis === "y";
      const dark = root.dataset.bsTheme === "dark";
      const grid = dark ? "rgba(148,163,184,0.12)" : "#eef1f6";
      Chart.defaults.font.family = "Inter, Arabic, sans-serif";
      Chart.defaults.font.size = 11;
      Chart.defaults.color = dark ? "#8d9cb4" : "#64748b";
      if (type === "line")
        data.datasets.forEach((ds, i) => {
          const color = SERIES[i % SERIES.length];
          Object.assign(ds, {
            borderColor: color,
            backgroundColor: `${color}${i === 0 ? "1f" : "00"}`,
            pointBackgroundColor: color,
            fill: i === 0,
            tension: 0.35,
            pointRadius: data.labels.length > 31 ? 0 : 2.5,
            pointHoverRadius: 5,
            borderWidth: 2,
          });
        });
      if (type === "bar")
        data.datasets.forEach((ds, i) => {
          if (ds.type === "line") {
            Object.assign(ds, { borderColor: "#10b981", backgroundColor: "#10b981", tension: 0.35, pointRadius: 2, borderWidth: 2 });
            return;
          }
          Object.assign(ds, {
            backgroundColor: SERIES[i % SERIES.length],
            hoverBackgroundColor: "#1d4ed8",
            borderRadius: 4,
            maxBarThickness: horizontal ? 16 : 32,
            categoryPercentage: 0.7,
          });
        });
      if (type === "doughnut")
        data.datasets.forEach((ds) => Object.assign(ds, { borderColor: dark ? "#111a2b" : "#fff", borderWidth: 2 }));
      if (horizontal) {
        const wrap = canvas.parentElement;
        if (wrap) wrap.style.height = `${Math.max(200, data.labels.length * 26 + 48)}px`;
      }
      const categoryTicks = {
        maxRotation: 0,
        autoSkip: !horizontal,
        autoSkipPadding: 12,
        callback(value) {
          return shortLabel(this.getLabelForValue(value));
        },
      };
      const valueTicks = { maxTicksLimit: 5, callback: compact };
      new Chart(canvas, {
        type,
        data,
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          indexAxis: horizontal ? "y" : "x",
          cutout: "72%",
          interaction: { mode: "index", intersect: false },
          plugins: {
            legend: {
              display: type === "line" || data.datasets.length > 1,
              position: "top",
              align: "end",
              rtl: root.dir === "rtl",
              labels: { usePointStyle: true, pointStyle: "circle", boxWidth: 6, boxHeight: 6, padding: 16 },
            },
            tooltip: {
              padding: 10,
              backgroundColor: "#0f172a",
              titleColor: "#f8fafc",
              bodyColor: "#e2e8f0",
              cornerRadius: 8,
              rtl: root.dir === "rtl",
              callbacks: { title: (items) => items.map((item) => item.label) },
            },
          },
          scales:
            type === "doughnut"
              ? {}
              : {
                  x: horizontal
                    ? { beginAtZero: true, grid: { color: grid }, border: { display: false }, ticks: valueTicks }
                    : { grid: { display: false }, border: { display: false }, ticks: categoryTicks },
                  y: horizontal
                    ? { grid: { display: false }, border: { display: false }, ticks: categoryTicks }
                    : { beginAtZero: true, grid: { color: grid }, border: { display: false }, ticks: valueTicks },
                },
        },
      });
    });
  }
  function redrawCharts() {
    document.querySelectorAll("canvas[data-chart][data-sp-chart]").forEach((canvas) => {
      window.Chart?.getChart?.(canvas)?.destroy();
      delete canvas.dataset.spChart;
    });
    initCharts(document);
  }
  // Product images: CSP forbids inline onerror handlers, so failures are handled here.
  function imageFallback(img) {
    const full = img.dataset.full;
    if (full && !img.dataset.triedFull) {
      img.dataset.triedFull = "1";
      img.src = full;
      return;
    }
    const placeholder = document.createElement("span");
    placeholder.className = `${img.className} product-icon`.trim();
    placeholder.setAttribute("role", "img");
    placeholder.setAttribute("aria-label", img.alt || "");
    placeholder.innerHTML = '<i data-lucide="package"></i>';
    img.replaceWith(placeholder);
    icons();
  }
  document.addEventListener(
    "error",
    (e) => {
      const img = e.target;
      if (img instanceof HTMLImageElement && img.matches("img.product-thumb, img[data-fallback]")) imageFallback(img);
    },
    true,
  );
  function sweepBrokenImages(scope) {
    scope.querySelectorAll("img.product-thumb, img[data-fallback]").forEach((img) => {
      if (img.complete && img.naturalWidth === 0 && img.getAttribute("src")) imageFallback(img);
    });
  }
  window.addEventListener("pageshow", () => {
    document.querySelectorAll(".transaction-form").forEach((f) => {
      f.dataset.submitting = "0";
      const button = f.querySelector(".form-footer button");
      if (button) {
        button.disabled = false;
        button.textContent = document.documentElement.lang === "ar" ? "حفظ" : "Save";
      }
    });
  });
  function initTransactionForm(form) {
    if (form.dataset.spForm) return;
    form.dataset.spForm = "1";
    const body = document.getElementById("line-items");
  const template = document.getElementById("line-template");
  const purchase = form.dataset.kind === "purchase";
  const format = (cents) =>
    new Intl.NumberFormat(document.documentElement.lang === "ar" ? "ar-EG" : "en-EG", {
      style: "currency",
      currency: form.dataset.currency,
    }).format(cents / 100);
  function calculate() {
    let subtotal = 0;
    body.querySelectorAll("tr").forEach((row) => {
      const option = row.querySelector(".line-product").selectedOptions[0];
      const qty = Number(row.querySelector(".line-quantity").value) || 0;
      const price = purchase
        ? Math.round((Number(row.querySelector(".line-cost").value) || 0) * 100)
        : Number(option?.dataset.price || 0);
      if (!purchase) row.querySelector(".unit-price").textContent = format(price);
      row.querySelector(".line-total").textContent = format(price * qty);
      subtotal += price * qty;
    });
    const discount = Math.round((Number(form.querySelector("[name=discount]")?.value) || 0) * 100);
    const tax = Math.round((Math.max(0, subtotal - discount) * Number(form.dataset.tax)) / 100);
    document.getElementById("subtotal-value").textContent = format(subtotal);
    document.getElementById("tax-value").textContent = format(tax);
    document.getElementById("total-value").textContent = format(subtotal - discount + tax);
  }
  function addLine(id) {
    const clone = template.content.cloneNode(true);
    body.appendChild(clone);
    const row = body.lastElementChild;
    if (id) {
      row.querySelector(".line-product").value = id;
      if (purchase)
        row.querySelector(".line-cost").value = (
          Number(row.querySelector(".line-product").selectedOptions[0]?.dataset.cost || 0) / 100
        ).toFixed(2);
    }
    icons();
    calculate();
    return row;
  }
  document.getElementById("add-line").addEventListener("click", () => addLine());
  body.addEventListener("click", (e) => {
    const btn = e.target.closest(".remove-line");
    if (btn) {
      btn.closest("tr").remove();
      calculate();
    }
  });
  body.addEventListener("change", (e) => {
    if (e.target.matches(".line-product") && purchase)
      e.target.closest("tr").querySelector(".line-cost").value = (
        Number(e.target.selectedOptions[0]?.dataset.cost || 0) / 100
      ).toFixed(2);
    calculate();
  });
  form.addEventListener("input", calculate);
  document.getElementById("product-finder").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const value = e.target.value.trim().toLowerCase();
    const match = [...template.content.querySelectorAll("option")].find(
      (o) =>
        o.value &&
        [o.dataset.barcode, o.dataset.sku, o.textContent.split(" · ")[0]].some(
          (v) => v && v.toLowerCase() === value,
        ),
    );
    if (!match) {
      toast("No exact product match. Choose a SKU from the suggestions.");
      return;
    }
    let row = [...body.rows].find((r) => r.querySelector(".line-product").value === match.value);
    if (row) {
      const quantity = row.querySelector(".line-quantity");
      quantity.value = Number(quantity.value) + 1;
    } else {
      row = [...body.rows].find((r) => !r.querySelector(".line-product").value);
      if (row) {
        row.querySelector(".line-product").value = match.value;
        if (purchase)
          row.querySelector(".line-cost").value = (Number(match.dataset.cost) / 100).toFixed(2);
      } else addLine(match.value);
    }
    e.target.value = "";
    calculate();
  });
  form.addEventListener("submit", (e) => {
    if (!body.rows.length) {
      e.preventDefault();
      toast("Add at least one product.");
      return;
    }
    if (form.dataset.submitting === "1") {
      e.preventDefault();
      return;
    }
    form.dataset.submitting = "1";
    const btn = form.querySelector("button[type=submit],.form-footer button");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Saving…";
    }
  });
  if (!body.rows.length) addLine();
  else calculate();
  }
  window.StorePro = window.StorePro || {};
  window.StorePro.refresh = function (root) {
    root = root || document;
    icons();
    sweepBrokenImages(root);
    bindConfirms(root);
    initCharts(root);
    root.querySelectorAll(".transaction-form").forEach(initTransactionForm);
  };
  window.StorePro.refresh();
});
