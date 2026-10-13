"use strict";
function spInitInvoice() {
  const btn = document.getElementById("print-invoice");
  if (!btn || btn.dataset.spInit) return;
  btn.dataset.spInit = "1";
  btn.addEventListener("click", () => window.print());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const salesLink = document.querySelector(".print-toolbar a");
      if (salesLink) window.location.assign(salesLink.href);
      else if (window.history.length > 1) history.back();
      else window.location.assign("/sales");
    }
  });
  document.querySelectorAll(".barcode").forEach((el) => {
    if (window.JsBarcode && !el.dataset.spBarcode)
      JsBarcode(el, el.dataset.value, {
        format: "CODE128",
        height: 34,
        width: 1.2,
        fontSize: 11,
        margin: 5,
      });
    el.dataset.spBarcode = "1";
  });
}
document.addEventListener("DOMContentLoaded", spInitInvoice);
document.addEventListener("storepro:content", spInitInvoice);
