"use strict";
function spStopBackups() {
  (window.__spBackupsTimers || []).forEach((id) => clearInterval(id));
  window.__spBackupsTimers = [];
}
document.addEventListener("storepro:leave", spStopBackups);
function spInitBackups() {
  spStopBackups();
  const root = document.querySelector("[data-backup-center]");
  if (!root) return;
  const emergency = root.dataset.recovery === "true";
  const endpoint = emergency ? "/api/recovery/status" : "/api/backups/status";
  let files = [],
    busy = false,
    restoring = false,
    active = false;
  const find = (id) => document.getElementById(id);
  const put = (id, text) => {
    if (find(id)) find(id).textContent = text;
  };
  const size = (n) => `${(n / 1048576).toFixed(2)} MB`;
  const date = (value) =>
    value
      ? new Intl.DateTimeFormat("en-GB", {
          timeZone: "Africa/Cairo",
          day: "2-digit",
          month: "2-digit",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }).format(new Date(value))
      : "—";
  const message = (text) => put("backup-message", text);
  const ui = window.StoreProUI;
  const tr = (text, values) => (ui ? ui.t(text, values) : text);
  const ask = (opts) => (ui ? ui.confirm(opts) : Promise.resolve(window.confirm(opts.message)));
  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || "";
  const bytes = (n) =>
    n >= 1073741824
      ? `${(n / 1073741824).toFixed(2)} GB`
      : `${(n / 1048576).toFixed(2)} MB`;
  function renderDestinations(locations) {
    (locations || []).forEach((l) => {
      const card = document.querySelector(`.dest-card[data-dest="${l.source}"]`);
      if (!card) return;
      const badge = card.querySelector("[data-dest-badge]");
      const bad = l.status !== "Writable";
      badge.className = `badge ${bad ? "text-bg-danger" : l.warning ? "text-bg-warning" : "text-bg-success"}`;
      badge.textContent = bad ? "Not Writable" : l.warning ? "Warning" : "Writable";
      const set = (sel, text) => {
        const el = card.querySelector(sel);
        if (el) el.textContent = text;
      };
      set("[data-dest-status]", bad ? "Not Writable" : l.warning ? "Writable · low space" : "Writable");
      set("[data-dest-last]", date(l.last_backup));
      set("[data-dest-free]", bytes(l.free || 0));
      set("[data-dest-count]", String(l.count ?? 0));
    });
  }
  function destValues() {
    const get = (s) => document.querySelector(`[data-dest-input="${s}"]`)?.value.trim() || "";
    return { backup_primary: get("Primary"), backup_secondary: get("Secondary") };
  }
  function renderRetention() {
    const items = files.filter((f) => f.healthy !== false);
    put("retention-count", String(files.length));
    put("retention-size", bytes(items.reduce((n, f) => n + (f.size || 0), 0)));
    if (!items.length) {
      put("retention-oldest", "—");
      put("retention-newest", "—");
      return;
    }
    const dates = items.map((f) => f.date).sort();
    put("retention-oldest", date(dates[0]));
    put("retention-newest", date(dates[dates.length - 1]));
  }
  async function postJSON(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(body || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const details = data.details ? ` ${Object.entries(data.details).map(([k, v]) => `${k}: ${v}`).join(" ")}` : "";
      throw new Error((data.error || "The request failed.") + details);
    }
    return data;
  }
  function wireDestinations() {
    const save = find("dest-save"),
      test = find("dest-test"),
      defaults = find("dest-defaults");
    if (save) save.addEventListener("click", async () => {
      save.disabled = true;
      try {
        const send = async (confirmCreate) => {
          const response = await fetch("/api/backups/paths", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRFToken": csrf() },
            body: JSON.stringify({ ...destValues(), confirm_create: !!confirmCreate }),
          });
          const data = await response.json().catch(() => ({}));
          if (response.status === 409 && data.needs_confirm) {
            const list = Object.entries(data.needs_confirm).map(([s, p]) => `${s}: ${p}`).join("\n");
            const create = await ask({
              title: tr("Create backup folders?"),
              message: tr("These backup folders do not exist and will be created:"),
              detail: list,
              confirmLabel: tr("Create folders"),
              tone: "primary",
            });
            if (create) return send(true);
            message(tr("Save cancelled — missing folders were not created."));
            return null;
          }
          if (!response.ok) {
            const details = data.details ? ` ${Object.entries(data.details).map(([k, v]) => `${k}: ${v}`).join(" ")}` : "";
            throw new Error((data.error || "The request failed.") + details);
          }
          return data;
        };
        const data = await send(false);
        if (data) {
          syncSettingsForm(destValues());
          message(data.message);
          await refresh();
        }
      } catch (error) {
        message(error.message);
      } finally {
        save.disabled = false;
      }
    });
    if (test) test.addEventListener("click", async () => {
      test.disabled = true;
      try {
        const data = await postJSON("/api/backups/test", {
          backup_primary: document.querySelector('[data-dest-input="Primary"]')?.value || "",
          backup_secondary: document.querySelector('[data-dest-input="Secondary"]')?.value || "",
        });
        (data.destinations || []).forEach((d) => {
          const card = document.querySelector(`.dest-card[data-dest="${d.source}"]`);
          if (!card) return;
          const badge = card.querySelector("[data-dest-badge]");
          badge.className = `badge ${d.writable ? "text-bg-success" : "text-bg-danger"}`;
          badge.textContent = d.writable ? "Writable" : "Not Writable";
          card.querySelector("[data-dest-status]").textContent = d.writable ? "Writable" : `Not Writable — ${d.error || "check path"}`;
          card.querySelector("[data-dest-free]").textContent = bytes(d.free || 0);
          card.querySelector("[data-dest-count]").textContent = String(d.count ?? 0);
          card.querySelector("[data-dest-last]").textContent = date(d.last_backup);
        });
        const failed = (data.destinations || []).filter((d) => !d.writable);
        message(failed.length ? `Test failed for: ${failed.map((d) => d.source).join(", ")}.` : "Both destinations are writable.");
      } catch (error) {
        message(error.message);
      } finally {
        test.disabled = false;
      }
    });
    if (defaults) defaults.addEventListener("click", async () => {
      const reset = await ask({
        title: tr("Reset backup destinations?"),
        message: tr("Reset both destinations to the installation folders?"),
        confirmLabel: tr("Reset destinations"),
        tone: "primary",
      });
      if (!reset) return;
      defaults.disabled = true;
      try {
        const data = await postJSON("/api/backups/defaults", {});
        document.querySelector('[data-dest-input="Primary"]').value = "";
        document.querySelector('[data-dest-input="Secondary"]').value = "";
        syncSettingsForm({ backup_primary: "", backup_secondary: "" });
        message(data.message);
        await refresh();
      } catch (error) {
        message(error.message);
      } finally {
        defaults.disabled = false;
      }
    });
    wireNativePicker();
  }
  // The Settings form also posts these paths; keep it in step so "Save Changes" never reverts them.
  function syncSettingsForm(values) {
    Object.entries(values).forEach(([name, value]) => {
      document.querySelectorAll(`form input[name="${name}"]`).forEach((input) => {
        input.value = value;
      });
    });
  }
  // Native OS folder picker (Windows Explorer dialog: all drives, new folders,
  // network locations). Browsers do not expose the absolute path of the
  // picked folder, so the picker is used for selection + permission
  // verification; the absolute path is then entered in the destination field
  // (copy it from the Explorer address bar) and authoritatively verified by
  // Test Paths on the server. Manual entry always remains available.
  //
  // NOTE: folder contents are never enumerated here. Hidden files and Windows
  // metadata (desktop.ini, thumbs.db, System Volume Information, Recycle Bin,
  // …) must never cause rejection: validation is limited to permission state
  // (+ write probe when ENFORCE_WRITE_PROBE is true). Reject only on:
  // missing folder, denied read, denied write, unavailable disk.
  //
  // DIAGNOSTIC MODE: ENFORCE_WRITE_PROBE is temporarily false while
  // investigating false rejections. Set back to true to re-enable the write
  // check. The quoted rejection text exists nowhere in StorePro code — if
  // shown, it comes from the browser's own sensitive-folder prompt
  // (Desktop/Documents/Downloads/…): choose Allow.
  const ENFORCE_WRITE_PROBE = false;
  const pickerLog = (step, details) => {
    try {
      console.debug("[StorePro folder-picker]", step, details || "");
    } catch {}
  };
  const pickerTrace = (text) => message(text);
  async function pickNativeFolder(source) {
    const input = document.querySelector(`[data-dest-input="${source}"]`);
    if (typeof window.showDirectoryPicker !== "function") {
      pickerTrace("Validation step: picker unavailable — using manual path entry.");
      message("This browser has no native folder picker. Type the absolute path manually, then use Test Paths.");
      input?.focus();
      return;
    }
    let handle = null;
    try {
      pickerLog("opening native picker", { source });
      handle = await window.showDirectoryPicker({ id: `storepro-${source.toLowerCase()}`, mode: "readwrite" });
    } catch (e) {
      if (e && e.name === "AbortError") {
        pickerLog("picker cancelled by user", { source });
        return;
      }
      pickerLog("picker failed to open", { source, name: e?.name, message: e?.message, stack: e?.stack });
      pickerTrace(`Validation step: picker open failed. Exception: ${e?.name}: ${e?.message}`);
      message(`Folder picker failed (${(e && e.name) || "error"}): ${(e && e.message) || e}. Type the path manually instead.`);
      return;
    }
    // Show the selection immediately, before any validation runs.
    // (Browsers expose only the folder name, never the absolute path.)
    pickerLog("folder selected", { source, selectedPath: handle && handle.name });
    pickerTrace(`Selected path: "${handle.name}" — starting validation…`);
    // Permission state is the read check; contents are never listed.
    let readState = "unknown",
      writeState = "unknown";
    try {
      readState = await handle.queryPermission({ mode: "read" });
    } catch (e) {
      pickerLog("queryPermission(read) threw", { selectedPath: handle.name, name: e?.name, message: e?.message, stack: e?.stack });
      pickerTrace(`Validation step: read-permission query threw. Exception: ${e?.name}: ${e?.message}`);
    }
    try {
      writeState = await handle.queryPermission({ mode: "readwrite" });
    } catch (e) {
      pickerLog("queryPermission(readwrite) threw", { selectedPath: handle.name, name: e?.name, message: e?.message, stack: e?.stack });
      pickerTrace(`Validation step: write-permission query threw. Exception: ${e?.name}: ${e?.message}`);
    }
    pickerLog("permission state", { selectedPath: handle.name, read: readState, readwrite: writeState });
    pickerTrace(`Validation step: permission check. Read: ${readState}. Write: ${writeState}.`);
    if (readState === "denied") {
      pickerTrace(`Validation step: rejected — read permission denied for "${handle.name}".`);
      message(`Read permission denied for folder "${handle.name}". Pick a folder you can read, or type the path manually.`);
      return;
    }
    if (writeState !== "granted") {
      pickerTrace(`Validation step: requesting write permission for "${handle.name}" — if the browser warns about system files, choose Allow (StorePro only writes backup ZIPs).`);
      message(`The browser will ask for access to "${handle.name}" — choose Allow. StorePro only writes backup ZIP files there.`);
      try {
        writeState = await handle.requestPermission({ mode: "readwrite" });
      } catch (e) {
        pickerLog("requestPermission threw", { selectedPath: handle.name, name: e?.name, message: e?.message, stack: e?.stack });
        pickerTrace(`Validation step: permission request threw. Exception: ${e?.name}: ${e?.message}. Stack: ${e?.stack}`);
        message(`Access request failed for folder "${handle.name}" (${e.name}: ${e.message}). Type the path manually instead.`);
        return;
      }
      pickerLog("permission after request", { selectedPath: handle.name, readwrite: writeState });
      pickerTrace(`Validation step: permission result for "${handle.name}": ${writeState}.`);
      if (writeState !== "granted") {
        message(`Access denied for folder "${handle.name}" (permission result: ${writeState}). Pick a folder you can write to, or type the path manually.`);
        return;
      }
    }
    if (!ENFORCE_WRITE_PROBE) {
      pickerLog("write probe skipped (temporarily disabled)", { selectedPath: handle.name, read: readState, readwrite: writeState });
      pickerTrace(`Validation step: write probe skipped (diagnostic mode). Result: accepted.`);
      message(`Explorer folder "${handle.name}" accepted (read: ${readState}, write: ${writeState}; write probe temporarily disabled). Paste its absolute path from the Explorer address bar into the ${source} field, then use Test Paths to verify.`);
      input?.focus();
      return;
    }
    // Write check (required for backups): create and remove a probe file.
    const probeName = `.storepro-write-test-${Date.now()}.tmp`;
    try {
      const probe = await handle.getFileHandle(probeName, { create: true });
      const writable = await probe.createWritable();
      await writable.write("StorePro");
      await writable.close();
      await handle.removeEntry(probeName);
    } catch (e) {
      pickerLog("write probe failed", {
        selectedPath: handle.name,
        probe: probeName,
        permission: writeState,
        name: e?.name,
        message: e?.message,
        stack: e?.stack,
      });
      pickerTrace(`Validation step: write probe failed. Exception: ${e?.name}: ${e?.message}. Stack: ${e?.stack}`);
      message(`Folder "${handle.name}" cannot be written (${e.name}: ${e.message}). Only folders Windows denies or that are read-only are rejected — pick a writable folder or type the path manually.`);
      return;
    }
    pickerLog("validation passed", { selectedPath: handle.name, read: readState, readwrite: writeState });
    pickerTrace(`Validation step: all checks passed for "${handle.name}".`);
    message(`Explorer folder "${handle.name}" verified: readable and writable. Paste its absolute path from the Explorer address bar into the ${source} field, then Save Paths.`);
    input?.focus();
  }
  function wireNativePicker() {
    document.querySelectorAll("[data-browse]").forEach((btn) =>
      btn.addEventListener("click", () => pickNativeFolder(btn.dataset.browse)),
    );
  }
  function renderFiles() {
    if (emergency) {
      const select = find("recovery-files"),
        selected = select.value;
      select.replaceChildren();
      files
        .filter((f) => f.healthy !== false)
        .forEach((f) => {
          const option = new Option(
            `${date(f.date)} · ${f.source} · ${size(f.size)}`,
            `${f.source}|${f.name}`,
          );
          select.add(option);
        });
      if (!select.options.length)
        select.add(new Option("No healthy recovery points available", ""));
      if ([...select.options].some((o) => o.value === selected)) select.value = selected;
      select.dispatchEvent(new Event("change"));
      return;
    }
    const tbody = find("backup-files"),
      filter = find("backup-source-filter").value;
    tbody.replaceChildren();
    files
      .filter((f) => !filter || f.source === filter)
      .forEach((f) => {
        const tr = document.createElement("tr");
        [date(f.date), size(f.size), f.source, f.name].forEach((value, index) => {
          const td = document.createElement("td");
          td.textContent = value;
          if (index === 3) td.className = "backup-id";
          tr.append(td);
        });
        const actions = document.createElement("td");
        const download = document.createElement("a");
        download.textContent = "Download";
        download.className = "btn btn-sm btn-light me-2";
        download.href = `/settings/backups/${encodeURIComponent(f.name)}?source=${encodeURIComponent(f.source)}`;
        const restore = document.createElement("button");
        restore.type = "button";
        restore.textContent = "Restore";
        restore.className = "btn btn-sm btn-outline-primary";
        restore.disabled = busy;
        restore.addEventListener("click", () => {
          const modal = find("backup-restore-modal"),
            form = modal.querySelector("form");
          form.reset();
          form.elements.source.value = f.source;
          form.elements.name.value = f.name;
          put("restore-selection", `${f.source} · ${date(f.date)} · ${f.name}`);
          bootstrap.Modal.getOrCreateInstance(modal).show();
        });
        if(root.dataset.canExport === "1") actions.append(download);
        if(root.dataset.canRestore === "1") actions.append(restore);
        tr.append(actions);
        tbody.append(tr);
      });
    if (!tbody.children.length) {
      const td = document.createElement("td");
      td.colSpan = 5;
      td.textContent = "No backups in this location yet.";
      const tr = document.createElement("tr");
      tr.append(td);
      tbody.append(tr);
    }
  }
  async function refresh() {
    if (active || document.hidden) return;
    active = true;
    try {
      const response = await fetch(endpoint, { headers: { Accept: "application/json" } });
      if (response.status === 401 || response.redirected) {
        location.assign("/login");
        return;
      }
      if (!response.ok) throw new Error("Could not read backup status.");
      const state = await response.json();
      if (state.restored && (emergency || restoring)) {
        location.assign("/login");
        return;
      }
      busy = state.busy;
      if (!busy) restoring = false;
      message(state.message);
      put("backup-last", date(state.last_backup));
      put("backup-next", date(state.next_backup));
      put("backup-size", size(state.size || 0));
      put("backup-count", state.count || 0);
      const warnings = find("backup-warnings");
      warnings.replaceChildren();
      (state.warnings || []).forEach((text) => {
        const el = document.createElement("div");
        el.className = "alert alert-warning";
        el.textContent = text;
        warnings.append(el);
      });
      if (find("backup-locations")) {
        find("backup-locations").replaceChildren();
        (state.locations || []).forEach((l) => {
          const card = document.createElement("div"),
            title = document.createElement("strong"),
            badge = document.createElement("span"),
            path = document.createElement("p");
          title.textContent = `${l.source} Destination`;
          const bad = l.status !== "Writable";
          badge.className = `badge ${bad ? "text-bg-danger" : l.warning ? "text-bg-warning" : "text-bg-success"}`;
          badge.textContent = bad ? "Not Writable" : l.warning ? "Warning" : l.status;
          title.append(badge);
          path.textContent = l.path;
          card.append(title, path);
          find("backup-locations").append(card);
        });
      }
      files = state.files || [];
      renderFiles();
      renderDestinations(state.locations);
      renderRetention();
      document
        .querySelectorAll(
          "[data-backup-action] button[type=submit], [data-backup-action] button:not([type])",
        )
        .forEach((b) => (b.disabled = busy));
    } catch (error) {
      message(error.message);
    } finally {
      active = false;
    }
  }
  find("backup-source-filter")?.addEventListener("change", renderFiles);
  find("backup-refresh")?.addEventListener("click", refresh);
  wireDestinations();
  find("recovery-files")?.addEventListener("change", (e) => {
    const [source, name] = e.target.value.split("|");
    const form = e.target.form;
    form.elements.source.value = source || "";
    form.elements.name.value = name || "";
  });
  document.querySelectorAll("[data-backup-action]").forEach((form) =>
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (busy) return;
      if (form.dataset.spSending) return; // already submitted; wait for the server
      if (form.hasAttribute("data-restore-form")) {
        const yes = await ask({
          title: tr("Restore this backup?"),
          message: tr("Replace current store data with this backup? All sessions will end."),
          detail: form.elements.name?.value || "",
          confirmLabel: tr("Restore backup"),
        });
        if (!yes || busy) return;
      }
      if (form.dataset.spSending) return;
      form.dataset.spSending = "1";
      const buttons = form.querySelectorAll("button");
      const submitter = event.submitter && form.contains(event.submitter) ? event.submitter : null;
      buttons.forEach((b) => (b.disabled = true));
      ui?.busy(submitter, true);
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { Accept: "application/json" },
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || data.message || `${tr("The request failed.")} (${response.status})`);
        restoring = form.hasAttribute("data-restore-form");
        if (form.elements.password) form.elements.password.value = "";
        if (find("backup-restore-modal"))
          bootstrap.Modal.getInstance(find("backup-restore-modal"))?.hide();
        message(data.message);
        await refresh();
      } catch (error) {
        const text = error instanceof TypeError ? tr("The request failed. Check your connection and try again.") : error.message;
        message(text);
        if (ui) ui.toast(text, "error");
      } finally {
        delete form.dataset.spSending;
        ui?.busy(submitter, false);
        buttons.forEach((b) => (b.disabled = busy));
      }
    }),
  );
  refresh();
  window.__spBackupsTimers = [
    setInterval(() => {
      if (busy || restoring) refresh();
    }, 2000),
    setInterval(refresh, 30000),
  ];
  if (!window.__spBackupsVisible) {
    window.__spBackupsVisible = true;
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && document.querySelector("[data-backup-center]")) refresh();
    });
  }
}
document.addEventListener("DOMContentLoaded", spInitBackups);
document.addEventListener("storepro:content", spInitBackups);
