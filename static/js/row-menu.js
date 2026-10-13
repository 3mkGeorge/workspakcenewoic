"use strict";
// Floating row-action menu for the Products/Inventory tables.
// Rendered with position:absolute on <body> so it is never clipped by
// .table-responsive / card / section overflow and never affects layout.
function spInitRowMenu() {
  if (window.__spRowMenu) return;
  window.__spRowMenu = true;
  let menu = document.getElementById("row-floating-menu");
  if (!menu) {
    menu = document.createElement("div");
    menu.id = "row-floating-menu";
    menu.className = "row-floating-menu";
    menu.setAttribute("role", "menu");
    menu.hidden = true;
    document.body.appendChild(menu);
  }
  let currentTrigger = null;

  function close() {
    if (menu.hidden) return;
    menu.hidden = true;
    menu.classList.remove("open");
    menu.innerHTML = "";
    if (currentTrigger) currentTrigger.setAttribute("aria-expanded", "false");
    currentTrigger = null;
  }

  function position(trigger) {
    const rect = trigger.getBoundingClientRect();
    menu.hidden = false;
    menu.classList.add("open");
    const mw = menu.offsetWidth;
    const mh = menu.offsetHeight;
    const margin = 8;
    // Absolute positioning: viewport rect plus page scroll offsets.
    const sx = window.scrollX || 0;
    const sy = window.scrollY || 0;
    let left = rect.right - mw;
    left = Math.max(margin, Math.min(left, window.innerWidth - mw - margin)) + sx;
    const spaceBelow = window.innerHeight - rect.bottom;
    let top;
    if (spaceBelow < mh + margin && rect.top > mh + margin) {
      top = rect.top - mh - 6;
      menu.dataset.placement = "up";
    } else {
      top = rect.bottom + 6;
      menu.dataset.placement = "down";
    }
    top = Math.max(margin, Math.min(top, window.innerHeight - mh - margin)) + sy;
    // Clamp horizontal for very narrow screens.
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
  }

  function open(trigger) {
    const source = trigger.closest(".row-actions")?.querySelector(".row-menu-items");
    if (!source) return;
    if (currentTrigger === trigger && !menu.hidden) {
      close();
      return;
    }
    menu.innerHTML = source.innerHTML;
    currentTrigger = trigger;
    trigger.setAttribute("aria-expanded", "true");
    position(trigger);
    if (window.lucide) window.lucide.createIcons();
  }

  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-row-menu-trigger]");
    if (trigger) {
      e.preventDefault();
      e.stopPropagation();
      open(trigger);
      return;
    }
    if (!menu.hidden && !e.target.closest("#row-floating-menu")) close();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !menu.hidden) {
      close();
      if (currentTrigger) currentTrigger.focus();
    }
  });

  window.addEventListener("resize", () => {
    if (!menu.hidden && currentTrigger) position(currentTrigger);
  });

  // Table scroll containers clip fixed-position math: close instead of detaching.
  document.addEventListener(
    "scroll",
    (e) => {
      if (menu.hidden) return;
      if (menu.contains(e.target)) return;
      if (e.target === document || e.target === document.body) {
        if (currentTrigger) position(currentTrigger);
        return;
      }
      close();
    },
    true,
  );

  // Delete confirm for cloned forms (originals are hidden templates).
  document.addEventListener("submit", (e) => {
    const form = e.target.closest ? e.target.closest("form[data-confirm]") : null;
    if (form && !window.confirm(form.dataset.confirm)) e.preventDefault();
  });

  menu.addEventListener("click", (e) => {
    if (e.target.closest("a,button")) setTimeout(close, 0);
  });
  document.addEventListener("storepro:leave", close);
}
document.addEventListener("DOMContentLoaded", spInitRowMenu);
document.addEventListener("storepro:content", spInitRowMenu);
