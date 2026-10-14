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
  let currentPage = location.pathname + location.search;

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

  const uiText = (key, fallback) => document.getElementById("sp-ui-strings")?.dataset[key] || fallback;

  // Pages with unsaved work register window.__storeproGuard; it returns a
  // message (ask first), false (block) or nothing (leave freely).
  async function mayLeave(url) {
    if (typeof window.__storeproGuard !== "function") return true;
    const verdict = window.__storeproGuard(url);
    if (verdict === false) return false;
    if (typeof verdict !== "string" || !verdict) return true;
    if (!window.StoreProUI) return window.confirm(verdict);
    return window.StoreProUI.confirm({
      title: uiText("leaveTitle", "Leave this page?"),
      message: verdict,
      confirmLabel: uiText("leaveOk", "Leave page"),
    });
  }

  // Keep the persistent shell in step with the page just rendered.
  function syncShell(doc, nextHtml) {
    let stored = null;
    try {
      stored = localStorage.getItem("storepro-theme");
    } catch {}
    const theme = nextHtml.getAttribute("data-bs-theme");
    // A store-wide theme saved in Settings applies unless this browser chose its own.
    if (!stored && theme && theme !== document.documentElement.dataset.bsTheme) {
      document.documentElement.dataset.bsTheme = theme;
      document.dispatchEvent(new CustomEvent("storepro:theme"));
    }
    // The topbar search shows the query only on the search results page.
    const box = document.querySelector(".global-search input[name=q]");
    const next = doc.querySelector(".global-search input[name=q]");
    if (box && next && document.activeElement !== box) box.value = next.value;
    // Alert dot and store name follow the server's latest state.
    const bell = document.querySelector(".topbar .notification");
    const nextBell = doc.querySelector(".topbar .notification");
    if (bell && nextBell) {
      const dot = nextBell.querySelector("b");
      bell.querySelector("b")?.remove();
      if (dot) bell.append(document.importNode(dot, true));
    }
  }

  async function render(url, { push = true, restoreScroll = false, formData = null, method = "GET", guard = true } = {}) {
    const seq = ++navSeq;
    if (guard && !(await mayLeave(push ? url : null))) return false;
    if (seq !== navSeq) return false;
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
      if (formData) {
        // Never replay a POST as a GET: keep the form as typed and say why.
        window.StoreProUI?.toast(uiText("failed", "The request failed. Check your connection and try again."), "error");
        return false;
      }
      location.href = url; // offline or failed: fall back to full load
      return false;
    }
    if (seq !== navSeq) return false;
    const ct = response.headers.get("content-type") || "";
    const cd = response.headers.get("content-disposition") || "";
    if (ct.includes("application/json") && !cd.includes("attachment")) {
      setLoading(false);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (data.code === "session_expired") {
          location.href = "/login";
          return false;
        }
        const text = data.error || `Request failed (${response.status}).`;
        if (window.StoreProUI) window.StoreProUI.toast(text, "error");
        else StorePro.toast?.(text);
        return false;
      }
      if (data.redirect) return render(data.redirect, { push: true, guard: false });
      return render(location.href, { push: false, guard: false });
    }
    if (!ct.includes("text/html") || cd.includes("attachment")) {
      setLoading(false);
      location.href = response.url || url;
      return false;
    }
    const html = await response.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const nextMain = doc.querySelector(CONTENT);
    const html_ = document.documentElement;
    const nextHtml = doc.documentElement;
    if (
      !doc.getElementById("sidebar") ||
      !nextMain ||
      ["lang", "dir"].some((k) => nextHtml.getAttribute(k) !== html_.getAttribute(k))
    ) {
      // Login page, or language changed: the shell itself must be re-rendered.
      // (The theme is not compared: the toggle is a per-browser choice the
      // server does not know about, and comparing it forced full reloads.)
      setLoading(false);
      location.href = response.url || url;
      return false;
    }
    await ensureAssets(doc);
    if (seq !== navSeq) return false;
    document.dispatchEvent(new CustomEvent("storepro:leave"));
    closeModals();
    document.title = doc.title;
    syncShell(doc, nextHtml);
    const main = document.querySelector(CONTENT);
    main.replaceChildren(...[...nextMain.childNodes].map((n) => document.importNode(n, true)));
    const hash = new URL(url, location.href).hash;
    const finalUrl = (response.url || url).split("#")[0] + hash;
    updateNav(finalUrl);
    // Re-rendering the page you are on (a save that redirects back, or a
    // second click on the active link) must not stack duplicate Back entries.
    const samePage = new URL(finalUrl, location.href).href === location.href;
    if (push && !samePage) history.pushState({ sp: true }, "", finalUrl);
    else history.replaceState({ sp: true }, "", finalUrl);
    currentPage = location.pathname + location.search;
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
    const anchor = hash && document.getElementById(decodeURIComponent(hash.slice(1)));
    if (anchor) {
      anchor.scrollIntoView();
    } else if (restoreScroll) {
      const y = scrollPos.get(location.pathname + location.search);
      window.scrollTo(0, y === undefined ? 0 : y);
    } else {
      window.scrollTo(0, 0);
    }
    document.getElementById("sidebar")?.classList.remove("is-open");
    return true;
  }

  // Registered on window so page scripts' document-level handlers run first and can preventDefault.
  window.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)
      return;
    const a = e.target.closest("a[href]");
    if (!a || shouldSkip(a)) return;
    e.preventDefault();
    render(a.href, { push: true });
  });

  const posting = new WeakSet();
  window.addEventListener("submit", (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement) || e.defaultPrevented) return;
    const submitter = e.submitter && form.contains(e.submitter) ? e.submitter : null;
    const data = new FormData(form);
    if (submitter?.name) data.append(submitter.name, submitter.value);
    if (form.method.toLowerCase() === "get") {
      e.preventDefault();
      const url = new URL(form.getAttribute("action") ? form.action : location.href, location.href);
      url.search = new URLSearchParams(data).toString();
      render(url.toString(), { push: true });
    } else {
      e.preventDefault();
      if (posting.has(form)) return; // double click or Enter twice: one request only
      posting.add(form);
      const button = submitter || form.querySelector("button[type=submit],button:not([type])");
      window.StoreProUI?.busy(button, true);
      render(form.action || location.href, {
        push: true,
        formData: data,
        method: "post",
        // Submitting the page's own form is not leaving it; shell forms (logout) are.
        guard: !form.closest(CONTENT),
      }).finally(() => {
        posting.delete(form);
        window.StoreProUI?.busy(button, false);
      });
    }
  });

  window.addEventListener("popstate", async () => {
    const target = location.pathname + location.search;
    if (target === currentPage) return; // only the #hash changed
    const left = location.href;
    if (!(await mayLeave(null))) {
      // Cancelled: put the address bar back on the page that is still shown.
      history.pushState({ sp: true }, "", currentPage);
      return;
    }
    if (location.href !== left) return; // another Back/Forward happened meanwhile
    render(location.href, { push: false, restoreScroll: true, guard: false });
  });

  StorePro.navigate = (url) => render(url, { push: true });
  StorePro.notePage = () => (currentPage = location.pathname + location.search);
  StorePro.reload = () => render(location.href, { push: false, guard: false });
  StorePro.replace = (url) => render(url, { push: false, guard: false });
})();
