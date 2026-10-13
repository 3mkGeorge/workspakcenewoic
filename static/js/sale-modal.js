"use strict";
// Invoice Details modal: full-width sales table, invoice opens a large
// centered modal loaded via AJAX. No page reload.
//
// SPA-safe: the modal markup lives inside main.content, so every element is
// looked up fresh on each open. The document-level click listener is
// registered exactly once (it holds no node references).
function spInitSaleModal() {
  if (window.__spSaleModal) return;
  window.__spSaleModal = true;
  let requestSeq = 0;

  const $ = (id) => document.getElementById(id);
  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || "";
  const icons = () => { if (window.lucide) window.lucide.createIcons(); };
  const money = (v, cur) =>
    `${cur || ""} ${(Number(v || 0) / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const text = (v) => (v === null || v === undefined || v === "" ? "Not assigned yet" : String(v));
  const toast = (msg) => {
    const el = $("app-toast");
    if (!el) return;
    el.querySelector(".toast-body").textContent = msg;
    if (window.bootstrap?.Toast) bootstrap.Toast.getOrCreateInstance(el).show();
  };
  const say = (msg, isError) => {
    const box = $("sale-modal-message");
    if (!box) return;
    box.textContent = msg || "";
    box.hidden = !msg;
    box.classList.toggle("sale-modal-error", !!isError);
  };
  const statusClass = (s) =>
    s === "Completed" ? "success" : s === "Refunded" || s === "Voided" ? "danger" : "warning";

  function setLoading() {
    $("sale-modal-loading").hidden = false;
    $("sale-modal-content").hidden = true;
    say("");
  }

  function renderInfo(d) {
    const info = $("sale-modal-info");
    info.replaceChildren();
    const pair = (parent, labelText, valueNode) => {
      const wrap = document.createElement("div");
      wrap.className = "ipair";
      const dt = document.createElement("dt");
      dt.textContent = labelText;
      const dd = document.createElement("dd");
      if (valueNode instanceof Node) dd.append(valueNode);
      else dd.textContent = text(valueNode);
      wrap.append(dt, dd);
      parent.append(wrap);
    };
    [
      ["Invoice Number", d.invoice],
      ["Date", d.datetime],
      ["Customer", d.customer],
      ["Payment Method", d.payment],
      ["User", d.user],
    ].forEach(([k, v]) => pair(info, k, v));
    const span = document.createElement("span");
    span.className = `badge-status ${statusClass(d.status)}`;
    span.textContent = d.status;
    pair(info, "Status", span);
    if (d.payments && d.payments.length > 1) {
      const dd = document.createElement("dd");
      d.payments.forEach((p) => {
        const sm = document.createElement("small");
        sm.className = "d-block muted";
        sm.textContent = `${p.method}: ${money(p.amount, d.currency)}`;
        dd.append(sm);
      });
      const wrap = document.createElement("div");
      wrap.className = "ipair";
      const dt = document.createElement("dt");
      dt.textContent = "Breakdown";
      wrap.append(dt, dd);
      info.append(wrap);
    }
    const badge = $("sale-modal-status");
    badge.replaceChildren();
    const head = document.createElement("span");
    head.className = `badge-status ${statusClass(d.status)}`;
    head.textContent = d.status;
    badge.append(head);
  }

  let selectionMode = false;

  function resetSelectionMode() {
    selectionMode = false;
    document.querySelectorAll(".sale-select-col, .sale-return-qty-col").forEach((el) => {
      el.hidden = true;
    });
    const btn = $("sale-modal-refund-selected");
    if (btn) {
      btn.innerHTML = `<i data-lucide="check-square"></i> Return Selected`;
      btn.classList.remove("btn-warning");
      btn.classList.add("btn-light");
    }
    const selectAll = $("sale-select-all");
    if (selectAll) selectAll.checked = true;
  }

  function renderItems(d) {
    const rows = $("sale-modal-rows");
    rows.replaceChildren();
    resetSelectionMode();
    d.items.forEach((item) => {
      const tr = document.createElement("tr");
      tr.dataset.itemId = item.id || "";
      tr.dataset.productId = item.product_id || "";
      tr.dataset.maxQty = item.quantity;

      const selTd = document.createElement("td");
      selTd.className = "sale-select-col";
      selTd.hidden = !selectionMode;
      const chk = document.createElement("input");
      chk.type = "checkbox";
      chk.className = "sale-item-check";
      chk.checked = true;
      chk.setAttribute("aria-label", `Select ${item.name}`);
      selTd.append(chk);
      tr.append(selTd);

      const imgTd = document.createElement("td");
      if (item.image) {
        const img = document.createElement("img");
        img.src = item.image;
        img.alt = item.name;
        img.loading = "lazy";
        img.className = "sale-item-thumb";
        imgTd.append(img);
      } else {
        const ph = document.createElement("span");
        ph.className = "sale-item-thumb sale-item-thumb-empty";
        ph.textContent = "📦";
        imgTd.append(ph);
      }
      tr.append(imgTd);
      const nameTd = document.createElement("td");
      nameTd.className = "sale-item-name";
      nameTd.textContent = item.name;
      const qtyTd = document.createElement("td");
      qtyTd.className = "num";
      qtyTd.textContent = item.quantity;
      const priceTd = document.createElement("td");
      priceTd.className = "num";
      priceTd.textContent = money(item.price, d.currency);
      const discTd = document.createElement("td");
      discTd.className = "num";
      discTd.textContent = money(item.discount, d.currency);
      const totalTd = document.createElement("td");
      totalTd.className = "fw-semibold num";
      totalTd.textContent = money(item.total, d.currency);
      tr.append(nameTd, qtyTd, priceTd, discTd, totalTd);

      const retTd = document.createElement("td");
      retTd.className = "sale-return-qty-col num";
      retTd.hidden = !selectionMode;
      const qtyIn = document.createElement("input");
      qtyIn.type = "number";
      qtyIn.className = "form-control form-control-sm sale-return-qty";
      qtyIn.value = item.quantity;
      qtyIn.min = "1";
      qtyIn.max = item.quantity;
      qtyIn.style.width = "75px";
      qtyIn.style.display = "inline-block";
      qtyIn.setAttribute("aria-label", `Return quantity for ${item.name}`);
      retTd.append(qtyIn);
      tr.append(retTd);

      rows.append(tr);
    });
    $("sale-modal-count").textContent = d.items.length;
  }

  function renderTotals(d) {
    const totals = $("sale-modal-totals");
    totals.replaceChildren();
    [
      ["Subtotal", money(d.subtotal, d.currency)],
      ["Discount", money(d.discount, d.currency)],
      [`VAT (${Number(d.tax_rate) / 100}%)`, money(d.tax, d.currency)],
    ].forEach(([k, v]) => {
      const dt = document.createElement("dt");
      dt.textContent = k;
      const dd = document.createElement("dd");
      dd.textContent = v;
      totals.append(dt, dd);
    });
    $("sale-modal-grand").textContent = money(d.total, d.currency);
  }

  function renderNotes(d) {
    const notes = $("sale-modal-notes");
    notes.replaceChildren();
    [
      ["Customer Notes", d.note, "No customer notes"],
      ["Internal Notes", d.pickup_notes, "No internal notes"],
    ].forEach(([k, v, emptyText]) => {
      const dt = document.createElement("dt");
      dt.textContent = k;
      const dd = document.createElement("dd");
      if (v) {
        dd.textContent = v;
      } else {
        dd.textContent = emptyText;
        dd.className = "sale-note-empty";
      }
      notes.append(dt, dd);
    });
  }

  function renderFooter(d) {
    const setHref = (id, href) => {
      const a = $(id);
      if (a) a.href = href;
    };
    setHref("sale-modal-print", `/sales/${d.id}/invoice`);
    setHref("sale-modal-receipt", `/sales/${d.id}/invoice?receipt=1`);
    setHref("sale-modal-edit", `/sales/${d.id}/edit`);
    // Mutations only apply to completed invoices (mirrors server rules).
    const live = d.status === "Completed";
    ["sale-modal-edit", "sale-modal-refund", "sale-modal-delete"].forEach((id) => {
      const el = $(id);
      if (el) el.hidden = !live;
    });
  }

  async function openModal(sid) {
    const seq = ++requestSeq;
    const modalEl = $("saleDetailsModal");
    if (!modalEl) return;
    $("sale-modal-inv").textContent = "…";
    $("sale-modal-sub").textContent = "";
    setLoading();
    if (window.bootstrap?.Modal) bootstrap.Modal.getOrCreateInstance(modalEl).show();
    try {
      const res = await fetch(`/api/sales/${encodeURIComponent(sid)}`, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      const data = await res.json().catch(() => ({}));
      if (seq !== requestSeq) return;
      if (!res.ok) throw new Error(data.error || "Unable to load invoice details.");
      if (seq !== requestSeq) return;
      $("sale-modal-inv").textContent = data.invoice;
      $("sale-modal-sub").textContent = `${data.datetime} · ${data.customer}`;
      renderInfo(data);
      renderItems(data);
      renderTotals(data);
      renderNotes(data);
      renderFooter(data);
      $("sale-modal-loading").hidden = true;
      $("sale-modal-content").hidden = false;
      icons();
      modalEl.dataset.saleId = data.id;
      modalEl.dataset.saleStatus = data.status;
    } catch (e) {
      if (seq !== requestSeq) return;
      console.error("Invoice details failed to load:", e);
      $("sale-modal-loading").hidden = true;
      say("Unable to load invoice details.", true);
    }
  }

  async function mutate(action, confirmText, successText, extraBody) {
    const modalEl = $("saleDetailsModal");
    const sid = modalEl?.dataset.saleId;
    if (!sid) return;
    if (!window.confirm(confirmText)) return;
    try {
      const res = await fetch(`/sales/${encodeURIComponent(sid)}/${action}`, {
        method: "POST",
        credentials: "same-origin",
        headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: extraBody ? JSON.stringify(extraBody) : undefined,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || "Action failed.");
      }
      if (window.bootstrap?.Modal) bootstrap.Modal.getInstance(modalEl)?.hide();
      toast(successText);
      if (window.StorePro?.reload) window.StorePro.reload();
      else location.reload();
    } catch (e) {
      console.error(`Invoice ${action} failed:`, e);
      say(e.message, true);
    }
  }

  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-sale-modal]");
    if (trigger) {
      e.preventDefault();
      const sid = trigger.getAttribute("data-sale-modal");
      // Never stack: close any open business modal (e.g. Shipping Details)
      // first, then open Invoice Details via the shared modal manager.
      if (window.StoreProModal) {
        window.StoreProModal.openExclusive("saleDetailsModal", () => openModal(sid));
      } else {
        openModal(sid);
      }
      return;
    }
    if (e.target.closest("#sale-select-all")) {
      const allChecked = $("sale-select-all")?.checked ?? true;
      document.querySelectorAll(".sale-item-check").forEach((chk) => {
        chk.checked = allChecked;
      });
      return;
    }
    if (e.target.closest("#sale-modal-refund")) {
      mutate("refund", "Refund this entire invoice and return all items to stock?", "Invoice refunded.");
      return;
    }
    if (e.target.closest("#sale-modal-refund-selected")) {
      if (!selectionMode) {
        selectionMode = true;
        document.querySelectorAll(".sale-select-col, .sale-return-qty-col").forEach((el) => {
          el.hidden = false;
        });
        const btn = $("sale-modal-refund-selected");
        if (btn) {
          btn.innerHTML = `<i data-lucide="check-circle-2"></i> Confirm Return`;
          btn.classList.remove("btn-light");
          btn.classList.add("btn-warning");
        }
        icons();
        return;
      }
      const selected = [];
      const trs = document.querySelectorAll("#sale-modal-rows tr");
      trs.forEach((tr) => {
        const chk = tr.querySelector(".sale-item-check");
        if (chk && chk.checked) {
          const qtyIn = tr.querySelector(".sale-return-qty");
          const qty = parseInt(qtyIn?.value || "1", 10);
          if (qty > 0) {
            selected.push({
              item_id: tr.dataset.itemId ? parseInt(tr.dataset.itemId, 10) : undefined,
              product_id: tr.dataset.productId ? parseInt(tr.dataset.productId, 10) : undefined,
              quantity: qty,
            });
          }
        }
      });
      if (selected.length === 0) {
        toast("Please select at least one item to return.");
        return;
      }
      mutate(
        "refund",
        `Return ${selected.length} selected item(s) to stock and process refund?`,
        "Selected items refunded and returned to stock.",
        { items: selected }
      );
      return;
    }
    if (e.target.closest("#sale-modal-delete")) {
      const runDelete = (reason) =>
        mutate(
          "delete",
          "Void this invoice and restore its stock? The audit record will remain.",
          "Invoice voided. The original is retained for the audit trail.",
          reason ? { cancel_reason: reason } : undefined,
        );
      if (window.StoreProCancel) {
        window.StoreProCancel.open({
          title: "Void Invoice",
          context: "Voiding this invoice restores its stock. A reason is required.",
          confirmLabel: "Confirm Void",
          onConfirm: (reason) => runDelete(reason),
        });
      } else {
        runDelete();
      }
    }
  });

  window.StoreProSaleModal = {
    open: (sid) => openModal(sid),
  };
}
// "/sales?selected=ID" (e.g. "View invoice" after saving) opens that invoice.
function spOpenRequestedSale() {
  const marker = document.querySelector("[data-open-sale]");
  if (!marker) return;
  const sid = marker.dataset.openSale;
  marker.remove();
  window.StoreProSaleModal?.open(sid);
}
document.addEventListener("DOMContentLoaded", spInitSaleModal);
document.addEventListener("storepro:content", spInitSaleModal);
document.addEventListener("DOMContentLoaded", spOpenRequestedSale);
document.addEventListener("storepro:content", spOpenRequestedSale);
