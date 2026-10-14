"use strict";
// Shipping Order Details: 5-stage workflow, view/edit courier modes,
// tracking assigned at shipment. In-place updates, no page reload.
function spInitShipping() {
  const root = document.getElementById("ship-detail");
  if (!root || root.dataset.spInit) return;
  root.dataset.spInit = "1";
  const orderId = root.dataset.orderId;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const box = document.getElementById("ship-message");
  // Single-state display: real value or "Not assigned yet" (zero stays zero).
  const NA = "Not assigned yet";
  const formatShipmentValue =
    window.StoreProFormat?.shipment ||
    ((v) => (v === null || v === undefined || v === "" ? NA : v));
  const STAGES = ["Pending", "Packed", "Ready For Shipment", "Shipped", "Out For Delivery", "Delivered"];
  const STAGE_KEY = { Pending: 0, Packed: 1, Preparing: 1, "Ready For Shipment": 2, Shipped: 3, "Out For Delivery": 4, Delivered: 5 };
  const ACTION_LABEL = (t) =>
    t === "Packed"
      ? "Mark Packed"
      : t === "Ready For Shipment"
        ? "Mark Ready For Shipment"
        : t === "Shipped"
          ? "Mark as Shipped"
          : t === "Out For Delivery"
            ? "Mark Out For Delivery"
            : t === "Delivered"
              ? "Mark as Delivered"
              : t === "Returned"
                ? "Mark Returned"
                : t === "Cancelled"
                  ? "Cancel Shipment"
                  : `Mark ${t}`;
  const NOTE_PREFIXES = ["Tracking code", "Tracking Added", "Tracking URL", "Courier ", "Shipping cost", "Shipment date"];
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

  const ui = () => window.StoreProUI;
  const tr = (text, values) => (ui() ? ui().t(text, values) : text);
  function message(text) {
    if (!box) return;
    box.textContent = text;
    box.hidden = !text;
  }
  let changing = false;
  const icons = () => { if (window.lucide) window.lucide.createIcons(); };
  async function post(url, body) {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRFToken": csrf,
      },
      body: JSON.stringify(body || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok)
      throw Error(data.error || data.message || "The request failed.");
    return data;
  }
  function parseCost(value) {
    if (typeof value !== "string") return null;
    const clean = value.replace(/[, ]/g, "");
    if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null;
    return Math.round(Number(clean) * 100);
  }

  function renderWorkflow(status) {
    const steps = document.getElementById("ship-steps");
    if (!steps) return;
    const idx = STAGE_KEY[status];
    steps.replaceChildren();
    steps.dataset.stage = idx === undefined ? -1 : idx;
    STAGES.forEach((label, i) => {
      const li = document.createElement("li");
      const done = idx !== undefined && (i < idx || idx === 5);
      li.className = `ship-step ${done ? "done" : ""} ${i === idx ? "current" : ""} ${idx !== undefined && i > idx && idx !== 5 ? "todo" : ""}`;
      const dot = document.createElement("span");
      dot.className = "ship-step-dot";
      dot.textContent = i + 1;
      const name = document.createElement("span");
      name.className = "ship-step-label";
      name.textContent = label;
      li.append(dot, name);
      steps.append(li);
    });
    const name = document.getElementById("ship-stage-name");
    if (name) name.textContent = idx === undefined ? status : STAGES[idx];
  }

  function setBadge(status) {
    [["ship-head-badge", true], ["ship-status-badge", false]].forEach(([id, big]) => {
      const badge = document.getElementById(id);
      if (badge) {
        badge.className = `badge text-bg-${BADGES[status] || "secondary"}${big ? " fs-6" : ""}`;
        badge.textContent = status;
      }
    });
  }

  function setActions(transitions) {
    const box = document.getElementById("ship-actions");
    if (!box) return;
    box.replaceChildren();
    if (!transitions.length) {
      const span = document.createElement("span");
      span.className = "muted";
      span.textContent = "This order is closed. No further actions.";
      box.append(span);
      return;
    }
    transitions.forEach((target) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `btn ${target === "Shipped" ? "btn-primary ship-ship-btn" : "btn-light"}`;
      btn.dataset.status = target;
      btn.textContent = ACTION_LABEL(target);
      box.append(btn);
    });
  }

  function renderTracking(code) {
    const view = document.getElementById("ship-tracking-view");
    if (!view) return;
    const cell = view.closest("dd") || view.parentElement;
    cell.replaceChildren();
    if (code) {
      const el = document.createElement("code");
      el.id = "ship-tracking-view";
      el.textContent = code;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-light btn-sm";
      btn.id = "copy-tracking";
      btn.textContent = "Copy";
      btn.addEventListener("click", copyTracking);
      cell.append(el, " ", btn);
    } else {
      const span = document.createElement("span");
      span.className = "muted";
      span.id = "ship-tracking-view";
      span.textContent = NA;
      cell.append(span);
    }
    icons();
  }

  function renderTrackingUrl(url) {
    const view = document.getElementById("ship-tracking-url-view");
    if (!view) return;
    view.replaceChildren();
    if (url) {
      const a = document.createElement("a");
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = url;
      view.append(a);
    } else {
      const span = document.createElement("span");
      span.className = "muted";
      span.textContent = NA;
      view.append(span);
    }
  }

  function prependEvent(event) {
    if (!event) return;
    const list = document.getElementById("ship-timeline");
    if (!list) return;
    const li = document.createElement("li");
    li.className = NOTE_PREFIXES.some((p) => event.action.startsWith(p))
      ? "ship-event-note"
      : "ship-event-status";
    const b = document.createElement("b");
    b.textContent = event.action;
    const small = document.createElement("small");
    small.textContent = `${event.actor} · ${event.at || ""}`;
    li.append(b, small);
    list.prepend(li);
  }

  function applyOrder(data) {
    const order = data.order;
    root.dataset.status = order.status;
    setBadge(order.status);
    // Shipment Information strip reads the same order object: status, courier,
    // tracking stay identical to the Courier card after every mutation.
    const stripBadge = document.getElementById("ship-strip-badge");
    if (stripBadge) {
      stripBadge.className = `badge text-bg-${BADGES[order.status] || "secondary"}`;
      stripBadge.textContent = order.status;
    }
    const set = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.textContent = value;
    };
    set("ship-strip-courier", formatShipmentValue(order.courier));
    const stripTracking = document.getElementById("ship-strip-tracking");
    if (stripTracking) {
      stripTracking.replaceChildren();
      if (order.tracking_code) {
        const el = document.createElement("code");
        el.textContent = order.tracking_code;
        stripTracking.append(el);
      } else {
        stripTracking.textContent = NA;
      }
    }
    setActions(data.transitions || []);
    renderWorkflow(order.status);
    prependEvent(data.event);
    if (order.status === "Delivered") {
      document.getElementById("delivered-info")?.removeAttribute("hidden");
      const by = document.getElementById("delivered-by-view");
      const at = document.getElementById("delivered-at-view");
      if (by) by.textContent = formatShipmentValue(order.delivered_by);
      if (at) at.textContent = formatShipmentValue(order.delivered_at);
    }
    set("ship-courier-view", formatShipmentValue(order.courier));
    renderTracking(order.tracking_code || "");
    renderTrackingUrl(order.tracking_url || "");
    if (order.status === "Delivered") {
      document.getElementById("courier-edit-toggle")?.setAttribute("hidden", "");
      setCourierMode(false);
    }
    // Keep the edit form in sync so reopening it never shows stale values.
    const syncInput = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.value = value;
    };
    syncInput("courier-name", order.courier || "");
    syncInput("courier-tracking", order.tracking_code || "");
    syncInput("courier-tracking-url", order.tracking_url || "");
    if (typeof order.shipping_cost === "number")
      syncInput("shipping-cost", (order.shipping_cost / 100).toFixed(2));
    syncInput("shipment-date", order.shipment_date || "");
    const cost = document.getElementById("ship-cost-view");
    if (cost && typeof data.order.shipping_cost === "number") {
      cost.textContent = `${data.order.currency || ""} ${(data.order.shipping_cost / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    const sdate = document.getElementById("ship-date-view");
    if (sdate) sdate.textContent = formatShipmentValue(data.order.shipment_date);
  }

  async function copyTracking() {
    const code = document.getElementById("ship-tracking-view")?.textContent || "";
    if (!code || code.includes("Not Assigned")) return;
    try {
      await navigator.clipboard.writeText(code.trim());
      message("Tracking code copied.");
    } catch {
      message("Copy failed. Select the code manually.");
    }
    setTimeout(() => message(""), 2500);
  }
  document.getElementById("copy-tracking")?.addEventListener("click", copyTracking);

  // Courier view/edit modes (tracking is assigned only via Mark as Shipped).
  const courierForm = document.getElementById("courier-form");
  const courierView = document.getElementById("courier-view");
  function setCourierMode(edit) {
    if (courierForm) courierForm.hidden = !edit;
    if (courierView) courierView.hidden = edit;
    const toggle = document.getElementById("courier-edit-toggle");
    if (toggle) toggle.hidden = edit;
  }
  document.getElementById("courier-edit-toggle")?.addEventListener("click", () => setCourierMode(true));
  document.getElementById("courier-cancel")?.addEventListener("click", () => setCourierMode(false));
  if (courierForm)
    courierForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const cost = parseCost(document.getElementById("shipping-cost").value);
      if (cost === null) {
        message("Enter a valid shipping cost.");
        return;
      }
      try {
        const body = {
          courier: document.getElementById("courier-name").value,
          shipping_cost: cost,
          shipment_date: document.getElementById("shipment-date").value,
        };
        const codeInput = document.getElementById("courier-tracking");
        if (codeInput && codeInput.value.trim()) body.tracking_code = codeInput.value;
        const urlInput = document.getElementById("courier-tracking-url");
        if (urlInput) body.tracking_url = urlInput.value.trim();
        const data = await post(`/api/shipping/${orderId}`, body);
        if (!data.changed.length) {
          message("No changes to save.");
          return;
        }
        applyOrder(data);
        setCourierMode(false);
        message(
          data.changed.includes("status Shipped")
            ? "Tracking saved. Order marked as Shipped."
            : "Courier saved."
        );
      } catch (error) {
        message(error.message);
      }
    });

  // Mark as Shipped: courier-supplied tracking only — saving ships the order.
  const shipInput = document.getElementById("ship-tracking-input");
  const shipUrlInput = document.getElementById("ship-tracking-url");
  const shipForm = document.getElementById("ship-form");
  if (shipForm)
    shipForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const err = document.getElementById("ship-error");
      if (err) err.hidden = true;
      const code = shipInput?.value.trim() || "";
      if (!code) {
        if (err) {
          err.textContent = "Enter the tracking code supplied by the courier.";
          err.hidden = false;
        }
        return;
      }
      try {
        const body = { tracking_code: code, ship: true };
        if (shipUrlInput?.value.trim()) body.tracking_url = shipUrlInput.value;
        const data = await post(`/api/shipping/${orderId}`, body);
        bootstrap.Modal.getInstance(document.getElementById("ship-modal"))?.hide();
        applyOrder(data);
        message("Order marked as Shipped.");
      } catch (error) {
        if (err) {
          err.textContent = error.message;
          err.hidden = false;
        } else {
          message(error.message);
        }
      }
    });

  const actions = document.getElementById("ship-actions");
  if (actions)
    actions.addEventListener("click", async (event) => {
      const btn = event.target.closest("button[data-status]");
      if (!btn) return;
      const target = btn.dataset.status;
      if (target === "Delivered") {
        const now = new Date();
        document.getElementById("delivered-date").value = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
        document.getElementById("delivered-time").value =
          String(now.getHours()).padStart(2, "0") +
          ":" +
          String(now.getMinutes()).padStart(2, "0");
        bootstrap.Modal.getOrCreateInstance(document.getElementById("deliver-modal")).show();
        return;
      }
      if (target === "Shipped") {
        if (shipInput) shipInput.value = "";
        const shipUrl = document.getElementById("ship-tracking-url");
        if (shipUrl) shipUrl.value = "";
        const err = document.getElementById("ship-error");
        if (err) err.hidden = true;
        const fill = (id, value) => {
          const el = document.getElementById(id);
          if (el) el.textContent = value;
        };
        fill("ship-confirm-courier", document.getElementById("ship-courier-view")?.textContent || NA);
        fill("ship-confirm-cost", document.getElementById("ship-cost-view")?.textContent || NA);
        fill("ship-confirm-date", document.getElementById("ship-date-view")?.textContent || NA);
        bootstrap.Modal.getOrCreateInstance(document.getElementById("ship-modal")).show();
        return;
      }
      if (target === "Cancelled" && window.StoreProCancel) {
        const number = root.dataset.orderNumber || orderId;
        window.StoreProCancel.open({
          title: tr("Cancel Shipment"),
          context: tr("Cancelling {order}. A reason is required.", { order: number }),
          confirmLabel: tr("Confirm Cancel"),
          onConfirm: async (reason) => {
            if (changing) return;
            changing = true;
            try {
              const data = await post(`/api/shipping/${orderId}/status`, {
                status: target,
                cancel_reason: reason,
              });
              applyOrder(data);
              message(tr("Order moved to {status}.", { status: tr(target) }));
            } catch (error) {
              message(error.message);
            } finally {
              changing = false;
            }
          },
        });
        return;
      }
      if (changing) return;
      const opts = {
        title: tr("Change shipment status?"),
        message: tr("Move this order to {status}?", { status: tr(target) }),
        detail: root.dataset.orderNumber || "",
        confirmLabel: tr(ACTION_LABEL(target)),
        tone: target === "Returned" || target === "Failed Delivery" ? "danger" : "primary",
      };
      if (!(await (ui() ? ui().confirm(opts) : Promise.resolve(window.confirm(opts.message))))) return;
      if (changing) return;
      changing = true;
      ui()?.busy(btn, true);
      try {
        const data = await post(`/api/shipping/${orderId}/status`, { status: target });
        applyOrder(data);
        message(tr("Order moved to {status}.", { status: tr(target) }));
      } catch (error) {
        message(error.message);
      } finally {
        changing = false;
        ui()?.busy(btn, false);
      }
    });
  const deliverForm = document.getElementById("deliver-form");
  if (deliverForm)
    deliverForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const data = await post(`/api/shipping/${orderId}/status`, {
          status: "Delivered",
          delivered_by: document.getElementById("delivered-by").value,
          delivered_date: document.getElementById("delivered-date").value,
          delivered_time: document.getElementById("delivered-time").value,
        });
        bootstrap.Modal.getInstance(document.getElementById("deliver-modal"))?.hide();
        applyOrder(data);
        message("Delivery confirmed.");
      } catch (error) {
        message(error.message);
      }
    });
}
document.addEventListener("DOMContentLoaded", spInitShipping);
document.addEventListener("storepro:content", spInitShipping);
