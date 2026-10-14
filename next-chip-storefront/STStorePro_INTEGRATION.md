# StorePro ↔ Next Chip storefront: integration contract

**Status: not implemented.** This document describes the API the storefront expects StorePro to expose. StorePro doesn't have this API yet. Until it does, the storefront runs in demo mode (`COMMERCE_MODE=demo`), and `COMMERCE_MODE=storepro` deliberately fails every call with `ProviderUnavailableError`. Nothing here claims an integration exists.

## 1. Ground rules

1. **No direct database access.** The storefront must never open StorePro's SQLite file, mount it, or copy it. Every read and write goes through an HTTP API that StorePro owns, so StorePro keeps its locking (`DB_LOCK`), RBAC, audit log and backup guarantees.
2. **Don't expose the dashboard.** The StorePro admin UI and its development port stay private. Publish a separate, narrow API surface:
   - its own blueprint, under `/api/storefront/v1`;
   - behind a reverse proxy;
   - reachable only from the storefront server, by IP allow-list or a private network.
3. **Server to server only.** The storefront calls StorePro from its own server, in route handlers and server components. Browsers never talk to StorePro, and credentials never reach the browser:
   - `STOREPRO_API_URL` and `STOREPRO_API_TOKEN` are server-only environment variables;
   - never use a `NEXT_PUBLIC_` prefix for them.
4. **StorePro is authoritative.** Prices, stock, shipping fees and order totals come from StorePro. The storefront re-prices every cart on the server, and StorePro must re-price again when it creates the order. A total sent by the storefront is a cross-check, never an input.
5. **Money is integer piastres** (1 EGP = 100), the same unit StorePro already stores. No floats cross the boundary.

## 2. Authentication

- `Authorization: Bearer <STOREPRO_API_TOKEN>` on every request.
- StorePro issues the token, stores only a hash, and lets an owner rotate or revoke it.
- The token is scoped to the storefront endpoints. It is not a user session and must not grant any dashboard permission.
- Use TLS end to end. Requests time out after `STOREPRO_API_TIMEOUT_MS` (default 8000 ms), and the storefront shows its "store temporarily unavailable" state.
- Optional hardening: sign requests with HMAC (`X-Signature: sha256=…` over method + path + body + timestamp) and reject timestamps more than 5 minutes off.

## 3. Endpoints → provider mapping

The storefront's provider interfaces are in `src/lib/commerce/providers.ts`. Each one maps to endpoints below. Responses are JSON; localized text is `{ "en": "...", "ar": "..." }`.

| Provider method | Endpoint | Notes |
| --- | --- | --- |
| `CatalogProvider.listProducts()` | `GET /api/storefront/v1/products` | Only `active` products flagged for web. Paginate with `?cursor=` if the catalog grows. |
| `CatalogProvider.getProductBySlug(slug)` | `GET /products/by-slug/{slug}` | 404 → storefront 404 |
| `CatalogProvider.getProductsByIds(ids)` | `GET /products?ids=a,b,c` | Unknown ids are simply missing from the response |
| `CategoryProvider.listCategories()` / `getCategory(slug)` / `listBrands()` | `GET /categories`, `GET /categories/{slug}`, `GET /brands` | Maps StorePro `categories` and `products.brand` |
| `PricingProvider.getPrices(ids)` | `GET /prices?ids=` | `{ productId, currency: "EGP", amount, compareAt?, saleEndsAt? }` |
| `AvailabilityProvider.getAvailability(ids)` | `GET /availability?ids=` | `{ productId, status, quantity }` (see §4) |
| `ShippingQuoteProvider.listGovernorates()` / `listZones()` | `GET /shipping/governorates`, `GET /shipping/zones` | |
| `ShippingQuoteProvider.quote(input)` | `POST /shipping/quote` `{ governorate, itemCount, subtotal }` | Returns `{ governorate, zoneId, fee, demo: false }`, or 422 `shipping_unavailable` |
| `PaymentProvider.listMethods()` | `GET /payment-methods` | Only methods StorePro can actually settle |
| `PromotionProvider.listPromotions()` | `GET /promotions` | The storefront shows a promotion only inside its window and while one of its products really has a valid sale price |
| `OrderProvider.createOrder(req)` | `POST /orders` (see §5) | Idempotent on `requestId` |
| `OrderProvider.getOrder(id)` | `GET /orders/{id}?token=…` | Must require an order access token (see §5.4) |

Implement these in `src/lib/commerce/storepro/providers.ts`, replacing the throwing stub. Nothing else in the storefront needs to change.

## 4. Field mapping

| Storefront | StorePro | Notes |
| --- | --- | --- |
| `Product.sku` | `products.sku` | **The join key.** Unique in StorePro. |
| `Product.id` | stable storefront id, or `sp-{products.id}` | Never reuse ids |
| `Product.slug` | new column or mapping table | URL-safe, stable once published |
| `Product.name`, `summary`, `description`, `specs`, `keywords` | `products.name` plus new web-content fields | StorePro has no Arabic/English content fields today (open decision) |
| `Product.images[]` | `product_images` (ordered, `is_primary` first) | Serve from an https media host listed in `NEXT_PUBLIC_IMAGE_HOSTS` |
| `Product.maxPerOrder` | new field, or a store-wide setting | |
| `Price.amount` | `products.price` | Piastres |
| `Price.compareAt`, `saleEndsAt` | `price_history` or a new sale table | A sale counts only while `amount < compareAt` and it hasn't ended |
| `Availability.quantity` | `products.stock` minus open web reservations | |
| `Availability.status` | from `products.status`: `In Stock` → `in_stock`, `Low Stock` → `low_stock`, `Out of Stock` → `out_of_stock`, `active = false` → `discontinued` | |
| `Category.slug` / `name` | `categories` | Needs `slug` and Arabic names |
| Governorate ids | `shipping_orders.governorate` | Use the same ids as `src/data/demo/catalog-meta.ts` (`cairo`, `giza`, …) |

## 5. Orders

### 5.1 Request

```http
POST /api/storefront/v1/orders
Authorization: Bearer …
Idempotency-Key: <requestId>
Content-Type: application/json

{
  "requestId": "3f2a…(16–64 chars)",
  "customer": { "name": "…", "phone": "01012345678", "governorate": "cairo", "city": "…", "address": "…", "notes": "…" },
  "lines": [{ "sku": "VTK-V1A-BLK", "quantity": 2 }],
  "paymentMethod": "cod",
  "expected": { "subtotal": 759800, "discount": 100000, "shipping": 6000, "total": 665800 }
}
```

StorePro must:

1. **Re-price** every line from its own data and **re-check stock** under `DB_LOCK`.
2. Compute the shipping fee for the governorate with the same rule the quote endpoint uses.
3. Compare its result with `expected`. On any mismatch, answer `409 { "reason": "repriced", "quote": … }` and create nothing. The storefront then shows "Some items changed. Review your cart".
4. Create the sale and shipment the way the POS does, so reports, invoices and refunds behave the same.
5. Record the channel (`web`) and `requestId` on the order.

The totals must match StorePro's invoice formula:

> **invoice total = (subtotal − discount) + VAT on products + shipping fee**, with **no VAT on the shipping fee**.
>
> The fee is stored on the shipment (`shipping_orders.shipping_cost`) and billed on the invoice. A partial refund keeps the fee; a full refund returns it.

### 5.2 Idempotency

- Same `requestId` with the same payload: return the original order (`200`).
- Same `requestId` with a different payload: `409 idempotency_conflict`.

The storefront generates a new `requestId` whenever the cart changes. It reuses the key when retrying after a network error, so a lost response never creates a duplicate order.

### 5.3 Response and status

`201 { "id": "WEB-000123", "status": "pending", "createdAt": "…", "accessToken": "…", "lines": […], "totals": { … } }`

| StorePro state | Storefront `OrderStatus` | Shown to the shopper |
| --- | --- | --- |
| Created, awaiting staff confirmation | `pending` | "Order received — awaiting confirmation" |
| Confirmed by staff | `confirmed` | "Order confirmed" |
| Rejected or cancelled | `failed` | "Order not accepted. Nothing will be charged or shipped" |

The storefront shows success only after this `201`. It never says "placed" or "on its way" for a demo order (`demo: true`).

### 5.4 Order lookup privacy

The confirmation page shows the customer's name, phone and address, so the order id alone must not unlock it:

- `POST /orders` returns an `accessToken`.
- The storefront keeps that token in an httpOnly cookie or in the confirmation URL.
- `GET /orders/{id}` requires the token.

Demo orders mitigate the same risk with an unguessable random suffix.

### 5.5 Stock reservation

Choose one of these (open decision):

- **(a)** Decrement stock when the order is created, and restore it on rejection or cancellation.
- **(b)** Reserve stock for N minutes, and decrement it on staff confirmation.

Either way, availability returned to the storefront must subtract open reservations.

## 6. Errors

| HTTP | Body `error` / `reason` | Storefront behaviour |
| --- | --- | --- |
| 401 / 403 | `unauthorized` | Logged on the server; shopper sees "store temporarily unavailable" |
| 404 | `not_found` | 404 page |
| 409 | `repriced`, `insufficient_stock`, `idempotency_conflict` | Cart re-quoted; shopper asked to review the cart |
| 422 | `invalid` (with field errors), `shipping_unavailable` | Field errors shown inline |
| 429 / 5xx / timeout | — | "Store temporarily unavailable"; checkout form keeps its data; nothing shown as placed |

Never echo internal error text, SQL, or stack traces in API responses.

## 7. Caching

- Catalog, category and product pages render per request (`connection()`), so prices and stock are never stale. Once the API exists, short server-side caching (for example 30–60 s, tagged per product and revalidated by a StorePro webhook) can be added in the provider layer.
- Cart quotes and orders are never cached.

## 8. Open decisions for Next Chip / StorePro owners

1. **VAT on web prices.** StorePro adds VAT on products at invoice time (`settings.tax_rate`). Should web prices be shown VAT-inclusive? If so, quotes must include VAT and §5.1 needs a `tax` field.
2. **Bilingual product content.** Where to store Arabic and English names, descriptions, specs and slugs: new StorePro columns, or a storefront CMS keyed by SKU.
3. **Which products are published on the web,** and the per-order limits.
4. **Stock reservation strategy** (§5.5).
5. **Shipping zones and fees per governorate.** The demo rates in `src/data/demo/catalog-meta.ts` are illustrative only.
6. **Payment gateway** (card or wallet). Not enabled until credentials, webhooks and reconciliation are agreed. Cash on delivery maps to StorePro's existing payment flow.
7. **Customer accounts** (sign-in and order history) and how they map to StorePro `customers`.
8. **Contact details and policies** (delivery times, returns, warranty). These are configured in `src/content/site.ts` and currently "to be confirmed".

## 9. Go-live checklist

- [ ] StorePro API implemented with the endpoints above, behind the token, and not publicly exposed beyond the storefront.
- [ ] `src/lib/commerce/storepro/providers.ts` implemented; contract tests run against a StorePro test instance with an **isolated database** (never the live store).
- [ ] `COMMERCE_MODE=storepro` and `STOREPRO_API_*` set on the server only; site rebuilt.
- [ ] End-to-end test: quote → order → staff confirmation in StorePro → invoice total equals the storefront total, including the shipping fee.
- [ ] Demo banner gone (it hides automatically in `storepro` mode); `robots.txt` allows indexing.
- [ ] `src/content/site.ts` filled in with confirmed contact details and policies.
