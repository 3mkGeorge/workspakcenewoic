"use strict";
// ProductDetailsDrawer: slide-in product details with no page reloads.
// Opened from row-action menus via [data-product-details="<id>"].
//
// SPA-safe: the router replaces main.content (which contains the drawer
// markup) on every navigation/render, so drawer/backdrop/body nodes MUST be
// looked up fresh on every call. Capturing them once at init binds the
// drawer to detached nodes: clicks then do nothing with no errors.
// Document-level listeners are registered exactly once (they hold no refs).
function spInitDetailsDrawer() {
  if (window.__spDetailsDrawer) return;
  window.__spDetailsDrawer = true;
  let currentId = null;
  let requestSeq = 0;

  const nodes = () => ({
    drawer: document.getElementById("product-details-drawer"),
    backdrop: document.getElementById("product-details-backdrop"),
    body: document.getElementById("product-details-body"),
    closeBtn: document.getElementById("product-details-close"),
  });
  const money = (value, currency) =>
    `${currency || ""} ${(Number(value || 0) / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const esc = (value) => {
    const el = document.createElement("span");
    el.textContent = value == null || value === "" ? "—" : String(value);
    return el.innerHTML;
  };
  const icons = () => { if (window.lucide) window.lucide.createIcons(); };
  const toast = (text) => {
    const el = document.getElementById("app-toast");
    if (!el) return;
    el.querySelector(".toast-body").textContent = text;
    if (window.bootstrap?.Toast) bootstrap.Toast.getOrCreateInstance(el).show();
  };

  function setOpen(open) {
    const { drawer, backdrop, closeBtn } = nodes();
    if (!drawer || !backdrop) return false;
    drawer.classList.toggle("open", open);
    backdrop.classList.toggle("open", open);
    backdrop.hidden = !open;
    drawer.setAttribute("aria-hidden", open ? "false" : "true");
    if (open) {
      closeBtn?.focus();
    } else {
      currentId = null;
    }
    return true;
  }

  function renderLoading() {
    const { body } = nodes();
    if (!body) return;
    body.replaceChildren();
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "Loading…";
    body.append(p);
  }

  function renderError(text) {
    const { body } = nodes();
    if (!body) return;
    body.replaceChildren();
    const p = document.createElement("p");
    p.className = "pd-error";
    p.textContent = text;
    body.append(p);
  }

  function renderDetails(data) {
    const { body } = nodes();
    if (!body) return false;
    body.replaceChildren();
    const hero = document.createElement("div");
    hero.className = "product-hero pd-hero";
    if (data.thumb_image) {
      const img = document.createElement("img");
      img.src = data.thumb_image;
      img.alt = data.name;
      img.loading = "lazy";
      hero.append(img);
    } else {
      const ph = document.createElement("span");
      ph.className = "pd-hero-icon";
      ph.innerHTML = '<i data-lucide="package"></i>';
      hero.append(ph);
    }
    const head = document.createElement("div");
    const title = document.createElement("h3");
    title.id = "pd-name";
    title.textContent = data.name;
    const status = document.createElement("span");
    const low = data.stock <= data.minimum;
    status.className = `badge-status ${data.stock === 0 ? "danger" : low ? "warning" : "success"}`;
    status.textContent = data.status;
    head.append(title, status);
    hero.append(head);
    const banner = document.createElement("div");
    const state = data.stock === 0 ? "out" : low ? "low" : "ok";
    banner.className = `pd-stock-banner ${state}`;
    const count = document.createElement("strong");
    count.textContent = data.stock;
    const caption = document.createElement("span");
    caption.textContent = "in stock";
    banner.append(count, caption, status.cloneNode(true));
    const list = document.createElement("dl");
    list.className = "detail-list";
    const rows = [
      ["SKU", data.sku],
      ["Category", data.category],
      ["Brand", data.brand],
      ["Barcode", data.barcode],
      ["Cost Price", money(data.cost, data.currency)],
      ["Selling Price", money(data.price, data.currency)],
      ["Current stock", data.stock],
      ["Minimum Stock", data.minimum],
      ["Supplier", data.supplier],
      ["Location", data.location],
      ["Created At", data.created_at],
      ["Last Updated", data.updated_at],
    ];
    rows.forEach(([label, value]) => {
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.innerHTML = esc(value);
      if (label === "Barcode") dd.className = "break-word";
      list.append(dt, dd);
    });
    body.append(hero, banner, list);
    icons();
    return true;
  }

  async function openDrawer(pid) {
    const seq = ++requestSeq;
    currentId = pid;
    const route = `/api/products/${encodeURIComponent(pid)}/preview`;
    console.debug("[product-details] clicked product id:", pid, "route:", route);
    const { drawer } = nodes();
    if (!drawer) {
      console.warn("[product-details] drawer markup is not on this page.");
      return;
    }
    renderLoading();
    setOpen(true);
    try {
      const res = await fetch(route, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      console.debug("[product-details] response status:", res.status, "for product id:", pid);
      const data = await res.json().catch(() => ({}));
      if (seq !== requestSeq) return; // superseded by a newer selection
      if (!res.ok) throw new Error(data.error || data.message || "Could not load product details.");
      const rendered = renderDetails(data);
      console.debug("[product-details] rendered:", rendered, "for product id:", pid);
    } catch (e) {
      if (seq !== requestSeq) return;
      console.error("[product-details] failed to load product id:", pid, e);
      renderError(e.message);
      toast("Unable to load product details.");
    }
  }

  function closeDrawer() {
    requestSeq++; // abandon any in-flight fetch
    setOpen(false);
  }

  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-product-details]");
    if (trigger) {
      e.preventDefault();
      openDrawer(trigger.getAttribute("data-product-details"));
      return;
    }
    if (e.target.closest("#product-details-close") || e.target.closest("#product-details-backdrop")) {
      closeDrawer();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.getElementById("product-details-drawer")?.classList.contains("open")) closeDrawer();
  });

  window.StoreProDetailsDrawer = { open: openDrawer, close: closeDrawer };
  document.addEventListener("storepro:leave", () => {
    if (document.getElementById("product-details-drawer")?.classList.contains("open")) closeDrawer();
  });
}
document.addEventListener("DOMContentLoaded", spInitDetailsDrawer);
document.addEventListener("storepro:content", spInitDetailsDrawer);
