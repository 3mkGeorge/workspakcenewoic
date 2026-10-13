"use strict";
// Shipment Details workspace modal: single order_detail payload drives every
// section (header, info, address, courier, products, summary, steps).
// SPA-safe: one document-level delegation, fresh lookups on every open.
function spInitShipmentModal() {
  if (window.__spShipmentModal) return;
  window.__spShipmentModal = true;

  const NA = "Not assigned yet";
  const fmt = (v) => (v === null || v === undefined || v === "" ? NA : v);
  const STAGES = ["Pending", "Packed", "Ready For Shipment", "Shipped", "Out For Delivery", "Delivered"];
  const ACTION = {
    Packed: "Mark Packed",
    "Ready For Shipment": "Mark Ready For Shipment",
    Shipped: "Mark as Shipped",
    "Out For Delivery": "Mark Out For Delivery",
    Delivered: "Mark as Delivered",
    Returned: "Mark Returned",
    Cancelled: "Cancel Shipment",
  };
  const BADGES = {
    Pending: "secondary",
    Packed: "info",
    Preparing: "info",
    "Ready For Shipment": "purple",
    Shipped: "orange",
    "Out For Delivery": "cyan",
    Delivered: "success",
    "Failed Delivery": "danger",
    Returned: "warning",
    Cancelled: "darkred",
  };

  const $ = (id) => document.getElementById(id);
  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || "";
  const icons = () => { if (window.lucide) window.lucide.createIcons(); };
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

  let current = null;
  let requestSeq = 0;

  function pairRow(parent, labelText, valueNode, nowrap) {
    const wrap = document.createElement("div");
    wrap.className = "fld";
    const lab = document.createElement("span");
    lab.className = "flabel";
    lab.textContent = labelText;
    const val = document.createElement("span");
    val.className = "fvalue" + (nowrap ? " sm-nowrap" : "");
    if (valueNode instanceof Node) val.append(valueNode);
    else val.textContent = valueNode;
    wrap.append(lab, val);
    parent.append(wrap);
  }

  function renderHeader(d, o) {
    $("shipmentModalNo").textContent = o.order_number;
    const sub = $("shipmentModalSub");
    sub.replaceChildren();
    sub.append("Invoice: ");
    if (o.sale_id) {
      const invBtn = document.createElement("button");
      invBtn.type = "button";
      invBtn.className = "ship-link";
      invBtn.dataset.saleModal = o.sale_id;
      invBtn.textContent = o.invoice;
      sub.append(invBtn);
    } else {
      sub.append(fmt(""));
    }
    sub.append(` • Customer: ${o.customer || fmt("")}`);
    const badge = $("shipmentModalStatus");
    badge.replaceChildren();
    const span = document.createElement("span");
    span.className = `badge text-bg-${BADGES[o.status] || "secondary"}`;
    span.textContent = o.status;
    badge.append(span);
  }

  function renderInfo(d, o) {
    const info = $("shipmentModalInfo");
    info.replaceChildren();
    pairRow(info, "Order Number", o.order_number, true);
    if (o.sale_id) {
      const invBtn = document.createElement("button");
      invBtn.type = "button";
      invBtn.className = "ship-link";
      invBtn.dataset.saleModal = o.sale_id;
      invBtn.textContent = o.invoice;
      pairRow(info, "Invoice Number", invBtn);
    } else {
      pairRow(info, "Invoice Number", fmt(""));
    }
    pairRow(info, "Customer", o.customer || fmt(""));
    pairRow(info, "Phone", o.phone || fmt(""));
    pairRow(info, "Tracking Code", fmt(o.tracking_code), !!o.tracking_code);
    pairRow(info, "Status", o.status);
    pairRow(info, "Courier", fmt(o.courier));
    pairRow(info, "Created At", d.created_display || fmt(""));
  }

  function renderAddress(d) {
    const addr = $("shipmentModalAddress");
    addr.textContent = d.address_lines || "Incomplete Address";
    const list = $("shipmentModalAddressList");
    list.replaceChildren();
    const a = d.address || {};
    let shown = 0;
    [["Governorate", a.governorate], ["City", a.city], ["District", a.district],
     ["Street", a.street], ["Building", a.building], ["Floor", a.floor],
     ["Apartment", a.apartment], ["Landmark", a.landmark], ["Postal Code", a.postal_code]
    ].forEach(([k, v]) => {
      if (!v) return;
      shown += 1;
      pairRow(list, k, v);
    });
    if (d.address_incomplete || !shown) {
      const note = document.createElement("p");
      note.className = "sm-incomplete";
      note.textContent = "Incomplete Address";
      list.append(note);
    }
  }

  function renderCourier(d, o) {
    const box = $("shipmentModalCourier");
    box.replaceChildren();
    pairRow(box, "Courier Company", fmt(o.courier));
    if (o.tracking_code) {
      const wrap = document.createElement("span");
      wrap.className = "sm-nowrap";
      const code = document.createElement("code");
      code.textContent = o.tracking_code;
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "btn btn-light btn-sm sm-copy-inline";
      copy.dataset.copyTracking = o.tracking_code;
      copy.textContent = "Copy";
      wrap.append(code, " ", copy);
      pairRow(box, "Tracking Code", wrap);
    } else {
      pairRow(box, "Tracking Code", fmt(""));
    }
    if (o.tracking_url) {
      const link = document.createElement("a");
      link.href = o.tracking_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = o.tracking_url;
      pairRow(box, "Tracking URL", link);
    } else {
      pairRow(box, "Tracking URL", fmt(""));
    }
    pairRow(box, "Shipping Cost", money(o.shipping_cost, o.currency));
    pairRow(box, "Shipment Date", fmt(o.shipment_date));
  }

  function renderProducts(d, o) {
    const rows = $("shipmentModalRows");
    rows.replaceChildren();
    (d.items || []).forEach((item, i) => {
      const tr = document.createElement("tr");
      const num = document.createElement("td");
      num.textContent = i + 1;
      const prod = document.createElement("td");
      prod.className = "pname";
      if (item.image) {
        const img = document.createElement("img");
        img.src = item.image;
        img.alt = item.name;
        img.loading = "lazy";
        img.className = "pthumb";
        prod.append(img, " ");
      }
      prod.append(item.name);
      const sku = document.createElement("td");
      sku.className = "muted";
      sku.textContent = fmt(item.sku);
      const qty = document.createElement("td");
      qty.className = "num";
      qty.textContent = item.quantity;
      const price = document.createElement("td");
      price.className = "num";
      price.textContent = money(item.price, o.currency);
      const disc = document.createElement("td");
      disc.className = "num";
      disc.textContent = money(item.discount, o.currency);
      const total = document.createElement("td");
      total.className = "num fw-semibold";
      total.textContent = money(item.total, o.currency);
      tr.append(num, prod, sku, qty, price, disc, total);
      rows.append(tr);
    });
    const summary = $("shipmentModalSummary");
    summary.replaceChildren();
    const st = d.sale_totals;
    if (st) {
      const box = document.createElement("dl");
      box.className = "detail-list totals sm-summary";
      [["Subtotal", money(st.subtotal, st.currency)],
       ["Discount", money(st.discount, st.currency)],
       [`VAT (${Number(st.tax_rate) / 100}%)`, money(st.tax, st.currency)],
      ].forEach(([k, v]) => {
        const dt = document.createElement("dt");
        dt.textContent = k;
        const dd = document.createElement("dd");
        dd.textContent = v;
        box.append(dt, dd);
      });
      const grand = document.createElement("div");
      grand.className = "sm-grand";
      const gb = document.createElement("b");
      gb.textContent = "Grand Total";
      const gv = document.createElement("b");
      gv.textContent = money(st.total, st.currency);
      grand.append(gb, gv);
      summary.append(box, grand);
    } else {
      summary.textContent = fmt("");
    }
  }

  function renderSteps(d, o) {
    const steps = $("shipmentModalSteps");
    steps.replaceChildren();
    const byAction = {};
    (d.events || []).forEach((e) => {
      if (!byAction[e.action]) byAction[e.action] = e;
    });
    const currentIdx = STAGES.indexOf(o.status);
    STAGES.forEach((stage, i) => {
      const li = document.createElement("li");
      const done = currentIdx !== -1 && (i < currentIdx || o.status === "Delivered");
      li.className = `sm-step${done ? " done" : ""}${i === currentIdx ? " current" : ""}${currentIdx !== -1 && i > currentIdx && o.status !== "Delivered" ? " todo" : ""}`;
      const dot = document.createElement("span");
      dot.className = "sm-step-dot";
      dot.textContent = done ? "✓" : i + 1;
      const lab = document.createElement("span");
      lab.className = "sm-step-label";
      lab.textContent = stage;
      li.append(dot, lab);
      const ev = byAction[stage] || (stage === "Pending" ? byAction["Order Created"] : null);
      if (ev && (ev.at || ev.actor)) {
        const meta = document.createElement("small");
        meta.className = "sm-step-meta";
        meta.textContent = [ev.at, ev.actor].filter(Boolean).join(" · ");
        li.append(meta);
      }
      if (i === currentIdx) {
        const cur = document.createElement("span");
        cur.className = "sm-step-current";
        cur.textContent = "Current Stage";
        li.append(cur);
      }
      steps.append(li);
    });
    // Terminal + activity events that are not stages appear once, below.
    const extra = (d.events || []).filter((e) =>
      !STAGES.includes(e.action) && e.action !== "Order Created");
    if (currentIdx === -1 || extra.length) {
      const list = document.createElement("ul");
      list.className = "sm-activity";
      if (currentIdx === -1) {
        const li = document.createElement("li");
        li.textContent = `Exception state: ${o.status}`;
        list.append(li);
      }
      extra.forEach((e) => {
        const li = document.createElement("li");
        li.textContent = [e.action, [e.actor, e.at].filter(Boolean).join(" · ")]
          .filter(Boolean)
          .join(" — ");
        list.append(li);
      });
      steps.append(list);
    }
  }

  function renderActions(d, o) {
    const bar = $("shipmentModalActions");
    bar.replaceChildren();
    (d.transitions || []).forEach((target) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = target === "Shipped" ? "btn btn-primary" : "btn btn-light";
      btn.dataset.smAction = target;
      btn.textContent = ACTION[target] || `Mark ${target}`;
      bar.append(btn);
    });
    if (!(d.transitions || []).length) {
      const span = document.createElement("span");
      span.className = "muted";
      span.textContent = "This order is closed. No further actions.";
      bar.append(span);
    }
  }

  function render(d) {
    const o = d.order;
    renderHeader(d, o);
    renderInfo(d, o);
    renderAddress(d);
    renderCourier(d, o);
    renderProducts(d, o);
    renderSteps(d, o);
    renderActions(d, o);
    $("shipmentModalEdit").onclick = () => openEditDialog();
    $("shipmentModalCourierEdit").onclick = () => openEditDialog();
    $("shipmentModalInfoEdit").onclick = () => openEditDialog();
    $("shipmentModalAddressEdit").onclick = () => openAddressDialog();
    $("shipmentModalOpenInvoice").onclick = () => openInvoice();
    $("shipmentModalOpenSummary").onclick = () => openInvoice();
    $("shipmentModalLabel").href = `/shipping/${o.id}/label`;
    const inv = $("shipmentModalInvoice");
    inv.href = `/sales/${o.sale_id}/invoice`;
    inv.hidden = !o.sale_id;
    icons();
  }

  async function open(oid) {
    const seq = ++requestSeq;
    if (!showModal("shipmentModal")) return;
    $("shipmentModalNo").textContent = "…";
    $("shipmentModalSub").textContent = "";
    $("shipmentModalLoading").hidden = false;
    $("shipmentModalContent").hidden = true;
    say("shipmentModalMessage", "");
    try {
      const data = await request(`/api/shipping/${encodeURIComponent(oid)}`);
      if (seq !== requestSeq) return;
      current = data;
      render(data);
      $("shipmentModalLoading").hidden = true;
      $("shipmentModalContent").hidden = false;
      icons();
    } catch (e) {
      if (seq !== requestSeq) return;
      console.error("Shipment details failed to load:", e);
      $("shipmentModalLoading").hidden = true;
      say("shipmentModalMessage", "Unable to load shipment details.", true);
    }
  }

  function updateTableRow(o, transitions) {
    const row = document.querySelector(`[data-ship-row="${CSS.escape(String(o.id))}"]`);
    if (!row) return;
    const badge = row.querySelector("[data-ship-status]");
    if (badge) {
      badge.className = `badge text-bg-${BADGES[o.status] || "secondary"} ship-status-btn`;
      badge.textContent = o.status;
      badge.dataset.status = o.status;
      badge.dataset.transitions = (transitions || []).join("|");
    }
    const trackingCell = row.querySelector("[data-copy-tracking]")?.closest("td")
      || [...row.children][7];
    if (trackingCell) {
      trackingCell.replaceChildren();
      if (o.tracking_code) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ship-tracking";
        btn.dataset.copyTracking = o.tracking_code;
        btn.title = "Copy tracking code";
        const code = document.createElement("code");
        code.textContent = o.tracking_code;
        btn.append(code);
        trackingCell.append(btn);
      } else {
        const span = document.createElement("span");
        span.className = "muted";
        span.textContent = NA;
        trackingCell.append(span);
      }
    }
    const deliverItem = row.querySelector("[data-ship-menu-deliver]");
    if (deliverItem) deliverItem.hidden = !(transitions || []).includes("Delivered");
    const courierCell = [...row.children][6];
    if (courierCell) {
      courierCell.replaceChildren();
      courierCell.className = "muted";
      courierCell.textContent = fmt(o.courier);
    }
  }

  async function applyStatus(oid, target, extra) {
    try {
      const data = await request(`/api/shipping/${encodeURIComponent(oid)}/status`, "POST", {
        status: target,
        ...(extra || {}),
      });
      updateTableRow(data.order, data.transitions);
      if (current && current.order.id === Number(oid)) {
        const fresh = await request(`/api/shipping/${encodeURIComponent(oid)}`);
        current = fresh;
        render(fresh);
      }
      toast(`Order moved to ${target}.`);
    } catch (e) {
      console.error("Shipment status change failed:", e);
      toast(e.message);
    }
  }

  function openInvoice() {
    const sid = current?.order.sale_id;
    if (!sid) {
      toast("No linked invoice.");
      return;
    }
    if (window.StoreProModal) {
      window.StoreProModal.openExclusive("saleDetailsModal", () => {
        if (window.StoreProSaleModal) window.StoreProSaleModal.open(sid);
      });
    } else if (window.StoreProSaleModal) {
      window.StoreProSaleModal.open(sid);
    }
  }

  function openEditDialog() {
    if (!current) return;
    const o = current.order;
    if (o.status === "Delivered") {
      toast("Delivered shipments are locked.");
      return;
    }
    $("shipmentEditCourier").value = o.courier || "";
    $("shipmentEditTracking").value = o.tracking_code || "";
    $("shipmentEditUrl").value = o.tracking_url || "";
    $("shipmentEditCost").value = (Number(o.shipping_cost || 0) / 100).toFixed(2);
    $("shipmentEditDate").value = o.shipment_date || "";
    say("shipmentEditError", "");
    showModal("shipmentEditModal");
  }

  function openAddressDialog() {
    if (!current) return;
    const a = current.address || {};
    $("shipmentAddrGov").value = a.governorate || "";
    $("shipmentAddrCity").value = a.city || "";
    $("shipmentAddrDistrict").value = a.district || "";
    $("shipmentAddrStreet").value = a.street || "";
    $("shipmentAddrLandmark").value = a.landmark || "";
    $("shipmentAddrBuilding").value = a.building || "";
    $("shipmentAddrFloor").value = a.floor || "";
    $("shipmentAddrApt").value = a.apartment || "";
    $("shipmentAddrPostal").value = a.postal_code || "";
    say("shipmentAddressError", "");
    showModal("shipmentAddressModal");
  }

  function parseCost(value) {
    const clean = String(value || "").replace(/[, ]/g, "");
    if (!/^\d{1,10}(\.\d{0,2})?$/.test(clean) || clean === "") return null;
    const [a, b = ""] = clean.split(".");
    return Number(a) * 100 + Number(b.padEnd(2, "0"));
  }

  async function refreshCurrent(oid) {
    const fresh = await request(`/api/shipping/${encodeURIComponent(oid)}`);
    current = fresh;
    render(fresh);
    return fresh;
  }

  function openShipDialog() {
    if (!current) return;
    const o = current.order;
    $("shipmentShipCourier").textContent = o.courier || NA;
    $("shipmentShipCost").textContent = money(o.shipping_cost, o.currency);
    $("shipmentShipDate").textContent = o.shipment_date || NA;
    $("shipmentShipTracking").value = "";
    $("shipmentShipUrl").value = "";
    say("shipmentShipError", "");
    showModal("shipmentShipModal");
  }

  function openDeliver(oid) {
    const form = $("ship-deliver-form");
    if (!form) return;
    form.dataset.oid = oid;
    const now = new Date();
    $("ship-delivered-date").value = now.toISOString().slice(0, 10);
    $("ship-delivered-time").value =
      String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0");
    $("ship-delivered-by").value = "";
    say("ship-deliver-error", "");
    showModal("shipDeliverModal");
  }

  document.addEventListener("click", (e) => {
    const view = e.target.closest("[data-ship-view]");
    if (view) {
      open(view.dataset.shipView);
      return;
    }
    const menuView = e.target.closest("[data-ship-menu-view]");
    if (menuView) {
      open(menuView.dataset.shipMenuView);
      return;
    }
    const prev = e.target.closest("#shipmentModalPrev");
    if (prev) {
      hideModal("shipmentModal");
      return;
    }
    const action = e.target.closest("[data-sm-action]");
    if (action) {
      const target = action.dataset.smAction;
      const oid = current?.order.id;
      if (!oid) return;
      if (target === "Shipped") {
        openShipDialog();
      } else if (target === "Delivered") {
        hideModal("shipmentModal");
        openDeliver(oid);
      } else if (target === "Cancelled" && window.StoreProCancel) {
        const o = current?.order;
        window.StoreProCancel.open({
          title: "Cancel Shipment",
          context: o ? `Cancelling ${o.order_number}. A reason is required.` : "",
          confirmLabel: "Confirm Cancel",
          onConfirm: (reason) => applyStatus(oid, target, { cancel_reason: reason }),
        });
      } else {
        const label = ACTION[target] || `Mark ${target}`;
        if (!window.confirm(`${label} this shipment?`)) return;
        applyStatus(oid, target);
      }
    }
  });

  document.addEventListener("submit", (e) => {
    if (!(e.target instanceof HTMLFormElement)) return;
    if (e.target.id !== "shipmentShipForm") return;
    e.preventDefault();
    const oid = current?.order.id;
    if (!oid) return;
    const code = $("shipmentShipTracking").value.trim();
    if (!code) {
      say("shipmentShipError", "Enter the tracking code supplied by the courier.", true);
      return;
    }
    const body = { tracking_code: code };
    const url = $("shipmentShipUrl").value.trim();
    if (url) body.tracking_url = url;
    request(`/api/shipping/${encodeURIComponent(oid)}`, "POST", body)
      .then((data) => {
        updateTableRow(data.order, data.transitions);
        hideModal("shipmentShipModal");
        return request(`/api/shipping/${encodeURIComponent(oid)}`);
      })
      .then((fresh) => {
        current = fresh;
        render(fresh);
        toast("Order marked as Shipped.");
      })
      .catch((err) => {
        console.error("Ship dialog save failed:", err);
        say("shipmentShipError", err.message, true);
      });
  });

  document.addEventListener("submit", (e) => {
    if (!(e.target instanceof HTMLFormElement)) return;
    if (e.target.id !== "shipmentEditForm") return;
    e.preventDefault();
    const oid = current?.order.id;
    if (!oid) return;
    const cost = parseCost($("shipmentEditCost").value);
    if (cost === null) {
      say("shipmentEditError", "Enter a valid shipping cost.", true);
      return;
    }
    const body = {
      courier: $("shipmentEditCourier").value,
      shipping_cost: cost,
      shipment_date: $("shipmentEditDate").value,
    };
    const code = $("shipmentEditTracking").value.trim();
    if (code) body.tracking_code = code;
    const url = $("shipmentEditUrl").value.trim();
    if (url) body.tracking_url = url;
    request(`/api/shipping/${encodeURIComponent(oid)}`, "POST", body)
      .then((data) => {
        updateTableRow(data.order, data.transitions);
        hideModal("shipmentEditModal");
        const shipped = (data.changed || []).includes("status Shipped");
        return request(`/api/shipping/${encodeURIComponent(oid)}`).then((fresh) => ({
          fresh,
          shipped,
        }));
      })
      .then(({ fresh, shipped }) => {
        current = fresh;
        render(fresh);
        toast(shipped ? "Tracking saved. Order marked as Shipped." : "Shipment saved.");
      })
      .catch((err) => {
        console.error("Shipment edit save failed:", err);
        say("shipmentEditError", err.message, true);
      });
  });

  document.addEventListener("submit", (e) => {
    if (!(e.target instanceof HTMLFormElement)) return;
    if (e.target.id !== "shipmentAddressForm") return;
    e.preventDefault();
    const oid = current?.order.id;
    if (!oid) return;
    const body = {
      governorate: $("shipmentAddrGov").value,
      city: $("shipmentAddrCity").value,
      district: $("shipmentAddrDistrict").value,
      street: $("shipmentAddrStreet").value,
      landmark: $("shipmentAddrLandmark").value,
      building: $("shipmentAddrBuilding").value,
      floor: $("shipmentAddrFloor").value,
      apartment: $("shipmentAddrApt").value,
      postal_code: $("shipmentAddrPostal").value,
    };
    request(`/api/shipping/${encodeURIComponent(oid)}`, "POST", body)
      .then(() => request(`/api/shipping/${encodeURIComponent(oid)}`))
      .then((fresh) => {
        current = fresh;
        render(fresh);
        hideModal("shipmentAddressModal");
        toast("Delivery address saved.");
      })
      .catch((err) => {
        console.error("Address save failed:", err);
        say("shipmentAddressError", err.message, true);
      });
  });

  window.StoreProShipment = { ...(window.StoreProShipment || {}), open, reload: () => current && open(current.order.id) };
  window.StoreProShipmentModal = { open, refresh: refreshCurrent };
}
document.addEventListener("DOMContentLoaded", spInitShipmentModal);
document.addEventListener("storepro:content", spInitShipmentModal);
