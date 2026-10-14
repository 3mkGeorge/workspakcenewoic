import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";
import ar from "@/i18n/dictionaries/ar";
import en from "@/i18n/dictionaries/en";
import { countText } from "@/i18n/format";
import { activeFilterCount, catalogHref, categoryHref, pageWindow, type CatalogContext } from "@/lib/catalog-urls";
import { formatEGP } from "@/lib/commerce/money";
import { proxy } from "@/proxy";

type Tree = { [k: string]: string | Tree };

function leaves(tree: Tree, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [k, v] of Object.entries(tree)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (typeof v === "string") out.set(key, v);
    else for (const [kk, vv] of leaves(v, key)) out.set(kk, vv);
  }
  return out;
}
const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("dictionaries", () => {
  const EN = leaves(en as unknown as Tree);
  const AR = leaves(ar as unknown as Tree);
  const isPluralForm = (key: string) => /\.(zero|one|two|few|many|other)$/.test(key);

  it("Arabic covers every English message and nothing is left empty", () => {
    const enKeys = [...EN.keys()].filter((k) => !isPluralForm(k));
    const arKeys = [...AR.keys()].filter((k) => !isPluralForm(k));
    expect(arKeys.sort()).toEqual(enKeys.sort());
    for (const [k, v] of [...EN, ...AR]) expect(v.trim(), k).not.toBe("");
  });

  it("translations keep the same placeholders", () => {
    for (const [k, v] of EN) {
      if (isPluralForm(k)) continue;
      expect(placeholders(AR.get(k)!), k).toEqual(placeholders(v));
    }
  });

  it("plural messages always define 'other' in both languages", () => {
    const plurals = [...EN.keys()].filter((k) => k.endsWith(".other")).map((k) => k.slice(0, -".other".length));
    expect(plurals.length).toBeGreaterThan(3);
    for (const base of plurals) expect(AR.has(`${base}.other`), base).toBe(true);
  });
});

describe("Arabic plurals and digits", () => {
  it("chooses the CLDR plural form", () => {
    expect(countText(en.catalog.results, 1, "en")).toBe("1 product");
    expect(countText(en.catalog.results, 12, "en")).toBe("12 products");
    expect(countText(ar.catalog.results, 1, "ar")).toBe("منتج واحد");
    expect(countText(ar.catalog.results, 2, "ar")).toBe("منتجان");
    expect(countText(ar.catalog.results, 5, "ar")).toBe("5 منتجات");
    expect(countText(ar.catalog.results, 28, "ar")).toBe("28 منتجًا");
    expect(countText(ar.catalog.results, 100, "ar")).toBe("100 منتج");
  });

  it("formats EGP with Latin digits in both languages", () => {
    expect(formatEGP(329900, "en")).toMatch(/EGP\s?3,299\.00/);
    expect(formatEGP(329900, "ar")).toMatch(/3,299\.00/);
    expect(formatEGP(329900, "ar")).not.toMatch(/[٠-٩]/);
  });
});

describe("catalog URLs", () => {
  const base: CatalogContext = { locale: "en", basePath: "/products", view: "grid", query: { sort: "featured", page: 2, brands: ["vortek"], stock: "all" } };

  it("keeps state in the URL and resets the page on filter changes", () => {
    expect(catalogHref(base)).toBe("/en/products?brand=vortek&page=2");
    expect(catalogHref(base, { brands: ["vortek", "glidex"], page: undefined })).toBe("/en/products?brand=vortek%2Cglidex");
    expect(catalogHref(base, { view: "list" })).toBe("/en/products?brand=vortek&page=2&view=list");
    expect(catalogHref({ ...base, locale: "ar" }, { sort: "price-asc", page: undefined })).toBe("/ar/products?brand=vortek&sort=price-asc");
  });

  it("category links live in the path, except inside search", () => {
    expect(categoryHref(base, "keyboards")).toBe("/en/categories/keyboards");
    expect(categoryHref({ ...base, basePath: "/search", query: { q: "rgb" } }, "keyboards")).toBe("/en/search?q=rgb&category=keyboards");
    const cat: CatalogContext = { ...base, basePath: "/categories/keyboards", fixedCategory: "keyboards", query: { category: "keyboards", sort: "newest" } };
    expect(catalogHref(cat)).toBe("/en/categories/keyboards?sort=newest");
    expect(categoryHref(cat, undefined)).toBe("/en/products?sort=newest");
    expect(activeFilterCount(cat)).toBe(0);
    expect(activeFilterCount({ ...base, query: { brands: ["a", "b"], minPrice: 10, onSale: true, stock: "in-stock" } })).toBe(5);
  });

  it("pagination windows collapse long ranges", () => {
    expect(pageWindow(1, 1)).toEqual([1]);
    expect(pageWindow(1, 3)).toEqual([1, 2, 3]);
    expect(pageWindow(5, 10)).toEqual([1, null, 4, 5, 6, null, 10]);
  });
});

describe("locale routing (proxy)", () => {
  const req = (path: string, headers: Record<string, string> = {}) => new NextRequest(new URL(path, "http://shop.test"), { headers });

  it("redirects unprefixed paths using the cookie, then Accept-Language", () => {
    expect(proxy(req("/")).headers.get("location")).toBe("http://shop.test/en");
    expect(proxy(req("/products?brand=vortek", { "accept-language": "ar-EG,ar;q=0.9,en;q=0.8" })).headers.get("location")).toBe(
      "http://shop.test/ar/products?brand=vortek",
    );
    expect(proxy(req("/cart", { "accept-language": "ar", cookie: "NEXT_LOCALE=en" })).headers.get("location")).toBe("http://shop.test/en/cart");
    expect(proxy(req("/", { "accept-language": "fr-FR,fr;q=0.9" })).headers.get("location")).toBe("http://shop.test/en");
  });

  it("remembers the locale of prefixed paths", () => {
    const res = proxy(req("/ar/products"));
    expect(res.headers.get("location")).toBeNull();
    expect(res.cookies.get("NEXT_LOCALE")?.value).toBe("ar");
    expect(proxy(req("/en", { cookie: "NEXT_LOCALE=en" })).cookies.get("NEXT_LOCALE")).toBeUndefined();
  });
});
