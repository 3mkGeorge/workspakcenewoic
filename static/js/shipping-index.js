"use strict";
// Shipping Orders interactive table: shipment/customer/invoice modals,
// click-to-copy tracking, in-place status changes, 3-dot row menu.
// SPA-safe: one document-level delegation (no node refs held); every modal
// element is looked up fresh on each open.
function spInitShippingIndex() {
  if (window.__spShippingIndex) return;
  window.__spShippingIndex = true;

  const BADGES = {
    Pending: "secondary",
    Preparing: "info",
    "Ready For Shipment": "purple",
    Shipped: "orange",
    "Out For Delivery": "cyan",
    Delivered: "success",
    "Failed Delivery": "danger",
    Returned: "warning",
    Cancelled: "darkred",
  };
  const FRIENDLY = {};
  const label = (s) => FRIENDLY[s] || s;

  const $ = (id) => document.getElementById(id);
  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || "";
  const icons = () => { if (window.lucide) window.lucide.createIcons(); };
  const NA = "Not assigned yet";
  const formatShipmentValue =
    window.StoreProFormat?.shipment ||
    ((v) => (v === null || v === undefined || v === "" ? NA : v));
  const money = (v, cur) =>
    `${cur || ""} ${(Number(v || 0) / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const toast = (msg) => {
    const el = $("app-toast");
    if (!el) return;
    el.querySelector(".toast-body").textContent = msg;
    if (window.bootstrap?.Toast) bootstrap.Toast.getOrCreateInstance(el).show();
  };
  const say = (id, msg, isError) => {
    const box = $(id);
    if (!box) return;
    box.textContent = msg || "";
    box.hidden = !msg;
    box.classList.toggle("ship-error", !!isError);
  };

  async function request(url, method, body) {
    const res = await fetch(url, {
      method: method || "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || data.message || "Request failed.");
    return data;
  }
  const showModal = (id) => {
    const el = $(id);
    if (el && window.bootstrap?.Modal) bootstrap.Modal.getOrCreateInstance(el).show();
    return el;
  };
  const hideModal = (id) => {
    const el = $(id);
    if (el && window.bootstrap?.Modal) bootstrap.Modal.getInstance(el)?.hide();
  };

  function rowFor(oid) {
    return document.querySelector(`[data-ship-row="${CSS.escape(String(oid))}"]`);
  }

  /* ---- click-to-copy tracking ---- */
  async function copyTracking(code) {
    const value = String(code || "").trim();
    if (!value) return;
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
      else {
        const ta = document.createElement("textarea");
        ta.value = value;
        document.body.append(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      toast("Tracking code copied.");
    } catch (e) {
      console.error("Copy tracking failed:", e);
      toast("Copy failed. Select the code manually.");
    }
  }

  /* ---- floating status menu (body-fixed: never clipped by table scroll) ---- */
  function statusMenu() {
    let menu = $("ship-status-menu");
    if (!menu) {
      menu = document.createElement("div");
      menu.id = "ship-status-menu";
      menu.className = "ship-status-menu";
      menu.setAttribute("role", "menu");
      menu.hidden = true;
      document.body.append(menu);
    }
    return menu;
  }
  function closeStatusMenu() {
    const menu = $("ship-status-menu");
    if (menu) {
      menu.hidden = true;
      menu.replaceChildren();
    }
  }
  function openStatusMenu(badge) {
    const menu = statusMenu();
    menu.replaceChildren();
    const oid = badge.dataset.shipStatus;
    const transitions = (badge.dataset.transitions || "").split("|").filter(Boolean);
    if (!transitions.length) {
      const span = document.createElement("span");
      span.className = "ship-status-empty";
      span.textContent = "No further transitions.";
      menu.append(span);
    } else {
      transitions.forEach((target) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "rf-item";
        item.dataset.statusTarget = target;
        item.dataset.statusOid = oid;
        item.dataset.statusNumber = badge.dataset.orderNumber || oid;
        item.textContent = target === "Delivered" ? "Mark Delivered" : `Move to ${label(target)}`;
        menu.append(item);
      });
    }
    const rect = badge.getBoundingClientRect();
    menu.hidden = false;
    const mw = menu.offsetWidth;
    const mh = menu.offsetHeight;
    const margin = 8;
    // Absolute positioning: viewport rect plus page scroll offsets.
    const sx = window.scrollX || 0;
    const sy = window.scrollY || 0;
    let left = Math.max(margin, Math.min(rect.left, window.innerWidth - mw - margin)) + sx;
    let top = rect.bottom + 6;
    if (top + mh + margin > window.innerHeight && rect.top - mh - 6 > margin) top = rect.top - mh - 6;
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(Math.max(margin, top) + sy)}px`;
    icons();
  }

  function syncRow(row, order, transitions) {
    if (!row) return;
    const badge = row.querySelector("[data-ship-status]");
    if (badge) {
      badge.className = `badge text-bg-${BADGES[order.status] || "secondary"} ship-status-btn`;
      badge.textContent = order.status;
      badge.dataset.status = order.status;
      badge.dataset.transitions = (transitions || []).join("|");
      badge.dataset.badge = BADGES[order.status] || "secondary";
    }
    const deliverItem = row.querySelector("[data-ship-menu-deliver]");
    if (deliverItem) deliverItem.hidden = !(transitions || []).includes("Delivered");
  }

  async function applyStatus(oid, target, extra) {
    try {
      const data = await request(`/api/shipping/${encodeURIComponent(oid)}/status`, "POST", {
        status: target,
        ...(extra || {}),
      });
      syncRow(rowFor(oid), data.order, data.transitions);
      closeStatusMenu();
      toast(`Order moved to ${label(target)}.`);
    } catch (e) {
      console.error("Shipping status change failed:", e);
      throw e;
    }
  }

  /* ---- deliver dialog ---- */
  function openDeliver(oid) {
    const form = $("ship-deliver-form");
    if (!form) return;
    form.dataset.oid = oid;
    const now = new Date();
    $("ship-delivered-date").value = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    $("ship-delivered-time").value =
      String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0");
    $("ship-delivered-by").value = "";
    say("ship-deliver-error", "");
    showModal("shipDeliverModal");
  }


  /* ---- customer modal ---- */
  function dlRow(dl, k, v) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    if (v instanceof Node) dd.append(v);
    else dd.textContent = formatShipmentValue(v);
    dl.append(dt, dd);
  }
  async function openCustomerByUrl(url) {
    if (!showModal("shipCustomerModal")) return;
    $("ship-customer-sub").textContent = "";
    $("ship-customer-content").hidden = true;
    say("ship-customer-message", "");
    try {
      const data = await request(url);
      $("ship-customer-sub").textContent = data.profile.name;
      const info = $("ship-customer-info");
      info.replaceChildren();
      const p = data.profile;
      dlRow(info, "Name", p.name);
      dlRow(info, "Phone", p.phone);
      dlRow(info, "Email", p.email);
      dlRow(info, "Address", p.address);
      dlRow(info, "Status", p.active ? "Active" : "Inactive");
      const stats = $("ship-customer-stats");
      stats.replaceChildren();
      const s = data.stats || {};
      dlRow(stats, "Shipments", s.shipments ?? 0);
      dlRow(stats, "Delivered", s.delivered ?? 0);
      dlRow(stats, "Open", s.open ?? 0);
      $("ship-customer-content").hidden = false;
      icons();
    } catch (e) {
      console.error("Customer profile failed to load:", e);
      say("ship-customer-message", "Unable to load customer profile.", true);
    }
  }
  async function openCustomer(oid) {
    return openCustomerByUrl(`/api/shipping/${encodeURIComponent(oid)}/customer`);
  }

  /* ---- delete ---- */
  async function deleteShipment(oid) {
    if (!window.confirm("Delete this shipment permanently? This cannot be undone.")) return;
    try {
      await request(`/api/shipping/${encodeURIComponent(oid)}`, "DELETE", {});
      rowFor(oid)?.remove();
      const count = $("ship-table-count");
      if (count) count.textContent = Math.max(0, Number(count.textContent || 0) - 1);
      toast("Shipment deleted.");
      if (window.StorePro?.reload) window.StorePro.reload();
    } catch (e) {
      console.error("Shipment delete failed:", e);
      toast(e.message);
    }
  }

  document.addEventListener("click", (e) => {
    const statusItem = e.target.closest("#ship-status-menu [data-status-target]");
    if (statusItem) {
      const oid = statusItem.dataset.statusOid;
      const target = statusItem.dataset.statusTarget;
      if (target === "Delivered") {
        closeStatusMenu();
        openDeliver(oid);
      } else if (target === "Cancelled" && window.StoreProCancel) {
        closeStatusMenu();
        window.StoreProCancel.open({
          title: "Cancel Shipment",
          context: `Cancelling ${statusItem.dataset.statusNumber || oid}. A reason is required.`,
          confirmLabel: "Confirm Cancel",
          onConfirm: (reason) =>
            applyStatus(oid, target, { cancel_reason: reason }).catch((err) =>
              toast(err.message),
            ),
        });
      } else {
        if (!window.confirm(`Move order to ${label(target)}?`)) return;
        applyStatus(oid, target).catch((err) => toast(err.message));
      }
      return;
    }
    const badge = e.target.closest("[data-ship-status]");
    if (badge) {
      const current = $("ship-status-menu");
      if (current && !current.hidden && current.dataset.oid === badge.dataset.shipStatus) {
        closeStatusMenu();
      } else {
        openStatusMenu(badge);
        const opened = $("ship-status-menu");
        if (opened && !opened.hidden) opened.dataset.oid = badge.dataset.shipStatus;
      }
      return;
    }
    if (!e.target.closest("#ship-status-menu")) closeStatusMenu();
    const openShipment = (oid) => {
      if (window.StoreProShipment?.open) window.StoreProShipment.open(oid);
    };
    const view = e.target.closest("[data-ship-view]");
    if (view) {
      openShipment(view.dataset.shipView);
      return;
    }
    const customer = e.target.closest("[data-ship-customer]");
    if (customer) {
      openCustomer(customer.dataset.shipCustomer);
      return;
    }
    const profile = e.target.closest("[data-customer-profile]");
    if (profile) {
      openCustomerByUrl(`/api/customers/${encodeURIComponent(profile.dataset.customerProfile)}/profile`);
      return;
    }
    const copy = e.target.closest("[data-copy-tracking]");
    if (copy) {
      copyTracking(copy.dataset.copyTracking);
      return;
    }
    const menuView = e.target.closest("[data-ship-menu-view]");
    if (menuView) {
      openShipment(menuView.dataset.shipMenuView);
      return;
    }
    const menuStatus = e.target.closest("[data-ship-menu-status]");
    if (menuStatus) {
      const rowBadge = rowFor(menuStatus.dataset.shipMenuStatus)?.querySelector("[data-ship-status]");
      if (rowBadge) {
        openStatusMenu(rowBadge);
        const menu = $("ship-status-menu");
        if (menu && !menu.hidden) menu.dataset.oid = rowBadge.dataset.shipStatus;
      }
      return;
    }
    const menuCopy = e.target.closest("[data-ship-menu-copy]");
    if (menuCopy) {
      copyTracking(menuCopy.dataset.shipMenuCopy);
      return;
    }
    const menuDeliver = e.target.closest("[data-ship-menu-deliver]");
    if (menuDeliver) {
      openDeliver(menuDeliver.dataset.shipMenuDeliver);
      return;
    }
    const menuDelete = e.target.closest("[data-ship-menu-delete]");
    if (menuDelete) {
      deleteShipment(menuDelete.dataset.shipMenuDelete);
      return;
    }
    const pickupBtn = e.target.closest("[data-pickup-action]");
    if (pickupBtn) {
      advancePickup(pickupBtn.dataset.pickupSale, pickupBtn.dataset.pickupAction);
    }
  });

  async function advancePickup(saleId, target) {
    if (!saleId || !target) return;
    if (!window.confirm(`Move pickup order to ${target}?`)) return;
    try {
      const data = await request(`/api/sales/${encodeURIComponent(saleId)}/pickup-status`, "POST", {
        status: target,
      });
      const row = document.querySelector(`[data-pickup-row="${CSS.escape(String(saleId))}"]`);
      if (row) {
        const badge = row.querySelector(".badge");
        if (badge) {
          badge.textContent = data.status;
          badge.className = `badge ${data.status === "Collected" ? "text-bg-success" : data.status === "Ready For Pickup" ? "text-bg-info" : "text-bg-secondary"}`;
        }
        row.querySelectorAll("[data-pickup-action]").forEach((btn) => {
          btn.hidden = !(data.transitions || []).includes(btn.dataset.pickupAction);
        });
      }
      toast(`Pickup order moved to ${data.status}.`);
    } catch (e) {
      console.error("Pickup status change failed:", e);
      toast(e.message);
    }
  }

  document.addEventListener("submit", (e) => {
    if (!(e.target instanceof HTMLFormElement)) return;
    if (e.target.id !== "ship-deliver-form") return;
    e.preventDefault();
    const oid = e.target.dataset.oid;
    applyStatus(
      oid,
      "Delivered",
      {
        delivered_by: $("ship-delivered-by").value,
        delivered_date: $("ship-delivered-date").value,
        delivered_time: $("ship-delivered-time").value,
      },
    )
      .then(() => {
        hideModal("shipDeliverModal");
        if (window.StoreProShipmentModal?.refresh) {
          window.StoreProShipmentModal.refresh(oid);
        }
      })
      .catch((err) => say("ship-deliver-error", err.message, true));
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeStatusMenu();
  });
  document.addEventListener("storepro:leave", closeStatusMenu);

  window.StoreProShipping = {
    ...(window.StoreProShipping || {}),
    customer: openCustomer,
    deliver: openDeliver,
  };
}
document.addEventListener("DOMContentLoaded", spInitShippingIndex);
document.addEventListener("storepro:content", spInitShippingIndex);
