"use strict";
/* StorePro SPA router: sidebar/topbar stay mounted, only main.content swaps.
 * Progressive enhancement over full server renders. No backend changes needed:
 * every view already returns complete HTML; flashes ride along inside content.
 */
(() => {
  if (!document.getElementById("sidebar")) return; // auth/recovery pages: native
  const CONTENT = "main.content";
  const scrollPos = new Map();
  let navSeq = 0;

  window.StorePro = window.StorePro || {};
  const StorePro = window.StorePro;

  const csrfToken = () =>
    document.querySelector('meta[name="csrf-token"]')?.content || "";

  function isDownloadLink(a, url) {
    if (a.hasAttribute("download")) return true;
    return /(^|\/)(settings\/backups\/|reports\/export\/)/.test(url.pathname);
  }

  function shouldSkip(a) {
    if (!a || !a.getAttribute("href")) return true;
    let url;
    try {
      url = new URL(a.href, location.href);
    } catch {
      return true;
    }
    if (url.origin !== location.origin) return true;
    if (url.protocol !== "http:" && url.protocol !== "https:") return true;
    if (a.target && a.target !== "_self") return true;
    if (a.dataset.action) return true; // theme/sidebar/print/back: app.js owns these
    if (a.pathname.startsWith("/api/")) return true;
    if (isDownloadLink(a, url)) return true;
    if (
      url.pathname === location.pathname &&
      url.search === location.search &&
      url.hash
    )
      return true; // in-page anchor: native scroll
    return false;
  }

  function closeModals() {
    document.querySelectorAll(".modal.show").forEach((m) => {
      try {
        window.bootstrap?.Modal.getInstance(m)?.hide();
      } catch {}
    });
  }

  function setLoading(on) {
    const main = document.querySelector(CONTENT);
    if (!main) return;
    main.classList.toggle("sp-loading", on);
    let skel = main.querySelector(":scope > .sp-skeleton");
    if (on && !skel) {
      skel = document.createElement("div");
      skel.className = "sp-skeleton";
      skel.setAttribute("aria-hidden", "true");
      main.prepend(skel);
    } else if (!on && skel) {
      skel.remove();
    }
  }

  async function ensureAssets(doc) {
    const css = new Set(
      [...doc.querySelectorAll('link[rel="stylesheet"]')]
        .map((l) => l.href)
        .filter((h) => h.includes("/static/")),
    );
    await Promise.all(
      [...css].map(
        (href) =>
          document.querySelector(`link[rel="stylesheet"][href="${href}"]`) ||
          new Promise((resolve) => {
            const l = document.createElement("link");
            l.rel = "stylesheet";
            l.href = href;
            l.onload = resolve;
            l.onerror = resolve;
            document.head.appendChild(l);
          }),
      ),
    );
    const scripts = new Set(
      [...doc.querySelectorAll("script[src]")]
        .map((s) => s.src)
        .filter((h) => h.includes("/static/")),
    );
    const loaded = new Set([...document.scripts].map((s) => s.src));
    for (const src of scripts) {
      if (loaded.has(src)) continue;
      loaded.add(src);
      await new Promise((resolve) => {
        const s = document.createElement("script");
        s.src = src;
        s.async = false;
        s.onload = resolve;
        s.onerror = resolve;
        document.body.appendChild(s);
      });
    }
  }

  function updateNav(url) {
    const path = new URL(url, location.href).pathname;
    const usersPage = path.startsWith("/settings/users");
    document.querySelectorAll("#sidebar .nav-item").forEach((a) => {
      const link = a.getAttribute("href");
      const active =
        (path === "/" && link === "/") ||
        (link !== "/" && path.startsWith(link) && !(link === "/settings" && usersPage));
      a.classList.toggle("active", active);
    });
  }

  async function render(url, { push = true, restoreScroll = false, formData = null, method = "GET" } = {}) {
    const seq = ++navSeq;
    if (typeof window.__storeproGuard === "function") {
      const verdict = window.__storeproGuard(push ? url : null);
      if (verdict === false) return false;
      if (typeof verdict === "string" && verdict && !confirm(verdict)) return false;
    }
    document.dispatchEvent(new CustomEvent("storepro:leave"));
    closeModals();
    if (!restoreScroll) scrollPos.set(location.pathname + location.search, window.scrollY);
    setLoading(true);
    let response;
    try {
      response = await fetch(url, {
        method,
        credentials: "same-origin",
        headers: {
          Accept: "text/html",
          "X-Requested-With": "XMLHttpRequest",
          ...(formData ? { "X-CSRFToken": csrfToken() } : {}),
        },
        body: formData,
      });
    } catch {
      setLoading(false);
      location.href = url; // offline or failed: fall back to full load
      return false;
    }
    if (seq !== navSeq) return false;
    const ct = response.headers.get("content-type") || "";
    const cd = response.headers.get("content-disposition") || "";
    if (!ct.includes("text/html") || cd.includes("attachment")) {
      setLoading(false);
      location.href = response.url || url;
      return false;
    }
    const html = await response.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const nextMain = doc.querySelector(CONTENT);
    if (!doc.getElementById("sidebar") || !nextMain) {
      // e.g. session expired and server returned the login page
      setLoading(false);
      location.href = response.url || url;
      return false;
    }
    await ensureAssets(doc);
    if (seq !== navSeq) return false;
    document.title = doc.title;
    const main = document.querySelector(CONTENT);
    main.replaceChildren(...[...nextMain.childNodes].map((n) => document.importNode(n, true)));
    updateNav(response.url || url);
    if (push) history.pushState({ sp: true }, "", response.url || url);
    else history.replaceState({ sp: true }, "", response.url || url);
    setLoading(false);
    main.classList.add("sp-enter");
    requestAnimationFrame(() => requestAnimationFrame(() => main.classList.remove("sp-enter")));
    try {
      window.StorePro.refresh?.();
      if (typeof window.initProductForm === "function") {
        window.initProductForm();
      }
    } catch {}
    document.dispatchEvent(new CustomEvent("storepro:content"));
    if (restoreScroll) {
      const y = scrollPos.get(location.pathname + location.search);
      window.scrollTo(0, y === undefined ? 0 : y);
    } else {
      window.scrollTo(0, 0);
    }
    document.getElementById("sidebar")?.classList.remove("is-open");
    return true;
  }

  document.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)
      return;
    const a = e.target.closest("a[href]");
    if (!a || shouldSkip(a)) return;
    e.preventDefault();
    render(a.href, { push: true });
  });

  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement) || e.defaultPrevented) return;
    if (form.method.toLowerCase() === "get") {
      e.preventDefault();
      const url = new URL(form.action || location.href, location.href);
      url.search = new URLSearchParams(new FormData(form)).toString();
      render(url.toString(), { push: true });
    } else {
      e.preventDefault();
      render(form.action || location.href, {
        push: true,
        formData: new FormData(form),
        method: "post",
      });
    }
  });

  window.addEventListener("popstate", () => {
    render(location.href, { push: false, restoreScroll: true });
  });

  StorePro.navigate = (url) => render(url, { push: true });
  StorePro.reload = () => render(location.href, { push: false });
})();
