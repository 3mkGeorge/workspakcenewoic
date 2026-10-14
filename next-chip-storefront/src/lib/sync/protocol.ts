/**
 * StorePro → Next Chip catalog snapshot, schema version 1.
 *
 * The whole payload is validated before anything is written. One malformed
 * record rejects the batch (and is reported by SKU/id) so a bad export can
 * never unpublish good products or show half a catalog.
 */
import type { LocalizedText } from "@/lib/commerce/types";

export const SCHEMA_VERSION = 1;
export const SOURCE = "storepro";
export const MAX_PRODUCTS = 20_000;
export const MAX_CATEGORIES = 500;
export const MAX_BRANDS = 2_000;
export const MAX_IMAGES_PER_PRODUCT = 8;
export const MAX_PRICE = 1_000_000_000; // 10,000,000.00 EGP in piastres

export type SyncAvailability = "in_stock" | "low_stock" | "out_of_stock";
export type ImageType = "image/jpeg" | "image/png" | "image/webp";

export interface SyncImage {
  hash: string;
  contentType: ImageType;
  width: number;
  height: number;
}

export interface SyncCategory {
  id: string;
  slug: string;
  name: LocalizedText;
  description: LocalizedText;
  icon: string;
  sortOrder: number;
}

export interface SyncBrand {
  id: string;
  slug: string;
  name: string;
}

export interface SyncProduct {
  id: string;
  sku: string;
  slug: string;
  name: LocalizedText;
  description: LocalizedText;
  categoryId: string;
  brandId: string | null;
  price: number;
  compareAt: number | null;
  saleEndsAt: string | null;
  availability: SyncAvailability;
  orderableQuantity: number;
  maxPerOrder: number;
  images: SyncImage[];
  published: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface SyncSnapshot {
  schemaVersion: 1;
  source: "storepro";
  snapshot: { id: string; sequence: number; generatedAt: string; complete: boolean };
  currency: "EGP";
  categories: SyncCategory[];
  brands: SyncBrand[];
  products: SyncProduct[];
}

export interface ValidationIssue {
  path: string;
  message: string;
}

export type ValidationResult = { ok: true; value: SyncSnapshot } | { ok: false; issues: ValidationIssue[] };

const ID = /^[a-z0-9][a-z0-9-]{0,63}$/;
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const HASH = /^[0-9a-f]{64}$/;
const SNAPSHOT_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$/;
// Printable text without control characters (tabs/newlines allowed in descriptions only).
const CONTROL = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/;
const IMAGE_TYPES: ImageType[] = ["image/jpeg", "image/png", "image/webp"];
const AVAILABILITY: SyncAvailability[] = ["in_stock", "low_stock", "out_of_stock"];

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);

class Checker {
  issues: ValidationIssue[] = [];
  fail(path: string, message: string) {
    if (this.issues.length < 50) this.issues.push({ path, message });
  }
  text(v: unknown, path: string, opts: { min?: number; max: number; multiline?: boolean }): string {
    if (typeof v !== "string") {
      this.fail(path, "must be a string");
      return "";
    }
    const s = v.normalize("NFC").trim();
    if (s.length < (opts.min ?? 0)) this.fail(path, `must be at least ${opts.min} characters`);
    if (s.length > opts.max) this.fail(path, `must be at most ${opts.max} characters`);
    if (opts.multiline ? CONTROL.test(s) : /[\u0000-\u001F\u007F]/.test(s)) this.fail(path, "contains control characters");
    return s;
  }
  pattern(v: unknown, re: RegExp, path: string, what: string): string {
    if (typeof v !== "string" || !re.test(v)) {
      this.fail(path, `must be a valid ${what}`);
      return "";
    }
    return v;
  }
  int(v: unknown, path: string, min: number, max: number): number {
    if (typeof v !== "number" || !Number.isSafeInteger(v) || v < min || v > max) {
      this.fail(path, `must be an integer between ${min} and ${max}`);
      return 0;
    }
    return v;
  }
  date(v: unknown, path: string): string {
    if (typeof v !== "string" || v.length > 40 || Number.isNaN(Date.parse(v))) {
      this.fail(path, "must be an ISO-8601 timestamp");
      return new Date(0).toISOString();
    }
    return new Date(v).toISOString();
  }
  localized(v: unknown, path: string, opts: { min?: number; max: number; multiline?: boolean }): LocalizedText {
    if (!isObj(v)) {
      this.fail(path, "must be an object with en and ar");
      return { en: "", ar: "" };
    }
    return { en: this.text(v.en, `${path}.en`, opts), ar: this.text(v.ar, `${path}.ar`, opts) };
  }
  array(v: unknown, path: string, max: number): unknown[] {
    if (!Array.isArray(v)) {
      this.fail(path, "must be an array");
      return [];
    }
    if (v.length > max) {
      this.fail(path, `must contain at most ${max} entries`);
      return [];
    }
    return v;
  }
}

export function validateSnapshot(input: unknown): ValidationResult {
  const c = new Checker();
  if (!isObj(input)) return { ok: false, issues: [{ path: "", message: "body must be a JSON object" }] };
  if (input.schemaVersion !== SCHEMA_VERSION) return { ok: false, issues: [{ path: "schemaVersion", message: `unsupported schema version (expected ${SCHEMA_VERSION})` }] };
  if (input.source !== SOURCE) c.fail("source", `must be "${SOURCE}"`);
  if (input.currency !== "EGP") c.fail("currency", 'must be "EGP"');

  const meta = isObj(input.snapshot) ? input.snapshot : (c.fail("snapshot", "must be an object"), {} as Obj);
  const snapshot = {
    id: c.pattern(meta.id, SNAPSHOT_ID, "snapshot.id", "snapshot id"),
    sequence: c.int(meta.sequence, "snapshot.sequence", 1, Number.MAX_SAFE_INTEGER),
    generatedAt: c.date(meta.generatedAt, "snapshot.generatedAt"),
    complete: meta.complete === true,
  };
  if (typeof meta.complete !== "boolean") c.fail("snapshot.complete", "must be true or false");

  const categories: SyncCategory[] = c.array(input.categories, "categories", MAX_CATEGORIES).map((raw, i) => {
    const p = `categories[${i}]`;
    const v = isObj(raw) ? raw : (c.fail(p, "must be an object"), {} as Obj);
    return {
      id: c.pattern(v.id, ID, `${p}.id`, "id"),
      slug: c.pattern(v.slug, SLUG, `${p}.slug`, "slug"),
      name: c.localized(v.name, `${p}.name`, { min: 1, max: 100 }),
      description: c.localized(v.description ?? { en: "", ar: "" }, `${p}.description`, { max: 500, multiline: true }),
      icon: typeof v.icon === "string" && /^[a-z0-9-]{0,40}$/.test(v.icon) ? v.icon : (c.fail(`${p}.icon`, "must be an icon name"), ""),
      sortOrder: c.int(v.sortOrder ?? 0, `${p}.sortOrder`, 0, 100_000),
    };
  });

  const brands: SyncBrand[] = c.array(input.brands, "brands", MAX_BRANDS).map((raw, i) => {
    const p = `brands[${i}]`;
    const v = isObj(raw) ? raw : (c.fail(p, "must be an object"), {} as Obj);
    return {
      id: c.pattern(v.id, ID, `${p}.id`, "id"),
      slug: c.pattern(v.slug, SLUG, `${p}.slug`, "slug"),
      name: c.text(v.name, `${p}.name`, { min: 1, max: 80 }),
    };
  });

  const products: SyncProduct[] = c.array(input.products, "products", MAX_PRODUCTS).map((raw, i) => {
    const v = isObj(raw) ? raw : (c.fail(`products[${i}]`, "must be an object"), {} as Obj);
    // Name the record by SKU/id in errors so the operator can find it in StorePro.
    const p = `products[${i}${typeof v.sku === "string" ? ` sku=${String(v.sku).slice(0, 60)}` : ""}]`;
    const price = c.int(v.price, `${p}.price`, 1, MAX_PRICE);
    const compareAt = v.compareAt === null || v.compareAt === undefined ? null : c.int(v.compareAt, `${p}.compareAt`, 1, MAX_PRICE);
    const maxPerOrder = c.int(v.maxPerOrder, `${p}.maxPerOrder`, 1, 99);
    const availability = AVAILABILITY.includes(v.availability as SyncAvailability)
      ? (v.availability as SyncAvailability)
      : (c.fail(`${p}.availability`, `must be one of ${AVAILABILITY.join(", ")}`), "out_of_stock" as const);
    const orderableQuantity = c.int(v.orderableQuantity, `${p}.orderableQuantity`, 0, maxPerOrder || 99);
    if (availability === "out_of_stock" && orderableQuantity !== 0) c.fail(`${p}.orderableQuantity`, "must be 0 when out of stock");
    if (availability !== "out_of_stock" && orderableQuantity === 0) c.fail(`${p}.orderableQuantity`, "must be positive when in stock");
    const images: SyncImage[] = c.array(v.images ?? [], `${p}.images`, MAX_IMAGES_PER_PRODUCT).map((img, j) => {
      const ip = `${p}.images[${j}]`;
      const o = isObj(img) ? img : (c.fail(ip, "must be an object"), {} as Obj);
      return {
        hash: c.pattern(o.hash, HASH, `${ip}.hash`, "SHA-256 hex digest"),
        contentType: IMAGE_TYPES.includes(o.contentType as ImageType) ? (o.contentType as ImageType) : (c.fail(`${ip}.contentType`, "must be image/jpeg, image/png or image/webp"), "image/jpeg"),
        width: c.int(o.width, `${ip}.width`, 1, 10_000),
        height: c.int(o.height, `${ip}.height`, 1, 10_000),
      };
    });
    const saleEndsAt = v.saleEndsAt === null || v.saleEndsAt === undefined ? null : c.date(v.saleEndsAt, `${p}.saleEndsAt`);
    if (compareAt !== null && compareAt <= price) c.fail(`${p}.compareAt`, "must be greater than price");
    if (typeof v.published !== "boolean") c.fail(`${p}.published`, "must be true or false");
    return {
      id: c.pattern(v.id, ID, `${p}.id`, "id"),
      sku: c.text(v.sku, `${p}.sku`, { min: 1, max: 60 }),
      slug: c.pattern(v.slug, SLUG, `${p}.slug`, "slug"),
      name: c.localized(v.name, `${p}.name`, { min: 1, max: 200 }),
      description: c.localized(v.description ?? { en: "", ar: "" }, `${p}.description`, { max: 5000, multiline: true }),
      categoryId: c.pattern(v.categoryId, ID, `${p}.categoryId`, "category id"),
      brandId: v.brandId === null || v.brandId === undefined ? null : c.pattern(v.brandId, ID, `${p}.brandId`, "brand id"),
      price,
      compareAt,
      saleEndsAt,
      availability,
      orderableQuantity,
      maxPerOrder,
      images,
      published: v.published === true,
      createdAt: c.date(v.createdAt, `${p}.createdAt`),
      updatedAt: c.date(v.updatedAt, `${p}.updatedAt`),
    };
  });

  // Uniqueness and references across the batch.
  const unique = (values: string[], what: string) => {
    const seen = new Set<string>();
    for (const value of values) {
      if (seen.has(value)) c.fail(what, `duplicate value "${value}"`);
      seen.add(value);
    }
  };
  unique(categories.map((x) => x.id), "categories.id");
  unique(categories.map((x) => x.slug), "categories.slug");
  unique(brands.map((x) => x.id), "brands.id");
  unique(brands.map((x) => x.slug), "brands.slug");
  unique(products.map((x) => x.id), "products.id");
  const published = products.filter((x) => x.published);
  unique(published.map((x) => x.slug), "products.slug");
  unique(published.map((x) => x.sku.toLowerCase()), "products.sku");
  if (snapshot.complete) {
    // A complete snapshot must describe itself fully: every reference resolves inside it.
    const categoryIds = new Set(categories.map((x) => x.id));
    const brandIds = new Set(brands.map((x) => x.id));
    products.forEach((x, i) => {
      if (!categoryIds.has(x.categoryId)) c.fail(`products[${i}].categoryId`, `unknown category "${x.categoryId}"`);
      if (x.brandId && !brandIds.has(x.brandId)) c.fail(`products[${i}].brandId`, `unknown brand "${x.brandId}"`);
    });
  }

  if (c.issues.length) return { ok: false, issues: c.issues };
  return {
    ok: true,
    value: { schemaVersion: 1, source: "storepro", snapshot, currency: "EGP", categories, brands, products },
  };
}
