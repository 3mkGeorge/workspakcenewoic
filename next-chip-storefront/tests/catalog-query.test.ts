import { describe, expect, it } from "vitest";
import { catalogQueryToParams, parseCatalogQuery, runCatalogQuery } from "@/lib/commerce/catalog-query";
import { createDemoCommerce } from "@/lib/commerce/demo/providers";
import { createStorefrontService } from "@/lib/commerce/service";

const NOW = new Date("2026-10-14T12:00:00+02:00");
const service = createStorefrontService(createDemoCommerce(), () => NOW);

describe("catalog query", () => {
  it("lists published products only (discontinued hidden)", async () => {
    const all = await service.queryCatalog({ perPage: 100 });
    expect(all.total).toBe(28);
    expect(all.items.some((i) => i.slug === "vortek-legacy-g1")).toBe(false);
  });

  it("filters by category, brand, price and availability together", async () => {
    const r = await service.queryCatalog({ category: "gaming-mice", brands: ["vortek"], minPrice: 1000, maxPrice: 3000, stock: "in-stock", perPage: 50 });
    expect(r.items.map((i) => i.slug).sort()).toEqual(["vortek-hex-ultralight", "vortek-v2-wired"]);
    for (const i of r.items) {
      expect(i.category.slug).toBe("gaming-mice");
      expect(i.availability.quantity).toBeGreaterThan(0);
    }
  });

  it("in-stock filter removes sold-out products", async () => {
    const all = await service.queryCatalog({ category: "gaming-mice", perPage: 50 });
    const inStock = await service.queryCatalog({ category: "gaming-mice", stock: "in-stock", perPage: 50 });
    expect(all.items.some((i) => i.availability.status === "out_of_stock")).toBe(true);
    expect(inStock.items.every((i) => i.availability.status !== "out_of_stock")).toBe(true);
  });

  it("searches name, SKU, brand and keywords in both languages", async () => {
    expect((await service.queryCatalog({ q: "GLX-DOT-32" })).items[0]?.slug).toBe("glidex-dots-pro");
    expect((await service.queryCatalog({ q: "rapid trigger" })).items[0]?.slug).toBe("kinetiq-mag60-he");
    expect((await service.queryCatalog({ q: "halcyon hybrid", perPage: 50 })).items.map((i) => i.slug)).toEqual(["halcyon-duet-iem"]);
    const arabic = await service.queryCatalog({ q: "لاسلكي", perPage: 50 });
    expect(arabic.total).toBeGreaterThan(2);
    expect((await service.queryCatalog({ q: "zzzz-nothing" })).total).toBe(0);
  });

  it("deals filter keeps only valid sales (expired sales excluded)", async () => {
    const deals = await service.queryCatalog({ onSale: true, perPage: 100 });
    expect(deals.total).toBeGreaterThan(0);
    for (const i of deals.items) {
      expect(i.price.compareAt).toBeGreaterThan(i.price.amount);
      expect(!i.price.saleEndsAt || Date.parse(i.price.saleEndsAt) > NOW.getTime()).toBe(true);
    }
    expect(deals.items.some((i) => i.slug === "kinetiq-k75")).toBe(false);
    expect(parseCatalogQuery({ sale: "1" }).onSale).toBe(true);
    expect(catalogQueryToParams({ onSale: true }).toString()).toBe("sale=1");
  });

  it("sorts by price and newest", async () => {
    const asc = (await service.queryCatalog({ sort: "price-asc", perPage: 100 })).items.map((i) => i.price.amount);
    expect(asc).toEqual([...asc].sort((a, b) => a - b));
    const desc = (await service.queryCatalog({ sort: "price-desc", perPage: 100 })).items.map((i) => i.price.amount);
    expect(desc).toEqual([...desc].sort((a, b) => b - a));
    const newest = (await service.queryCatalog({ sort: "newest", perPage: 100 })).items.map((i) => i.publishedAt);
    expect(newest).toEqual([...newest].sort().reverse());
  });

  it("paginates and clamps out-of-range pages", async () => {
    const p1 = await service.queryCatalog({ perPage: 12, page: 1 });
    const p3 = await service.queryCatalog({ perPage: 12, page: 3 });
    const beyond = await service.queryCatalog({ perPage: 12, page: 99 });
    expect(p1.pageCount).toBe(3);
    expect(p1.items).toHaveLength(12);
    expect(p3.items).toHaveLength(4);
    expect(beyond.page).toBe(3);
  });

  it("builds brand facets and price range from search+category scope", async () => {
    const r = await service.queryCatalog({ category: "keyboards", brands: ["kinetiq"] });
    expect(r.facets.brands.map((b) => b.brand.slug).sort()).toEqual(["kinetiq", "vortek"]);
    expect(r.facets.priceRange.min).toBeLessThanOrEqual(r.facets.priceRange.max);
  });

  it("parses untrusted URL params safely and round-trips them", () => {
    const q = parseCatalogQuery({ q: " mouse ", category: "gaming-mice", brand: "vortek,nexa-labs,BAD<>", min: "3000", max: "1000", stock: "in-stock", sort: "price-desc", page: "2" });
    expect(q).toMatchObject({ q: "mouse", category: "gaming-mice", brands: ["vortek", "nexa-labs"], minPrice: 1000, maxPrice: 3000, stock: "in-stock", sort: "price-desc", page: 2 });
    expect(catalogQueryToParams(q).toString()).toBe("q=mouse&category=gaming-mice&brand=vortek%2Cnexa-labs&min=1000&max=3000&stock=in-stock&sort=price-desc&page=2");
    const junk = parseCatalogQuery({ sort: "drop table", page: "-4", min: "abc", category: "../etc" });
    expect(junk).toMatchObject({ sort: "featured", page: 1, minPrice: undefined, category: undefined });
  });

  it("runCatalogQuery handles an empty catalog", () => {
    const r = runCatalogQuery([], {});
    expect(r).toMatchObject({ total: 0, page: 1, pageCount: 1, items: [] });
  });
});
