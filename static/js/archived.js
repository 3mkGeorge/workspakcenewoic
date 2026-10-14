"use strict";
// Archived Products Center: browse, search, filter, restore, view details,
// permanent delete. Instant UI refresh, no page reload.
//
// SPA-safe: the router swaps main.content on every navigation, so this init
// is re-entrant. Bindings are guarded per DOM generation (dataset.spBound);
// detached nodes take their listeners with them. No global once-flag.
function spInitArchived() {
  const root = document.getElementById("archived-manager");
  if (!root || root.dataset.spBound === "1") return;
  root.dataset.spBound = "1";
  const modalEl = document.getElementById("archivedProductsModal");
  if (!modalEl) return;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const currency = root.dataset.currency || "EGP";
  const canRestore = root.dataset.canRestore === "1";
  const canDelete = root.dataset.canDelete === "1";
  const $ = (id) => document.getElementById(id);
  let items = [];
  let deleteId = null;

  const money = (v) =>
    `${(Number(v || 0) / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
  const toast = (text, type = "success") => window.StoreProUI?.toast(text, type);
  const say = (text, isError) => {
    const box = $("arch-message");
    if (!box) return;
    box.textContent = text || "";
    box.hidden = !text;
    box.classList.toggle("cat-error", !!isError);
  };
  const icons = () => { if (window.lucide) window.lucide.createIcons(); };

  async function api(url, method, body) {
    const res = await fetch(url, {
      method: method || "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || data.message || "Request failed.");
    return data;
  }

  function showView(name) {
    ["arch-list-view", "arch-delete-view"].forEach((id) => {
      const v = $(id);
      if (v) v.hidden = id !== name;
    });
    say("");
  }

  function setBadge(n) {
    const btn = $("archived-products-btn");
    if (!btn) return;
    let badge = $("archived-count-badge");
    if (n > 0) {
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "archived-badge";
        badge.id = "archived-count-badge";
        btn.append(badge);
      }
      badge.textContent = n;
    } else if (badge) {
      badge.remove();
    }
  }

  function setBtnBusy(on) {
    const btn = $("archived-products-btn");
    if (!btn) return;
    btn.disabled = on;
    btn.classList.toggle("is-loading", on);
    if (on) btn.setAttribute("aria-busy", "true");
    else btn.removeAttribute("aria-busy");
  }

  // Products/Inventory re-render in place (metrics, charts, table) once the
  // archive dialog closes, keeping filters and scroll position.
  function refreshListing() {
    if (window.StoreProUI?.refreshView) window.StoreProUI.refreshView();
  }

  function afterChange(message) {
    document.dispatchEvent(new CustomEvent("storepro:catalog-changed"));
    refreshListing();
    toast(message);
  }

  function render() {
    const total = $("arch-total");
    if (total) total.textContent = items.length;
    setBadge(items.length);
    const cards = $("arch-cards");
    if (!cards) return;
    cards.replaceChildren();
    const empty = $("arch-empty");
    if (empty) empty.hidden = items.length > 0;
    items.forEach((p) => {
      const card = document.createElement("article");
      card.className = "cat-card arch-card";
      card.style.animation = "none";
      const img = p.thumb
        ? Object.assign(document.createElement("img"), { src: p.thumb, alt: p.name, loading: "lazy", className: "arch-thumb" })
        : (() => { const s = document.createElement("span"); s.className = "arch-thumb arch-thumb-empty"; s.textContent = "📦"; return s; })();
      const info = document.createElement("div");
      info.className = "cat-card-info";
      const nm = document.createElement("strong");
      nm.textContent = p.name;
      info.append(nm);
      [["SKU", p.sku], ["Category", p.category], ["Supplier", p.supplier],
       ["Cost", money(p.cost)], ["Price", money(p.price)],
       ["Stock", p.stock], ["Archived Date", p.archived_at],
       ["Archived By", p.archived_by || "—"]].forEach(([k, v]) => {
        const sm = document.createElement("small");
        sm.className = "muted d-block";
        sm.textContent = `${k}: ${v}`;
        info.append(sm);
      });
      const status = document.createElement("span");
      status.className = "badge-status warning";
      status.textContent = "ARCHIVED";
      info.append(status);
      card.append(img, info);
      const actions = document.createElement("div");
      actions.className = "cat-card-actions";
      if (canRestore) {
        const rb = document.createElement("button");
        rb.type = "button";
        rb.className = "btn btn-light btn-sm";
        rb.textContent = "Restore";
        rb.addEventListener("click", () => doRestore(p.id));
        actions.append(rb);
      }
      const vb = document.createElement("button");
      vb.type = "button";
      vb.className = "btn btn-light btn-sm";
      vb.textContent = "View Details";
      vb.addEventListener("click", () => openDetails(p.id));
      actions.append(vb);
      if (canDelete) {
        const db = document.createElement("button");
        db.type = "button";
        db.className = "btn btn-light btn-sm";
        db.textContent = "Delete Permanently";
        db.addEventListener("click", () => openDelete(p.id));
        actions.append(db);
      }
      card.append(actions);
      cards.append(card);
    });
    icons();
  }

  function filters() {
    const params = new URLSearchParams();
    const q = $("arch-search").value.trim();
    if (q) params.set("q", q);
    ["category", "supplier", "sort"].forEach((k) => {
      const v = $(`arch-${k}`).value;
      if (v) params.set(k === "category" ? "category_id" : k === "supplier" ? "supplier_id" : "sort", v);
    });
    if ($("arch-from").value) params.set("from", $("arch-from").value);
    if ($("arch-to").value) params.set("to", $("arch-to").value);
    return params.toString();
  }

  async function load() {
    try {
      const qs = filters();
      const data = await api(`/api/products/archived${qs ? `?${qs}` : ""}`);
      items = data.products || [];
      render();
    } catch (e) {
      console.error("Archived products failed to load:", e);
      say("Unable to load archived products.", true);
    }
  }

  async function openArchive(preset) {
    if (preset && preset.categoryId) $("arch-category").value = String(preset.categoryId);
    showView("arch-list-view");
    setBtnBusy(true);
    try {
      if (window.bootstrap?.Modal) bootstrap.Modal.getOrCreateInstance(modalEl).show();
      await load();
    } finally {
      setBtnBusy(false);
    }
  }
  window.StoreProArchive = { open: openArchive };

  async function doRestore(pid) {
    try {
      await api(`/api/products/${pid}/restore`, "POST", {});
      items = items.filter((p) => p.id !== pid);
      render();
      afterChange("Product restored successfully.");
    } catch (e) {
      console.error("Archived product restore failed:", e);
      say(e.message, true);
    }
  }

  function openDetails(pid) {
    // Reuse the existing Product Details drawer; it loads archived products
    // fine via /api/products/<id>/preview (no active filter server-side).
    try {
      if (window.bootstrap?.Modal) bootstrap.Modal.getInstance(modalEl)?.hide();
    } catch {}
    if (window.StoreProDetailsDrawer) window.StoreProDetailsDrawer.open(pid);
    else say("Product details are unavailable.", true);
  }

  async function openDelete(pid) {
    deleteId = pid;
    showView("arch-delete-view");
    $("arch-delete-blockers").hidden = true;
    $("arch-delete-confirm").disabled = false;
    try {
      const data = (await api(`/api/archived/${pid}`)).product;
      $("arch-delete-text").textContent = `"${data.name}" (SKU ${data.sku}).`;
      const refs = [
        [data.sales, "sales"],
        [data.purchases, "purchase records"],
        [data.movements, "stock movement"],
      ].filter(([n]) => n > 0);
      if (refs.length) {
        const ul = $("arch-blockers-list");
        ul.replaceChildren();
        refs.forEach(([n, label]) => {
          const li = document.createElement("li");
          li.textContent = `${n} ${label}`;
          ul.append(li);
        });
        $("arch-delete-blockers").hidden = false;
        $("arch-delete-confirm").disabled = true;
        say("Cannot permanently delete. It is referenced by the records above.", true);
      }
    } catch (e) {
      console.error("Archived product details failed to load:", e);
      say(e.message, true);
      $("arch-delete-confirm").disabled = true;
    }
  }
  $("arch-delete-cancel").addEventListener("click", () => showView("arch-list-view"));
  $("arch-delete-confirm").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      await api(`/api/products/${deleteId}/permanent`, "DELETE", {});
      items = items.filter((p) => p.id !== deleteId);
      render();
      showView("arch-list-view");
      afterChange("Product permanently deleted.");
    } catch (err) {
      console.error("Archived product permanent delete failed:", err);
      say(err.message, true);
    } finally {
      btn.disabled = false;
    }
  });

  ["arch-search", "arch-category", "arch-supplier", "arch-from", "arch-to", "arch-sort"].forEach((id) =>
    $(id).addEventListener(id === "arch-search" ? "input" : "change", load),
  );
  $("archived-products-btn")?.addEventListener("click", () => openArchive());
  modalEl.addEventListener("hidden.bs.modal", () => showView("arch-list-view"));
}
document.addEventListener("DOMContentLoaded", spInitArchived);
document.addEventListener("storepro:content", spInitArchived);
