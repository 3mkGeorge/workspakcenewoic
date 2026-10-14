"use strict";
// Product edit-page image manager: multi upload, drag&drop, progress,
// preview before saving, reorder, primary, delete, replace, live preview.
function spInitMedia() {
  const form = document.getElementById("product-form");
  if (!form || form.dataset.spMedia) return;
  form.dataset.spMedia = "1";
  const pid = form.dataset.productId || "";
  const dropzone = document.getElementById("media-dropzone");
  const input = document.getElementById("media-input");
  const grid = document.getElementById("media-grid");
  const progress = document.getElementById("media-progress");
  const fill = document.getElementById("media-progress-fill");
  const plabel = document.getElementById("media-progress-label");
  const errorEl = document.getElementById("media-error");
  const primaryIndexInput = document.getElementById("media-primary-index");
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const ACCEPT = ["image/png", "image/jpeg", "image/webp"];

  let existing = [];
  try {
    existing = JSON.parse(grid.dataset.existing || "[]");
  } catch { existing = []; }
  let pending = []; // {file, url, primary}
  let dragId = null;

  const showError = (msg) => {
    errorEl.textContent = msg;
    errorEl.hidden = !msg;
  };
  const refreshIcons = () => { if (window.lucide) window.lucide.createIcons(); };
  const setProgress = (ratio, label) => {
    progress.hidden = false;
    fill.style.width = `${Math.round(ratio * 100)}%`;
    plabel.textContent = label || "";
    if (ratio >= 1) setTimeout(() => { progress.hidden = true; fill.style.width = "0"; }, 600);
  };

  function validFile(file) {
    if (!ACCEPT.includes(file.type)) {
      showError(`Skipped ${file.name}: JPG, PNG, or WebP only.`);
      return false;
    }
    if (file.size > 32 * 1024 * 1024) {
      showError(`Skipped ${file.name}: file is too large.`);
      return false;
    }
    return true;
  }

  // ---------- rendering ----------
  function cardShell(id, thumbUrl, name, isPrimary, isPending) {
    const card = document.createElement("div");
    card.className = "media-card" + (isPrimary ? " is-primary" : "");
    card.draggable = true;
    card.dataset.id = id;
    card.innerHTML = `
      ${isPrimary ? '<span class="media-badge">Primary</span>' : ""}
      <img loading="lazy" alt="">
      <div class="media-name"></div>
      <div class="media-row">
        <button type="button" class="icon-button media-primary-btn${isPrimary ? " is-primary" : ""}" title="Set as Primary Image" aria-label="Set as Primary Image"><i data-lucide="star"></i></button>
        <button type="button" class="icon-button media-up" title="Move left" aria-label="Move left"><i data-lucide="arrow-left"></i></button>
        <button type="button" class="icon-button media-down" title="Move right" aria-label="Move right"><i data-lucide="arrow-right"></i></button>
        ${isPending
          ? '<button type="button" class="icon-button media-remove" title="Remove" aria-label="Remove"><i data-lucide="x"></i></button>'
          : `<label class="icon-button" title="Replace image" aria-label="Replace image"><i data-lucide="repeat"></i><input type="file" accept="image/png,image/jpeg,image/webp" hidden></label>
             <button type="button" class="icon-button media-delete" title="Delete image" aria-label="Delete image"><i data-lucide="trash-2"></i></button>`}
      </div>`;
    card.querySelector("img").src = thumbUrl;
    card.querySelector(".media-name").textContent = name;
    return card;
  }

  function render() {
    grid.innerHTML = "";
    existing.forEach((rec) => {
      grid.append(cardShell(`e-${rec.id}`, rec.thumb_url || rec.url, rec.file_name, rec.is_primary, false));
    });
    pending.forEach((p, i) => {
      grid.append(cardShell(`p-${i}`, p.url, p.file.name, p.primary, true));
    });
    const order = pending.findIndex((p) => p.primary);
    primaryIndexInput.value = String(Math.max(0, order));
    refreshIcons();
  }

  // ---------- existing product API ----------
  async function api(url, opts = {}) {
    const res = await fetch(url, {
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf, ...(opts.headers || {}) },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw Error(data.error || data.message || "Image update failed.");
    return data;
  }

  async function refreshExisting() {
    if (!pid) return;
    const data = await api(`/api/products/${pid}/images`, { headers: { Accept: "application/json" } });
    existing = data.images || [];
    render();
  }

  function uploadExisting(files) {
    if (!files.length || !pid) return;
    const body = new FormData();
    files.forEach((f) => body.append("images", f));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/products/${pid}/images`);
    xhr.setRequestHeader("X-CSRFToken", csrf);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) setProgress(e.loaded / e.total, `Uploading ${files.length} image(s)…`);
    };
    xhr.onload = async () => {
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status < 200 || xhr.status >= 300) throw Error(data.error || "Upload failed.");
        existing = data.images || [];
        showError("");
      } catch (e) {
        showError(e.message);
      }
      render();
      setProgress(1, "Upload complete");
    };
    xhr.onerror = () => showError("Upload failed. Check your connection and try again.");
    setProgress(0, `Uploading ${files.length} image(s)…`);
    xhr.send(body);
  }

  // ---------- events ----------
  dropzone.addEventListener("click", (e) => {
    if (e.target.closest("button") && !e.target.closest("#media-browse")) return;
    input.click();
  });
  document.getElementById("media-browse").addEventListener("click", (e) => {
    e.stopPropagation();
    input.click();
  });
  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
  });
  ["dragenter", "dragover"].forEach((ev) => dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  }));
  ["dragleave", "drop"].forEach((ev) => dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
  }));
  dropzone.addEventListener("drop", (e) => {
    const files = [...(e.dataTransfer?.files || [])].filter(validFile);
    if (!files.length) return;
    if (pid) uploadExisting(files);
    else {
      files.forEach((f) => pending.push({ file: f, url: URL.createObjectURL(f), primary: !pending.length && !existing.length }));
      showError("");
      render();
    }
  });
  input.addEventListener("change", () => {
    const files = [...(input.files || [])].filter(validFile);
    input.value = "";
    if (!files.length) return;
    if (pid) uploadExisting(files);
    else {
      files.forEach((f) => pending.push({ file: f, url: URL.createObjectURL(f), primary: !pending.length }));
      showError("");
      render();
    }
  });

  grid.addEventListener("click", async (e) => {
    const card = e.target.closest(".media-card");
    if (!card) return;
    const id = card.dataset.id;
    const isPending = id.startsWith("p-");
    const idx = Number(id.slice(2));
    if (e.target.closest(".media-primary-btn")) {
      if (isPending) {
        pending.forEach((p, i) => { p.primary = i === idx; });
        // File order defines primary_index; keep visual order stable.
      } else if (pid) {
        try {
          const data = await api(`/api/products/${pid}/images/${idx}/primary`, { method: "POST" });
          existing = data.images || [];
          showError("");
        } catch (err) { showError(err.message); }
      }
      render();
      return;
    }
    if (e.target.closest(".media-remove")) {
      URL.revokeObjectURL(pending[idx].url);
      const wasPrimary = pending[idx].primary;
      pending.splice(idx, 1);
      if (wasPrimary && pending.length) pending[0].primary = true;
      render();
      return;
    }
    if (e.target.closest(".media-delete")) {
      if (!pid || card.dataset.spDeleting) return;
      const ui = window.StoreProUI;
      const opts = {
        title: ui ? ui.t("Delete this image?") : "Delete this image?",
        message: ui ? ui.t("The image is removed from this product. This cannot be undone.") : "",
        confirmLabel: ui ? ui.t("Delete image") : "Delete image",
      };
      if (!(await (ui ? ui.confirm(opts) : Promise.resolve(window.confirm(opts.title))))) return;
      card.dataset.spDeleting = "1";
      try {
        const data = await api(`/api/products/${pid}/images/${idx}/delete`, { method: "POST" });
        existing = data.images || [];
        showError("");
        render();
      } catch (err) { showError(err.message); }
      finally { delete card.dataset.spDeleting; }
      return;
    }
    if (e.target.closest(".media-up") || e.target.closest(".media-down")) {
      const delta = e.target.closest(".media-up") ? -1 : 1;
      if (isPending) {
        const j = idx + delta;
        if (j < 0 || j >= pending.length) return;
        [pending[idx], pending[j]] = [pending[j], pending[idx]];
        render();
      } else if (pid) {
        const ids = existing.map((r) => r.id);
        const j = idx; // position in current order
        const pos = existing.findIndex((r) => r.id === Number(card.dataset.id.slice(2)));
        const swap = pos + delta;
        if (swap < 0 || swap >= ids.length) return;
        [ids[pos], ids[swap]] = [ids[swap], ids[pos]];
        try {
          const data = await api(`/api/products/${pid}/images/reorder`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ order: ids }),
          });
          existing = data.images || [];
          showError("");
          render();
        } catch (err) { showError(err.message); }
      }
    }
  });

  // Replace file input inside existing cards.
  grid.addEventListener("change", async (e) => {
    const fileInput = e.target.closest('.media-row input[type="file"]');
    if (!fileInput) return;
    const card = e.target.closest(".media-card");
    const imageId = Number(card.dataset.id.slice(2));
    const file = fileInput.files?.[0];
    fileInput.value = "";
    if (!file || !validFile(file) || !pid) return;
    const body = new FormData();
    body.append("image", file);
    try {
      setProgress(0, "Replacing image…");
      const res = await fetch(`/api/products/${pid}/images/${imageId}/replace`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrf },
        body,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw Error(data.error || "Replace failed.");
      existing = data.images || [];
      showError("");
      render();
      setProgress(1, "Image replaced");
    } catch (err) { showError(err.message); }
  });

  // Drag & drop reorder for cards.
  grid.addEventListener("dragstart", (e) => {
    const card = e.target.closest(".media-card");
    if (!card) return;
    dragId = card.dataset.id;
    card.classList.add("dragging");
  });
  grid.addEventListener("dragend", (e) => {
    e.target.closest(".media-card")?.classList.remove("dragging");
  });
  grid.addEventListener("dragover", (e) => {
    e.preventDefault();
    const over = e.target.closest(".media-card");
    if (!over || over.dataset.id === dragId) return;
    const dragged = grid.querySelector(`[data-id="${CSS.escape(dragId)}"]`);
    if (!dragged) return;
    const rect = over.getBoundingClientRect();
    const before = (e.clientX - rect.left) < rect.width / 2;
    over.before(dragged);
    if (!before) over.after(dragged);
  });
  grid.addEventListener("drop", async (e) => {
    e.preventDefault();
    if (!dragId) return;
    const order = [...grid.querySelectorAll(".media-card")].map((c) => c.dataset.id);
    dragId = null;
    const pendOrder = order.filter((id) => id.startsWith("p-")).map((id) => Number(id.slice(2)));
    if (pendOrder.length === pending.length && !pid) {
      pending = pendOrder.map((i) => pending[i]);
      render();
      return;
    }
    if (pid && order.every((id) => id.startsWith("e-"))) {
      const ids = order.map((id) => Number(id.slice(2)));
      try {
        const data = await api(`/api/products/${pid}/images/reorder`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ order: ids }),
        });
        existing = data.images || [];
        showError("");
        render();
      } catch (err) { showError(err.message); render(); }
    } else {
      render();
    }
  });

  // New-product submit with upload progress (multipart XHR follows the redirect).
  if (!pid) {
    form.addEventListener("submit", (e) => {
      if (!pending.length) return; // no staged files: normal submit
      e.preventDefault();
      const body = new FormData(form);
      body.delete("images");
      pending.forEach((p) => body.append("images", p.file, p.file.name));
      const xhr = new XMLHttpRequest();
      xhr.open("POST", form.action || window.location.href);
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable) setProgress(ev.loaded / ev.total, "Saving product with images…");
      };
      xhr.onload = () => {
        if (xhr.status >= 400) {
          let message = "";
          try {
            message = JSON.parse(xhr.responseText).error || "";
          } catch {
            const doc = new DOMParser().parseFromString(xhr.responseText, "text/html");
            message = doc.querySelector("section.error-panel p")?.textContent.trim() || "";
          }
          progress.hidden = true;
          showError(message || `Save failed (${xhr.status}).`);
          return;
        }
        setProgress(1, "Saved");
        const target = xhr.responseURL || "/products";
        if (window.StorePro && window.StorePro.navigate) window.StorePro.navigate(target);
        else window.location.assign(target);
      };
      xhr.onerror = () => showError("Save failed. Check your connection and try again.");
      setProgress(0, "Saving product with images…");
      xhr.send(body);
    });
  }

  // ---------- stock count validation (Edit Product inventory card) ----------
  const stockInput = document.getElementById("current_stock");
  const stockError = document.getElementById("stock-error");
  function validStock() {
    if (!stockInput) return true;
    if (!/^\d+$/.test(stockInput.value.trim())) {
      stockError.textContent = "Enter a whole number, 0 or more.";
      stockError.hidden = false;
      return false;
    }
    stockError.hidden = true;
    return true;
  }
  if (stockInput) {
    stockInput.addEventListener("input", validStock);
    form.addEventListener("submit", (e) => {
      if (!validStock()) {
        e.preventDefault();
        e.stopImmediatePropagation();
        stockInput.focus();
      }
    });
  }

  render();
}
document.addEventListener("DOMContentLoaded", spInitMedia);
document.addEventListener("storepro:content", spInitMedia);
