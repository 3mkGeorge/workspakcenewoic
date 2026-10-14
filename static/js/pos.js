/* StorePro POS. Monetary state is integer minor units; the server is authoritative. */
(() => {
  "use strict";
  function bootPOS() {
    const root = document.getElementById("pos");
    if (!root) return;
    if (window.__spPosBooted) {
      // Financial form state can't be safely rebuilt in place; the draft in
      // localStorage restores it after reload.
      window.location.reload();
      return;
    }
    window.__spPosBooted = true;
    const posListeners = new AbortController();
    const posSignal = { signal: posListeners.signal };
  const cfg = JSON.parse(root.dataset.config),
    $ = (id) => document.getElementById(id);
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const draftKey = `storepro-pos-v2:${cfg.draft_scope}`;
  const money = (n) =>
    `${(n / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${cfg.currency}`;
  const decimal = (n) => (n / 100).toFixed(2);
  function cents(value) {
    const s = String(value).trim();
    if (!/^\d{1,10}(\.\d{0,2})?$/.test(s)) return null;
    const [a, b = ""] = s.split(".");
    return Number(a) * 100 + Number(b.padEnd(2, "0"));
  }
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function button(text, cls, action) {
    const b = el("button", cls, text);
    b.type = "button";
    if (action) b.addEventListener("click", action);
    return b;
  }
  const PACKAGE_ICON =
    '<svg class="lucide" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="m7.5 4.27 9 5.15"/></svg>';
  function placeholder() {
    const span = el("span", "pos-product-symbol");
    span.innerHTML = PACKAGE_ICON;
    return span;
  }
  function image(p) {
    if (!p.image) return placeholder();
    const im = el("img", "pos-product-image");
    im.src = p.image;
    im.alt = "";
    im.loading = "lazy";
    im.addEventListener("error", () => im.replaceWith(placeholder()), { once: true });
    return im;
  }
  let state = {
    token: cfg.token,
    items: [],
    customer: null,
    invoice_discount: 0,
    note: "",
    payments: [{ method: "Cash", amount: 0 }],
  };
  let saveInFlight = false,
    dirty = false,
    saved = false,
    busy = false,
    checking = false,
    quoteVersion = 0,
    changeVersion = 0,
    quoteTimer,
    searchTimer,
    customerTimer;
  let serverIssues = [],
    storageConflict = false,
    results = [],
    activeResult = -1,
    nextOffset = null,
    searchController;
  let lastInteraction = Date.now(),
    cancelIntent = "invoice";
  ["pointerdown", "keydown", "input"].forEach((name) =>
    root.addEventListener(name, () => {
      lastInteraction = Date.now();
    }),
  );
  let shortcuts = { frequent: [], recent: [] },
    shortcutTab = "frequent",
    lastTotals,
    localInvalid = false;
  const customerModal = new bootstrap.Modal($("customer-modal"));
  const cancelModal = new bootstrap.Modal($("cancel-modal"));
  const successModal = new bootstrap.Modal($("success-modal"));
  const editing = cfg.initial ? `&editing=${cfg.initial.sale_id}` : "";
  function message(text, success = false) {
    const box = $("pos-message");
    box.textContent = text;
    box.classList.toggle("success", success);
    box.hidden = !text;
  }
  async function api(path, body, signal) {
    let response;
    try {
      response = await fetch(`/api/pos${path}`, {
        method: body === undefined ? "GET" : "POST",
        credentials: "same-origin",
        headers:
          body === undefined
            ? { Accept: "application/json" }
            : {
                "Content-Type": "application/json",
                Accept: "application/json",
                "X-CSRFToken": csrf,
              },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal,
      });
    } catch (error) {
      if (error.name === "AbortError") throw error;
      throw Error(
        "Cannot reach StorePro. Your invoice is kept on this device. Try again when the local server is available.",
      );
    }
    let data;
    try {
      data = await response.json();
    } catch {
      throw Error(
        "Your session may have expired. Save your draft and sign in again in another tab, then refresh this page.",
      );
    }
    if (!response.ok)
      throw Error(data.error || data.message || "The request could not be completed.");
    return data;
  }
  function payload() {
    return {
      token: state.token,
      items: state.items.map((i) => ({
        product_id: i.product.id,
        quantity: i.quantity,
        discount: i.discount,
        unit_price: i.product.price,
      })),
      customer_id: state.customer?.id || null,
      invoice_discount: state.invoice_discount,
      note: state.note,
      payments: state.payments,
      tax_rate: cfg.tax_rate,
      currency: cfg.currency,
      fulfillment: fulfillmentPayload(),
      ...(cfg.initial
        ? { sale_id: cfg.initial.sale_id, revision: state.revision ?? cfg.initial.revision }
        : {}),
    };
  }
  function totals() {
    const subtotal = state.items.reduce((s, i) => s + i.quantity * i.product.price, 0),
      lineDiscount = state.items.reduce((s, i) => s + i.discount, 0),
      cost = state.items.reduce((s, i) => s + i.quantity * i.product.cost, 0);
    const discount = lineDiscount + state.invoice_discount,
      net = Math.max(0, subtotal - discount);
    const tax = Number((BigInt(Math.round(net)) * BigInt(cfg.tax_rate) + 5000n) / 10000n);
    return {
      subtotal,
      lineDiscount,
      discount,
      tax,
      total: net + tax,
      profit: net - cost,
      margin: net ? (100 * (net - cost)) / net : 0,
    };
  }
  function invalidReason() {
    if (!state.items.length) return "Add a product to start your sale.";
    if (localInvalid)
      return (
        [...root.querySelectorAll("input")].find((i) => !i.closest(".modal") && !i.validity.valid)
          ?.validationMessage || "Check the highlighted input."
      );
    if (
      state.items.some((i) => !i.product.active || i.quantity > i.product.stock || i.quantity < 1)
    )
      return "Resolve unavailable products or stock quantities before saving.";
    if (
      state.items.some((i) => i.discount > i.quantity * i.product.price) ||
      lastTotals.discount > lastTotals.subtotal
    )
      return "Discounts cannot exceed the value of the products.";
    if (lastTotals.subtotal > 1000000000000) return "This invoice exceeds the supported amount.";
    if (state.payments.reduce((s, p) => s + p.amount, 0) !== lastTotals.total)
      return "Payment amounts must equal the grand total.";
    if (state.payments.some((p) => p.amount === 0) && lastTotals.total > 0)
      return "Enter an amount for every payment, or remove the empty payment.";
    if (serverIssues.length) return serverIssues.join(" ");
    return "";
  }
  function refreshTotals() {
    lastTotals = totals();
    if (state.payments.length === 1) state.payments[0].amount = lastTotals.total;
    for (const [id, value] of Object.entries({
      subtotal: lastTotals.subtotal,
      "item-discounts": lastTotals.lineDiscount,
      "discount-total": lastTotals.discount,
      "tax-total": lastTotals.tax,
      "grand-total": lastTotals.total,
      "profit-total": lastTotals.profit,
      "receipt-subtotal": lastTotals.subtotal,
      "receipt-discount": lastTotals.discount,
      "receipt-tax": lastTotals.tax,
      "receipt-total": lastTotals.total,
    }))
      $(id).textContent = money(value);
    $("profit-margin").textContent = `${lastTotals.margin.toFixed(1)}%`;
    $("tax-label").textContent = `${$("tax-label").dataset.label || "VAT"} (${cfg.tax_rate / 100}%)`;
    $("item-count").textContent = state.items.length;
    $("units-count").textContent = `${state.items.reduce((s, i) => s + i.quantity, 0)} units`;
    const paid = state.payments.reduce((s, p) => s + p.amount, 0),
      balance = lastTotals.total - paid;
    $("balance-label").textContent = balance < 0 ? "Overallocated" : "Remaining balance";
    $("payment-balance").textContent = money(Math.abs(balance));
    $("payment-balance").parentElement.classList.toggle("unbalanced", balance !== 0);
    const onlyPayment = $("payment-rows").querySelector("input");
    if (state.payments.length === 1 && onlyPayment)
      onlyPayment.value = decimal(state.payments[0].amount);
    const why = invalidReason();
    $("save-sale").disabled = busy || checking || saved || !!why;
    $("save-hint").textContent = busy
      ? "Saving invoice securely…"
      : checking
        ? "Validating current prices and stock…"
        : why || "Ready to save · stock is validated again at checkout";
    renderReceipt();
  }
  function renderCart(flashId) {
    const body = $("cart-items");
    body.replaceChildren();
    $("cart-empty").hidden = state.items.length > 0;
    for (const item of state.items) {
      const p = item.product,
        tr = el("tr", p.id === flashId ? "pos-row-flash" : "");
      tr.dataset.id = p.id;
      const cells = Array.from({ length: 9 }, () => el("td"));
      cells[0].append(image(p));
      cells[1].append(el("strong", "", p.name));
      if (!p.active || item.quantity > p.stock)
        cells[1].append(
          el(
            "small",
            "pos-row-error",
            !p.active ? "Product unavailable" : "Quantity exceeds current stock",
          ),
        );
      cells[2].textContent = p.sku;
      cells[3].append(
        el(
          "span",
          `pos-stock ${p.stock === 0 ? "empty" : p.stock <= p.minimum ? "low" : ""}`,
          `${p.stock} in stock`,
        ),
      );
      cells[4].textContent = money(p.price);
      const step = el("div", "pos-stepper"),
        minus = button("−", "", () => quantity(item, item.quantity - 1)),
        plus = button("+", "", () => quantity(item, item.quantity + 1)),
        input = el("input");
      input.type = "text";
      input.inputMode = "numeric";
      input.value = item.quantity;
      input.setAttribute("aria-label", `Quantity for ${p.name}`);
      minus.setAttribute("aria-label", `Decrease ${p.name}`);
      plus.setAttribute("aria-label", `Increase ${p.name}`);
      minus.disabled = item.quantity <= 1;
      plus.disabled = item.quantity >= p.stock || !p.active;
      input.addEventListener("input", () => {
        const v = /^\d+$/.test(input.value) ? Number(input.value) : 0;
        const valid = Number.isSafeInteger(v) && v >= 1 && v <= p.stock;
        input.setCustomValidity(valid ? "" : `Choose 1 to ${p.stock} units.`);
        if (valid) {
          item.quantity = v;
          cells[7].textContent = money(v * p.price - item.discount);
          minus.disabled = v <= 1;
          plus.disabled = v >= p.stock;
        }
        localInvalid = hasInvalidInputs();
        changed();
      });
      input.addEventListener("change", () => {
        const v = /^\d+$/.test(input.value) ? Number(input.value) : 0;
        if (!Number.isSafeInteger(v) || v < 1 || v > p.stock) {
          message(`Choose a quantity from 1 to ${p.stock} for ${p.name}.`);
          input.value = item.quantity;
          input.setCustomValidity("");
          localInvalid = hasInvalidInputs();
          refreshTotals();
          return;
        }
        quantity(item, v);
      });
      step.append(minus, input, plus);
      cells[5].append(step);
      const discount = el("input", "pos-line-discount");
      discount.type = "text";
      discount.inputMode = "decimal";
      discount.value = decimal(item.discount);
      discount.setAttribute("aria-label", `Line discount for ${p.name}`);
      discount.addEventListener("input", () => {
        const v = cents(discount.value);
        discount.setCustomValidity(v === null ? "Enter a valid amount." : "");
        if (v !== null) item.discount = v;
        localInvalid = hasInvalidInputs();
        cells[7].textContent = money(item.quantity * p.price - item.discount);
        changed();
      });
      discount.addEventListener("blur", () => {
        if (cents(discount.value) !== null) discount.value = decimal(item.discount);
      });
      cells[6].append(discount);
      cells[7].textContent = money(item.quantity * p.price - item.discount);
      const remove = button("×", "pos-remove", () => {
        state.items = state.items.filter((i) => i !== item);
        renderCart();
        changed();
      });
      remove.setAttribute("aria-label", `Remove ${p.name}`);
      cells[8].append(remove);
      tr.append(...cells);
      body.append(tr);
    }
    localInvalid = hasInvalidInputs();
    refreshTotals();
  }
  function hasInvalidInputs() {
    return [...root.querySelectorAll("input")].some(
      (i) => !i.closest(".modal") && !i.validity.valid,
    );
  }
  function quantity(item, value) {
    if (value < 1 || value > item.product.stock) {
      message(`Only ${item.product.stock} units of ${item.product.name} are available.`);
      return;
    }
    item.quantity = value;
    renderCart(item.product.id);
    changed();
  }
  function addProduct(p) {
    if (busy || saved) return;
    if (!p.active || p.stock < 1) {
      message(`${p.name} is out of stock.`);
      return;
    }
    const item = state.items.find((i) => i.product.id === p.id);
    if (item) {
      item.product = p;
      if (item.quantity >= p.stock) {
        message(`All ${p.stock} available units of ${p.name} are already on the invoice.`);
        return;
      }
      item.quantity++;
    } else {
      if (state.items.length >= 100) {
        message("An invoice supports up to 100 different products.");
        return;
      }
      state.items.push({ product: p, quantity: 1, discount: 0 });
    }
    message(p.stock <= p.minimum ? `Low stock: ${p.name} has ${p.stock} available units.` : "");
    renderCart(p.id);
    changed();
  }
  function renderPayments() {
    const box = $("payment-rows");
    box.replaceChildren();
    state.payments.forEach((payment, index) => {
      const row = el("div", "pos-payment-row"),
        select = el("select");
      select.setAttribute("aria-label", `Payment method ${index + 1}`);
      for (const method of cfg.methods) {
        const option = el("option", "", method);
        option.value = method;
        select.append(option);
      }
      select.value = payment.method;
      select.addEventListener("change", () => {
        payment.method = select.value;
        changed(false);
      });
      const input = el("input");
      input.type = "text";
      input.inputMode = "decimal";
      input.value = decimal(payment.amount);
      input.readOnly = state.payments.length === 1;
      input.setAttribute("aria-label", `Payment amount ${index + 1}`);
      input.addEventListener("input", () => {
        const v = cents(input.value);
        input.setCustomValidity(v === null ? "Enter a valid payment amount." : "");
        if (v !== null) payment.amount = v;
        localInvalid = hasInvalidInputs();
        changed(false);
      });
      input.addEventListener("blur", () => {
        if (cents(input.value) !== null) input.value = decimal(payment.amount);
      });
      row.append(select, input);
      if (state.payments.length > 1) {
        const remove = button("×", "", () => {
          state.payments.splice(index, 1);
          renderPayments();
          changed(false);
        });
        remove.setAttribute("aria-label", `Remove payment ${index + 1}`);
        row.append(remove);
      }
      box.append(row);
    });
    $("add-payment").disabled = state.payments.length >= 5;
    localInvalid = hasInvalidInputs();
    refreshTotals();
  }
  function renderReceipt() {
    const box = $("receipt-items");
    box.replaceChildren();
    for (const item of state.items) {
      const row = el("div", "pos-receipt-line"),
        name = el("span", "", item.product.name);
      name.append(
        el(
          "small",
          "",
          `${item.quantity} × ${money(item.product.price)}${item.discount ? " · discount " + money(item.discount) : ""}`,
        ),
      );
      row.append(name, el("strong", "", money(item.quantity * item.product.price - item.discount)));
      box.append(row);
    }
    $("receipt-customer").textContent = state.customer?.name || "Walk-in customer";
    $("receipt-date").textContent =
      new Date().toLocaleDateString("en-GB") +
      " · " +
      new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    const payments = $("receipt-payments");
    payments.replaceChildren();
    state.payments.forEach((p) => {
      const row = el("div");
      row.append(el("span", "", p.method), el("span", "", money(p.amount)));
      payments.append(row);
    });
  }
  function changed(validate = true) {
    dirty = true;
    saved = false;
    changeVersion++;
    serverIssues = [];
    $("draft-status").textContent = "Unsaved changes";
    refreshTotals();
    if (validate) {
      clearTimeout(quoteTimer);
      quoteTimer = setTimeout(() => validateQuote(), 350);
    }
  }
  async function validateQuote() {
    if (!state.items.length || busy || saved || localInvalid) return false;
    const requestId = ++quoteVersion,
      version = changeVersion;
    checking = true;
    refreshTotals();
    try {
      const data = await api("/quote", payload());
      if (requestId !== quoteVersion || version !== changeVersion) return false;
      if (data.saved_invoice) {
        finishSaved(data.saved_invoice);
        return false;
      }
      serverIssues = data.issues.map((i) => (typeof i === "string" ? i : i.message));
      let changedProducts = false;
      for (const line of data.items || data.lines || []) {
        const item = state.items.find((i) => i.product.id === line.product.id);
        if (item && JSON.stringify(item.product) !== JSON.stringify(line.product)) {
          item.product = line.product;
          changedProducts = true;
        }
      }
      if (changedProducts) renderCart();
      $("stock-status").textContent = data.valid
        ? "Stock verified · " +
          new Date().toLocaleTimeString("en-GB", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })
        : serverIssues.join(" ");
      if (serverIssues.length) message(serverIssues.join(" "));
      return data.valid;
    } catch (error) {
      if (requestId === quoteVersion) {
        serverIssues = [error.message];
        message(error.message);
      }
      return false;
    } finally {
      if (requestId === quoteVersion) {
        checking = false;
        refreshTotals();
      }
    }
  }
  function closeSearch() {
    clearTimeout(searchTimer);
    searchController?.abort();
    $("product-results").hidden = true;
    $("product-search").setAttribute("aria-expanded", "false");
    $("product-search").removeAttribute("aria-activedescendant");
    activeResult = -1;
  }
  function showResults() {
    const box = $("product-results");
    box.replaceChildren();
    box.hidden = false;
    $("product-search").setAttribute("aria-expanded", "true");
    if (!results.length)
      box.append(
        el("div", "pos-results-message", "No matching products. Try a name, SKU, or barcode."),
      );
    results.forEach((p, index) => {
      const b = button("", "pos-result", () => selectProduct(p));
      b.id = `pos-result-${index}`;
      b.setAttribute("role", "option");
      b.setAttribute("aria-selected", String(index === activeResult));
      b.append(image(p));
      const info = el("span", "pos-result-info");
      info.append(
        el("strong", "", p.name),
        el("small", "", `${p.sku}${p.barcode ? " · " + p.barcode : ""}`),
      );
      const price = el("span", "pos-result-price", money(p.price));
      price.append(
        el(
          "small",
          p.stock === 0 ? "empty" : p.stock <= p.minimum ? "low" : "",
          p.stock
            ? `${p.stock} available${p.stock <= p.minimum ? " · low stock" : ""}`
            : "Out of stock",
        ),
      );
      b.append(info, price);
      box.append(b);
    });
    if (nextOffset !== null)
      box.append(
        button("Load more products", "pos-button pos-load-more", () => searchProducts(true)),
      );
  }
  async function searchProducts(more = false) {
    if (searchController) searchController.abort();
    searchController = new AbortController();
    const query = $("product-search").value.trim(),
      offset = more ? nextOffset : 0;
    if (!more) {
      results = [];
      activeResult = -1;
      $("product-results").replaceChildren(el("div", "pos-results-message", "Searching products…"));
      $("product-results").hidden = false;
      $("product-search").setAttribute("aria-expanded", "true");
    }
    try {
      const data = await api(
        `/products?q=${encodeURIComponent(query)}&offset=${offset || 0}${editing}`,
        undefined,
        searchController.signal,
      );
      results = more ? results.concat(data.items) : data.items;
      nextOffset = data.next_offset;
      showResults();
    } catch (error) {
      if (error.name !== "AbortError") {
        $("product-results").replaceChildren(el("div", "pos-results-message", error.message));
      }
    }
  }
  function selectProduct(p) {
    addProduct(p);
    $("product-search").value = "";
    closeSearch();
    $("product-search").focus();
  }
  let barcodeQueue = Promise.resolve();
  function scan(code) {
    barcodeQueue = barcodeQueue.then(async () => {
      try {
        const data = await api(`/products?barcode=${encodeURIComponent(code)}${editing}`);
        if (data.items.length === 1) selectProduct(data.items[0]);
        else message(`No active product has barcode “${code}”.`);
      } catch (error) {
        message(error.message);
      }
    });
  }
  $("product-search").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => searchProducts(), 170);
  });
  $("product-search").addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if ($("product-results").hidden) {
        searchProducts();
        return;
      }
      activeResult = Math.max(
        0,
        Math.min(results.length - 1, activeResult + (event.key === "ArrowDown" ? 1 : -1)),
      );
      showResults();
      if (activeResult >= 0) {
        $("product-search").setAttribute("aria-activedescendant", `pos-result-${activeResult}`);
        $(`pos-result-${activeResult}`).scrollIntoView({ block: "nearest" });
      }
    } else if (event.key === "Enter") {
      event.preventDefault();
      clearTimeout(searchTimer);
      if (activeResult >= 0 && results[activeResult]) selectProduct(results[activeResult]);
      else {
        const code = $("product-search").value.trim();
        const exact = results.find(
          (p) => p.barcode === code || p.sku.toLowerCase() === code.toLowerCase(),
        );
        if (exact) selectProduct(exact);
        else if (code) scan(code);
      }
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      if ($("product-results").hidden) cancel();
      else closeSearch();
    }
  });
  function renderShortcuts() {
    const box = $("product-shortcuts");
    box.replaceChildren();
    const items = shortcuts[shortcutTab];
    $("shortcut-count").textContent = "Last 90 days";
    if (!items.length) {
      box.append(
        el(
          "div",
          "pos-shortcuts-empty",
          shortcutTab === "recent"
            ? "Recently sold products will appear here after your first sale."
            : "Your best sellers will appear here as sales are completed.",
        ),
      );
      return;
    }
    items.forEach((p) => {
      const b = button("", "pos-shortcut", () => addProduct(p));
      b.disabled = !p.active || p.stock < 1;
      b.append(
        image(p),
        el("span", "pos-shortcut-add", "+"),
        el("strong", "", p.name),
        el("small", "", p.stock ? money(p.price) : "Out of stock"),
      );
      b.title = `${p.name} · ${p.stock} available`;
      box.append(b);
    });
  }
  async function loadShortcuts() {
    try {
      shortcuts = await api(`/shortcuts?${editing}`);
      renderShortcuts();
    } catch {
      $("product-shortcuts").replaceChildren(
        el(
          "div",
          "pos-shortcuts-empty",
          "Shortcuts unavailable. Product search is still available.",
        ),
      );
    }
  }
  root.querySelectorAll("[data-shortcut]").forEach((b) =>
    b.addEventListener("click", () => {
      shortcutTab = b.dataset.shortcut;
      root
        .querySelectorAll("[data-shortcut]")
        .forEach((t) => t.classList.toggle("selected", t === b));
      renderShortcuts();
    }),
  );
  function setCustomer(customer) {
    state.customer = customer;
    $("customer-label").textContent = customer?.name || "Walk-in customer";
    $("remove-customer").hidden = !customer;
    $("customer-search").value = "";
    $("customer-results").hidden = true;
    $("customer-search").setAttribute("aria-expanded", "false");
    if (customer && state.fulfillment?.method === "delivery" && !cfg.initial)
      autofillAddress();
    refreshTotals();
  }
  let customerVersion = 0;
  async function searchCustomers() {
    const version = ++customerVersion;
    try {
      const data = await api(
        "/customers?q=" + encodeURIComponent($("customer-search").value.trim()),
      );
      if (version !== customerVersion) return;
      const box = $("customer-results");
      box.replaceChildren();
      box.hidden = false;
      $("customer-search").setAttribute("aria-expanded", "true");
      const walk = button("Walk-in customer", "", () => {
        setCustomer(null);
        changed(false);
      });
      walk.setAttribute("role", "option");
      box.append(walk);
      for (const c of data.items) {
        const b = button(c.name, "", () => {
          setCustomer(c);
          changed(false);
        });
        b.setAttribute("role", "option");
        if (c.phone) b.append(el("small", "", c.phone));
        box.append(b);
      }
    } catch (error) {
      message(error.message);
    }
  }
  $("customer-search").addEventListener("input", () => {
    clearTimeout(customerTimer);
    customerTimer = setTimeout(searchCustomers, 180);
  });
  $("customer-search").addEventListener("focus", searchCustomers);
  $("customer-search").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      $("customer-results").querySelector("button")?.focus();
    }
  });
  $("customer-results").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      e.target.nextElementSibling?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      e.target.previousElementSibling?.focus();
    } else if (e.key === "Escape") {
      $("customer-results").hidden = true;
      $("customer-search").focus();
    }
  });
  $("remove-customer").addEventListener("click", () => {
    setCustomer(null);
    changed(false);
  });
  function newCustomer() {
    if (busy || saved || $("new-customer").disabled) return;
    customerModal.show();
  }
  $("new-customer").addEventListener("click", newCustomer);
  $("customer-modal").addEventListener("shown.bs.modal", () => $("new-customer-name").focus());
  $("customer-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = $("save-customer");
    if (submit.disabled) return;
    submit.disabled = true;
    $("customer-error").hidden = true;
    try {
      const data = await api("/customers", Object.fromEntries(new FormData(event.target)));
      setCustomer(data);
      changed(false);
      event.target.reset();
      customerModal.hide();
      message(`${data.name} was added and selected.`, true);
    } catch (error) {
      $("customer-error").textContent = error.message;
      $("customer-error").hidden = false;
    } finally {
      submit.disabled = false;
    }
  });
  /* Delivery & Fulfillment */
  const SHIP_IDS = {
    name: "ship-name", phone: "ship-phone", gov: "ship-gov",
    city: "ship-city", street: "ship-street", landmark: "ship-landmark",
  };
  function defaultFulfillment() {
    return {
      method: "pickup", pickup_date: "", pickup_notes: "",
      name: "", phone: "", gov: "", city: "",
      street: "", landmark: "",
      courier: "", shipping_cost: 0, update_profile: false,
    };
  }
  if (!state.fulfillment || typeof state.fulfillment !== "object")
    state.fulfillment = defaultFulfillment();
  let fulfillVersion = 0;
  function fulfillmentMethod() {
    return document.querySelector('input[name="fulfill-method"]:checked')?.value || "pickup";
  }
  function updateFulfillSummary() {
    const f = state.fulfillment;
    const pill = $("fulfill-summary");
    if (pill) {
      const delivery = f.method === "delivery";
      pill.hidden = false;
      pill.textContent = delivery ? `🚚 Delivery · ${money(f.shipping_cost || 0)}` : "🏪 Pickup";
      pill.classList.toggle("delivery", delivery);
    }
    const badge = $("ship-fee-badge");
    if (badge) badge.textContent = money(f.shipping_cost || 0);
  }
  function renderFulfillment() {
    state.fulfillment = { ...defaultFulfillment(), ...state.fulfillment };
    const f = state.fulfillment;
    document.querySelectorAll('input[name="fulfill-method"]').forEach(
      (r) => (r.checked = r.value === f.method),
    );
    const delivery = f.method === "delivery";
    $("pickup-pane").hidden = delivery;
    $("delivery-pane").hidden = !delivery;
    $("pickup-date").value = f.pickup_date || "";
    $("pickup-notes").value = f.pickup_notes || "";
    for (const [key, id] of Object.entries(SHIP_IDS)) {
      const input = $(id);
      if (input && document.activeElement !== input) input.value = f[key] || "";
      if (input) {
        const required = delivery && ["name", "phone", "gov", "city", "street"].includes(key);
        input.required = required;
        input.disabled = !delivery;
      }
    }
    const courier = $("ship-courier");
    if (courier && document.activeElement !== courier) courier.value = f.courier || "";
    if (courier) courier.disabled = !delivery;
    const cost = $("ship-cost");
    if (cost && document.activeElement !== cost) cost.value = decimal(f.shipping_cost || 0);
    if (cost) cost.disabled = !delivery;
    const up = $("ship-update-profile");
    if (up) {
      up.checked = !!f.update_profile;
      up.disabled = !delivery;
    }
    updateFulfillSummary();
    localInvalid = hasInvalidInputs();
  }
  function syncFulfillment(clearAutofill) {
    const f = state.fulfillment;
    f.method = fulfillmentMethod();
    f.pickup_date = $("pickup-date").value;
    f.pickup_notes = $("pickup-notes").value.trim();
    for (const [key, id] of Object.entries(SHIP_IDS)) f[key] = $(id).value.trim();
    f.courier = $("ship-courier").value.trim();
    const v = cents($("ship-cost").value);
    $("ship-cost").setCustomValidity(v === null ? "Enter a valid shipping cost." : "");
    if (v !== null) f.shipping_cost = v;
    const up = $("ship-update-profile");
    f.update_profile = !!(up && up.checked && !up.disabled);
    if (clearAutofill) f._autofilled_for = null;
    renderFulfillment();
    changed(false);
  }
  document.querySelectorAll('input[name="fulfill-method"]').forEach((r) =>
    r.addEventListener("change", () => {
      syncFulfillment(true);
      if (state.fulfillment.method === "delivery") autofillAddress();
    }),
  );
  $("fulfillment-card").addEventListener("input", (e) => {
    if (e.target.closest("#delivery-pane, #pickup-pane")) {
      syncFulfillment(false);
      localInvalid = hasInvalidInputs();
    }
  });
  async function autofillAddress() {
    const customer = state.customer;
    const f = state.fulfillment;
    if (customer?.name && !$("ship-name").value) {
      f.name = customer.name;
      $("ship-name").value = customer.name;
    }
    if (customer?.phone && !$("ship-phone").value) {
      f.phone = customer.phone;
      $("ship-phone").value = customer.phone;
    }
    if (!customer?.id || f._autofilled_for === customer.id) return;
    const version = ++fulfillVersion;
    try {
      const response = await fetch(
        `/api/shipping/last-address?customer_id=${customer.id}`,
        { headers: { Accept: "application/json" }, credentials: "same-origin" },
      );
      const data = await response.json();
      if (!response.ok)
        throw Error(data.error || "Could not load the saved delivery address.");
      if (version !== fulfillVersion || !data.address) return;
      f._autofilled_for = customer.id;
      const serverToCompact = {
        customer_name: "name", phone: "phone", governorate: "gov",
        city: "city", street: "street", landmark: "landmark",
      };
      for (const [serverKey, key] of Object.entries(serverToCompact)) {
        const id = SHIP_IDS[key];
        if ($(id) && !$(id).value && data.address[serverKey]) {
          f[key] = data.address[serverKey];
          $(id).value = data.address[serverKey];
        }
      }
      changed(false);
    } catch (error) {
      message(error.message);
    }
  }
  function fulfillmentPayload() {
    if (cfg.initial) return undefined;
    const f = state.fulfillment;
    if (f.method === "pickup")
      return { method: "pickup", pickup_date: f.pickup_date, pickup_notes: f.pickup_notes };
    const address = {};
    for (const key of Object.keys(SHIP_IDS)) address[key] = f[key] || "";
    // server field names (dropped compact-form fields sent empty)
    const serverAddress = {
      customer_name: address.name, phone: address.phone, alt_phone: "",
      governorate: address.gov, city: address.city, district: "",
      landmark: address.landmark,
      street: address.street, building: "", floor: "",
      apartment: "", postal_code: "", notes: "",
    };
    return {
      method: "delivery",
      address: serverAddress,
      courier: f.courier,
      shipping_cost: f.shipping_cost,
      update_profile: f.update_profile,
    };
  }
  $("invoice-discount").addEventListener("input", () => {
    const v = cents($("invoice-discount").value);
    $("invoice-discount").setCustomValidity(v === null ? "Enter a valid discount amount." : "");
    if (v !== null) state.invoice_discount = v;
    localInvalid = hasInvalidInputs();
    changed();
  });
  $("invoice-discount").addEventListener("blur", () => {
    if (cents($("invoice-discount").value) !== null)
      $("invoice-discount").value = decimal(state.invoice_discount);
  });
  $("sale-note").addEventListener("input", () => {
    state.note = $("sale-note").value;
    changed(false);
  });
  function addPayment() {
    if (state.payments.length >= 5) return;
    const method = cfg.methods.find((m) => !state.payments.some((p) => p.method === m)) || "Cash";
    state.payments.push({
      method,
      amount: Math.max(0, lastTotals.total - state.payments.reduce((s, p) => s + p.amount, 0)),
    });
    renderPayments();
    changed(false);
    $("payment-rows").lastElementChild.querySelector("input").focus();
  }
  $("add-payment").addEventListener("click", addPayment);
  function focusSearch() {
    if (busy || saved) return;
    $("product-search").focus();
    $("product-search").select();
    searchProducts();
  }
  $("browse-products").addEventListener("click", focusSearch);
  function cancel() {
    if (busy || saved) return;
    closeSearch();
    if (dirty || state.items.length) {
      cancelIntent = "invoice";
      $("cancel-modal-title").textContent = "Discard this invoice?";
      $("cancel-modal").querySelector(".modal-body").textContent =
        "Your unsaved items, payments, and draft will be cleared.";
      $("confirm-cancel").textContent = "Discard invoice";
      cancelModal.show();
    } else window.location.assign("/sales");
  }
  $("cancel-sale").addEventListener("click", cancel);
  $("clear-cart").addEventListener("click", () => {
    if (state.items.length) {
      cancelIntent = "items";
      $("cancel-modal-title").textContent = "Clear all items?";
      $("cancel-modal").querySelector(".modal-body").textContent =
        "The products and discounts will be removed. Your customer and note will stay.";
      $("confirm-cancel").textContent = "Clear items";
      cancelModal.show();
    }
  });
  function removeDraft() {
    try {
      localStorage.removeItem(draftKey);
    } catch {}
  }
  $("confirm-cancel").addEventListener("click", () => {
    if (cancelIntent === "items") {
      state.items = [];
      state.invoice_discount = 0;
      $("invoice-discount").value = "0.00";
      $("invoice-discount").setCustomValidity("");
      state.payments = [{ method: state.payments[0].method, amount: 0 }];
      serverIssues = [];
      renderCart();
      renderPayments();
      changed(false);
      cancelModal.hide();
      return;
    }
    dirty = false;
    saved = true;
    removeDraft();
    window.location.assign("/sales");
  });
  function saveDraft() {
    if (!dirty || saved || storageConflict) return;
    try {
      localStorage.setItem(
        draftKey,
        JSON.stringify({
          version: 2,
          time: Date.now(),
          currency: cfg.currency,
          tax_rate: cfg.tax_rate,
          state,
        }),
      );
      $("draft-status").textContent =
        "Draft saved · " +
        new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    } catch {
      $("draft-status").textContent = "Draft storage unavailable";
    }
  }
  async function restoreDraft() {
    let draft;
    try {
      draft = JSON.parse(localStorage.getItem(draftKey));
    } catch {}
    if (!draft) return;
    try {
      if (
        draft.version !== 2 ||
        Date.now() - draft.time > 86400000 ||
        draft.currency !== cfg.currency ||
        !Array.isArray(draft.state?.items) ||
        draft.state.items.length > 100 ||
        !/^[a-f0-9]{32,64}$/.test(draft.state.token)
      )
        throw Error("invalid");
      const s = draft.state;
      if (
        !Number.isSafeInteger(s.invoice_discount) ||
        s.invoice_discount < 0 ||
        typeof s.note !== "string" ||
        !Array.isArray(s.payments) ||
        !s.payments.length ||
        s.payments.length > 5 ||
        s.payments.some(
          (p) => !cfg.methods.includes(p.method) || !Number.isSafeInteger(p.amount) || p.amount < 0,
        )
      )
        throw Error("invalid");
      for (const i of s.items) {
        if (
          !Number.isInteger(i.product?.id) ||
          !Number.isInteger(i.quantity) ||
          i.quantity < 1 ||
          i.quantity > 1000000 ||
          !Number.isSafeInteger(i.discount) ||
          i.discount < 0 ||
          !Number.isSafeInteger(i.product.price) ||
          i.product.price < 0 ||
          !Number.isSafeInteger(i.product.cost) ||
          i.product.cost < 0
        )
          throw Error("invalid");
      }
      if (cfg.initial && s.revision !== cfg.initial.revision) {
        message(
          "The saved invoice changed after this draft was created. The current invoice is loaded; the older draft has not been applied.",
        );
        return;
      }
      state = s;
      dirty = true;
      $("draft-status").textContent = "Draft restored";
      message("Draft restored. Current prices and stock are being checked.", true);
      if (draft.tax_rate !== cfg.tax_rate)
        message("Draft restored. The VAT setting changed; review the updated total.");
    } catch {
      removeDraft();
      message("An expired or incompatible draft was removed.");
    }
  }
  window.addEventListener("storage", (event) => {
    if (event.key === draftKey && dirty && !saved) {
      storageConflict = true;
      $("draft-status").textContent = "Draft open in another tab";
      message(
        "This draft changed in another tab. Automatic draft saving is paused here. Finish this invoice in one tab only; refresh to load the latest saved draft.",
      );
    }
  }, posSignal);
  window.addEventListener("pagehide", saveDraft, posSignal);
  window.addEventListener("beforeunload", saveDraft, posSignal);
  window.__spPosDraftTimer = setInterval(saveDraft, 10000);
  function finishSaved(result) {
    saved = true;
    dirty = false;
    removeDraft();
    $("draft-status").textContent = "Invoice saved";
    $("saved-description").textContent = `${result.invoice} · ${money(result.total)}`;
    $("print-receipt").href = result.receipt_url;
    $("print-invoice").href = result.invoice_url;
    $("view-invoice").href = result.detail_url;
    successModal.show();
  }
  async function save() {
    if (busy || saved || saveInFlight) return;
    document.activeElement?.blur();
    localInvalid = hasInvalidInputs();
    refreshTotals();
    if (invalidReason()) {
      message(invalidReason());
      return;
    }
    saveInFlight = true;
    root.inert = true;
    clearTimeout(quoteTimer);
    const valid = await validateQuote();
    if (!valid || invalidReason()) {
      if (!saved) message(invalidReason() || "Review current prices and stock, then save again.");
      saveInFlight = false;
      root.inert = false;
      return;
    }
    busy = true;
    refreshTotals();
    saveDraft();
    try {
      const result = await api("/sales", payload());
      finishSaved(result);
    } catch (error) {
      message(error.message);
      serverIssues = [];
      saveDraft();
    } finally {
      busy = false;
      saveInFlight = false;
      root.inert = false;
      refreshTotals();
    }
  }
  $("save-sale").addEventListener("click", save);
  $("next-sale").addEventListener("click", () => {
    if (cfg.initial) {
      window.location.assign("/sales/new");
      return;
    }
    successModal.hide();
    state = {
      token:
        crypto.randomUUID().replaceAll("-", "") +
        crypto.randomUUID().replaceAll("-", "").slice(0, 16),
      items: [],
      customer: null,
      invoice_discount: 0,
      note: "",
      payments: [{ method: "Cash", amount: 0 }],
      fulfillment: defaultFulfillment(),
    };
    saved = false;
    dirty = false;
    serverIssues = [];
    storageConflict = false;
    $("invoice-discount").value = "0.00";
    $("invoice-discount").setCustomValidity("");
    $("sale-note").value = "";
    setCustomer(null);
    renderFulfillment();
    renderCart();
    renderPayments();
    message("");
    $("draft-status").textContent = "No unsaved changes";
    loadShortcuts();
    $("product-search").focus();
  });
  // Enter-terminated keyboard-wedge scanners. Normal typing and modal form input are left alone.
  let scanBuffer = "",
    scanStart = 0,
    scanLast = 0,
    scanTarget = null,
    scanOriginal = "";
  document.addEventListener(
    "keydown",
    (event) => {
      if (event.ctrlKey || event.altKey || event.metaKey || event.isComposing) return;
      const modalOpen = !!root.querySelector(".modal.show");
      if (!modalOpen && !busy && !saved) {
        const actions = {
          F2: newCustomer,
          F3: focusSearch,
          F4: () => {
            $("invoice-discount").focus();
            $("invoice-discount").select();
          },
          F7: addPayment,
          F8: save,
        };
        if (actions[event.key]) {
          event.preventDefault();
          event.stopImmediatePropagation();
          actions[event.key]();
          return;
        }
      }
      if (modalOpen || busy || saved) {
        scanBuffer = "";
        return;
      }
      if (event.key === "Escape" && event.target !== $("product-search")) {
        event.preventDefault();
        cancel();
        return;
      }
      if (
        event.key === "/" &&
        root.contains(event.target) &&
        /INPUT|TEXTAREA/.test(event.target.tagName)
      )
        event.stopImmediatePropagation();
      const time = performance.now();
      if (event.key.length === 1 && !event.repeat) {
        if (time - scanLast > 65 || scanTarget !== event.target) {
          scanBuffer = "";
          scanStart = time;
          scanTarget = event.target;
          scanOriginal = event.target.value || "";
        }
        scanBuffer += event.key;
        scanLast = time;
        if (scanBuffer.length > 80) scanBuffer = "";
      } else if (event.key === "Enter") {
        const isScan =
          scanBuffer.length >= 4 &&
          time - scanLast < 100 &&
          (scanLast - scanStart) / Math.max(1, scanBuffer.length - 1) < 40;
        if (isScan) {
          event.preventDefault();
          event.stopImmediatePropagation();
          clearTimeout(searchTimer);
          if (scanTarget !== $("product-search") && /INPUT|TEXTAREA/.test(scanTarget.tagName)) {
            scanTarget.value = scanOriginal;
            scanTarget.dispatchEvent(new Event("input", { bubbles: true }));
          }
          scan(scanBuffer);
        }
        scanBuffer = "";
      } else if (!["Shift", "CapsLock"].includes(event.key)) scanBuffer = "";
    },
    { capture: true, signal: posListeners.signal },
  );
  document.addEventListener(
    "click",
    (e) => {
      if (!e.target.closest(".pos-search-wrap")) closeSearch();
      if (!e.target.closest(".pos-customer-search")) {
        $("customer-results").hidden = true;
        $("customer-search").setAttribute("aria-expanded", "false");
      }
    },
    posSignal,
  );
  window.__spPosQuoteTimer = setInterval(() => {
    if (
      !document.hidden &&
      !busy &&
      !saved &&
      state.items.length &&
      Date.now() - lastInteraction < 60000
    )
      validateQuote();
  }, 10000);
  window.addEventListener(
    "focus",
    () => {
      if (state.items.length && !busy && !saved) validateQuote();
    },
    posSignal,
  );
  const heldKey = `storepro-pos-held-v1:${cfg.draft_scope}`;
  function esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
  function getHeldSales() {
    try { return JSON.parse(localStorage.getItem(heldKey) || "[]"); } catch { return []; }
  }
  function saveHeldSales(list) {
    try { localStorage.setItem(heldKey, JSON.stringify(list)); } catch {}
  }
  function updateHeldBadge() {
    const list = getHeldSales();
    const countEl = $("held-count");
    if (countEl) countEl.textContent = list.length;
  }
  function holdCurrentSale() {
    if (!state.items.length) {
      message("Add items to your cart before putting a sale on hold.");
      return;
    }
    const list = getHeldSales();
    const holdItem = {
      id: "hold-" + Date.now().toString(36) + "-" + Math.random().toString(36).substr(2, 4),
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      items: JSON.parse(JSON.stringify(state.items)),
      customer: state.customer ? { ...state.customer } : null,
      invoice_discount: state.invoice_discount || 0,
      note: $("sale-note") ? $("sale-note").value : (state.note || ""),
      payments: JSON.parse(JSON.stringify(state.payments || [])),
      fulfillment: state.fulfillment ? JSON.parse(JSON.stringify(state.fulfillment)) : null,
      itemCount: state.items.reduce((s, i) => s + (i.quantity || 1), 0),
      totalText: $("grand-total") ? $("grand-total").textContent : money(0),
    };
    list.unshift(holdItem);
    saveHeldSales(list);
    updateHeldBadge();

    state.items = [];
    state.customer = null;
    state.invoice_discount = 0;
    state.note = "";
    state.payments = [{ method: "Cash", amount: 0 }];
    state.fulfillment = defaultFulfillment();
    localStorage.removeItem(draftKey);
    dirty = false;
    $("invoice-discount").value = "0.00";
    $("invoice-discount").setCustomValidity("");
    if ($("sale-note")) $("sale-note").value = "";
    setCustomer(null);
    renderFulfillment();
    renderCart();
    renderPayments();
    refreshTotals();
    message("Sale placed on hold. Ready for next customer.", false);
    $("product-search").focus();
  }

  function showHeldModal() {
    const list = getHeldSales();
    const tbody = $("held-sales-list");
    const emptyEl = $("held-sales-empty");
    if (!tbody) return;
    tbody.replaceChildren();
    if (!list.length) {
      if (emptyEl) emptyEl.hidden = false;
    } else {
      if (emptyEl) emptyEl.hidden = true;
      list.forEach((hold) => {
        const tr = document.createElement("tr");
        const custName = hold.customer ? hold.customer.name : "Walk-in customer";
        tr.innerHTML = `
          <td><strong>${esc(hold.time)}</strong></td>
          <td>${esc(custName)}</td>
          <td><span class="badge text-bg-light">${hold.itemCount} items</span></td>
          <td><strong class="text-primary">${esc(hold.totalText)}</strong></td>
          <td><small class="text-muted">${esc(hold.note || "—")}</small></td>
          <td class="text-end">
            <button type="button" class="pos-button pos-primary btn-sm resume-hold-btn" style="padding:4px 10px;font-size:12px">Resume</button>
            <button type="button" class="pos-button pos-danger btn-sm discard-hold-btn" style="padding:4px 10px;font-size:12px">Discard</button>
          </td>
        `;
        tr.querySelector(".resume-hold-btn").onclick = () => {
          resumeHeldSale(hold.id);
          const modalEl = $("held-sales-modal");
          if (modalEl && window.bootstrap) {
            const modal = bootstrap.Modal.getInstance(modalEl);
            if (modal) modal.hide();
          }
        };
        tr.querySelector(".discard-hold-btn").onclick = () => {
          discardHeldSale(hold.id);
          showHeldModal();
        };
        tbody.appendChild(tr);
      });
    }
    const modalEl = $("held-sales-modal");
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  }

  async function resumeHeldSale(holdId) {
    if (!getHeldSales().some(h => h.id === holdId)) return;
    if (state.items.length) {
      const ui = window.StoreProUI;
      const tr = (text) => (ui ? ui.t(text) : text);
      const opts = {
        title: tr("Resume held sale?"),
        message: tr("Replace the items currently in this invoice with the held sale?"),
        confirmLabel: tr("Replace items"),
      };
      if (!(await (ui ? ui.confirm(opts) : Promise.resolve(window.confirm(opts.message))))) return;
    }
    // Re-read after the dialog: the hold may have been resumed or discarded meanwhile.
    const list = getHeldSales();
    const idx = list.findIndex(h => h.id === holdId);
    if (idx === -1) return;
    const hold = list[idx];
    list.splice(idx, 1);
    saveHeldSales(list);
    updateHeldBadge();

    state.items = hold.items || [];
    state.customer = hold.customer || null;
    state.invoice_discount = hold.invoice_discount || 0;
    state.note = hold.note || "";
    state.payments = hold.payments || [{ method: "Cash", amount: 0 }];
    if (hold.fulfillment) state.fulfillment = hold.fulfillment;

    $("invoice-discount").value = decimal(state.invoice_discount);
    $("invoice-discount").setCustomValidity("");
    if ($("sale-note")) $("sale-note").value = state.note;
    setCustomer(state.customer);
    renderFulfillment();
    renderCart();
    renderPayments();
    refreshTotals();
    dirty = true;
    saveDraft();
    validateQuote();
    message("Held sale resumed.", false);
  }

  function discardHeldSale(holdId) {
    const list = getHeldSales().filter(h => h.id !== holdId);
    saveHeldSales(list);
    updateHeldBadge();
  }

  const holdBtn = $("hold-sale");
  if (holdBtn) holdBtn.onclick = holdCurrentSale;
  const resumeBtn = $("resume-sale");
  if (resumeBtn) resumeBtn.onclick = showHeldModal;
  window.addEventListener(
    "keydown",
    (e) => {
      if (e.key !== "F6") return;
      e.preventDefault();
      if (busy || saved || root.querySelector(".modal.show")) return;
      holdCurrentSale();
    },
    posSignal,
  );

  async function initialize() {
    if (cfg.initial) state = { ...state, ...cfg.initial, token: cfg.token };
    if (!state.fulfillment || typeof state.fulfillment !== "object")
      state.fulfillment = defaultFulfillment();
    if (cfg.initial) {
      $("fulfillment-new").hidden = true;
      $("fulfillment-locked").hidden = false;
      const f = cfg.initial.fulfillment;
      $("fulfillment-summary").textContent = f
        ? f.method === "delivery"
          ? `Delivery · ${f.summary}`
          : `Store Pickup${f.summary ? ` · ${f.summary}` : ""}`
        : "Store Pickup";
    }
    await restoreDraft();
    updateHeldBadge();
    if (!state.fulfillment || typeof state.fulfillment !== "object")
      state.fulfillment = defaultFulfillment();
    $("invoice-discount").value = decimal(state.invoice_discount);
    $("sale-note").value = state.note;
    setCustomer(state.customer);
    renderFulfillment();
    renderCart();
    renderPayments();
    loadShortcuts();
    if (state.items.length) {
      try {
        const data = await api(
          "/products?ids=" + state.items.map((i) => i.product.id).join(",") + editing,
        );
        for (const item of state.items) {
          const p = data.items.find((p) => p.id === item.product.id);
          if (p) item.product = p;
          else item.product = { ...item.product, active: false, stock: 0 };
        }
        renderCart();
        await validateQuote();
      } catch (error) {
        serverIssues = [error.message];
        message(error.message);
        refreshTotals();
      }
    }
    $("product-search").focus();
  }
  initialize();
  // Unsaved-invoice guard + teardown for SPA navigation.
  window.__storeproGuard = () =>
    dirty && !saved && state.items.length
      ? document.getElementById("sp-ui-strings")?.dataset.leaveMessage ||
        "You have unsaved changes. They will be lost if you leave."
      : null;
  document.addEventListener(
    "storepro:leave",
    () => {
      clearInterval(window.__spPosDraftTimer);
      clearInterval(window.__spPosQuoteTimer);
      try {
        saveDraft();
      } catch {}
      window.__storeproGuard = null;
      posListeners.abort();
    },
    posSignal,
  );
  }
  if (document.readyState !== "loading") bootPOS();
  else document.addEventListener("DOMContentLoaded", bootPOS);
  document.addEventListener("storepro:content", () => {
    if (document.getElementById("pos")) bootPOS();
  });
})();
