import { readdirSync } from "node:fs";
import { createHash, randomBytes } from "node:crypto";
import { PGlite } from "@electric-sql/pglite";
import { NextRequest } from "next/server";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { POST as syncPOST } from "@/app/api/storepro/catalog-sync/route";
import { POST as mediaCheckPOST } from "@/app/api/storepro/media/check/route";
import { PUT as mediaPUT } from "@/app/api/storepro/media/[hash]/route";
import { GET as statusGET } from "@/app/api/storepro/status/route";
import { GET as publicStatusGET } from "@/app/api/catalog/status/route";
import { GET as mediaGET } from "@/app/media/[file]/route";
import { fromPGlite, type Db } from "@/lib/catalog-db/db";
import { migrate, MIGRATIONS_DIR } from "@/lib/catalog-db/migrate";
import { EXPECTED_SCHEMA_VERSION } from "@/lib/catalog-db/server";
import { createCatalogStore, type CatalogStore } from "@/lib/catalog-db/store";
import { commerceMode, getCommerce } from "@/lib/commerce";
import { ProviderUnavailableError } from "@/lib/commerce/providers";
import { createStorefrontService } from "@/lib/commerce/service";
import { createSyncedCommerce } from "@/lib/commerce/synced/providers";
import { isStale } from "@/lib/freshness";
import { sign, verify } from "@/lib/sync/hmac";
import { validateSnapshot, type SyncProduct, type SyncSnapshot } from "@/lib/sync/protocol";

const SECRET = "test-secret-" + "x".repeat(40);
const PREVIOUS = "previous-secret-" + "y".repeat(40);
const NOW = new Date("2026-10-14T12:00:00Z");
// 1x1 PNG
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64");
const PNG_HASH = createHash("sha256").update(PNG).digest("hex");

let pg: PGlite;
let db: Db;
let store: CatalogStore;
let seq = 1_000;
const g = globalThis as typeof globalThis & { __nextChipCatalog?: unknown };

function product(n: number, over: Partial<SyncProduct> = {}): SyncProduct {
  return {
    id: `sp-${n}`,
    sku: `SKU-${n}`,
    slug: `product-${n}`,
    name: { en: `Product ${n}`, ar: `منتج ${n}` },
    description: { en: `Description ${n}. More text.`, ar: "" },
    categoryId: n % 2 ? "spc-1" : "spc-2",
    brandId: n === 3 ? null : "spb-acme",
    price: 10_000 * n,
    compareAt: null,
    saleEndsAt: null,
    availability: n === 4 ? "out_of_stock" : n === 2 ? "low_stock" : "in_stock",
    orderableQuantity: n === 4 ? 0 : n === 2 ? 2 : 5,
    maxPerOrder: 5,
    images: [],
    published: true,
    createdAt: `2026-0${(n % 9) + 1}-01T00:00:00Z`,
    updatedAt: "2026-10-01T00:00:00Z",
    ...over,
  };
}

function snapshot(products: SyncProduct[], over: Partial<SyncSnapshot["snapshot"]> = {}): SyncSnapshot {
  seq += 1;
  return {
    schemaVersion: 1,
    source: "storepro",
    snapshot: { id: `snap-${seq}-${randomBytes(3).toString("hex")}`, sequence: seq, generatedAt: NOW.toISOString(), complete: true, ...over },
    currency: "EGP",
    categories: [
      { id: "spc-1", slug: "mice-1", name: { en: "Mice", ar: "ماوس" }, description: { en: "", ar: "" }, icon: "mouse", sortOrder: 1 },
      { id: "spc-2", slug: "keyboards-2", name: { en: "Keyboards", ar: "كيبورد" }, description: { en: "", ar: "" }, icon: "gamepad-2", sortOrder: 2 },
    ],
    brands: [{ id: "spb-acme", slug: "acme", name: "Acme" }],
    products,
  };
}

interface SignOpts {
  secret?: string;
  timestamp?: number;
  nonce?: string;
  contentType?: string;
  tamper?: boolean;
}

function signed(method: string, path: string, body: Uint8Array | string, o: SignOpts = {}) {
  const bytes = typeof body === "string" ? Buffer.from(body) : Buffer.from(body);
  const ts = String(o.timestamp ?? Math.floor(Date.now() / 1000));
  const nonce = o.nonce ?? randomBytes(16).toString("hex");
  const headers: Record<string, string> = {
    "x-nextchip-timestamp": ts,
    "x-nextchip-nonce": nonce,
    "x-nextchip-signature": sign(o.secret ?? SECRET, method, path, ts, nonce, bytes),
  };
  if (o.contentType !== "") headers["content-type"] = o.contentType ?? "application/json";
  const sent = o.tamper ? Buffer.from(bytes.toString().replace("Product", "Hacked")) : bytes;
  return new NextRequest(new URL(path, "https://shop.test"), { method, headers, body: method === "GET" ? undefined : sent });
}

async function push(s: SyncSnapshot | object, o: SignOpts = {}) {
  const res = await syncPOST(signed("POST", "/api/storepro/catalog-sync", JSON.stringify(s), o));
  return { status: res.status, body: (await res.json()) as Record<string, unknown> };
}

const count = async (sql: string) => Number((await db.query<{ n: string }>(sql)).rows[0]!.n);
const service = () => createStorefrontService(createSyncedCommerce(store), () => NOW);

beforeAll(async () => {
  pg = new PGlite();
  db = fromPGlite(pg);
  await migrate(db);
  store = createCatalogStore(db);
  g.__nextChipCatalog = { db, store, schemaChecked: true };
  vi.spyOn(console, "info").mockImplementation(() => {});
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterAll(async () => {
  delete g.__nextChipCatalog;
  await pg.close();
});
beforeEach(() => {
  process.env.NEXT_CHIP_SYNC_SECRET = SECRET;
  delete process.env.NEXT_CHIP_SYNC_SECRET_PREVIOUS;
});

describe("schema", () => {
  it("expected schema version is the newest migration", () => {
    const files = readdirSync(MIGRATIONS_DIR).filter((f) => f.endsWith(".sql")).sort();
    expect(files.at(-1)).toBe(`${EXPECTED_SCHEMA_VERSION}.sql`);
  });
  it("migrations are idempotent", async () => {
    expect(await migrate(db)).toEqual([]);
  });
});

describe("HMAC signing", () => {
  const body = Buffer.from('{"a":1}');
  const ts = String(Math.floor(NOW.getTime() / 1000));
  const nonce = "0".repeat(32);
  const headers = (signature: string, t = ts, n = nonce) => ({ timestamp: t, nonce: n, signature });
  const now = Math.floor(NOW.getTime() / 1000);

  it("accepts a correct signature and the previous secret during rotation", () => {
    expect(verify([SECRET], "POST", "/p", headers(sign(SECRET, "POST", "/p", ts, nonce, body)), body, now).ok).toBe(true);
    expect(verify([SECRET, PREVIOUS], "POST", "/p", headers(sign(PREVIOUS, "POST", "/p", ts, nonce, body)), body, now).ok).toBe(true);
  });
  it("rejects wrong secrets, tampered bodies, other paths and methods", () => {
    const good = sign(SECRET, "POST", "/p", ts, nonce, body);
    expect(verify([SECRET], "POST", "/p", headers(sign("z".repeat(40), "POST", "/p", ts, nonce, body)), body, now)).toEqual({ ok: false, reason: "bad_signature" });
    expect(verify([SECRET], "POST", "/p", headers(good), Buffer.from('{"a":2}'), now).ok).toBe(false);
    expect(verify([SECRET], "POST", "/other", headers(good), body, now).ok).toBe(false);
    expect(verify([SECRET], "PUT", "/p", headers(good), body, now).ok).toBe(false);
  });
  it("rejects expired or future timestamps and malformed headers", () => {
    const old = String(now - 301);
    expect(verify([SECRET], "POST", "/p", headers(sign(SECRET, "POST", "/p", old, nonce, body), old), body, now)).toEqual({ ok: false, reason: "expired" });
    const future = String(now + 301);
    expect(verify([SECRET], "POST", "/p", headers(sign(SECRET, "POST", "/p", future, nonce, body), future), body, now)).toEqual({ ok: false, reason: "expired" });
    expect(verify([SECRET], "POST", "/p", { timestamp: null, nonce, signature: "v1=" }, body, now)).toEqual({ ok: false, reason: "missing_headers" });
    expect(verify([SECRET], "POST", "/p", headers(sign(SECRET, "POST", "/p", ts, "nonce", body), ts, "nonce"), body, now)).toEqual({ ok: false, reason: "bad_nonce" });
  });
});

describe("snapshot validation", () => {
  it("accepts a well-formed snapshot", () => {
    expect(validateSnapshot(snapshot([product(1), product(2)])).ok).toBe(true);
  });
  it("rejects the whole batch for one malformed record and names its SKU", () => {
    const r = validateSnapshot(snapshot([product(1), product(2, { price: 0 }), product(3, { slug: "Bad Slug" })]));
    expect(r.ok).toBe(false);
    if (r.ok) return;
    expect(r.issues.some((i) => i.path.includes("sku=SKU-2") && i.path.endsWith(".price"))).toBe(true);
    expect(r.issues.some((i) => i.path.endsWith(".slug"))).toBe(true);
  });
  it("rejects duplicate SKUs/slugs, unknown references, bad versions and stock contradictions", () => {
    const issues = (s: unknown) => (validateSnapshot(s) as { issues?: { message: string }[] }).issues?.map((i) => i.message).join(" | ") ?? "";
    expect(issues(snapshot([product(1), product(2, { sku: "sku-1" })]))).toMatch(/duplicate/);
    expect(issues(snapshot([product(1, { categoryId: "spc-9" })]))).toMatch(/unknown category/);
    expect(issues({ ...snapshot([]), schemaVersion: 2 })).toMatch(/unsupported schema version/);
    expect(issues(snapshot([product(1, { availability: "out_of_stock", orderableQuantity: 3 })]))).toMatch(/must be 0/);
    expect(issues(snapshot([product(1, { compareAt: 5_000 })]))).toMatch(/greater than price/);
  });
});

describe("sync endpoint security", () => {
  it("refuses when no secret is configured", async () => {
    delete process.env.NEXT_CHIP_SYNC_SECRET;
    expect((await push(snapshot([product(1)]))).status).toBe(503);
  });
  it("rejects unsigned, wrongly signed, tampered and expired requests", async () => {
    const unsigned = new NextRequest("https://shop.test/api/storepro/catalog-sync", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
    expect((await syncPOST(unsigned)).status).toBe(401);
    expect((await push(snapshot([product(1)]), { secret: "w".repeat(40) })).status).toBe(401);
    expect((await push(snapshot([product(1)]), { tamper: true })).status).toBe(401);
    const expired = await push(snapshot([product(1)]), { timestamp: Math.floor(Date.now() / 1000) - 600 });
    expect(expired).toMatchObject({ status: 401, body: { error: "expired" } });
    expect(await count("SELECT count(*) AS n FROM catalog_products")).toBe(0);
  });
  it("rejects replayed nonces", async () => {
    const nonce = randomBytes(16).toString("hex");
    const s = snapshot([product(1)]);
    expect((await push(s, { nonce })).status).toBe(200);
    expect(await push(s, { nonce })).toMatchObject({ status: 409, body: { error: "replay" } });
  });
  it("enforces content type and size limits", async () => {
    expect((await push(snapshot([product(1)]), { contentType: "text/plain" })).status).toBe(415);
    process.env.NEXT_CHIP_SYNC_MAX_BYTES = "100";
    try {
      expect((await push(snapshot([product(1)]))).status).toBe(413);
    } finally {
      delete process.env.NEXT_CHIP_SYNC_MAX_BYTES;
    }
  });
  it("rejects malformed JSON without touching the catalog", async () => {
    const before = await count("SELECT count(*) AS n FROM catalog_products WHERE published");
    const res = await syncPOST(signed("POST", "/api/storepro/catalog-sync", "{not json"));
    expect(res.status).toBe(400);
    expect(await count("SELECT count(*) AS n FROM catalog_products WHERE published")).toBe(before);
  });
});

describe("applying snapshots", () => {
  it("publishes a complete snapshot and serves it through the storefront", async () => {
    const r = await push(snapshot([product(1), product(2), product(3), product(4), product(5, { compareAt: 60_000, saleEndsAt: "2026-12-01T00:00:00Z" })]));
    expect(r).toMatchObject({ status: 200, body: { status: "applied", publishedProducts: 5 } });
    const sf = service();
    const all = await sf.queryCatalog({ perPage: 50 });
    expect(all.total).toBe(5);
    expect((await sf.queryCatalog({ category: "keyboards-2" })).items.map((i) => i.id).sort()).toEqual(["sp-2", "sp-4"]);
    expect((await sf.queryCatalog({ q: "SKU-3" })).items.map((i) => i.id)).toEqual(["sp-3"]);
    expect((await sf.queryCatalog({ q: "منتج 5" })).items.map((i) => i.id)).toEqual(["sp-5"]);
    expect((await sf.queryCatalog({ onSale: true })).items.map((i) => i.id)).toEqual(["sp-5"]);
    expect((await sf.queryCatalog({ stock: "in-stock", perPage: 50 })).items.map((i) => i.id)).not.toContain("sp-4");
    const detail = await sf.getProduct("product-1");
    expect(detail?.item).toMatchObject({ sku: "SKU-1", price: { amount: 10_000, currency: "EGP" }, availability: { status: "in_stock", quantity: 5 } });
    expect(detail?.item.category.icon).toBe("mouse");
    expect((await sf.getCategory("keyboards-2"))?.icon).toBe("box"); // unknown StorePro icon → generic
    expect((await sf.getProduct("product-3"))?.item.brand).toBeNull();
    const home = await sf.getHome();
    expect(home.categories.map((c) => [c.slug, c.count])).toEqual([["mice-1", 3], ["keyboards-2", 2]]);
    expect(home.newArrivals.length).toBeGreaterThan(0);
    expect(home.promotions).toEqual([]);
  });

  it("is idempotent: redelivering the same snapshot creates nothing new", async () => {
    const s = snapshot([product(1), product(2), product(3), product(4), product(5)]);
    expect((await push(s)).body.status).toBe("applied");
    const rows = await count("SELECT count(*) AS n FROM catalog_products");
    expect((await push(s)).body.status).toBe("duplicate");
    expect(await count("SELECT count(*) AS n FROM catalog_products")).toBe(rows);
    expect((await push({ ...s, products: [product(1)] })).body).toMatchObject({ error: "snapshot_conflict" });
  });

  it("updates prices in place and refuses out-of-order snapshots", async () => {
    const newer = snapshot([product(1, { price: 12_345 }), product(2), product(3), product(4), product(5)]);
    const older = snapshot([product(1, { price: 1 }), product(2), product(3), product(4), product(5)], { sequence: 5 });
    expect((await push(newer)).body.status).toBe("applied");
    expect((await service().getProduct("product-1"))?.item.price.amount).toBe(12_345);
    expect(await count("SELECT count(*) AS n FROM catalog_products WHERE id = 'sp-1'")).toBe(1);
    expect(await push(older)).toMatchObject({ status: 409, body: { error: "stale_snapshot" } });
    expect((await service().getProduct("product-1"))?.item.price.amount).toBe(12_345);
  });

  it("an unchanged complete snapshot still refreshes freshness", async () => {
    const products = [product(1, { price: 12_345 }), product(2), product(3), product(4), product(5)];
    const before = (await store.syncState()).lastSuccessAt;
    await new Promise((r) => setTimeout(r, 20));
    expect((await push(snapshot(products))).body.status).toBe("unchanged");
    expect(Date.parse((await store.syncState()).lastSuccessAt!)).toBeGreaterThan(Date.parse(before!));
  });

  it("unpublishes products missing from a complete snapshot without deleting them", async () => {
    expect((await push(snapshot([product(1, { price: 12_345 }), product(2), product(3), product(4)]))).body).toMatchObject({ status: "applied", unpublishedProducts: 1 });
    expect(await count("SELECT count(*) AS n FROM catalog_products WHERE id = 'sp-5'")).toBe(1);
    expect(await count("SELECT count(*) AS n FROM catalog_products WHERE id = 'sp-5' AND published")).toBe(0);
    const sf = service();
    expect(await sf.getProduct("product-5")).toBeNull();
    // A cart still holding it cannot buy it.
    const quote = await sf.quoteCart([{ productId: "sp-5", quantity: 1 }]);
    expect(quote.purchasable).toBe(false);
    expect(quote.lines[0]?.issue).toBe("unknown_product");
  });

  it("partial snapshots only touch listed products and can unpublish explicitly", async () => {
    const r = await push(snapshot([product(2, { price: 22_222 }), product(3, { published: false })], { complete: false }));
    expect(r.body).toMatchObject({ status: "applied", unpublishedProducts: 1 });
    const sf = service();
    expect((await sf.getProduct("product-2"))?.item.price.amount).toBe(22_222);
    expect(await sf.getProduct("product-3")).toBeNull();
    expect((await sf.getProduct("product-1"))?.item.price.amount).toBe(12_345); // untouched
  });

  it("an invalid batch leaves the last good catalog intact and records the error", async () => {
    const before = await count("SELECT count(*) AS n FROM catalog_products WHERE published");
    const good = (await store.syncState()).lastSnapshotId;
    const r = await push(snapshot([product(1, { price: -5 }), product(9)]));
    expect(r.status).toBe(422);
    expect(await count("SELECT count(*) AS n FROM catalog_products WHERE published")).toBe(before);
    const state = await store.syncState();
    expect(state.lastSnapshotId).toBe(good);
    expect(state.lastError).toMatch(/Snapshot rejected/);
  });

  it("rolls back a batch that passes validation but conflicts in the database", async () => {
    const before = (await db.query<{ id: string; price: string }>("SELECT id, price FROM catalog_products ORDER BY id")).rows;
    // Partial snapshot: new product takes the published slug of sp-1, and also changes sp-2's price.
    const r = await push(snapshot([product(2, { price: 99_999 }), product(7, { slug: "product-1", sku: "SKU-7" })], { complete: false }));
    expect(r).toMatchObject({ status: 409, body: { error: "apply_failed" } });
    expect((await db.query<{ id: string; price: string }>("SELECT id, price FROM catalog_products ORDER BY id")).rows).toEqual(before);
    expect(await count("SELECT count(*) AS n FROM catalog_products WHERE id = 'sp-7'")).toBe(0);
  });

  it("re-publishes a product when it returns to a complete snapshot", async () => {
    expect((await push(snapshot([product(1), product(2), product(3), product(4), product(5)]))).body.status).toBe("applied");
    expect((await service().getProduct("product-5"))?.item.id).toBe("sp-5");
  });

  it("resolves a renamed product by its trailing StorePro id", async () => {
    expect((await service().getProduct("old-name-5"))?.item.slug).toBe("product-5");
    expect(await service().getProduct("unrelated-slug")).toBeNull();
  });
});

describe("media", () => {
  const put = (hash: string, bytes: Buffer, type = "image/png") =>
    mediaPUT(signed("PUT", `/api/storepro/media/${hash}`, bytes, { contentType: type }), { params: Promise.resolve({ hash }) });

  it("stores verified images idempotently and serves them publicly", async () => {
    const check = await mediaCheckPOST(signed("POST", "/api/storepro/media/check", JSON.stringify({ hashes: [PNG_HASH] })));
    expect(await check.json()).toEqual({ missing: [PNG_HASH] });
    expect((await put("a".repeat(64), PNG)).status).toBe(422); // hash mismatch
    expect((await put(PNG_HASH, PNG, "image/jpeg")).status).toBe(422); // bytes are not JPEG
    expect((await put(PNG_HASH, PNG)).status).toBe(201);
    expect((await put(PNG_HASH, PNG)).status).toBe(200);
    const res = await mediaGET(new NextRequest(`https://shop.test/media/${PNG_HASH}.png`), { params: Promise.resolve({ file: `${PNG_HASH}.png` }) });
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("image/png");
    expect(res.headers.get("cache-control")).toContain("immutable");
    expect(Buffer.from(await res.arrayBuffer()).equals(PNG)).toBe(true);
    const wrongExt = await mediaGET(new NextRequest(`https://shop.test/media/${PNG_HASH}.jpg`), { params: Promise.resolve({ file: `${PNG_HASH}.jpg` }) });
    expect(wrongExt.status).toBe(404);
  });

  it("shows only images whose bytes arrived", async () => {
    const missing = "b".repeat(64);
    const img = (hash: string) => ({ hash, contentType: "image/png" as const, width: 1, height: 1 });
    const r = await push(snapshot([product(1, { images: [img(PNG_HASH), img(missing)] }), product(2), product(3), product(4), product(5)]));
    expect(r.body.missingMedia).toEqual([missing]);
    const images = (await service().getProduct("product-1"))!.item.images;
    expect(images.map((i) => i.src)).toEqual([`/media/${PNG_HASH}.png`]);
  });
});

describe("status, freshness and mode selection", () => {
  it("signed status reports the last snapshot; the public status hides internals", async () => {
    const res = await statusGET(signed("GET", "/api/storepro/status", "", { contentType: "" }));
    const body = (await res.json()) as Record<string, unknown>;
    expect(res.status).toBe(200);
    expect(body).toMatchObject({ schemaVersion: EXPECTED_SCHEMA_VERSION, publishedProducts: 5, stale: false });
    expect((await statusGET(new NextRequest("https://shop.test/api/storepro/status"))).status).toBe(401);
    process.env.COMMERCE_MODE = "synced";
    try {
      const pub = (await (await publicStatusGET()).json()) as Record<string, unknown>;
      expect(pub).toMatchObject({ mode: "synced", available: true, published: true, stale: false });
      expect(Object.keys(pub)).not.toContain("lastError");
      expect(Object.keys(pub)).not.toContain("lastSnapshotId");
    } finally {
      delete process.env.COMMERCE_MODE;
    }
  });

  it("stale after the configured window", () => {
    const now = Date.parse("2026-10-14T12:00:00Z");
    expect(isStale(null, now)).toBe(true);
    expect(isStale("2026-10-14T11:00:00Z", now, 120)).toBe(false);
    expect(isStale("2026-10-14T09:00:00Z", now, 120)).toBe(true);
  });

  it("selects providers explicitly and never falls back to demo data", async () => {
    const saved = { mode: process.env.COMMERCE_MODE, url: process.env.DATABASE_URL };
    try {
      delete process.env.COMMERCE_MODE;
      expect(commerceMode()).toBe("demo");
      expect((await getCommerce()).mode).toBe("demo");
      process.env.COMMERCE_MODE = "synced";
      expect((await getCommerce()).mode).toBe("synced"); // uses the test database
      const holder = g.__nextChipCatalog;
      delete g.__nextChipCatalog;
      delete process.env.DATABASE_URL;
      await expect(getCommerce()).rejects.toBeInstanceOf(ProviderUnavailableError);
      g.__nextChipCatalog = holder;
      process.env.COMMERCE_MODE = "storepro-live";
      expect(commerceMode()).toBe("misconfigured");
      await expect(getCommerce()).rejects.toBeInstanceOf(ProviderUnavailableError);
    } finally {
      if (saved.mode === undefined) delete process.env.COMMERCE_MODE;
      else process.env.COMMERCE_MODE = saved.mode;
      if (saved.url !== undefined) process.env.DATABASE_URL = saved.url;
    }
  });

  it("an empty synchronized catalog stays empty (no sample products)", async () => {
    const empty = new PGlite();
    const edb = fromPGlite(empty);
    await migrate(edb);
    const sf = createStorefrontService(createSyncedCommerce(createCatalogStore(edb)), () => NOW);
    expect((await sf.queryCatalog({})).total).toBe(0);
    expect((await sf.getHome()).categories).toEqual([]);
    expect(await sf.freshness()).toMatchObject({ lastSuccessAt: null, publishedProducts: 0 });
    await empty.close();
  });
});
