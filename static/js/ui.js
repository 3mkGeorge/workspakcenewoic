"use strict";
/* StoreProUI: the one shared layer for confirmations, toasts, busy buttons,
 * popup focus handling and single-open menus. Loaded before partial.js and
 * router.js so its document-level submit guard runs before they submit. */
(() => {
  if (window.StoreProUI) return;
  const doc = document;
  const $ = (id) => doc.getElementById(id);
  const label = (key, fallback) => doc.getElementById("sp-ui-strings")?.dataset[key] || fallback;
  // Translations for script-built text (server sends them only in Arabic).
  let dict = null;
  function t(text, values) {
    if (dict === null) {
      try {
        dict = JSON.parse(doc.getElementById("sp-ui-strings")?.dataset.i18n || "{}");
      } catch {
        dict = {};
      }
    }
    let out = dict[text] || text;
    if (values) out = out.replace(/\{(\w+)\}/g, (m, k) => (k in values ? String(values[k]) : m));
    return out;
  }
  // Items inside a floating menu disappear when it closes; focus goes back to
  // the button that opened the menu instead.
  const focusTarget = (el) => el?.closest?.("[data-sp-popup]")?.__spOwner || el;

  // ---- Toasts ---------------------------------------------------------------
  const ICONS = { success: "circle-check", error: "circle-alert", info: "info", warning: "triangle-alert" };
  function toast(message, type = "info") {
    const el = $("app-toast");
    if (!el || !message) return;
    const tone = ICONS[type] ? type : "info";
    el.classList.remove("is-success", "is-error", "is-info", "is-warning");
    el.classList.add(`is-${tone}`);
    el.setAttribute("role", tone === "error" ? "alert" : "status");
    el.setAttribute("aria-live", tone === "error" ? "assertive" : "polite");
    const icon = el.querySelector(".sp-toast-icon");
    if (icon) {
      icon.innerHTML = `<i data-lucide="${ICONS[tone]}"></i>`;
      window.lucide?.createIcons?.();
    }
    el.querySelector(".toast-body").textContent = String(message);
    try {
      const instance = window.bootstrap?.Toast.getOrCreateInstance(el, { delay: tone === "error" ? 8000 : 4000 });
      instance?.show();
    } catch {}
  }

  // ---- Confirm dialog ---------------------------------------------------------
  let pending = null;
  function confirmDialog(options = {}) {
    const opts = typeof options === "string" ? { message: options } : options;
    const modalEl = $("sp-confirm-modal");
    if (!modalEl || !window.bootstrap?.Modal) return Promise.resolve(window.confirm(opts.message || ""));
    if (pending) return pending.promise; // a second request while open reuses the open dialog
    const danger = opts.tone !== "primary";
    modalEl.querySelector(".sp-confirm-title").textContent = opts.title || label("confirmTitle", "Please confirm");
    const body = modalEl.querySelector(".sp-confirm-message");
    body.textContent = opts.message || "";
    const detail = modalEl.querySelector(".sp-confirm-detail");
    detail.textContent = opts.detail || "";
    detail.hidden = !opts.detail;
    const ok = modalEl.querySelector("[data-sp-confirm-ok]");
    const cancel = modalEl.querySelector("[data-sp-confirm-cancel]");
    ok.textContent = opts.confirmLabel || label("confirmOk", "Confirm");
    cancel.textContent = opts.cancelLabel || label("cancel", "Cancel");
    ok.className = `btn ${danger ? "btn-danger" : "btn-primary"}`;
    modalEl.querySelector(".sp-confirm-icon").className = `sp-confirm-icon ${danger ? "red" : "blue"}`;
    const returnFocus = focusTarget(doc.activeElement);
    let resolveFn;
    const promise = new Promise((resolve) => (resolveFn = resolve));
    pending = { promise, result: false };
    const instance = bootstrap.Modal.getOrCreateInstance(modalEl, { backdrop: "static", keyboard: true });
    const onOk = () => {
      pending.result = true;
      instance.hide();
    };
    ok.addEventListener("click", onOk, { once: true });
    modalEl.addEventListener(
      "shown.bs.modal",
      () => (danger ? cancel : ok).focus(),
      { once: true },
    );
    modalEl.addEventListener(
      "hidden.bs.modal",
      () => {
        ok.removeEventListener("click", onOk);
        const result = pending?.result || false;
        pending = null;
        if (returnFocus && returnFocus.isConnected) returnFocus.focus({ preventScroll: true });
        resolveFn(result);
      },
      { once: true },
    );
    instance.show();
    return promise;
  }

  // ---- Busy buttons -------------------------------------------------------------
  function busy(button, on = true) {
    if (!button) return;
    if (on) {
      if (button.dataset.spBusy) return;
      button.dataset.spBusy = "1";
      button.dataset.spWasDisabled = button.disabled ? "1" : "";
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      button.classList.add("is-busy");
    } else {
      if (!button.dataset.spBusy) return;
      button.disabled = button.dataset.spWasDisabled === "1";
      button.removeAttribute("aria-busy");
      button.classList.remove("is-busy");
      delete button.dataset.spBusy;
      delete button.dataset.spWasDisabled;
    }
  }

  // ---- Destructive form guard ----------------------------------------------------
  // Any form[data-confirm] is held until the user confirms in the custom dialog.
  // Nothing is sent before that: submission is re-issued only after "OK".
  // Capture phase, so the question comes before any page or router handler.
  doc.addEventListener("submit", (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-confirm")) return;
    if (form.dataset.spConfirmed === "1") {
      delete form.dataset.spConfirmed;
      return;
    }
    e.preventDefault();
    e.stopImmediatePropagation();
    const submitter = e.submitter && form.contains(e.submitter) ? e.submitter : null;
    // data-confirm-detail-from="#a, #b" names the record from live field values.
    const live = (form.dataset.confirmDetailFrom || "")
      .split(",")
      .map((sel) => sel.trim() && form.querySelector(sel.trim()))
      .map((el) => (!el ? "" : el instanceof HTMLSelectElement ? el.selectedOptions[0]?.textContent.trim() : el.value?.trim()))
      .filter(Boolean)
      .join(" · ");
    confirmDialog({
      title: form.dataset.confirmTitle,
      message: form.dataset.confirm,
      detail: live || form.dataset.confirmDetail,
      confirmLabel: form.dataset.confirmLabel,
      tone: form.dataset.confirmTone,
    }).then((yes) => {
      if (!yes) return;
      const detached = !form.isConnected;
      if (detached) {
        form.hidden = true;
        doc.body.appendChild(form);
      }
      form.dataset.spConfirmed = "1";
      if (form.requestSubmit) form.requestSubmit(submitter && submitter.isConnected ? submitter : undefined);
      else form.submit();
      if (detached) setTimeout(() => form.remove(), 0);
    });
  }, true);

  // ---- Single-open popups ------------------------------------------------------
  // Every custom menu listens for this and closes itself, so menus never overlap.
  function closeMenus(except) {
    doc.dispatchEvent(new CustomEvent("storepro:menus-close", { detail: { except } }));
  }

  // Place a body-level popup beside its anchor, inside the viewport. "start"
  // aligns with the anchor's inline-start edge, "end" with its inline-end edge
  // (mirrored automatically in RTL). Flips above when there is no room below.
  function placePopup(popup, anchor, align = "start") {
    const rect = anchor.getBoundingClientRect();
    popup.hidden = false;
    const mw = popup.offsetWidth;
    const mh = popup.offsetHeight;
    const margin = 8;
    const rtl = getComputedStyle(anchor).direction === "rtl";
    const atLeftEdge = (align === "start") !== rtl;
    let left = atLeftEdge ? rect.left : rect.right - mw;
    left = Math.max(margin, Math.min(left, window.innerWidth - mw - margin));
    let top = rect.bottom + 6;
    popup.dataset.placement = "down";
    if (top + mh + margin > window.innerHeight && rect.top - mh - 6 > margin) {
      top = rect.top - mh - 6;
      popup.dataset.placement = "up";
    }
    top = Math.max(margin, Math.min(top, window.innerHeight - mh - margin));
    popup.style.left = `${Math.round(left + (window.scrollX || 0))}px`;
    popup.style.top = `${Math.round(top + (window.scrollY || 0))}px`;
  }

  // Arrow/Home/End move between items, Escape/Tab close and return focus.
  // Returns true when the key was handled.
  function menuKeys(e, popup, close, itemSelector = "[role=menuitem]") {
    const list = [...popup.querySelectorAll(itemSelector)].filter(
      (el) => !el.disabled && !el.hidden && el.getAttribute("aria-disabled") !== "true",
    );
    const i = list.indexOf(doc.activeElement);
    const go = (n) => list.length && list[(n + list.length) % list.length].focus();
    switch (e.key) {
      case "Escape":
      case "Tab":
        close(true);
        break;
      case "ArrowDown":
        go(i + 1);
        break;
      case "ArrowUp":
        go(i < 0 ? -1 : i - 1);
        break;
      case "Home":
        go(0);
        break;
      case "End":
        go(-1);
        break;
      default:
        return false;
    }
    e.preventDefault();
    e.stopPropagation();
    return true;
  }

  // ---- Modal focus return + duplicate guard --------------------------------------
  const returnTargets = new WeakMap();
  const openModal = (except) => [...doc.querySelectorAll(".modal.show")].find((m) => m !== except);
  doc.addEventListener("show.bs.modal", (e) => {
    closeMenus();
    const trigger = focusTarget(e.relatedTarget || doc.activeElement);
    if (trigger && trigger !== doc.body) returnTargets.set(e.target, trigger);
    if (e.target.id === "sp-confirm-modal") {
      // A confirmation can sit above another dialog: lift its own backdrop too.
      Promise.resolve().then(() => {
        const backdrops = doc.querySelectorAll("body > .modal-backdrop");
        backdrops[backdrops.length - 1]?.classList.add("sp-confirm-backdrop");
      });
    }
  });
  function sweepBackdrops() {
    if (doc.querySelector(".modal.show, .modal.showing")) return;
    doc.querySelectorAll(".modal-backdrop").forEach((b) => b.remove());
    doc.body.classList.remove("modal-open");
    doc.body.style.removeProperty("overflow");
    doc.body.style.removeProperty("padding-right");
  }
  doc.addEventListener("hidden.bs.modal", (e) => {
    const trigger = returnTargets.get(e.target);
    returnTargets.delete(e.target);
    const under = openModal(e.target);
    if (under) {
      doc.body.classList.add("modal-open"); // the dialog underneath still owns the page
      if (e.target.id !== "sp-confirm-modal" && !(trigger && under.contains(trigger))) under.focus({ preventScroll: true });
    } else {
      sweepBackdrops(); // leftovers from interrupted transitions must never block the page
    }
    if (e.target.id === "sp-confirm-modal") return;
    if (trigger && trigger.isConnected && (!under || under.contains(trigger))) trigger.focus({ preventScroll: true });
  });
  doc.addEventListener("storepro:leave", () => closeMenus());
  // After SPA navigation, dialogs from the previous page are gone; so must be their backdrops.
  doc.addEventListener("storepro:content", () => setTimeout(sweepBackdrops, 450));

  window.StoreProUI = { toast, confirm: confirmDialog, busy, closeMenus, placePopup, menuKeys, t };
})();
