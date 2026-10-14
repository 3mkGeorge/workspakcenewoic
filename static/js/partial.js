"use strict";
/* Component-level partial updates:swap only the affected region, never the
 * whole page. All listeners are delegated and bound once, so re-rendered
 * content can never double-bind. Sidebar, topbar, modals and scroll stay put.
 */
(() => {
  if (!document.getElementById("sidebar")) return;

  function toast(text, type = "info") {
    if (window.StoreProUI) return window.StoreProUI.toast(text, type);
    const el = document.getElementById("app-toast");
    if (!el || !text) return;
    el.querySelector(".toast-body").textContent = text;
    try {
      window.bootstrap?.Toast.getOrCreateInstance(el).show();
    } catch {}
  }
  const failedText = () =>
    document.getElementById("sp-ui-strings")?.dataset.failed || "The request failed. Check your connection and try again.";

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
      toast(error instanceof TypeError ? failedText() : error.message, "error");
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
      if (a.hasAttribute("data-no-partial")) return; // needs the whole page (e.g. edit mode)
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
  // The page only reloads once the server confirms; on failure the form keeps
  // everything the user typed.
  const TONES = { danger: "error", warning: "warning", success: "success", info: "info" };
  function flashTone(el) {
    const cls = [...el.classList].find((c) => c.startsWith("alert-") && TONES[c.slice(6)]);
    return cls ? TONES[cls.slice(6)] : "info";
  }
  async function ajaxReload(form, submitter) {
    const body = new FormData(form);
    if (submitter?.name) body.append(submitter.name, submitter.value);
    const response = await fetch(form.action || location.href, {
      method: "post",
      credentials: "same-origin",
      headers: {
        Accept: "text/html",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content || "",
      },
      body,
    });
    if ((response.headers.get("content-type") || "").includes("application/json")) {
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (data.code === "session_expired") {
          location.href = "/login";
          return;
        }
        toast(data.error || `Request failed (${response.status}).`, "error");
        return;
      }
      await reloadAfterSave(form);
      if (data.message) toast(data.message, "success");
      return;
    }
    const doc = new DOMParser().parseFromString(await response.text(), "text/html");
    if (!response.ok) {
      const err =
        doc.querySelector("section.error-panel p")?.textContent.trim() ||
        `Request failed (${response.status}).`;
      toast(err, "error");
      return;
    }
    if (!doc.getElementById("sidebar")) {
      location.href = response.url || "/login"; // signed out mid-session
      return;
    }
    const flashes = [...doc.querySelectorAll("main.content .alert.sp-flash")].map((el) => ({
      text: el.textContent.trim().replace(/\s+/g, " ").slice(0, 200),
      tone: flashTone(el),
    }));
    const failure = flashes.find((f) => f.tone === "error");
    if (failure) {
      toast(failure.text, "error"); // nothing was saved: keep the form as typed
      return;
    }
    await reloadAfterSave(form);
    const shown = flashes.find((f) => f.tone === "warning") || flashes.find((f) => f.tone === "success") || flashes[0];
    toast(
      shown ? shown.text : document.getElementById("sp-ui-strings")?.dataset.saved || "Saved.",
      shown ? (shown.tone === "info" ? "success" : shown.tone) : "success",
    );
    document.querySelectorAll("main.content .alert.sp-flash").forEach((el) => el.remove());
  }

  // After a confirmed save, refresh this page (keeping search and paging), or
  // the form's data-reload-url when the saved view should change (edit -> list).
  async function reloadAfterSave(form) {
    const next = form.dataset.reloadUrl;
    if (next && window.StorePro?.replace) return window.StorePro.replace(next);
    if (window.StorePro && window.StorePro.reload) return window.StorePro.reload();
    location.reload();
  }

  const inflight = new WeakSet();
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement) || e.defaultPrevented) return;
    if (form.method.toLowerCase() === "get") return;
    if (!form.closest("[data-ajax-reload]")) return;
    e.preventDefault();
    e.stopPropagation();
    if (inflight.has(form)) return; // a second click while saving never sends twice
    inflight.add(form);
    const submitter = e.submitter && form.contains(e.submitter) ? e.submitter : form.querySelector("button[type=submit],button:not([type])");
    window.StoreProUI?.busy(submitter, true);
    ajaxReload(form, e.submitter)
      .catch((error) => toast(error instanceof TypeError ? failedText() : error.message, "error"))
      .finally(() => {
        inflight.delete(form);
        window.StoreProUI?.busy(submitter, false);
      });
  });

  window.StorePro = window.StorePro || {};
  window.StorePro.toast = toast;
  window.StorePro.partial = { load: loadPartial, ajaxReload };
})();
