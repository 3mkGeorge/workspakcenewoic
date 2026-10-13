/**
 * Product form initialization for StorePro.
 * Handles SKU generation, EAN-13 barcode generation, and quick-add modals for Category and Supplier.
 */
function initProductForm() {
  const btnSku = document.getElementById('btn-generate-sku');
  const btnBarcode = document.getElementById('btn-generate-barcode');
  const catForm = document.getElementById('quick-category-form');
  const supForm = document.getElementById('quick-supplier-form');

  // If not on product form page, return early
  if (!btnSku && !btnBarcode && !catForm && !supForm) return;

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const input = document.querySelector('input[name="csrf_token"]');
    return input ? input.value : '';
  }

  if (btnSku) {
    btnSku.onclick = function() {
      const code = 'SKU-' + Date.now().toString(36).toUpperCase() + '-' + Math.floor(100 + Math.random() * 900);
      const skuInput = document.getElementById('product-sku');
      if (skuInput) skuInput.value = code;
    };
  }

  if (btnBarcode) {
    btnBarcode.onclick = function() {
      let num = '20' + Math.floor(Math.random() * 1e10).toString().padStart(10, '0');
      let sum = 0;
      for (let i = 0; i < 12; i++) sum += parseInt(num[i], 10) * (i % 2 === 0 ? 1 : 3);
      let check = (10 - (sum % 10)) % 10;
      const barInput = document.getElementById('product-barcode');
      if (barInput) barInput.value = num + check;
    };
  }

  if (catForm) {
    catForm.onsubmit = async function(e) {
      e.preventDefault();
      const nameInput = document.getElementById('quick-category-name');
      const err = document.getElementById('quick-cat-error');
      if (!nameInput) return;
      const name = nameInput.value.trim();
      if (!name) return;
      try {
        const res = await fetch('/api/categories', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
          body: JSON.stringify({ name: name }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed to create category');
        const cat = data.category;
        const sel = document.getElementById('product-category-id');
        if (sel) {
          const opt = new Option(cat.name, cat.id, true, true);
          sel.add(opt);
        }
        const modalEl = document.getElementById('quickCategoryModal');
        if (modalEl && window.bootstrap && window.bootstrap.Modal) {
          const modalInstance = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
          modalInstance.hide();
        }
        nameInput.value = '';
        if (err) err.hidden = true;
      } catch (ex) {
        if (err) {
          err.textContent = ex.message;
          err.hidden = false;
        }
      }
    };
  }

  if (supForm) {
    supForm.onsubmit = async function(e) {
      e.preventDefault();
      const nameInput = document.getElementById('quick-supplier-name');
      const phoneInput = document.getElementById('quick-supplier-phone');
      const err = document.getElementById('quick-sup-error');
      if (!nameInput) return;
      const name = nameInput.value.trim();
      const phone = phoneInput ? phoneInput.value.trim() : '';
      if (!name) return;
      try {
        const res = await fetch('/api/suppliers', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
          body: JSON.stringify({ name: name, phone: phone }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed to create supplier');
        const sup = data.supplier;
        const sel = document.getElementById('product-supplier-id');
        if (sel) {
          const opt = new Option(sup.name, sup.id, true, true);
          sel.add(opt);
        }
        const modalEl = document.getElementById('quickSupplierModal');
        if (modalEl && window.bootstrap && window.bootstrap.Modal) {
          const modalInstance = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
          modalInstance.hide();
        }
        nameInput.value = '';
        if (phoneInput) phoneInput.value = '';
        if (err) err.hidden = true;
      } catch (ex) {
        if (err) {
          err.textContent = ex.message;
          err.hidden = false;
        }
      }
    };
  }
}

window.initProductForm = initProductForm;

// Auto-run on direct page load
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initProductForm);
} else {
  initProductForm();
}

// Auto-run on dynamic SPA content updates
document.addEventListener('storepro:content', initProductForm);
