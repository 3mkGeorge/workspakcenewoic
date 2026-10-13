# StorePro v1.0 – User Guide & Operator Manual

Welcome to **StorePro**, your reliable, offline-ready local store management and Point of Sale (POS) system. This manual guides store cashiers, clerks, and sales operators through daily retail operations.

---

## 1. Getting Started

### Starting StorePro
1. On your Windows desktop or application folder, double-click **`run.bat`**.
2. A command console will open. **Keep this console open** while you are working.
3. Open your web browser (Google Chrome, Microsoft Edge, or Mozilla Firefox) and navigate to:
   ```
   http://127.0.0.1:5000
   ```
4. If this is the store's very first launch, the administrator setup screen will appear. Otherwise, the sign-in screen appears.

### Signing In & Idle Security
1. Enter your assigned **Username** and **Password**.
2. Click **Sign in**.
3. **Session Timeout:** For security, if the workstation remains inactive longer than the configured session duration (default: 60 minutes), your session will lock automatically. Re-enter your credentials to resume.
4. **Signing Out:** When leaving the workstation, click your name in the bottom-left sidebar and select **Logout**.

---

## 2. Point of Sale (POS) & Checkout Workflow

To open the register, click **Sales** -> **New Sale** (`/sales/new`) from the left sidebar navigation.

### Adding Products to Cart
- **Barcode Scanning:** Plug in any standard USB or Bluetooth barcode scanner in keyboard-wedge mode. Simply scan the product barcode; the item is instantly added or its quantity incremented.
- **Search by Name or SKU:** Type product name, SKU, or category into the search box. Press `Enter` or click on the matching item to add it.
- **Touch / Quick Tap:** Click any product card on the screen to add it immediately.

### Adjusting Cart Items
- **Quantity:** Use the `+` and `-` buttons or click the quantity field to type an exact amount.
- **Line Item Discount:** If authorized, click the line item discount field to apply a promotional reduction.
- **Removing Items:** Click the trash icon (`Delete`) to remove an item from the sale.

### Customer Selection
- By default, sales are assigned to **Walk-in Customer**.
- To attach a loyalty or registered customer, start typing their name or phone number in the customer selector.
- Click **+ Add Customer** if you need to register a new customer on the spot.

### Collecting Payment & Finalizing
StorePro supports 5 payment methods with exact penny-accurate split billing:
1. **Cash:** Enter the cash amount tendered. The system displays exact customer change due.
2. **Visa / Mastercard:** Enter the terminal transaction amount.
3. **Bank Transfer:** Record direct bank or wire transfers.
4. **Mobile Wallet:** Record mobile wallet or digital payments (e.g. Vodafone Cash, Apple Pay).
5. **Split Payment:** Click **Add Payment Method** to combine methods (e.g., $50 Cash + $75 Card). The total payments must match the invoice total exactly.
6. Click **Complete Sale**.

### Invoices & Printing
- Once completed, the official receipt displays automatically.
- Click **Print Invoice** or press `Ctrl + P` to trigger thermal receipt printers (80mm/58mm) or standard A4 invoice printing.
- Receipts include the store logo, contact info, tax breakdown, cashier name, and barcode.

---

## 3. Order Fulfillment & Delivery Tracking

For orders that require shipment or scheduled pickup:
1. When ringing up the sale, select **Fulfillment Method**:
   - **Store Pickup:** Choose pickup date/time and recipient contact.
   - **Delivery:** Enter delivery address, recipient phone number, and delivery instructions.
2. View pending orders under **Orders** -> **Deliveries & Pickups**.
3. Update order status as it progresses:
   - **Delivery orders:** `Pending` -> `Packed` -> `Ready` -> `Shipped` -> `Delivered` (or `Returned` / `Cancelled`).
   - **Store pickup orders:** `Pending Pickup` -> `Ready For Pickup` -> `Collected`.

---

## 4. Product Catalog & Inventory Inquiries

To look up inventory levels without making a sale:
1. Navigate to **Inventory** -> **Products** (`/products`).
2. Filter by category, supplier, or stock status:
   - **In Stock:** Products with healthy quantities above the safety threshold.
   - **Low Stock:** Products below their configured minimum reorder point.
   - **Out of Stock:** Products with zero inventory available.
3. Click any product to view its gallery images, cost, selling price, and historical movement ledger.

---

## 5. Keyboard Navigation & Accessibility Shortcuts

StorePro supports keyboard-only operation for high-speed counter service:
- **Skip to Main Content:** Press `Tab` upon page load to skip the navigation sidebar.
- **Barcode Input Focus:** Press `/` or click into the search field to begin typing product queries.
- **Tab Navigation:** All form fields, buttons, and modal dialogs feature high-contrast focus rings (`:focus-visible`).
- **Modal Close:** Press `Escape` to close any open popup modal.
- **Language Switch:** If your store operates in Arabic, click the language toggle in the header for native Right-to-Left (RTL) mode.
