"use strict";
let spAdjustAbort = null;
function spInitAdjust() {
  const form = document.getElementById("adjust-form");
  if (!form || form.dataset.spBound) return;
  form.dataset.spBound = "1";
  spAdjustAbort?.abort();
  spAdjustAbort = new AbortController();
  const { signal } = spAdjustAbort;
  const isAdmin = form.dataset.admin === "1";
  const products = JSON.parse(document.getElementById("adjust-products").textContent || "[]");
  const byId = Object.fromEntries(products.map((p) => [String(p.id), p]));
  const search = document.getElementById("product-search");
  const list = document.getElementById("product-list");
  const pid = document.getElementById("product-id");
  const qty = document.getElementById("adjust-qty");
  const typeSel = document.getElementById("adjust-type");
  const qtyError = document.getElementById("qty-error");
  const saveBtn = document.getElementById("save-adjust");
  const icons = () => { if (window.lucide) window.lucide.createIcons(); };

  function current() {
    return byId[pid.value] || null;
  }
  function signedQty() {
    const raw = qty.value.trim();
    if (!/^-?\d+$/.test(raw)) return null;
    const type = typeSel.value;
    const magnitude = Math.abs(parseInt(raw, 10));
    if (type === "Add Stock") return magnitude;
    if (type === "Remove Stock" || type === "Damaged Items") return -magnitude;
    return parseInt(raw, 10);
  }
  function badgeClass(status) {
    return status === "In Stock" ? "success" : status === "Out of Stock" ? "danger" : "warning";
  }
  function progressWidth(p) {
    if (!(p.minimum > 0)) return p.stock > 0 ? 100 : 0;
    return Math.max(0, Math.min(100, Math.round((p.stock / (p.minimum * 2)) * 100)));
  }
  function esc(text) {
    const el = document.createElement("span");
    el.textContent = text == null ? "" : String(text);
    return el.innerHTML;
  }
  function renderSnapshot() {
    const box = document.getElementById("snapshot");
    const p = current();
    if (!p) {
      box.innerHTML = '<p class="muted">Select a product to preview it here.</p>';
      return;
    }
    const img = p.image
      ? `<img class="product-thumb" src="${esc(p.image)}" alt="" loading="lazy">`
      : `<span class="product-thumb product-icon"><i data-lucide="package"></i></span>`;
    box.innerHTML =
      `<div class="product-hero">${img}<div><h3>${esc(p.name)}</h3><span class="badge-status ${badgeClass(p.status)}">${esc(p.status)}</span></div></div>` +
      `<dl class="detail-list"><dt>SKU</dt><dd>${esc(p.sku)}</dd><dt>Category</dt><dd>${esc(p.category) || "—"}</dd>` +
      `<dt>Cost Price</dt><dd>${esc(p.cost)}</dd><dt>Selling Price</dt><dd>${esc(p.price)}</dd>` +
      `<dt>Current Stock</dt><dd><b>${p.stock}</b></dd><dt>Minimum Stock</dt><dd>${p.minimum}</dd></dl>` +
      `<div class="stock-progress"><div class="stock-progress-bar" style="width:${progressWidth(p)}%"></div></div>`;
    const view = document.getElementById("view-product");
    if (view) view.href = `/products?selected=${p.id}`;
    const stat = document.querySelector(".metrics .metric strong");
    if (stat) stat.textContent = p.stock;
    icons();
  }
  function renderList(filter) {
    const q = (filter || "").trim().toLowerCase();
    const matches = products
      .filter((p) => !q || p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q) || (p.barcode || "").toLowerCase().includes(q))
      .slice(0, 60);
    list.replaceChildren();
    list.hidden = !matches.length;
    matches.forEach((p) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "combo-item" + (String(p.id) === pid.value ? " active" : "");
      b.setAttribute("role", "option");
      const thumb = p.image
        ? `<img class="product-thumb" src="${esc(p.image)}" alt="" loading="lazy">`
        : `<span class="product-thumb product-icon"><i data-lucide="package"></i></span>`;
      b.innerHTML = `${thumb}<span><span class="combo-name"></span><small>${esc(p.sku)}</small></span><b>${p.stock}</b>`;
      b.querySelector(".combo-name").textContent = p.name;
      b.addEventListener("click", () => {
        pid.value = p.id;
        search.value = `${p.name} · ${p.sku}`;
        list.hidden = true;
        renderSnapshot();
        renderCalc();
      });
      list.append(b);
    });
    icons();
  }
  function renderCalc() {
    const p = current();
    const delta = signedQty();
    document.getElementById("calc-current").textContent = p ? p.stock : 0;
    const deltaEl = document.getElementById("calc-delta");
    const newEl = document.getElementById("calc-new");
    if (delta === null || !p) {
      deltaEl.textContent = "—";
      deltaEl.className = "";
      newEl.textContent = "—";
      newEl.className = "";
      return;
    }
    const next = p.stock + delta;
    deltaEl.textContent = (delta >= 0 ? "+" : "") + delta;
    deltaEl.className = delta > 0 ? "text-success" : delta < 0 ? "text-danger" : "";
    newEl.textContent = next;
    newEl.className = next < 0 ? "text-danger" : delta > 0 ? "text-success" : delta < 0 ? "text-danger" : "";
    const override = form.querySelector('input[name="allow_override"]');
    const bad = next < 0 && !(isAdmin && override && override.checked);
    qtyError.textContent = next < 0 ? "This would take stock below zero." : "";
    qtyError.hidden = next >= 0;
    saveBtn.disabled = bad;
    // "Save & New" submits the same adjustment, so it follows the same rule.
    const saveNew = form.querySelector('button[name="save_and_new"]');
    if (saveNew) saveNew.disabled = bad;
  }
  const barcodeScanner = document.getElementById("adjust-barcode-scanner");
  const scanFeedback = document.getElementById("scan-feedback");
  const clearScanBtn = document.getElementById("btn-adjust-clear-scan");

  function resolveBarcode(code) {
    if (!code) return;
    const clean = code.trim().toLowerCase();
    let match = products.find((p) => p.barcode && p.barcode.toLowerCase() === clean);
    if (!match) match = products.find((p) => p.sku && p.sku.toLowerCase() === clean);
    if (!match) match = products.find((p) => p.name && p.name.toLowerCase().includes(clean));

    if (match) {
      pid.value = match.id;
      search.value = `${match.name} · ${match.sku}`;
      if (list) list.hidden = true;
      renderSnapshot();
      renderCalc();
      if (scanFeedback) {
        scanFeedback.innerHTML = `<span class="text-success fw-bold">✓ Matched: ${esc(match.name)} (${esc(match.sku)})</span>`;
      }
      qty.focus();
      qty.select();
    } else {
      if (scanFeedback) {
        scanFeedback.innerHTML = `<span class="text-danger fw-bold">✗ No product found matching "${esc(code)}".</span>`;
      }
    }
  }

  if (barcodeScanner) {
    barcodeScanner.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        resolveBarcode(barcodeScanner.value);
      }
    });
    barcodeScanner.addEventListener("input", () => {
      const val = barcodeScanner.value.trim();
      if (val.length >= 8) {
        const exact = products.find((p) => p.barcode && p.barcode.toLowerCase() === val.toLowerCase());
        if (exact) resolveBarcode(val);
      }
    });
  }
  if (clearScanBtn && barcodeScanner) {
    clearScanBtn.addEventListener("click", () => {
      barcodeScanner.value = "";
      if (scanFeedback) scanFeedback.textContent = "Scanned barcodes instantly resolve the product, update stock preview, and jump to quantity.";
      barcodeScanner.focus();
    });
  }

  search.addEventListener("input", () => renderList(search.value));
  search.addEventListener("focus", () => renderList(search.value));
  document.addEventListener(
    "click",
    (e) => {
      if (!e.target.closest("#product-search") && !e.target.closest("#product-list"))
        list.hidden = true;
    },
    { signal },
  );
  document.querySelectorAll("[data-step]").forEach((b) =>
    b.addEventListener("click", () => {
      const v = parseInt(qty.value || "0", 10) || 0;
      qty.value = v + parseInt(b.dataset.step, 10);
      renderCalc();
    }),
  );
  [qty, typeSel].forEach((el) => el.addEventListener("input", renderCalc));
  typeSel.addEventListener("change", renderCalc);
  form.querySelector('input[name="allow_override"]')?.addEventListener("change", renderCalc);
  form.addEventListener("submit", (e) => {
    if (signedQty() === null || signedQty() === 0) {
      e.preventDefault();
      qtyError.textContent = "Enter a whole nonzero number.";
      qtyError.hidden = false;
      qty.focus();
    }
  });
  // Recent table filters
  const recentSearch = document.getElementById("recent-search");
  const recentType = document.getElementById("recent-type");
  function renderRecent() {
    if (!recentSearch) return;
    const q = recentSearch.value.trim().toLowerCase();
    const t = recentType.value;
    document.querySelectorAll("#recent-table tbody tr").forEach((tr) => {
      const okQ = !q || (tr.dataset.search || "").includes(q);
      const okT = !t || tr.dataset.type === t;
      tr.hidden = !(okQ && okT);
    });
  }
  recentSearch?.addEventListener("input", renderRecent);
  recentType?.addEventListener("change", renderRecent);
  // Init
  const initial = current();
  search.value = initial ? `${initial.name} · ${initial.sku}` : "";
  renderSnapshot();
  renderCalc();
}
document.addEventListener("DOMContentLoaded", spInitAdjust);
document.addEventListener("storepro:content", spInitAdjust);
