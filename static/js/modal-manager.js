"use strict";
// StoreProModal: single reusable business-modal manager.
//
// Rules enforced app-wide:
// - Only one business modal (".modal[data-business-modal]") is active at once.
// - Opening a new one automatically closes the current one first — modals
//   never stack (e.g. Invoice Details opens only after Shipping Details
//   has fully closed).
// - ESC / backdrop close the active modal (native Bootstrap behavior).
// - Body scroll lock is native Bootstrap (modal-open); the manager only
//   guarantees singularity, so locks never compound.
// - Modal markup is server-rendered once per view and replaced by the SPA
//   router on navigation, so duplicate DOM instances cannot accumulate;
//   all lookups are fresh on every call.
function spInitModalManager() {
  if (window.__spModalManager) return;
  window.__spModalManager = true;

  function activeModal() {
    return document.querySelector(".modal.show[data-business-modal]");
  }
  function instanceFor(el) {
    if (!el || !window.bootstrap?.Modal) return null;
    try {
      return bootstrap.Modal.getOrCreateInstance(el);
    } catch {
      return null;
    }
  }

  function open(id) {
    const el = document.getElementById(id);
    if (!el) return false;
    instanceFor(el)?.show();
    return true;
  }
  function close(id) {
    const el = id ? document.getElementById(id) : activeModal();
    if (!el) return false;
    try {
      bootstrap.Modal.getInstance(el)?.hide();
    } catch {
      return false;
    }
    return true;
  }
  // Close the current business modal first, then run opener once the
  // close transition finishes. If nothing is open, run opener immediately.
  function openExclusive(nextId, opener) {
    const current = activeModal();
    if (current && current.id !== nextId) {
      const run = () => opener();
      current.addEventListener("hidden.bs.modal", run, { once: true });
      instanceFor(current)?.hide();
    } else {
      opener();
    }
  }

  window.StoreProModal = {
    open,
    close,
    active: () => activeModal()?.id || null,
    openExclusive,
  };

  // Shared empty-state formatter for shipment fields. One state everywhere:
  // the real value, or "Not assigned yet". Numerical zero stays a value.
  window.StoreProFormat = {
    shipment: (value) =>
      value === null || value === undefined || value === ""
        ? "Not assigned yet"
        : value,
  };
}
document.addEventListener("DOMContentLoaded", spInitModalManager);
document.addEventListener("storepro:content", spInitModalManager);
