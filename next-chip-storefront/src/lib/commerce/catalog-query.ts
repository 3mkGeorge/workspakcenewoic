/**
 * Pure catalog filtering, searching, sorting and pagination. Runs on the server
 * against whatever the active providers return; unit-tested in isolation.
 */
import { effectiveSale } from "./pricing";
import type { CatalogItem, CatalogQuery, CatalogResult, CatalogSort, StockFilter } from "./types";

export const DEFAULT_PER_PAGE = 12;
export const SORTS: CatalogSort[] = ["featured", "newest", "price-asc", "price-desc"];

const normalize = (s: string) =>
  s
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[ً-ٰٟ]/g, "") // Arabic diacritics
    .replace(/[أإآ]/g, "ا")
    .replace(/ة/g, "ه")
    .replace(/ى/g, "ي")
    .replace(/\s+/g, " ")
    .trim();

/** Every term must appear in the product's searchable text (name, SKU, brand, keywords, category, summary). */
export function matchesSearch(item: CatalogItem, q: string): boolean {
  const terms = normalize(q).split(" ").filter(Boolean);
  if (!terms.length) return true;
  const haystack = normalize(
    [
      item.name,
      item.sku,
      item.brand.name,
      item.category.name.en,
      item.category.name.ar,
      item.summary.en,
      item.summary.ar,
      ...item.keywords,
    ].join(" "),
  );
  return terms.every((t) => haystack.includes(t));
}

export const isPurchasable = (item: CatalogItem) =>
  (item.availability.status === "in_stock" || item.availability.status === "low_stock") && item.availability.quantity > 0;

function compare(sort: CatalogSort) {
  switch (sort) {
    case "price-asc":
      return (a: CatalogItem, b: CatalogItem) => a.price.amount - b.price.amount || a.name.localeCompare(b.name);
    case "price-desc":
      return (a: CatalogItem, b: CatalogItem) => b.price.amount - a.price.amount || a.name.localeCompare(b.name);
    case "newest":
      return (a: CatalogItem, b: CatalogItem) => b.publishedAt.localeCompare(a.publishedAt) || a.name.localeCompare(b.name);
    case "featured":
    default:
      // Featured first, then best sellers by rank, then in-stock, then newest.
      return (a: CatalogItem, b: CatalogItem) =>
        Number(b.featured) - Number(a.featured) ||
        (a.bestSellerRank ?? 9999) - (b.bestSellerRank ?? 9999) ||
        Number(isPurchasable(b)) - Number(isPurchasable(a)) ||
        b.publishedAt.localeCompare(a.publishedAt);
  }
}

/** Parse untrusted URL search params into a safe CatalogQuery. */
export function parseCatalogQuery(params: Record<string, string | string[] | undefined>): CatalogQuery {
  const one = (k: string) => {
    const v = params[k];
    return (Array.isArray(v) ? v[0] : v)?.trim() || undefined;
  };
  const num = (k: string) => {
    const v = one(k);
    if (v === undefined || !/^\d{1,7}$/.test(v)) return undefined;
    return Number(v);
  };
  const brandsRaw = params.brand;
  const brands = (Array.isArray(brandsRaw) ? brandsRaw : brandsRaw ? brandsRaw.split(",") : [])
    .map((b) => b.trim())
    .filter((b) => /^[a-z0-9-]{1,40}$/.test(b))
    .slice(0, 20);
  const sort = one("sort") as CatalogSort | undefined;
  const stock = one("stock") === "in-stock" ? "in-stock" : "all";
  const page = num("page");
  const category = one("category");
  const q = one("q")?.slice(0, 80);
  let minPrice = num("min");
  let maxPrice = num("max");
  if (minPrice !== undefined && maxPrice !== undefined && minPrice > maxPrice) [minPrice, maxPrice] = [maxPrice, minPrice];
  return {
    q,
    category: category && /^[a-z0-9-]{1,60}$/.test(category) ? category : undefined,
    brands,
    minPrice,
    maxPrice,
    stock: stock as StockFilter,
    onSale: one("sale") === "1",
    sort: sort && SORTS.includes(sort) ? sort : "featured",
    page: page && page > 0 ? page : 1,
  };
}

/** Serialize a query back to URL params (omitting defaults) so filters live in the URL. */
export function catalogQueryToParams(query: CatalogQuery): URLSearchParams {
  const p = new URLSearchParams();
  if (query.q) p.set("q", query.q);
  if (query.category) p.set("category", query.category);
  if (query.brands?.length) p.set("brand", query.brands.join(","));
  if (query.minPrice !== undefined) p.set("min", String(query.minPrice));
  if (query.maxPrice !== undefined) p.set("max", String(query.maxPrice));
  if (query.stock === "in-stock") p.set("stock", "in-stock");
  if (query.onSale) p.set("sale", "1");
  if (query.sort && query.sort !== "featured") p.set("sort", query.sort);
  if (query.page && query.page > 1) p.set("page", String(query.page));
  return p;
}

export function runCatalogQuery(all: CatalogItem[], query: CatalogQuery, now = new Date()): CatalogResult {
  const perPage = query.perPage ?? DEFAULT_PER_PAGE;
  // Facets reflect search + category (not brand/price/stock), so shoppers can widen again.
  let scoped = all.filter((i) => i.availability.status !== "discontinued");
  if (query.q) scoped = scoped.filter((i) => matchesSearch(i, query.q!));
  if (query.category) scoped = scoped.filter((i) => i.category.slug === query.category);

  const brandCounts = new Map<string, { brand: CatalogItem["brand"]; count: number }>();
  for (const i of scoped) {
    const entry = brandCounts.get(i.brand.slug) ?? { brand: i.brand, count: 0 };
    entry.count++;
    brandCounts.set(i.brand.slug, entry);
  }
  const prices = scoped.map((i) => effectiveSale(i.price, now).amount);
  const priceRange = prices.length
    ? { min: Math.floor(Math.min(...prices) / 100), max: Math.ceil(Math.max(...prices) / 100) }
    : { min: 0, max: 0 };

  let items = scoped;
  if (query.brands?.length) items = items.filter((i) => query.brands!.includes(i.brand.slug));
  if (query.minPrice !== undefined) items = items.filter((i) => effectiveSale(i.price, now).amount >= query.minPrice! * 100);
  if (query.maxPrice !== undefined) items = items.filter((i) => effectiveSale(i.price, now).amount <= query.maxPrice! * 100);
  if (query.stock === "in-stock") items = items.filter(isPurchasable);
  if (query.onSale) items = items.filter((i) => effectiveSale(i.price, now).onSale);
  items = [...items].sort(compare(query.sort ?? "featured"));

  const total = items.length;
  const pageCount = Math.max(1, Math.ceil(total / perPage));
  const page = Math.min(Math.max(1, query.page ?? 1), pageCount);
  return {
    items: items.slice((page - 1) * perPage, page * perPage),
    total,
    page,
    pageCount,
    perPage,
    facets: {
      brands: [...brandCounts.values()].sort((a, b) => a.brand.name.localeCompare(b.brand.name)),
      priceRange,
    },
  };
}
