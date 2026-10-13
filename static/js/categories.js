"use strict";
// Category Management: cards, live search, sort, pagination, create/edit/
// delete with live filter-dropdown refresh. Mutations are audited server-side.
function spInitCategories() {
  if (window.__spCategories) return;
  window.__spCategories = true;
  const root = document.getElementById("category-manager");
  if (!root) return;
  const modalEl = document.getElementById("categoryManagerModal");
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const canCreate = root.dataset.canCreate === "1";
  const canEdit = root.dataset.canEdit === "1";
  const canDelete = root.dataset.canDelete === "1";
  const SWATCHES = ["#3b82f6", "#22be85", "#ffa317", "#a669fa", "#e96987", "#5eb9c9", "#a4c943", "#9bacca", "#f43f5e", "#111827"];
  const PAGE_SIZE = 8;
  const $ = (id) => document.getElementById(id);
  let items = [];
  let editingId = null;
  let deleteTarget = null;
  let page = 1;

  const say = (text, isError) => {
    const box = $("cat-message");
    box.textContent = text || "";
    box.hidden = !text;
    box.classList.toggle("cat-error", !!isError);
  };
  const icons = () => { if (window.lucide) window.lucide.createIcons(); };

  async function api(url, method, body) {
    const res = await fetch(url, {
      method: method || "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || data.message || "Request failed.");
    return data;
  }

  function showView(name) {
    ["cat-list-view", "cat-form-view", "cat-delete-view"].forEach((id) =>
      $(id).hidden = id !== name,
    );
    say("");
  }

  function visibleItems() {
    const q = ($("cat-search").value || "").toLowerCase().trim();
    let list = q
      ? items.filter((c) => c.name.toLowerCase().includes(q) || (c.description || "").toLowerCase().includes(q))
      : [...items];
    if ($("cat-sort").value === "count") list.sort((a, b) => b.products - a.products || a.name.localeCompare(b.name));
    else list.sort((a, b) => a.name.localeCompare(b.name));
    return list;
  }

  function render() {
    $("cat-total").textContent = items.length;
    const list = visibleItems();
    const pages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
    page = Math.min(Math.max(1, page), pages);
    const slice = list.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
    const cards = $("cat-cards");
    cards.replaceChildren();
    $("cat-empty").hidden = items.length > 0;
    slice.forEach((c) => {
      const card = document.createElement("article");
      card.className = "cat-card";
      const badge = document.createElement("span");
      badge.className = "cat-emoji";
      if (c.icon) {
        const ic = document.createElement("i");
        ic.setAttribute("data-lucide", c.icon);
        badge.append(ic);
      } else {
        badge.textContent = "📦";
      }
      if (c.color) badge.style.background = `${c.color}1f`;
      const info = document.createElement("div");
      info.className = "cat-card-info";
      const nm = document.createElement("strong");
      nm.textContent = c.name;
      info.append(nm);
      const meta = document.createElement("small");
      meta.className = "muted";
      meta.textContent = c.archived > 0
        ? `Products: ${c.products} (+${c.archived} archived)`
        : `Products: ${c.products}`;
      info.append(meta);
      card.append(badge, info);
      const actions = document.createElement("div");
      actions.className = "cat-card-actions";
      if (canEdit) {
        const eb = document.createElement("button");
        eb.type = "button";
        eb.className = "btn btn-light btn-sm";
        eb.textContent = "Edit";
        eb.addEventListener("click", () => openForm(c));
        actions.append(eb);
      }
      if (canDelete) {
        const db = document.createElement("button");
        db.type = "button";
        db.className = "btn btn-light btn-sm";
        db.textContent = "Delete";
        db.addEventListener("click", () => openDelete(c));
        actions.append(db);
      }
      card.append(actions);
      cards.append(card);
    });
    if (!slice.length && items.length) {
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = "No categories match your search.";
      cards.append(p);
    }
    const pag = $("cat-pagination");
    pag.hidden = pages <= 1;
    $("cat-page-info").textContent = `Page ${page} of ${pages}`;
    $("cat-prev").disabled = page <= 1;
    $("cat-next").disabled = page >= pages;
    icons();
  }

  function refreshFilterOptions() {
    const select = $("category-filter-select");
    if (!select) return;
    const current = select.value;
    select.querySelectorAll("option[value]:not([value=''])").forEach((o) => o.remove());
    [...items]
      .sort((a, b) => a.name.localeCompare(b.name))
      .forEach((c) => {
        const o = document.createElement("option");
        o.value = c.id;
        o.textContent = `${c.name} (${c.products})`;
        select.append(o);
      });
    if ([...select.options].some((o) => o.value === current)) select.value = current;
  }

  async function load() {
    try {
      const data = await api("/api/categories");
      items = data.categories || [];
      render();
      refreshFilterOptions();
    } catch (e) {
      say(e.message, true);
    }
  }

  function openModal() {
    if (window.bootstrap?.Modal) bootstrap.Modal.getOrCreateInstance(modalEl).show();
    page = 1;
    load();
  }

  // ---- create / edit ----
  function buildSwatches(selected) {
    const wrap = $("cat-swatches");
    wrap.replaceChildren();
    [{ c: "", label: "None" }, ...SWATCHES.map((c) => ({ c, label: c }))].forEach(({ c, label }) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "cat-swatch" + (selected === c ? " selected" : "");
      b.title = label;
      b.setAttribute("aria-label", `Color ${label}`);
      if (c) b.style.background = c;
      b.addEventListener("click", () => { $("cat-color").value = c; buildSwatches(c); });
      wrap.append(b);
    });
  }
  function openForm(c) {
    editingId = c ? c.id : null;
    $("cat-form-title").textContent = c ? "Edit Category" : "New Category";
    $("cat-form-save").textContent = c ? "Save Changes" : "Create Category";
    const info = $("cat-assigned-info");
    if (c) {
      info.textContent = `Products currently assigned: ${c.products} Products`;
      info.hidden = false;
    } else {
      info.hidden = true;
    }
    $("cat-name").value = c ? c.name : "";
    $("cat-description").value = c ? c.description : "";
    $("cat-color").value = c ? c.color : "";
    $("cat-icon").value = c ? c.icon : "";
    buildSwatches(c ? c.color : "");
    showView("cat-form-view");
    setTimeout(() => $("cat-name").focus(), 100);
  }
  $("cat-form-view").addEventListener("submit", async (e) => {
    e.preventDefault();
    const save = $("cat-form-save");
    save.disabled = true;
    try {
      const body = {
        name: $("cat-name").value,
        description: $("cat-description").value,
        color: $("cat-color").value,
        icon: $("cat-icon").value,
      };
      if (editingId) await api(`/api/categories/${editingId}`, "POST", body);
      else await api("/api/categories", "POST", body);
      await load();
      showView("cat-list-view");
    } catch (err) {
      say(err.message, true);
    } finally {
      save.disabled = false;
    }
  });
  $("cat-form-cancel").addEventListener("click", () => showView("cat-list-view"));

  // ---- delete (counts come from the same authoritative query as validation) ----
  async function openDelete(c) {
    deleteTarget = c;
    $("cat-delete-name").textContent = c.name;
    $("cat-delete-count").textContent = "…";
    $("cat-delete-archived").hidden = true;
    $("cat-delete-blocking").hidden = true;
    showView("cat-delete-view");
    let fresh = c;
    try {
      const data = await api(`/api/categories/${c.id}`);
      fresh = data.category;
      const idx = items.findIndex((x) => x.id === c.id);
      if (idx >= 0) items[idx] = { ...items[idx], ...fresh };
    } catch (e) {
      say(e.message, true);
    }
    deleteTarget = fresh;
    $("cat-delete-name").textContent = fresh.name;
    $("cat-delete-active").textContent = fresh.products;
    $("cat-delete-archived-count").textContent = fresh.archived;
    const openArch = $("cat-open-archived");
    openArch.hidden = !(fresh.archived > 0);
    openArch.onclick = () => {
      if (window.bootstrap?.Modal) bootstrap.Modal.getInstance(modalEl)?.hide();
      if (window.StoreProArchive) window.StoreProArchive.open({ categoryId: fresh.id });
      else location.assign(`/inventory?category_id=${fresh.id}`);
    };
    if (fresh.archived > 0) {
      const note = $("cat-delete-archived");
      note.textContent = `Includes ${fresh.archived} archived product(s) — archived products still block deletion.`;
      note.hidden = false;
    }
    const block = $("cat-delete-blocking");
    const list = $("cat-blocking-list");
    list.replaceChildren();
    if ((fresh.blocking || []).length) {
      fresh.blocking.forEach((p) => {
        const li = document.createElement("li");
        li.textContent = `${p.name}${p.active ? "" : " (archived)"}`;
        list.append(li);
      });
      block.hidden = false;
    }
    const sel = $("cat-delete-target");
    sel.replaceChildren();
    items.filter((x) => x.id !== fresh.id).forEach((x) => {
      const o = document.createElement("option");
      o.value = x.id;
      o.textContent = `${x.name} (${x.products})`;
      sel.append(o);
    });
    const onlyRadio = $("cat-delete-only-radio");
    const moveRadio = document.querySelector('input[name="cat-delete-mode"][value="move"]');
    const purgeOption = $("cat-purge-option");
    const purgeRadio = purgeOption.querySelector('input[name="cat-delete-mode"]');
    const archivedOnly = fresh.total > 0 && fresh.products === 0;
    purgeOption.hidden = !archivedOnly;
    $("cat-purge-warn").hidden = !archivedOnly;
    if (fresh.total > 0) {
      onlyRadio.disabled = true;
      onlyRadio.title = "Move products first — products are never orphaned.";
      moveRadio.checked = true;
      sel.disabled = false;
    } else {
      onlyRadio.disabled = false;
      onlyRadio.checked = true;
      sel.disabled = true;
    }
    $("cat-delete-warn").hidden = fresh.total === 0;
    icons();
  }
  document.querySelectorAll('input[name="cat-delete-mode"]').forEach((r) =>
    r.addEventListener("change", () => {
      $("cat-delete-target").disabled = document.querySelector('input[name="cat-delete-mode"]:checked').value !== "move";
    }),
  );
  $("cat-delete-cancel").addEventListener("click", () => showView("cat-list-view"));
  $("cat-delete-confirm").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const mode = document.querySelector('input[name="cat-delete-mode"]:checked')?.value;
    if (mode === "purge" && !confirm(
      `Permanently delete ${deleteTarget.total} archived product(s) and the category "${deleteTarget.name}"? This cannot be undone. Products with sales, purchase, stock-movement or price history cannot be purged.`
    )) {
      return;
    }
    btn.disabled = true;
    try {
      if (mode === "move") {
        await api(`/api/categories/${deleteTarget.id}/delete`, "POST", {
          mode: "move",
          target_id: Number($("cat-delete-target").value),
        });
      } else if (mode === "purge") {
        await api(`/api/categories/${deleteTarget.id}/purge`, "POST", {});
      } else {
        await api(`/api/categories/${deleteTarget.id}/delete`, "POST", {});
      }
      await load();
      showView("cat-list-view");
    } catch (err) {
      say(err.message, true);
    } finally {
      btn.disabled = false;
    }
  });

  // ---- toolbar ----
  $("cat-search").addEventListener("input", () => { page = 1; render(); });
  $("cat-sort").addEventListener("change", () => { page = 1; render(); });
  $("cat-prev").addEventListener("click", () => { page--; render(); });
  $("cat-next").addEventListener("click", () => { page++; render(); });
  $("cat-add-open")?.addEventListener("click", () => openForm(null));
  $("cat-empty-add")?.addEventListener("click", () => openForm(null));
  document.querySelectorAll("#manage-categories").forEach((b) =>
    b.addEventListener("click", openModal),
  );
  document.addEventListener("input", (e) => {
    if (e.target.id !== "category-filter-search") return;
    const q = e.target.value.toLowerCase();
    document.querySelectorAll("#category-filter-select option").forEach((o) => {
      o.hidden = !!o.value && !o.textContent.toLowerCase().includes(q);
    });
  });
  modalEl.addEventListener("hidden.bs.modal", () => {
    showView("cat-list-view");
    if (location.hash === "#categories") history.replaceState(null, "", location.pathname + location.search);
  });
  // Dashboard widget + deep link support.
  if (location.hash === "#categories") openModal();
  // Restores / permanent deletes elsewhere refresh counts + dropdown.
  document.addEventListener("storepro:catalog-changed", () => load());
}
document.addEventListener("DOMContentLoaded", spInitCategories);
document.addEventListener("storepro:content", spInitCategories);
