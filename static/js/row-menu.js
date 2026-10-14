"use strict";
// Floating row-action menu for the Products/Inventory tables.
// Rendered with position:absolute on <body> so it is never clipped by
// .table-responsive / card / section overflow and never affects layout.
// One menu at a time: it closes on outside click, Escape, Tab, scrolling the
// table, navigation, when a dialog opens, or when another menu opens.
function spInitRowMenu() {
  if (window.__spRowMenu) return;
  window.__spRowMenu = true;
  let menu = document.getElementById("row-floating-menu");
  if (!menu) {
    menu = document.createElement("div");
    menu.id = "row-floating-menu";
    menu.className = "row-floating-menu";
    menu.setAttribute("role", "menu");
    menu.setAttribute("data-sp-popup", "");
    menu.hidden = true;
    document.body.appendChild(menu);
  }
  let currentTrigger = null;
  const items = () =>
    [...menu.querySelectorAll(".rf-item")].filter(
      (el) => !el.disabled && el.getAttribute("aria-disabled") !== "true",
    );

  function close({ restoreFocus = false } = {}) {
    if (menu.hidden) return;
    const trigger = currentTrigger;
    menu.hidden = true;
    menu.classList.remove("open");
    menu.replaceChildren();
    currentTrigger = null;
    menu.__spOwner = null;
    if (!trigger) return;
    trigger.setAttribute("aria-expanded", "false");
    if (restoreFocus && trigger.isConnected) trigger.focus({ preventScroll: true });
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
    // The trigger sits at the row's inline end; open the menu toward the row
    // (leftwards in LTR, rightwards in RTL) and keep it inside the viewport.
    const rtl = getComputedStyle(trigger).direction === "rtl";
    let left = rtl ? rect.left : rect.right - mw;
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
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
  }

  function open(trigger, { focus = "none", toggle = true } = {}) {
    const source = trigger.closest(".row-actions")?.querySelector(".row-menu-items");
    if (!source) return;
    if (currentTrigger === trigger && !menu.hidden) {
      if (toggle) close({ restoreFocus: true });
      else (focus === "last" ? items().at(-1) : items()[0])?.focus();
      return;
    }
    window.StoreProUI?.closeMenus(menu);
    close();
    menu.innerHTML = source.innerHTML;
    menu.querySelectorAll(".rf-item").forEach((el) => {
      el.setAttribute("role", "menuitem");
      el.tabIndex = -1;
    });
    menu.querySelectorAll("hr").forEach((hr) => hr.setAttribute("role", "separator"));
    menu.setAttribute("aria-label", trigger.getAttribute("aria-label") || "");
    menu.__spOwner = trigger; // dialogs opened from an item return focus here
    currentTrigger = trigger;
    trigger.setAttribute("aria-expanded", "true");
    if (window.lucide) window.lucide.createIcons();
    position(trigger);
    if (focus === "first") items()[0]?.focus();
    else if (focus === "last") items().at(-1)?.focus();
  }

  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-row-menu-trigger]");
    if (trigger) {
      e.preventDefault();
      e.stopPropagation();
      // detail === 0: activated from the keyboard, so move focus into the menu.
      open(trigger, { focus: e.detail === 0 ? "first" : "none" });
      return;
    }
    if (!menu.hidden && !menu.contains(e.target)) close();
  });

  document.addEventListener("keydown", (e) => {
    const trigger = e.target.closest?.("[data-row-menu-trigger]");
    if (trigger && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      open(trigger, { focus: e.key === "ArrowDown" ? "first" : "last", toggle: false });
      return;
    }
    if (menu.hidden) return;
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close({ restoreFocus: true });
      return;
    }
    if (!menu.contains(e.target)) return;
    const list = items();
    const i = list.indexOf(document.activeElement);
    const go = (n) => {
      e.preventDefault();
      list[(n + list.length) % list.length]?.focus();
    };
    if (e.key === "ArrowDown") go(i + 1);
    else if (e.key === "ArrowUp") go(i < 0 ? -1 : i - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(-1);
    else if (e.key === "Tab") {
      e.preventDefault();
      close({ restoreFocus: true });
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

  // Choosing an item closes the menu once its own handlers have run.
  // Confirmations for form[data-confirm] items come from ui.js.
  menu.addEventListener("click", (e) => {
    const item = e.target.closest(".rf-item");
    if (!item) return;
    if (item.disabled || item.getAttribute("aria-disabled") === "true") {
      e.preventDefault();
      return;
    }
    setTimeout(() => close(), 0);
  });
  document.addEventListener("storepro:menus-close", (e) => {
    if (e.detail?.except !== menu) close();
  });
  document.addEventListener("storepro:leave", () => close());
}
document.addEventListener("DOMContentLoaded", spInitRowMenu);
document.addEventListener("storepro:content", spInitRowMenu);
