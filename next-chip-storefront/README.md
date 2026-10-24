# Next Chip — storefront

The public online store for Next Chip (gaming mice, mousepads, skates, keyboards, audio, microphones, cables), in Arabic (RTL) and English (LTR).

StorePro stays the back office for inventory, prices and orders. This app never touches StorePro's database. It talks to commerce data only through provider interfaces, in one of two modes:

- **`demo`** (default): sample products from local fixtures, for development, tests and previews.
- **`synced`**: the real catalog that StorePro pushes to this site. StorePro sends HMAC-signed snapshots over outbound HTTPS, and they are stored in PostgreSQL. This is **Stage 1**: checkout, shipping rates and payment options are still demo, so no order reaches StorePro. Every page says so.

Architecture, data mapping, signing format and operations are in [`STStorePro_INTEGRATION.md`](./STStorePro_INTEGRATION.md).

> **Demo mode is honest.** Every page shows a "Demo" banner. Products, prices, stock and shipping rates are samples. Product images are generated illustrations marked "DEMO RENDER". Checkout creates a demo order in server memory only: nothing is charged, nothing is sent to StorePro, nothing is shipped, and the confirmation page says so. Search engines are told not to index the site (`robots.txt` disallows everything and pages send `noindex`).

## Requirements

- Node.js ≥ 22.18 (developed on Node 22.22). The `db:migrate` script relies on Node's built-in TypeScript support.
- npm
- PostgreSQL 14+ for `synced` mode only. Demo mode needs no database.

Fonts are bundled through `@fontsource`, so nothing loads from a CDN.

## Setup and run

```bash
cd next-chip-storefront
npm install --no-audit --no-fund --legacy-peer-deps
cp .env.example .env.local        # optional; the defaults run the demo

npm run dev                       # http://localhost:3100 (hot reload)
# or a production build:
npm run build && npm start        # http://localhost:3100
```

To run the synchronized catalog locally:

```bash
export COMMERCE_MODE=synced DATABASE_URL=postgres://user:pass@127.0.0.1:5432/nextchip_dev NEXT_CHIP_SYNC_SECRET=<32+ chars>
npm run db:migrate && npm run build && npm start
```

Then configure StorePro to publish to `http://127.0.0.1:3100` (see the integration doc, §7). Until StorePro sends its first snapshot, the home page says "Catalog coming soon". It never falls back to sample products.

`/` redirects to `/en` or `/ar`. It uses the `NEXT_LOCALE` cookie first, then the browser's `Accept-Language`, then English.

| Script | What it does |
| --- | --- |
| `npm run dev` | Development server on port 3100 |
| `npm run build` / `npm start` | Production build / server on port 3100 |
| `npm run typecheck` | `next typegen` + `tsc --noEmit` |
| `npm test` | Unit and integration tests (Vitest; sync tests use an in-process PostgreSQL engine) |
| `npm run db:migrate` | Apply `db/migrations/*.sql` to `DATABASE_URL` (safe to repeat) |
| `npm run art` | Regenerates the demo product SVGs in `public/images/products/` |

## Environment

See [`.env.example`](./.env.example).

| Variable | Default | Notes |
| --- | --- | --- |
| `COMMERCE_MODE` | `demo` | `demo` or `synced`. Any other value is a configuration error (pages show the "something went wrong" state, never demo data). Read at build time as well as run time: rebuild after changing it. |
| `SITE_URL` | `http://localhost:3100` | Canonical URLs, sitemap, structured data |
| `DATABASE_URL` | — | `synced` only. PostgreSQL connection string. **Server-side only.** |
| `DATABASE_SSL`, `DATABASE_POOL_MAX` | — / `5` | `require` verifies the database's TLS certificate. |
| `NEXT_CHIP_SYNC_SECRET` | — | HMAC secret shared with StorePro (32+ characters). **Server-side only.** The sync endpoints answer `503` until it is set. |
| `NEXT_CHIP_SYNC_SECRET_PREVIOUS` | — | Second accepted secret, used only during rotation. |
| `NEXT_CHIP_CATALOG_STALE_MINUTES` | `120` | After this long without a successful sync, shoppers see a "may have changed" notice. |
| `NEXT_CHIP_SYNC_MAX_BYTES` | 8 MB | Largest accepted snapshot body. |
| `NEXT_CHIP_ALLOW_INDEXING` | `false` | `synced` only. Lets search engines index the site; keep it off while checkout is a demo. |
| `NEXT_PUBLIC_IMAGE_HOSTS` | *(empty)* | Comma-separated https hosts allowed for remote product images. Synced photos are served from `/media/` and need no entry. Every other remote URL falls back to a placeholder. |

## What's in the box

**Pages** (all under `/en/…` and `/ar/…`):

- Home: hero, category tiles, valid promotions only, featured / new arrivals / best sellers, and a service strip built from configured data.
- Catalog (`/products`), category pages (`/categories/[slug]`), search (`/search?q=`) and deals (`/products?sale=1`):
  - Grid and list views.
  - Category, brand, price, in-stock and on-sale filters.
  - Sorting and pagination.
  - Everything lives in the URL, so Back and Forward restore it.
  - On phones and tablets, filters open in a drawer.
- Product page: gallery with thumbnails, a full-screen lightbox (arrows and swipe follow the reading direction, zoom), price that shows a sale only while it is valid, stock message, SKU, specs, a quantity stepper capped by stock and the per-order limit, wishlist, related products, and JSON-LD for `Product` and `BreadcrumbList`.
- Cart:
  - Prices come from the server.
  - Shows stock and per-order problems with one-click fixes.
  - Choosing a governorate shows the shipping fee.
  - Total = subtotal − sale discounts + shipping.
- Checkout:
  - Fields: name, Egyptian mobile (Arabic digits accepted), governorate, city, address, notes.
  - Cash on delivery is the only method enabled in the demo.
  - Field-level errors, guarded against double submit, idempotent on the server, with clear failure states.
- Order confirmation, account (demo orders placed from this browser), wishlist.
- About, contact, shipping policy (fee table from the shipping provider), returns, privacy, terms.
- Localized 404 and error pages.

**Business facts are never invented.** Phone, WhatsApp, email, address, hours, delivery times, return window, refund method and warranty live in [`src/content/site.ts`](./src/content/site.ts). They are all `null` for now and show as "To be confirmed by Next Chip". Fill them in there.

## Architecture

```
src/
  app/[locale]/…           pages (server components); app/api/… route handlers
  proxy.ts                 locale redirect + NEXT_LOCALE cookie
  lib/commerce/
    types.ts               domain types (money = integer piastres, like StorePro)
    providers.ts           Catalog/Category/Pricing/Availability/ShippingQuote/Payment/Promotion/Order provider interfaces
    demo/providers.ts      demo implementation over fixtures (in-memory orders)
    synced/providers.ts    catalog from the synchronized PostgreSQL tables (Stage 1: shipping/orders still demo)
  lib/catalog-db/          PostgreSQL access, migrations runner, catalog store (snapshot apply + reads)
  lib/sync/                snapshot protocol + validation, HMAC signing, request guard, handlers
  app/api/storepro/…       signed StorePro endpoints: catalog-sync, media/check, media/[hash], status
  app/media/[file]         public product photos by content hash
  db/migrations/           SQL migrations (npm run db:migrate)
    service.ts             use-cases: catalog query, home, cart quote, place order
    catalog-query.ts, cart-math.ts, pricing.ts, checkout-validation.ts, money.ts, safe-image.ts
  data/demo/               the only place demo data lives (products.json, catalog-meta.ts)
  content/site.ts          configurable store facts (contact, policies)
  i18n/                    en/ar dictionaries (type-checked to match), plural rules, formatters
  components/              server components + client/ (interactive pieces)
  lib/client/              browser store (cart/wishlist/governorate in localStorage), hooks
  styles/                  tokens.css → base → components → layout → pages
```

Trust boundaries:

- **The browser never decides money.** Cart lines sent to the server are only `{ productId, quantity }`. `/api/cart/quote` and `/api/checkout` re-price everything from the providers. Any price or total in a request body is ignored, and a test asserts the checkout request contains only customer details, lines, the payment method and an idempotency key.
- `/api/checkout` refuses cross-origin and non-JSON requests and caps the body size. Order ids are unguessable (`DEMO-1001-3fa9c2d1`).
- A success screen appears only after the provider returns `201`. Network or server errors keep the form filled and say that nothing was placed.
- Security headers: CSP (`self` only; no third-party script, style, font or image sources), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy` and `Permissions-Policy`. Product image URLs pass through `safeImageSrc` (local `/images/…`, synced `/media/<sha256>.<ext>`, or allow-listed https hosts only). JSON-LD escapes `<`.
- **StorePro sync endpoints.**
  - Every request is authenticated with HMAC-SHA256 over method, path, timestamp, nonce and body hash, within a ±5-minute window, and each nonce is accepted once.
  - The whole snapshot is validated before anything is written, then applied in one database transaction. A bad batch never replaces the last good catalog.
  - Nothing is deleted; products StorePro stops publishing are unpublished.
  - Exact stock levels are never sent: StorePro sends an availability status and a quantity capped at the per-order limit.

## Design system

The look is dark charcoal surfaces with one restrained electric-lime accent (`--accent: #b8f53b`), used for primary actions, prices on sale and focus rings. Tokens live in [`src/styles/tokens.css`](./src/styles/tokens.css):

| Token group | Contents |
| --- | --- |
| Surfaces | `--bg`, `--surface`, `--surface-2/3`, `--line` |
| Text | `--text`, `--text-2`, `--muted` |
| Status | `--success`, `--warning`, `--danger` |
| Type | Space Grotesk for display and Inter for body in English; IBM Plex Sans Arabic for both in Arabic, with a fluid scale (`--fs-*`) |
| Spacing and shape | 4px spacing scale, radii, shadows |
| Layout | 1280px container, 16/24/32px gutters, 64/72px header |
| Motion | `--dur*` timings, which drop to 0 under `prefers-reduced-motion` |

Components (`components.css`):

- Buttons and icon buttons with counters.
- Form fields with error and hint states, check and radio cards.
- Badges, stock labels and prices.
- Product cards (grid and list), quantity stepper, popover and menu items.
- Native `<dialog>` modals and drawers.
- Toasts, alerts, empty states, skeletons, breadcrumbs, pagination.

Layout uses logical properties (`inset-inline-*`, `margin-inline-*`), so RTL mirrors without overrides. Directional icons carry `.flip-rtl`. Arabic uses Latin digits for prices and counts, as Egyptian stores do. Arabic counts use CLDR plural forms (منتج واحد / منتجان / 5 منتجات / 28 منتجًا).

Interaction rules every component follows:

- Menus and popovers close on Escape (focus goes back to the trigger), on a click outside, and when focus leaves them.
- Dialogs use the native `<dialog>`, which traps focus. They close on Escape or a backdrop click and return focus to their trigger.
- The shop menu and search suggestions support arrow keys, Home and End.
- There is a skip link and every control has a visible focus ring. Primary buttons, icon buttons and steppers are 44px tall; compact controls (chips, small buttons) are at least 32px.

## Tests and verification

```bash
npm test          # 68 tests
npm run typecheck
npm run build
```

The tests in `tests/` cover:

- Catalog filters, search (including Arabic), sorting, pagination and URL parsing.
- Sale validity, promotions, cart math, stock and per-order limits, server-side quotes.
- Checkout validation (Egyptian mobiles, Arabic digits), demo order idempotency, and that client prices are ignored.
- Image URL safety.
- Dictionary parity: every Arabic key present, same placeholders.
- Arabic plurals and digits, catalog URL helpers, and locale negotiation in the proxy.
- **Catalog sync** (`tests/catalog-sync.test.ts`). These run the real route handlers and the real migration on an in-process PostgreSQL engine:
  - Request security: HMAC signing and secret rotation, expired timestamps, replayed nonces, wrong secrets and tampered bodies, unconfigured secret, content type and size limits.
  - Validation: one malformed record rejects the batch.
  - Applying snapshots:
    - complete versus partial snapshots;
    - idempotent redelivery;
    - snapshot id reuse and out-of-order rejection;
    - price updates in place;
    - unpublishing without deletion;
    - rollback on a database conflict;
    - the unchanged fast path refreshing freshness.
  - Media verification and serving.
  - Catalog queries for home, search, categories, product pages and deals.
  - Mode selection with no demo fallback, the stale threshold, and an empty synced catalog.

Browser verification was run against the production build with Playwright and Chromium. It does not ship with the project because it depends on a local browser install.

- A crawl of 14 pages at 1920×1080, 1366×768, 1024×768, 768×1024, 390×844 and 360×800, in both English and Arabic (168 page loads). It checked for horizontal overflow, console errors and CSP violations, broken images, `lang`/`dir` and a single `h1`. Everything was clean apart from the intentional 404 test page.
- 20 end-to-end flows, all passing:
  - Shop menu: keyboard, Escape, click outside.
  - Search: combobox suggestions.
  - Catalog: filters, sort, price, chips, list view, pagination, Back/Forward; empty state and deals.
  - Product page: gallery and lightbox; quantity caps and add to cart; sold-out products and the wishlist.
  - Cart: governorate shipping fees and totals, removing items, the clear-cart confirmation, stock problems, and a failed quote with retry.
  - Checkout validation, then order confirmation and the account page.
  - Checkout double submit (three clicks in one tick plus Enter → one request); network and server failures; a cart that changed before checkout.
  - Language switch keeps the query; skip link; Back from a product page.
  - Mobile drawer, search sheet and filters drawer; RTL drawer sides, lightbox direction and digits.
  - 404 pages.

Screenshots from that run are in [`docs/screenshots/`](./docs/screenshots/).

Synchronized-catalog verification (local PostgreSQL 16 plus an isolated copy of StorePro):

- **End-to-end:** 52 checks pass. StorePro's real **Settings › Website** page publishes products, and its real scheduler runs. The checks cover:
  - images and EGP prices;
  - category mapping;
  - Arabic names and RTL;
  - per-order caps;
  - a price change without duplicate rows;
  - unpublishing and archiving;
  - a rejected invalid snapshot with the last good catalog intact;
  - the stale-catalog warning;
  - a website outage, then recovery;
  - checkout staying demo, with no StorePro invoice or customer created.
- **Crawl:** 10 synced pages at all 6 viewports in English and Arabic (120 page loads), with zero layout, console or image issues.

## Not included (on purpose)

- **Newsletter signup.** There is no backend to store subscriptions, so no form is shown.
- **Real payments.** Card and wallet payments are defined in the payment provider but disabled until a gateway is configured with credentials.
- **Customer sign-in.** The account page explains that accounts will come from StorePro.
