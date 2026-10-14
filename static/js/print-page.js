"use strict";
// Standalone print pages (shipping label): the CSP forbids inline scripts and
// onclick handlers, so printing is wired here. <body data-auto-print> prints
// once the page has loaded; [data-print] buttons print on demand.
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-print]")) window.print();
});
window.addEventListener("load", () => {
  if (document.body.hasAttribute("data-auto-print")) setTimeout(() => window.print(), 300);
});
