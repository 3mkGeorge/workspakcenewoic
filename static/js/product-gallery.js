"use strict";
// Shared product preview + gallery viewer. Full-size images load only here;
// tables use thumbnails.
(function () {
  function ready(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }

  function initGallery() {
    // Bind once per rendered modal pair: in-app navigation brings fresh copies,
    // and the previous page's document listeners must not keep driving the old ones.
    const previewEl = document.getElementById("productPreviewModal");
    const galleryEl = document.getElementById("productGalleryModal");
    if (!previewEl && !galleryEl) return;
    const anchor = previewEl || galleryEl;
    if (anchor.dataset.spBound) return;
    anchor.dataset.spBound = "1";
    window.__spGalleryAbort?.abort();
    const binding = (window.__spGalleryAbort = new AbortController());
    const { signal } = binding;
    document.addEventListener("storepro:leave", () => binding.abort(), { signal });
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";

    async function getJSON(url) {
      const res = await fetch(url, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw Error(data.error || "Unable to load product.");
      return data;
    }

    function showModal(el) {
      if (window.bootstrap?.Modal) bootstrap.Modal.getOrCreateInstance(el).show();
    }

    // Generic viewer bound to a prefix: pp- or gal-.
    function viewer(prefix) {
      const main = document.getElementById(`${prefix}-main`);
      const img = document.getElementById(`${prefix}-image`);
      const thumbs = document.getElementById(`${prefix}-thumbs`);
      const counter = document.getElementById(`${prefix}-counter`);
      const empty = document.getElementById(`${prefix}-empty`);
      const state = { images: [], index: 0 };
      function label() {
        return state.images.length
          ? `Image ${state.index + 1} of ${state.images.length}`
          : "";
      }
      function render() {
        const item = state.images[state.index];
        if (!item) {
          if (img) img.removeAttribute("src");
          if (counter) counter.textContent = "";
          if (empty) empty.hidden = false;
          if (main) main.style.display = "none";
          if (thumbs) thumbs.innerHTML = "";
          syncCounters();
          return;
        }
        if (empty) empty.hidden = true;
        if (main) main.style.display = "";
        img.src = item.url || item.thumb_url;
        img.alt = item.file_name || "";
        img.dataset.full = item.url || item.thumb_url;
        main.classList.remove("zoomed");
        if (counter) counter.textContent = label();
        thumbs.innerHTML = "";
        state.images.forEach((it, i) => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "gal-thumb" + (i === state.index ? " active" : "");
          btn.setAttribute("role", "option");
          btn.setAttribute("aria-selected", i === state.index ? "true" : "false");
          btn.setAttribute("aria-label", `Image ${i + 1} of ${state.images.length}`);
          const thumb = document.createElement("img");
          thumb.src = it.thumb_url || it.url;
          thumb.alt = "";
          thumb.loading = "lazy";
          btn.append(thumb);
          btn.addEventListener("click", () => {
            state.index = i;
            render();
          });
          thumbs.append(btn);
        });
        if (window.lucide) window.lucide.createIcons();
        syncCounters();
      }
      function syncCounters() {
        const top = document.getElementById("gal-counter-top");
        const bottom = document.getElementById("gal-counter-bottom");
        if (prefix === "gal") {
          if (top) top.textContent = label();
          if (bottom) bottom.textContent = label();
        }
      }
      function go(delta) {
        if (!state.images.length) return;
        state.index = (state.index + delta + state.images.length) % state.images.length;
        render();
      }
      document.getElementById(`${prefix}-prev`)?.addEventListener("click", () => go(-1));
      document.getElementById(`${prefix}-next`)?.addEventListener("click", () => go(1));
      img?.addEventListener("click", () => main.classList.toggle("zoomed"));
      document.getElementById(`${prefix}-zoom`)?.addEventListener("click", () => main.classList.toggle("zoomed"));
      document.getElementById(`${prefix}-full`)?.addEventListener("click", async () => {
        try {
          if (document.fullscreenElement) await document.exitFullscreen();
          else await main.requestFullscreen();
        } catch {}
      });
      return { state, render, go, set(images, index = 0) {
        state.images = images || [];
        state.index = Math.min(index, Math.max(0, state.images.length - 1));
        render();
      } };
    }

    const pp = previewEl ? viewer("pp") : null;
    const gal = galleryEl ? viewer("gal") : null;

    document.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (galleryEl?.classList.contains("show") && gal) gal.go(e.key === "ArrowRight" ? 1 : -1);
      else if (previewEl?.classList.contains("show") && pp) pp.go(e.key === "ArrowRight" ? 1 : -1);
    }, { signal });

    let previewImages = [];
    let previewId = null;

    async function openPreview(pid) {
      if (!previewEl) return;
      previewId = pid;
      const loading = document.getElementById("pp-loading");
      const content = document.getElementById("pp-content");
      const error = document.getElementById("pp-error");
      loading.hidden = false;
      content.hidden = true;
      error.hidden = true;
      showModal(previewEl);
      try {
        const data = await getJSON(`/api/products/${pid}/preview`);
        document.getElementById("pp-name").textContent = data.name || "";
        document.getElementById("pp-subtitle").textContent = `${data.sku || ""} · ${data.category || ""}`;
        const set = (id, v) => { document.getElementById(id).textContent = v; };
        set("pp-d-name", data.name || "—");
        set("pp-d-sku", data.sku || "—");
        set("pp-d-cat", data.category || "—");
        const money = (v) => `${(Number(v || 0) / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${data.currency || ""}`;
        set("pp-d-cost", money(data.cost));
        set("pp-d-price", money(data.price));
        set("pp-d-stock", String(data.stock ?? "—"));
        set("pp-d-status", data.status || "—");
        previewImages = data.images || [];
        pp.set(previewImages, Math.max(0, previewImages.findIndex((i) => i.is_primary)));
        document.getElementById("pp-edit").href = `/products/${pid}/edit`;
        loading.hidden = true;
        content.hidden = false;
        if (window.lucide) window.lucide.createIcons();
      } catch (e) {
        loading.hidden = true;
        error.textContent = e.message;
        error.hidden = false;
      }
    }

    function openGallery(images, title, index = 0) {
      if (!galleryEl) return;
      document.getElementById("gal-title").textContent = title || "Product Gallery";
      gal.set(images || [], index);
      showModal(galleryEl);
    }

    document.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-product-preview]");
      if (btn) {
        e.preventDefault();
        openPreview(btn.getAttribute("data-product-preview"));
        return;
      }
      if (e.target.closest("#pp-open-gallery")) {
        const title = document.getElementById("pp-name")?.textContent || "Product Gallery";
        const idx = pp ? pp.state.index : 0;
        openGallery(previewImages, title, idx);
      }
    }, { signal });

    // Public hook for the Price Analytics "View Gallery" button.
    window.StoreProGallery = {
      async open(productId, title) {
        try {
          const data = await getJSON(`/api/products/${productId}/preview`);
          openGallery(data.images || [], title || data.name || "Product Gallery",
            Math.max(0, (data.images || []).findIndex((i) => i.is_primary)));
        } catch (e) {
          openGallery([], title || "Product Gallery");
        }
      },
    };
    void csrf;
  }
  ready(initGallery);
  document.addEventListener("storepro:content", initGallery);
})();
