"use strict";
/* Component-level partial updates:swap only the affected region, never the
 * whole page. All listeners are delegated and bound once, so re-rendered
 * content can never double-bind. Sidebar, topbar, modals and scroll stay put.
 */
(() => {
  if (!document.getElementById("sidebar")) return;

  function toast(text) {
    const el = document.getElementById("app-toast");
    if (!el || !text) return;
    el.querySelector(".toast-body").textContent = text;
    try {
      window.bootstrap?.Toast.getOrCreateInstance(el).show();
    } catch {}
  }

  async function fetchHtml(url) {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "text/html", "X-Requested-With": "XMLHttpRequest" },
    });
    const ct = response.headers.get("content-type") || "";
    if (!response.ok || !ct.includes("text/html")) {
      const data = ct.includes("application/json") ? await response.json().catch(() => ({})) : {};
      throw new Error(data.error || `Request failed (${response.status}).`);
    }
    return new DOMParser().parseFromString(await response.text(), "text/html");
  }

  function region(name, doc) {
    const scope = doc || document;
    return scope.querySelector(`[data-partial="${name}"]`);
  }

  async function loadPartial(url, name, { push = true } = {}) {
    const target = region(name);
    if (!target) return false;
    target.classList.add("sp-region-loading");
    try {
      const doc = await fetchHtml(url);
      const fresh = region(name, doc);
      if (!fresh) {
        window.StorePro?.navigate ? window.StorePro.navigate(url) : (location.href = url);
        return false;
      }
      target.replaceChildren(...[...fresh.childNodes].map((n) => document.importNode(n, true)));
      if (push) history.pushState({ sp: true }, "", url);
      window.StorePro?.notePage?.();
      try {
        window.StorePro?.refresh?.();
      } catch {}
      if (window.lucide) window.lucide.createIcons();
      document.dispatchEvent(new CustomEvent("storepro:region", { detail: { name } }));
      return true;
    } catch (error) {
      toast(error.message);
      return false;
    } finally {
      target.classList.remove("sp-region-loading");
    }
  }

  // Links inside a partial region update just that region (same origin, GET).
  document.addEventListener(
    "click",
    (e) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)
        return;
      const holder = e.target.closest("[data-partial]");
      if (!holder) return;
      const a = e.target.closest("a[href]");
      if (!a || !holder.contains(a)) return;
      let url;
      try {
        url = new URL(a.href, location.href);
      } catch {
        return;
      }
      if (url.origin !== location.origin) return;
      if (a.target && a.target !== "_self") return;
      if (a.hasAttribute("download")) return;
      if (a.pathname.startsWith("/api/")) return;
      if (url.pathname !== location.pathname) return; // other pages: full router navigation
      if (/(^|\/)(settings\/backups\/|reports\/export\/)/.test(url.pathname)) return;
      e.preventDefault();
      e.stopPropagation();
      loadPartial(url.toString(), holder.dataset.partial, { push: true });
    },
    true,
  );

  // GET filter forms bound to a region swap that region instead of navigating.
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement) || e.defaultPrevented) return;
    const name = form.dataset ? form.dataset.partialForm : undefined;
    if (!name || form.method.toLowerCase() !== "get") return;
    e.preventDefault();
    e.stopPropagation();
    const url = new URL(form.action || location.href, location.href);
    url.search = new URLSearchParams(new FormData(form)).toString();
    loadPartial(url.toString(), name, { push: true });
  });

  // Same-page forms: submit via AJAX, toast the flash, refresh content fast.
  async function ajaxReload(form) {
    const response = await fetch(form.action || location.href, {
      method: "post",
      credentials: "same-origin",
      headers: {
        Accept: "text/html",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content || "",
      },
      body: new FormData(form),
    });
    if ((response.headers.get("content-type") || "").includes("application/json")) {
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast(data.error || `Request failed (${response.status}).`);
        return;
      }
      if (window.StorePro && window.StorePro.reload) await window.StorePro.reload();
      else location.reload();
      if (data.message) toast(data.message);
      return;
    }
    const doc = new DOMParser().parseFromString(await response.text(), "text/html");
    if (!response.ok) {
      const err =
        doc.querySelector("section.error-panel p")?.textContent.trim() ||
        `Request failed (${response.status}).`;
      toast(err);
      return;
    }
    const flashes = [...doc.querySelectorAll("main.content .alert.sp-flash")].map((el) =>
      el.textContent.trim().replace(/\s+/g, " ").slice(0, 200),
    );
    if (window.StorePro && window.StorePro.reload) await window.StorePro.reload();
    else location.reload();
    const ok = flashes.find((t) => /saved|updated|received|completed|success/i.test(t)) || flashes[0];
    toast(ok || (document.documentElement.lang === "ar" ? "تم الحفظ." : "Saved."));
    document.querySelectorAll("main.content .alert.sp-flash").forEach((el) => el.remove());
  }

  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement) || e.defaultPrevented) return;
    if (form.method.toLowerCase() === "get") return;
    if (!form.closest("[data-ajax-reload]")) return;
    e.preventDefault();
    e.stopPropagation();
    ajaxReload(form).catch((error) => toast(error.message));
  });

  window.StorePro = window.StorePro || {};
  window.StorePro.toast = toast;
  window.StorePro.partial = { load: loadPartial, ajaxReload };
})();
