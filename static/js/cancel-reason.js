"use strict";
// Shared cancellation-reason dialog for shipment + invoice cancel flows.
// Single delegated submit binding; transient confirm modal (layers over the
// active business modal by design, then closes itself).
// Usage: window.StoreProCancel.open({ title, context, confirmLabel, onConfirm })
function spInitCancelReason() {
  if (window.__spCancelReason) return;
  window.__spCancelReason = true;

  const $ = (id) => document.getElementById(id);
  let handler = null;

  function setError(text) {
    const box = $("cancel-reason-error");
    if (!box) return;
    box.textContent = text || "";
    box.hidden = !text;
  }

  function open({ title, context, confirmLabel, onConfirm }) {
    const modalEl = $("cancelReasonModal");
    if (!modalEl) return false;
    handler = typeof onConfirm === "function" ? onConfirm : null;
    const titleEl = $("cancelReasonTitle");
    if (titleEl && title) titleEl.textContent = title;
    const ctx = $("cancel-reason-context");
    if (ctx) {
      ctx.textContent = context || "";
      ctx.hidden = !context;
    }
    const confirm = $("cancel-reason-confirm");
    if (confirm && confirmLabel) confirm.textContent = confirmLabel;
    const preset = $("cancel-reason-preset");
    if (preset) {
      preset.value = "";
      preset.dispatchEvent(new Event("change"));
    }
    const other = $("cancel-reason-other");
    if (other) other.value = "";
    setError("");
    if (window.bootstrap?.Modal) bootstrap.Modal.getOrCreateInstance(modalEl).show();
    return true;
  }

  function close() {
    const modalEl = $("cancelReasonModal");
    if (modalEl && window.bootstrap?.Modal) bootstrap.Modal.getInstance(modalEl)?.hide();
  }

  document.addEventListener("change", (e) => {
    if (e.target?.id !== "cancel-reason-preset") return;
    const wrap = $("cancel-reason-other-wrap");
    if (wrap) wrap.hidden = e.target.value !== "__other";
    setError("");
  });

  document.addEventListener("submit", (e) => {
    if (!(e.target instanceof HTMLFormElement)) return;
    if (e.target.id !== "cancel-reason-form") return;
    e.preventDefault();
    const preset = $("cancel-reason-preset");
    let reason = (preset?.value || "").trim();
    if (!reason) {
      setError("Choose a cancellation reason.");
      return;
    }
    if (reason === "__other") {
      reason = ($("cancel-reason-other")?.value || "").trim();
      if (!reason) {
        setError("Describe the cancellation reason.");
        return;
      }
    }
    const fn = handler;
    handler = null;
    close();
    if (fn) fn(reason.slice(0, 200));
  });

  window.StoreProCancel = { open, close };
}
document.addEventListener("DOMContentLoaded", spInitCancelReason);
document.addEventListener("storepro:content", spInitCancelReason);
