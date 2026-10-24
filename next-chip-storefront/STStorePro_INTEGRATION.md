# StorePro → Next Chip integration

**Status:**

| Stage | State |
| --- | --- |
| Stage 1: catalog synchronization | Implemented and tested end to end in a local environment |
| Stage 2: web order ingestion | Not implemented |

In Stage 1, checkout is a demo: it never creates StorePro invoices or customers, and the storefront says so on every page. No production deployment, hosted database or production secret has been configured as part of this work. Section 9 lists what is still required.

## 1. Architecture and trust boundaries

```
 Shop PC (Windows)                                    Hosting (public)
 ┌──────────────────────────────┐   outbound HTTPS   ┌──────────────────────────────────┐
 │ StorePro (Flask, SQLite)     │ ─────────────────▶ │ Next Chip (Next.js)              │
 │  services/web_catalog_sync.py│   HMAC-signed      │  /api/storepro/catalog-sync      │
 │  Settings › Website          │   snapshots +      │  /api/storepro/media/*           │
 │  manage.py web-sync          │   product images   │  /api/storepro/status            │
 └──────────────────────────────┘                    │        │                         │
        never exposed; no inbound                    │        ▼                         │
        connections are needed                       │  PostgreSQL (catalog_* tables)   │
                                                     │        │                         │
                                                     │  storefront pages, /media/<hash> │
                                                     └──────────────────────────────────┘
```

- **Push, not pull.** StorePro sends data out and the website never connects to StorePro, so the shop PC needs no inbound port, tunnel or public address. The website never opens StorePro's SQLite file.
- **StorePro is authoritative** for product identity and SKU, web names and descriptions, categories and brands, selling price (EGP), availability, public photos and publication status.
- **The website keeps the last good catalog.** If the shop PC goes offline, shoppers keep seeing the last accepted catalog. After `NEXT_CHIP_CATALOG_STALE_MINUTES` (default 120) without a successful sync, every page shows "Prices and availability were last updated … and may have changed". Product pages also show when availability was last updated.
- **The browser never decides money.** Carts send product ids and quantities only; prices, availability and per-order limits come from the synchronized catalog on the server.
- **Secrets stay on servers.** The shared secret lives in StorePro's environment (or `instance/web-sync.env`) and in the website's server environment. It never appears in `NEXT_PUBLIC_*` variables, bundles, responses, logs, the diagnostics page or `web_sync_state.json`.
- **What leaves the store.** The snapshot contains only: SKU, web name and description, category, brand, price, an availability status, a quantity capped at the per-order limit, and public photos. These never leave the store:
  - cost
  - supplier
  - barcode
  - shelf location
  - the minimum-stock threshold
  - exact stock above the cap
  - customer data

## 2. Data mapping

**Publication.** A product is offered online only when an operator ticks it on **Settings › Website** (table `web_listings`) and it is eligible:

- `products.active` is true (not archived);
- price is greater than 0 and at most 10,000,000 EGP;
- it has a category and a SKU.

Products that are ticked but ineligible are skipped, and the reason is shown in the sync warnings.

| Next Chip field | StorePro source | Notes |
| --- | --- | --- |
| `id` | `sp-{products.id}` | Stable forever. Future web orders refer to this id. |
| `sku` | `products.sku` | Unique among published products (case-insensitive). |
| `slug` | `slugify(web name)-{products.id}` | A renamed product keeps its trailing id. Old URLs permanently redirect to the new slug. |
| `name.en` / `name.ar` | `web_listings.name_en` / `name_ar`, else `products.name` | If no Arabic name is set, Arabic pages show the English or StorePro name. |
| `description.en/ar` | `web_listings.description_en/ar` | Optional. Pages hide empty descriptions. |
| `categoryId`, category | `spc-{categories.id}`; `categories.name`, `.description`, `.icon` | The single StorePro name is used in both languages. Lucide icon names map to the storefront's icons, otherwise a generic box. |
| `brandId`, brand | `spb-{slugify(products.brand)}`; `products.brand` | Empty brand → no brand. |
| `price` | `products.price` | Integer piastres. Currency is always `EGP`. |
| `compareAt`, `saleEndsAt` | — | StorePro has no sale prices, so these are sent as `null`. The protocol supports them for later. |
| `availability` | `Product.status` rule | `stock = 0` → `out_of_stock`; `stock ≤ minimum` → `low_stock`; otherwise `in_stock`. |
| `orderableQuantity` | `min(stock, maxPerOrder)` | Exact stock above the cap is never sent. |
| `maxPerOrder` | `web_listings.max_per_order`, else `NEXT_CHIP_SYNC_MAX_PER_ORDER` (default 5) | Range 1–99. |
| `images[]` | `product_images` (primary first), else legacy `products.image` | JPEG/PNG/WebP, at most 5 MB, at most 8 per product. Uploaded as bytes and addressed by SHA-256. A missing or unreadable file is skipped with a warning, and the website shows a placeholder. |
| `createdAt` / `updatedAt` | `products.created_at` / latest of product or listing update | "Newest" sort uses `createdAt`. |

## 3. Website storage (PostgreSQL)

Migration: `db/migrations/0001_synced_catalog.sql`, applied with `npm run db:migrate`. It records progress in `schema_migrations` and is safe to run repeatedly.

| Table | Purpose |
| --- | --- |
| `catalog_products`, `catalog_categories`, `catalog_brands` | The catalog. Rows are never deleted: removed items get `published = false`. |
| `catalog_media` | Product images, keyed by SHA-256 of the bytes. Served at `/media/<hash>.<ext>` with immutable caching. |
| `catalog_snapshots` | One row per accepted or rejected snapshot: id, sequence, completeness, content hash, status. Payloads are not stored. |
| `catalog_sync_state` | Last success, last snapshot, last error. Drives the freshness notice and diagnostics. |
| `catalog_sync_nonces` | Recently used request nonces (replay protection; purged after 15 minutes). |

`COMMERCE_MODE` behaviour:

- `synced`: reads only from these tables. If `DATABASE_URL` is missing, unreachable or not migrated, pages show the "something went wrong" state.
- `demo`: the fixtures under `src/data/demo` are only reachable here.
- Any other value is a configuration error. **There is no fallback to demo products.**

The empty-catalog and stale states are shown explicitly:

- **Empty:** "Catalog coming soon".
- **Stale:** the warning banner.

## 4. Sync API (website side)

All four endpoints require a signed request (§5).

| Endpoint | Body | Answer |
| --- | --- | --- |
| `POST /api/storepro/catalog-sync` | Snapshot JSON (≤ 8 MB, `application/json`) | `200 {status: applied\|unchanged\|duplicate, snapshotId, publishedProducts, unpublishedProducts, missingMedia}` |
| `POST /api/storepro/media/check` | `{hashes: [...]}` (≤ 5000) | `200 {missing: [...]}` |
| `PUT /api/storepro/media/<sha256>` | Image bytes (`image/jpeg\|png\|webp`, ≤ 5 MB) | `201` stored / `200` already present. The SHA-256 and the file signature are verified. |
| `GET /api/storepro/status` | — | Last success, last snapshot and sequence, published count, last error, stale flag, schema version |

The public `GET /api/catalog/status` exposes only freshness (`lastUpdatedAt`, `stale`, `published`). It is used by the storefront banner and shows no errors or ids.

**Snapshot (schema version 1):**

```json
{
  "schemaVersion": 1,
  "source": "storepro",
  "snapshot": { "id": "sp-20261014T211531407Z-2052b749b1d0", "sequence": 1792012531407, "generatedAt": "2026-10-14T21:15:31.407Z", "complete": true },
  "currency": "EGP",
  "categories": [{ "id": "spc-1", "slug": "gaming-1", "name": {"en": "Gaming", "ar": "Gaming"}, "description": {"en": "", "ar": ""}, "icon": "", "sortOrder": 1 }],
  "brands": [{ "id": "spb-logitech", "slug": "logitech", "name": "Logitech" }],
  "products": [{
    "id": "sp-1", "sku": "LGPX2-001", "slug": "logitech-g-pro-x2-1",
    "name": {"en": "Logitech G Pro X2", "ar": "لوجيتك جي برو إكس 2"}, "description": {"en": "…", "ar": "…"},
    "categoryId": "spc-1", "brandId": "spb-logitech", "price": 120000, "compareAt": null, "saleEndsAt": null,
    "availability": "in_stock", "orderableQuantity": 2, "maxPerOrder": 2,
    "images": [{"hash": "<sha256>", "contentType": "image/png", "width": 256, "height": 256}],
    "published": true, "createdAt": "…", "updatedAt": "…"
  }]
}
```

**How a snapshot is applied:**

1. **Validate the whole batch first.** Every field, length and character is checked, along with duplicate SKUs and slugs and references to categories and brands. One malformed record rejects the batch (`422`), and the response names the record by its SKU. Nothing is written.
2. **Apply in one transaction.** The website locks the sync-state row and checks the snapshot id and sequence:
   - Same id and same content → `duplicate` (idempotent redelivery).
   - Same id with different content → `409 snapshot_conflict`.
   - Sequence not newer than the last applied snapshot → `409 stale_snapshot`, and nothing changes.
3. **Complete snapshots** (`complete: true`, which is what StorePro sends) unpublish every product, category and brand they don't list, then upsert the rest. Missing items are treated as removed **only** after the whole complete snapshot has been accepted.
4. **Partial snapshots** (`complete: false`) only touch the records they list. A product with `published: false` is unpublished explicitly. Referenced categories and brands must already be published.
5. **Database conflicts** (for example a published slug collision) roll back the whole transaction (`409 apply_failed`). The last good catalog stays exactly as it was.
6. **Unchanged catalog.** If a complete snapshot matches the last one, the website only refreshes freshness (`unchanged`). Regular scheduled syncs therefore keep the "last updated" time current at almost no cost.

Images are stored as sent. The storefront shows only images whose bytes have arrived, and `missingMedia` tells StorePro what to retry.

## 5. Request signing (format v1)

```
timestamp = Unix seconds                      → header X-NextChip-Timestamp
nonce     = 32 lowercase hex characters       → header X-NextChip-Nonce
canonical = "NEXTCHIP-SYNC-V1\n" + METHOD + "\n" + PATH + "\n" + timestamp + "\n" + nonce + "\n" + hex(SHA-256(body))
signature = "v1=" + hex(HMAC-SHA256(secret, canonical))   → header X-NextChip-Signature
```

- `PATH` is the URL path without the query string (for example `/api/storepro/catalog-sync`). If a reverse proxy rewrites paths, the website must see the same path the publisher signed.
- The website rejects requests whose timestamp is more than 300 seconds from its clock (`401 expired`). Keep both clocks synchronized; Windows time sync is enough.
- Each nonce is accepted once (`409 replay`). Retries use a new nonce and timestamp.
- The check order is: secret configured (`503`), content type (`415`), body size (`413`), signature (`401`), nonce, then validation. Unauthenticated requests never write to the database.

**Rotating the secret without downtime:**

1. Generate a new secret: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
2. On the website, set `NEXT_CHIP_SYNC_SECRET_PREVIOUS=<old>` and `NEXT_CHIP_SYNC_SECRET=<new>`, then restart. The website now accepts both.
3. In StorePro, set `NEXT_CHIP_SYNC_SECRET=<new>` and restart StorePro. Use **Settings › Website › Sync now** to confirm.
4. Remove `NEXT_CHIP_SYNC_SECRET_PREVIOUS` from the website and restart.

If a secret may have leaked, replace both sides immediately and skip the overlap period.

## 6. StorePro publisher

| Part | What it is |
| --- | --- |
| `services/web_catalog_sync.py` | Builds the snapshot (read-only database queries), signs requests, uploads missing images, sends the snapshot, retries and records state. |
| `services/web_listings.py` | Publication rules and the editing service behind the Website page. |
| `routes/website.py` and `templates/settings/website*.html` | **Settings › Website.** See the permissions note below. |
| `models.WebListing` | Table `web_listings`. An additive migration (schema version 6) creates it; see §6.1. |

**Website page permissions:**

| Action | Permission |
| --- | --- |
| View the page and diagnostics | `settings.view` |
| Sync now | `settings.edit` |
| Publication ticks and web details | `products.edit` |

**What the Website page shows:**

- whether sync is enabled;
- the website address (never the secret);
- the last successful sync;
- the last failure and its reason;
- the number of products published;
- the snapshot version;
- whether the last snapshot was complete;
- warnings from the last run;
- the website's own report, via **Check website**.

### 6.1 StorePro schema change

`web_listings` is a new table. It does not alter any existing table:

- `services/migrations.py` adds it with `CREATE TABLE`, and the schema version goes from 5 to 6.
- When StorePro starts with this version, it first saves a copy of the database (`instance/pre-*.sqlite3`), as for every earlier upgrade.
- Restoring an older backup still works: the restore check creates the empty table before comparing schemas.
- Backups made after the upgrade include the table, so restoring them needs this or a newer StorePro version.
- To reverse the change: stop StorePro and drop `web_listings`. No other data refers to it.

### 6.2 Configuration

Configuration comes from environment variables, or from `instance\web-sync.env`; environment variables win. See StorePro's `.env.example`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `NEXT_CHIP_SYNC_ENABLED` | `false` | Master switch for scheduled **and** manual syncs. Production sync stays off until an operator sets this to `true`. |
| `NEXT_CHIP_SYNC_URL` | — | Website origin only, for example `https://shop.example.com`. Must use `https://`; `http://` is accepted only for `localhost` or `127.0.0.1`. |
| `NEXT_CHIP_SYNC_SECRET` | — | Shared secret of at least 32 characters, the same value as on the website. |
| `NEXT_CHIP_SYNC_INTERVAL_MINUTES` | `15` | Scheduled interval (5–1440 minutes). |
| `NEXT_CHIP_SYNC_MAX_PER_ORDER` | `5` | Default per-order cap (1–99). |
| `NEXT_CHIP_SYNC_TIMEOUT_SECONDS` | `20` | Per-request timeout (5–120 seconds). |

`instance\` is excluded from Git and from StorePro backup archives. After restoring onto a new PC, enter the secret again.

### 6.3 Running a sync

| Situation | How |
| --- | --- |
| StorePro is running | **Settings › Website › Sync now** (needs `settings.edit`). Success and failure are both shown and written to the audit log. |
| StorePro is stopped | `python manage.py web-sync`. It uses the same single-instance lock as the other maintenance commands. |
| Check without sending | `python manage.py web-sync --dry-run` builds and checks the snapshot and prints the product, category and image counts. |
| Show status | `python manage.py web-sync --status` shows the configuration (without the secret), the last result and the website's own report. |

**Scheduled syncs:**

- Only the running StorePro server schedules syncs. It already holds the exclusive `instance\server.lock`, so there is exactly one publisher.
- The first scheduled sync runs about 60 seconds after start-up, then every `NEXT_CHIP_SYNC_INTERVAL_MINUTES`.
- No Windows Task Scheduler entry is needed. Disabled means no sync runs.
- The job appears in **Settings › System Telemetry** as `web_catalog_sync`.

### 6.4 Failures and retries

**Network errors.** Timeouts, refused connections, TLS errors and HTTP 429 or 5xx are retried with backoff after 2 s and 4 s (three attempts in total). Each attempt uses a fresh nonce and timestamp. After that, the run is recorded as failed with the last answer, for example "Gave up after 3 attempts. Website unreachable (URLError: …)" or "Gave up after 3 attempts. Website rejected the request (HTTP 503, sync_not_configured): …". The website keeps serving the last good catalog, and the next scheduled run tries again.

**Rejections.**
- `4xx` answers are not retried. The page shows the reason, including the first validation problem with its SKU.
- Redirects are refused: the signed payload is never sent to another host.

**Image uploads.** An image that fails to upload becomes a warning, and the next run retries it.

**Status file.** Results are kept in `instance\web_sync_state.json`, which never contains the secret or the payload. Logs contain the outcome only.

## 7. Local testing

**Website:**

```bash
# PostgreSQL 14+ reachable locally
export COMMERCE_MODE=synced DATABASE_URL=postgres://user:pass@127.0.0.1:5432/nextchip_dev
export NEXT_CHIP_SYNC_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
npm run db:migrate && npm run build && npm start      # http://localhost:3100
```

**StorePro.** Use a copy of the store, never the live `instance\store.db`.

```bat
set NEXT_CHIP_SYNC_ENABLED=true
set NEXT_CHIP_SYNC_URL=http://127.0.0.1:3100
set NEXT_CHIP_SYNC_SECRET=<same secret>
python app.py
```

Then tick products under **Settings › Website** and press **Sync now**.

**Automated tests:**

- Next Chip: `npm test`. The sync tests run the real route handlers and the real migration on an in-process PostgreSQL engine (PGlite), so no server is needed.
- StorePro: `pytest tests/test_web_catalog_sync.py`. These run against an isolated test database and a local fake website that verifies signatures independently.

## 8. Deployment requirements

- **HTTPS only for the website.** Terminate TLS at the host or a reverse proxy, and forward the original path unchanged.
- **Managed PostgreSQL** (version 14 or later recommended), reachable from the website server only. Use `DATABASE_SSL=require` for hosted databases. Run `npm run db:migrate` before the first start and after every upgrade.
- **Server-only variables:** `COMMERCE_MODE=synced`, `DATABASE_URL`, `NEXT_CHIP_SYNC_SECRET` and `SITE_URL`. Build with these set: `COMMERCE_MODE` affects which pages are pre-rendered.
- **Resources:** the website needs Node.js 22.18 or later. Image bytes live in PostgreSQL, so plan database storage at roughly the total size of the published photos.
- **Shop PC:** needs outbound HTTPS to the website and nothing more.

## 9. Known limitations and launch blockers

| Item | Status |
| --- | --- |
| Hosted PostgreSQL, website hosting, domain and TLS | **Not provisioned.** Required for a live sync. |
| Production `NEXT_CHIP_SYNC_SECRET` on both sides | **Not generated or installed.** |
| `NEXT_CHIP_SYNC_ENABLED=true` on the shop PC | **Off by default.** An operator must enable it. |
| Selecting products and writing Arabic and English web names and descriptions | Store work under **Settings › Website**. StorePro holds only one name per product and category. |
| Web order ingestion (Stage 2) | **Not implemented.** Checkout stays a labelled demo, the site stays `noindex`, and no order reaches StorePro. |
| Shipping fees per governorate and payment options | Still the illustrative demo configuration. Needs real rates before orders go live. |
| VAT on web prices | Website shows `products.price`. StorePro adds VAT at invoice time, so whether web prices are VAT-inclusive must be decided before orders go live. |
| Sale prices or promotions from StorePro | Not modelled in StorePro. The website shows no deals for synced products. |
| Contact details and policies | Still "to be confirmed" in `src/content/site.ts`. |
| Image storage | Images are kept in PostgreSQL. A CDN or object store could replace this later without changing the protocol. |
