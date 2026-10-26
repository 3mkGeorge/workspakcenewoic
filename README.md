# StorePro — Windows Store Management



A local Flask application built from the seven supplied StorePro UI references. The application runs on your Windows PC, stores business data in SQLite, and uses local copies of Bootstrap, Chart.js, fonts, and icons. It makes no external requests during normal use.



## Start the application



1. Install **Python 3.13, Windows x64**, if it is not already installed. The launcher uses Python on PATH, then tries the Python launcher.

2. Extract the entire `StorePro-Windows.zip` file to a writable folder. Do not run it from inside the ZIP.

3. Double-click **run.bat**. The first run installs dependencies from the included `wheels` folder without internet access.

4. Open **http://127.0.0.1:5000** in a browser.

5. Create your administrator account. Choose a password of at least 12 characters. There are no default credentials.



Keep the StorePro console window open while working. Press Ctrl+C in that window to stop it. On later visits, double-click `run.bat` and sign in. Only one StorePro process may open the same store. The server listens on `127.0.0.1`, not the network.



Python itself is a prerequisite; it is not bundled. The offline wheels in this package target Python 3.13 x64 on Windows. For a different Python version, create a virtual environment and install `requirements.txt` with internet access first.



## Configure your store



Open **Settings** to set store details, logo, invoice prefixes, receipt wording, VAT, language, and appearance. Defaults are **English**, **EGP**, **14% VAT**, and **DD/MM/YYYY**. Business dates use the Africa/Cairo timezone, including daylight saving time.



English and Arabic interfaces are supported, with right-to-left layouts and local Arabic fonts. Product names, customer names, notes, and other user-entered information remain as entered. Monetary values include an explicit currency code. EGP is the default; USD, EUR, SAR, and AED are available before entering products or transactions. Currency becomes locked afterwards so existing amounts cannot accidentally be relabeled. This is a single-currency store, with no exchange-rate conversion.



The header moon button changes this browser's appearance immediately; Settings sets the store default. A browser-specific theme takes precedence over the store default until toggled in that browser.



## First working day



1. Add categories from **Products → Categories**.

2. Add suppliers from **Purchases → Suppliers**.

3. Add products, including SKU, optional unique barcode, purchase cost, selling price, minimum stock, location, and optional image.

4. Enter opening quantities or create purchase orders. **Receive** an order once goods arrive; this adds the complete order to stock.

5. Add customers or use Walk-in Customer. Open **New Sale**, choose products and quantities, apply any invoice discount, choose a payment method, and save.

6. Select an invoice to print an A4 invoice or an 80 mm receipt, edit it, refund it, or void it according to your role.

7. Record operating expenses from **Dashboard → Expenses** to include them in profit and loss.



A USB barcode scanner configured as a keyboard can enter a barcode into the sale search box and send Enter. Search also matches names and SKUs; use Arrow Up/Down and Enter to select a result. Repeated scans increase the existing line quantity. The global search matches products, SKUs, barcodes, invoices, customers, suppliers, and purchase orders. Press `/` to focus it.



## Modules and behavior



- **Dashboard:** today's sales, profit, expenses, purchases and unique registered customers; current catalog and inventory totals; stock alerts; 7-, 30-, and 90-day trends; top-selling products; recent sales; quick actions.

- **Sales:** customer selection, multiple items, Cash/Visa/Mastercard/Bank Transfer/Wallet and split allocations, VAT, item and invoice discounts, idempotent creation, editable completed invoices, full refunds, invoice history, soft deletion through voiding, print invoices and receipts, search, date/status/payment filters, pagination, and live detail panels.

- **Products:** add/edit/archive, unique SKU and barcode, image upload, category, supplier, brand, cost, price, opening stock, reorder threshold, location, stock filters and details. A product must have zero stock and no outstanding purchase orders before it can be removed from the catalog.

- **Inventory:** guarded stock adjustments, stock receipt through purchase orders, stock-movement history, current cost valuation, category charts, location valuations, low-stock and out-of-stock alerts.

- **Purchases:** supplier directory, purchase orders, Pending/Processing/Received/Cancelled lifecycle, receive-once protection, weighted-average purchase cost, search/filtering, detail panels, purchase trends and top suppliers.

- **Reports:** sales, purchases, current inventory, product performance, customer, supplier and profit/loss reports; date/product/category/customer filters; daily/weekly/monthly chart grouping; Excel and PDF downloads; browser printing.

- **Settings:** general/store details, languages/currencies, invoice and receipt options, VAT, security, account management, roles, audit logs, automatic/manual backups, validated restore, and appearance.



## Financial and stock rules



- Amounts are stored as integer minor units. For EGP, one pound is 100 piastres. VAT is calculated on subtotal minus all item and invoice discounts and rounded half-up to the nearest piastre.

- Selling prices exclude VAT. Profit is net sales excluding VAT minus the product cost captured when sold, minus recorded operating expenses. Purchase order totals are inventory cost excluding recoverable input VAT; input VAT settlement is not an accounting module in this application.

- Received inventory recalculates weighted-average cost. Sales preserve name, category, price, cost, tax rate, currency, customer name, cashier and store snapshots. Later product changes do not rewrite historical invoices.

- Completed invoice edits reverse the previous stock movements and apply the replacement in one transaction. A revision number prevents stale edits. Old invoice financial/item data is retained in audit-log revision snapshots.

- Refunds apply to the **entire invoice**. Partial refunds and partial purchase receipts are not included. Refund/void returns all sold units once. The original invoice remains available for audit and printing.

- Reports exclude refunded/voided sales from the original sale period; they do not post a separate cash refund in the refund-date period. Net profit follows this operational reporting model, rather than a general ledger or statutory tax-return model.

- Stock adjustments affect inventory quantity/valuation. Record write-off expenses separately when needed for profit reporting. No payment gateway or electronic tax-authority submission is involved.

- Product/category report filters select whole invoices containing a matching item, as stated above the report. Customer filters affect sales; current inventory reports are as-of-now. Periods longer than 180 days automatically use monthly charts if daily grouping was selected.

- Empty screens display genuine empty states. Dashboard values, charts, counts, and alerts come from stored records; no fabricated growth percentages are displayed.



## Users and roles



| Role | Permissions |

|---|---|

| Admin | All modules, users, settings, backup/restore and audit log |

| Manager | Catalog, stock, purchasing, sales, edits/refunds/voids, expenses and reports |

| Cashier | View operational pages, create sales, and add/edit customers |



Only administrators manage accounts. Users may change their own password with their current password. Account changes invalidate that user's sessions; restores invalidate all sessions. Passwords use Werkzeug's scrypt hashing. Forms use CSRF protection, login attempts are throttled, and idle sessions expire after the configured interval. Deletion of financial history is deliberately implemented as voiding with an audit record.



## Dual backup and restore

The backup module now writes concurrent verified copies to configurable Primary and Secondary destinations. Defaults are `backups/` and `backups-secondary/` in this installation. Configure separate drives in Settings for independent disk protection.

Live backup, daily scheduling, ZIP compression and integrity verification are enabled by default, with unlimited retention of every copy in each location. Backup Now runs asynchronously and reports each destination separately. Restore from either folder requires administrator password confirmation and `RESTORE`. A dedicated recovery page supports damaged databases.

See [BACKUPS.md](BACKUPS.md) for setup, schedules, retention, restore and emergency recovery details, archive limits, and upgrade instructions.

Stop StorePro before running maintenance commands:

```powershell
.venv\Scripts\python.exe manage.py backup
.venv\Scripts\python.exe manage.py schema
```

## Optional demo data



The live application starts empty. To explore a populated example, create a separate copy of the application, create an administrator account in that copy, stop its server, and run:



```powershell

.venv\Scripts\python.exe manage.py demo --confirm-demo

```



Restart the application. Demo loading is refused if products or transactions already exist. Sample product thumbnails were extracted from the user-supplied design reference. The demo loader creates example records; it is never executed during ordinary startup.



## Project layout



```text

store-app/

  app.py                  Application factory and local Waitress entry point

  manage.py               Backup/schema/demo maintenance commands

  run.bat                 Offline Windows setup and launch

  requirements.txt        Direct runtime dependencies

  requirements-lock.txt   Exact runtime dependency versions

  requirements-dev.txt    Test dependencies

  schema.sql              SQLite DDL matching the SQLAlchemy models

  models/                 Database models and constraints

  routes/                 Authentication, catalog, transactions, reports, settings

  services/               Stock/accounting logic, analytics, backup, translations

  templates/              Jinja2 templates for every module

  static/css/             Responsive light/dark/RTL styling

  static/js/              Charts, barcode input, sale calculations, printing

  static/images/          Logo and optional demo reference assets

  static/uploads/         Validated uploaded PNG images

  static/vendor/          Local frontend libraries, fonts and license notices

  wheels/                 Offline Python packages for Windows x64 / Python 3.13

  tests/                  Automated integration and transaction tests

  backups/                Generated StorePro backup ZIP files

  instance/               Created at runtime: SQLite database, secret, logs, lock

```



`schema.sql` is a reference and provisioning artifact; startup creates an empty database automatically. Do not run the schema file against an existing store. Keep the application in a writable local folder rather than a network share or a synchronized multi-user database location.



## Verification and development



The app uses Waitress for Windows serving, following the [Flask deployment documentation](https://flask.palletsprojects.com/en/stable/deploying/waitress/). The Flask debug server is not used by the launcher.

For the Linux/Render deployment (Gunicorn, persistent disk, HTTPS settings and migration steps), see [`RENDER_DEPLOYMENT.md`](RENDER_DEPLOYMENT.md).



```powershell

py -3.13 -m venv .venv

.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

.venv\Scripts\python.exe -m pytest tests -q

```



Tests cover page rendering, VAT rounding, stock changes, overselling, concurrent sales of the last unit, multi-item rollback, duplicate submissions, edit conflicts, invoice snapshots, refunds, purchase receipt/cancellation, role enforcement, valid and missing CSRF tokens, session invalidation/expiry, upload validation, backup/restore, invalid ZIPs, reporting, exports, Arabic layouts, demo loading, and external-asset independence.



Tests never use the store's database. Every test runs on its own temporary database, and `tests/conftest.py` makes any attempt to open `instance\store.db` (or a database named by `STOREPRO_DATABASE_URI`) fail the test. Tests that need real users, such as the `reset_users.bat` check, read a private copy.

Changing financial rules or models should be followed by integration tests and a backup/restore rehearsal with non-production data. Schema changes use explicit, idempotent migrations in services/migrations.py; existing business rows are preserved.



## Troubleshooting



- **Python missing:** install Python 3.13 x64 with the launcher, then rerun `run.bat`.

- **Port 5000 in use:** stop the other StorePro window. To use another port, set `STOREPRO_PORT=5001` before running the application and open the matching local URL.

- **Cannot write database:** extract the app into a folder where your Windows account has write access.

- **Expired form:** reload the form and submit again. Use the browser Back button to recover entered values after a validation message.

- **Unexpected error:** inspect `instance/application.log`; failed database operations roll back.

- **No chart data:** check the date range and whether sales are completed or orders are cancelled.



See `THIRD_PARTY_NOTICES.md` for included library and asset information.



## New Sale POS update



New Sale uses asynchronous product and customer searches, lazy-loaded product images, merged item lines, stock-aware quantity controls, fixed-amount line discounts, an invoice discount, a sticky checkout summary, and a live receipt preview. Search results show the current available stock and selling price. The server validates stock, prices, VAT, and exact payment allocation again before committing the transaction.



- F2: new customer; F3: product search; F4: invoice discount; F7: split payment; F8: save; Escape: close the active picker/modal, or cancel the invoice.

- Enter-terminated keyboard-wedge barcode scanners add products directly and merge repeat scans. Scanner detection uses rapid keystrokes outside modal forms; slow entry also works in the product search field followed by Enter.

- Frequently/recently sold shortcuts use completed invoices in the last 90 days.

- Split payments record amounts against Cash, Visa, Mastercard, Bank Transfer, or Wallet. Their sum must equal the grand total; no payment processor is contacted. Refunds retain the original allocations for audit.

- Discounts are amounts in the store currency. A line discount applies to the whole line, not each unit. Unit prices remain the store's authoritative selling prices. Profit excludes collected VAT and uses recorded product costs.

- Unsaved invoices are written to this browser's localStorage every ten seconds and on navigation/refresh. Drafts are scoped to the current user and invoice; drafts older than 24 hours are not restored. Another tab changing the same draft pauses autosaving in the current tab. Saving or discarding an invoice clears its draft. Drafts are not part of a database backup.

- A committed invoice whose confirmation was interrupted is recovered by its request token, including after stock has sold out. Stale invoice-edit drafts cannot overwrite a newer invoice revision.

- Product stock is refreshed while the POS is actively used; background polling stops after one minute without interaction so it does not continually extend an idle login session.



### Updating an existing installation



Stop StorePro, extract the files in `StorePro-POS-Update.zip` over the existing `store-app` folder, then run `run.bat`. Keep the existing `instance`, `static/uploads`, and `backups` folders. The update package contains no store database, credentials, or uploaded media. On startup, an existing pre-POS database is backed up beside the live database as `pre-pos-<timestamp>.sqlite3`, then upgraded transactionally. Existing invoice totals and payment labels are preserved. The migration adds `sale_items.discount` with a zero default and a `sale_payments` table. Legacy backups are migrated in staging before restore validation.



New POS invoices reopen in the POS editor for managers/admins. Legacy invoices retain their existing editor. Existing Card and Mobile Wallet filters include their new Visa/Mastercard and Wallet equivalents, including matching split allocations. Printed invoices show recorded payment allocations.



POS routes: `GET /api/pos/products`, `GET /api/pos/shortcuts`, `GET /api/pos/customers`, `POST /api/pos/customers`, `POST /api/pos/quote`, and `POST /api/pos/sales`. Write requests require the current session and CSRF token. All JSON monetary fields are integer minor units; VAT rates are basis points (1400 = 14%).



## Product price tracking



Every saved selling-price or cost-price change now appends a PriceHistory record, including weighted-average cost changes caused by receiving purchases. Records capture product ID/name, old/new cost and selling prices, signed amounts/percentages, user ID/name, currency, source, and UTC timestamp. The SQLAlchemy update listener inserts the record in the same transaction as the product update; a failed update rolls both back. SQLite triggers reject history UPDATE and DELETE operations. Product/user renames do not rewrite snapshots. Direct external edits to the SQLite product table are unsupported; use StorePro's product and purchase workflows.



Products → select a product → Price Tracking shows current/lowest/highest/average selling prices, a Chart.js selling/cost trend for the last 30 changes, newest-first history, and Excel/PDF downloads for managers/admins. History loads ten rows at a time. Product rows show direction, percentage, and the last signed amount with its relative date. A cost-only change is marked Cost Price.



The average is the arithmetic mean of the first recorded old selling price and every recorded new selling-price observation, including cost-only changes; it is not time-weighted. Existing stores start with no fabricated history. Before the first change, all analytics cards show the current price and the chart displays an empty state. Percentage change from a zero old value is undefined and displayed as N/A, rather than an invented percentage. Amounts remain exact integer piastres; percentages are stored to four decimal places and displayed to two.



Alerts are enabled by default and can be switched on/off per product by an admin or manager. The warning applies when the latest selling or cost change exceeds 20% in either direction, using the unrounded amounts for comparison. Exactly 20% does not trigger it. A zero starting price has no percentage comparison.



Price-history timestamps always use Cairo time and DD/MM/YYYY HH:mm, independently of other date preferences. EGP is shown with ج.م. Stores already using another currency keep their actual currency; existing amounts are never relabeled or converted.



### Apply this update



Stop StorePro, copy the contents of StorePro-Price-Tracking-Update.zip over the existing installation, and start run.bat. On this workspace the source files have already been updated. If an old server is running, double-click restart.bat; it stops only an app.py process running from this installation's virtual environment, then launches StorePro again. Finish active work before restarting.



On the first startup after the update, the existing SQLite file receives a pre-prices-<timestamp>.sqlite3 recovery copy beside it, followed by an additive transaction that creates price_history and products.price_alerts. Existing prices and transactions are unchanged. Older backups are upgraded in staging before restore. Only the two known append-only protection triggers are permitted in backup validation; other triggers/views remain rejected. Restoring a backup restores the price history to that backup's point in time.



New routes:

- GET /api/products/<id>/price-history — authenticated, cursor pagination via before=<history_id>, plus analytics and last-30 chart data. JSON money is in minor units.

- POST /products/<id>/price-alerts — admin/manager, CSRF protected, enabled=0 or enabled=1.

- GET /products/<id>/price-history/export/xlsx or /pdf — admin/manager; all history, newest first.



The existing product edit and purchase receipt routes automatically invoke tracking. No new Python or JavaScript dependency is required. Tests are in tests/test_prices.py.


## Hybrid employee permissions

Open Users → Permissions to assign a role and individual grants or denials. Denials always win, including for administrators. See [PERMISSIONS.md](PERMISSIONS.md) for the editor, configurable role policies, APIs, migration, and access boundaries.

## Next Chip website catalog sync

StorePro can publish selected products to the Next Chip website (`next-chip-storefront/`). StorePro pushes signed snapshots over outbound HTTPS, so the shop PC never accepts incoming connections and the website never opens `instance\store.db`. Only public fields are sent: SKU, web name and description, category, brand, selling price, availability status and photos. Cost, suppliers, barcodes, locations and exact stock stay in the store.

This is Stage 1, catalog only. The website's checkout is still a labelled demo and never creates invoices here.

1. **Configure.** Copy the values from `.env.example` into `instance\web-sync.env`, or into the Windows environment of the account that runs StorePro:
   - `NEXT_CHIP_SYNC_URL`: the website address, `https://` only;
   - `NEXT_CHIP_SYNC_SECRET`: the same secret as on the website, at least 32 characters;
   - `NEXT_CHIP_SYNC_ENABLED=true` when you're ready.

   Restart StorePro.
2. **Choose products.** Open **Settings › Website**, tick the products to show online and save. Use **Web details** for an Arabic or English web name, descriptions and a per-order limit.
3. **Sync.** Press **Sync now**. While StorePro runs, it syncs again every `NEXT_CHIP_SYNC_INTERVAL_MINUTES` (default 15).

The same page shows:
- whether sync is enabled and configured;
- the last success and the last failure, with its reason;
- the number of products published;
- the snapshot version;
- the website's own report (**Check website**).

From a console with StorePro stopped:
- `python manage.py web-sync` runs one sync;
- `--dry-run` checks the snapshot without sending it;
- `--status` shows the current state.

**Upgrade note:** this update adds one new table, `web_listings` (schema version 6). Nothing in your existing data changes. As with earlier updates, StorePro saves a copy of the database (`instance\pre-*.sqlite3`) before upgrading it.

Details are in `next-chip-storefront/STStorePro_INTEGRATION.md`.
