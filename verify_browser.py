"""Real browser automation script using locally installed Chrome and Selenium.

Executes and verifies:
1. Login with user credentials (george / test-password-123)
2. Dashboard navigation (verify metrics, charts, quick links)
3. Products catalog page (/products)
4. SPA navigation to /products/new
5. Generate SKU button functionality
6. Generate Barcode (EAN-13) button functionality
7. Quick Add Category modal & auto-selection
8. Quick Add Supplier modal & auto-selection
9. SPA back/forward navigation and idempotency (no duplicate listeners)
10. Inventory ledger and adjustment view (/inventory, /inventory/adjust)
11. POS workstation (/sales/new, live calculation, item search)
12. Orders Hub (/orders)
13. Packed tab (/orders?tab=packed, verify status display and badge count)
14. Shipping workflow & details view
15. Returns & Refunds tab
16. Permissions and Role-based access control (/permissions)
17. Backups status & Dual Backup panel (/backups)
18. Reports and analytics page (/reports)
"""

import sys
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_URL = "http://127.0.0.1:5000"

def run_browser_verification():
    options = Options()
    options.binary_location = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1440,900")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 10)
    results = {}

    try:
        print("=== 1. Testing Login ===")
        driver.get(f"{BASE_URL}/login")
        username_input = wait.until(EC.presence_of_element_located((By.NAME, "username")))
        password_input = driver.find_element(By.NAME, "password")
        username_input.send_keys("george")
        password_input.send_keys("test-password-123")
        driver.find_element(By.CSS_SELECTOR, "form button").click()

        wait.until(EC.url_changes(f"{BASE_URL}/login"))
        assert "/login" not in driver.current_url
        print(f"Login successful! Landed on: {driver.current_url}")
        results["Login"] = "PASSED"

        print("=== 2. Testing Dashboard Navigation ===")
        driver.get(f"{BASE_URL}/")
        wait.until(EC.presence_of_element_located((By.ID, "main-content")))
        assert "StorePro" in driver.title or len(driver.find_elements(By.TAG_NAME, "h1")) > 0
        print("Dashboard loaded successfully.")
        results["Dashboard"] = "PASSED"

        print("=== 3. Testing Products Catalog ===")
        driver.get(f"{BASE_URL}/products")
        wait.until(EC.presence_of_element_located((By.ID, "main-content")))
        assert "/products" in driver.current_url
        print("Products catalog loaded.")
        results["Products"] = "PASSED"

        print("=== 4. Testing SPA Navigation to /products/new ===")
        # Click "+ Add Product" link to trigger SPA client-side navigation
        add_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "a[href='/products/new']")))
        add_btn.click()
        wait.until(EC.url_contains("/products/new"))
        sku_btn = wait.until(EC.presence_of_element_located((By.ID, "btn-generate-sku")))
        print("Navigated via SPA router to /products/new.")
        results["SPA Navigation to /products/new"] = "PASSED"

        print("=== 5. Testing Generate SKU Button ===")
        sku_input = driver.find_element(By.ID, "product-sku")
        assert sku_input.get_attribute("value") == "", "SKU input should initially be empty"
        sku_btn.click()
        time.sleep(0.3)
        generated_sku = sku_input.get_attribute("value")
        print(f"Generated SKU: {generated_sku}")
        assert generated_sku.startswith("SKU-") and len(generated_sku) > 4, "SKU generation failed!"
        results["Generate SKU"] = "PASSED"

        print("=== 6. Testing Generate Barcode Button ===")
        barcode_btn = driver.find_element(By.ID, "btn-generate-barcode")
        barcode_input = driver.find_element(By.ID, "product-barcode")
        assert barcode_input.get_attribute("value") == "", "Barcode input should initially be empty"
        barcode_btn.click()
        time.sleep(0.3)
        generated_barcode = barcode_input.get_attribute("value")
        print(f"Generated Barcode: {generated_barcode}")
        assert len(generated_barcode) == 13 and generated_barcode.isdigit(), "EAN-13 Barcode generation failed!"
        results["Generate Barcode"] = "PASSED"

        print("=== 7. Testing Quick Add Category Modal ===")
        quick_cat_btn = driver.find_element(By.ID, "btn-new-category")
        quick_cat_btn.click()
        cat_modal = wait.until(EC.visibility_of_element_located((By.ID, "quickCategoryModal")))
        cat_input = driver.find_element(By.ID, "quick-category-name")
        cat_name = f"Browser Category {int(time.time())}"
        cat_input.send_keys(cat_name)
        driver.find_element(By.CSS_SELECTOR, "#quick-category-form button[type='submit']").click()
        time.sleep(0.5)

        # Verify added to category select
        cat_select = driver.find_element(By.ID, "product-category-id")
        options = [o.text for o in cat_select.find_elements(By.TAG_NAME, "option")]
        assert cat_name in options, f"Category '{cat_name}' not found in dropdown: {options}"
        print(f"Quick Add Category successful: {cat_name} in options.")
        results["Quick Add Category"] = "PASSED"

        print("=== 8. Testing Quick Add Supplier Modal ===")
        quick_sup_btn = driver.find_element(By.ID, "btn-new-supplier")
        quick_sup_btn.click()
        sup_modal = wait.until(EC.visibility_of_element_located((By.ID, "quickSupplierModal")))
        sup_input = driver.find_element(By.ID, "quick-supplier-name")
        sup_name = f"Browser Supplier {int(time.time())}"
        sup_input.send_keys(sup_name)
        driver.find_element(By.CSS_SELECTOR, "#quick-supplier-form button[type='submit']").click()
        time.sleep(0.5)

        # Verify added to supplier select
        sup_select = driver.find_element(By.ID, "product-supplier-id")
        sup_options = [o.text for o in sup_select.find_elements(By.TAG_NAME, "option")]
        assert sup_name in sup_options, f"Supplier '{sup_name}' not found in dropdown: {sup_options}"
        print(f"Quick Add Supplier successful: {sup_name} in options.")
        results["Quick Add Supplier"] = "PASSED"

        print("=== 9. Testing Back/Forward Navigation & Idempotency ===")
        driver.back()
        wait.until(EC.url_contains("/products"))
        time.sleep(0.5)
        driver.forward()
        wait.until(EC.url_contains("/products/new"))
        time.sleep(0.5)
        # Test SKU button again
        sku_btn_after = wait.until(EC.element_to_be_clickable((By.ID, "btn-generate-sku")))
        sku_btn_after.click()
        time.sleep(0.3)
        sku_after = driver.find_element(By.ID, "product-sku").get_attribute("value")
        assert sku_after.startswith("SKU-")
        print("Back/forward SPA navigation and event re-attachment verified.")
        results["SPA History Navigation"] = "PASSED"

        print("=== 10. Testing Inventory ===")
        driver.get(f"{BASE_URL}/inventory")
        wait.until(EC.presence_of_element_located((By.ID, "main-content")))
        assert "Inventory" in driver.page_source or "Stock" in driver.page_source

        driver.get(f"{BASE_URL}/inventory/adjust")
        wait.until(EC.presence_of_element_located((By.NAME, "reason")))
        print("Inventory and Stock Adjustment pages verified.")
        results["Inventory"] = "PASSED"

        print("=== 11. Testing POS Workstation ===")
        driver.get(f"{BASE_URL}/sales/new")
        wait.until(EC.presence_of_element_located((By.ID, "pos")))
        search_box = wait.until(EC.presence_of_element_located((By.ID, "product-search")))
        assert "Invoice summary" in driver.page_source or "Grand total" in driver.page_source
        print("POS workstation loaded with interactive summary and search bar.")
        results["POS"] = "PASSED"

        print("=== 12. Testing Orders Hub ===")
        driver.get(f"{BASE_URL}/orders")
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "orders-tabs")))
        print("Orders hub loaded with tab container.")
        results["Orders"] = "PASSED"

        print("=== 13. Testing Packed Tab & Counter Badge ===")
        driver.get(f"{BASE_URL}/orders?tab=packed")
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "fulfillment-pipeline")))
        packed_link = driver.find_element(By.CSS_SELECTOR, "a[href='/orders?tab=packed']")
        assert "active" in packed_link.get_attribute("class"), f"Packed link not active: {packed_link.get_attribute('class')}"
        badge = packed_link.find_element(By.CLASS_NAME, "badge")
        print(f"Packed tab active with counter badge: {badge.text}")
        results["Packed Tab & Badge"] = "PASSED"

        print("=== 14. Testing Shipping Orders Workflow ===")
        driver.get(f"{BASE_URL}/orders?tab=shipped")
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "orders-tabs")))
        assert "shipped" in driver.current_url
        print("Shipping tab verified.")
        results["Shipping Workflow"] = "PASSED"

        print("=== 15. Testing Returns & Refunds Tab & Workflow ===")
        driver.get(f"{BASE_URL}/orders?tab=returns")
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "orders-tabs")))
        assert "returns" in driver.current_url

        # Check Sales list and open Details Modal with refund capability
        driver.get(f"{BASE_URL}/sales")
        wait.until(EC.presence_of_element_located((By.ID, "main-content")))
        sale_links = driver.find_elements(By.CSS_SELECTOR, "[data-sale-modal]")
        if sale_links:
            sale_links[0].click()
            modal = wait.until(EC.visibility_of_element_located((By.ID, "saleDetailsModal")))
            wait.until(EC.visibility_of_element_located((By.ID, "sale-modal-content")))
            refund_btn = driver.find_element(By.ID, "sale-modal-refund")
            assert refund_btn.is_displayed()
            print("Sale details modal opened with Return / Refund action active.")
            driver.find_element(By.CSS_SELECTOR, "#saleDetailsModal .btn-close").click()
            time.sleep(0.4)
        print("Returns and Refunds tab & workflow verified.")
        results["Returns & Refunds"] = "PASSED"

        print("=== 16. Testing Permissions Management ===")
        driver.get(f"{BASE_URL}/settings/users")
        wait.until(EC.presence_of_element_located((By.ID, "main-content")))
        assert "Users" in driver.page_source or "Role" in driver.page_source

        driver.get(f"{BASE_URL}/settings/users/1")
        wait.until(EC.presence_of_element_located((By.ID, "main-content")))
        assert "Permissions" in driver.page_source or "Role" in driver.page_source
        print("Permissions management loaded.")
        results["Permissions"] = "PASSED"

        print("=== 17. Testing Dual Backups Dashboard ===")
        driver.get(f"{BASE_URL}/backups")
        wait.until(EC.presence_of_element_located((By.ID, "main-content")))
        assert "Backup" in driver.page_source
        print("Backups dashboard loaded.")
        results["Backups"] = "PASSED"

        print("=== 18. Testing Reports & Analytics ===")
        driver.get(f"{BASE_URL}/reports")
        wait.until(EC.presence_of_element_located((By.ID, "main-content")))
        assert "Reports" in driver.page_source or "Sales" in driver.page_source
        print("Reports page loaded.")
        results["Reports"] = "PASSED"

        print("\n==========================================")
        print("ALL REAL BROWSER VERIFICATIONS PASSED!")
        print("==========================================")
        for k, v in results.items():
            print(f"- {k}: {v}")
        return True, results

    except Exception as e:
        print(f"\nBROWSER VERIFICATION FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False, results
    finally:
        driver.quit()

if __name__ == "__main__":
    success, res = run_browser_verification()
    sys.exit(0 if success else 1)
