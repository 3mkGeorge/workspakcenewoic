import { describe, expect, it } from "vitest";
import { computeTotals, normalizeLines, priceLines } from "@/lib/commerce/cart-math";
import { effectiveSale, isPromotionValid } from "@/lib/commerce/pricing";
import { createDemoCommerce } from "@/lib/commerce/demo/providers";
import { createStorefrontService } from "@/lib/commerce/service";
import { DEMO_PROMOTIONS } from "@/data/demo/catalog-meta";
import { DEMO_PRICES } from "@/data/demo";
import type { PricedLine } from "@/lib/commerce/types";

const NOW = new Date("2026-10-14T12:00:00+02:00");
const service = createStorefrontService(createDemoCommerce(), () => NOW);

describe("sale prices", () => {
  it("applies a sale only while it is lower and not expired", () => {
    expect(effectiveSale({ productId: "x", currency: "EGP", amount: 900, compareAt: 1000 }, NOW)).toEqual({ amount: 900, regular: 1000, onSale: true });
    expect(effectiveSale({ productId: "x", currency: "EGP", amount: 900, compareAt: 800 }, NOW).onSale).toBe(false);
    expect(effectiveSale({ productId: "x", currency: "EGP", amount: 900, compareAt: 1000, saleEndsAt: "2026-08-31T00:00:00Z" }, NOW)).toEqual({ amount: 900, regular: 900, onSale: false });
  });

  it("shows only promotions inside their window with a product really on sale", () => {
    const valid = DEMO_PROMOTIONS.filter((p) => isPromotionValid(p, DEMO_PRICES, NOW)).map((p) => p.id);
    expect(valid).toEqual(["promo-aim-season"]);
    expect(isPromotionValid(DEMO_PROMOTIONS[0]!, DEMO_PRICES, new Date("2026-12-15T00:00:00Z"))).toBe(false);
  });
});

describe("cart math", () => {
  const line = (p: Partial<PricedLine>): PricedLine => ({
    productId: "p", sku: "S", name: { en: "N", ar: "N" }, slug: "n", quantity: 1, unitPrice: 0, regularUnitPrice: 0, lineTotal: 0, maxQuantity: 9, ...p,
  });

  it("total = subtotal − discount + shipping, counting only purchasable lines", () => {
    const t = computeTotals(
      [
        line({ quantity: 2, unitPrice: 9000, regularUnitPrice: 10000 }),
        line({ quantity: 1, unitPrice: 5000, regularUnitPrice: 5000 }),
        line({ quantity: 1, unitPrice: 7000, regularUnitPrice: 7000, issue: "unavailable" }),
      ],
      6000,
    );
    expect(t).toEqual({ subtotal: 25000, discount: 2000, shipping: 6000, total: 29000, itemCount: 3 });
  });

  it("charges no shipping on an empty cart", () => {
    expect(computeTotals([], 6000)).toEqual({ subtotal: 0, discount: 0, shipping: 0, total: 0, itemCount: 0 });
  });

  it("normalizes untrusted lines: merges duplicates, drops junk, caps quantity", () => {
    expect(
      normalizeLines([
        { productId: "p-a", quantity: 2 },
        { productId: "p-a", quantity: 3 },
        { productId: "p-b", quantity: 0 },
        { productId: "<script>", quantity: 1 },
        { productId: "p-c", quantity: 1.5 },
        { productId: "p-d", quantity: 500 },
        "nope",
      ]),
    ).toEqual([
      { productId: "p-a", quantity: 5 },
      { productId: "p-d", quantity: 99 },
    ]);
  });

  it("flags stock and per-order limits instead of silently changing quantities", () => {
    const products = new Map([["p1", { id: "p1", sku: "S1", name: "P1", slug: "p1", images: [], maxPerOrder: 2 } as never]]);
    const prices = new Map([["p1", { productId: "p1", currency: "EGP" as const, amount: 1000 }]]);
    const lines = (qty: number, stock: number) =>
      priceLines([{ productId: "p1", quantity: qty }], products, prices, new Map([["p1", { productId: "p1", status: "in_stock" as const, quantity: stock }]]), NOW)[0]!;
    expect(lines(3, 10).issue).toBe("max_per_order");
    expect(lines(2, 1).issue).toBe("insufficient_stock");
    expect(lines(1, 0).issue).toBe("unavailable");
    expect(lines(2, 10)).toMatchObject({ issue: undefined, maxQuantity: 2, lineTotal: 2000 });
  });
});

describe("server cart quote (demo providers)", () => {
  it("prices from providers, never from the client", async () => {
    const q = await service.quoteCart([{ productId: "p-vortek-v1-air", quantity: 1, unitPrice: 1, total: 1 }], "cairo");
    expect(q.lines[0]).toMatchObject({ unitPrice: 329900, regularUnitPrice: 379900 });
    expect(q.totals).toEqual({ subtotal: 379900, discount: 50000, shipping: 6000, total: 335900, itemCount: 1 });
    expect(q.shipping).toMatchObject({ zoneId: "greater-cairo", fee: 6000, demo: true });
    expect(q.purchasable).toBe(true);
  });

  it("uses each governorate's zone fee and recalculates when quantities change", async () => {
    const one = await service.quoteCart([{ productId: "p-glidex-hybrid-l", quantity: 1 }], "aswan");
    const three = await service.quoteCart([{ productId: "p-glidex-hybrid-l", quantity: 3 }], "aswan");
    expect(one.totals).toMatchObject({ subtotal: 89900, shipping: 9500, total: 99400 });
    expect(three.totals).toMatchObject({ subtotal: 269700, shipping: 9500, total: 279200 });
  });

  it("marks sold-out and unknown products as not purchasable", async () => {
    const q = await service.quoteCart([
      { productId: "p-nexa-wraith-mini", quantity: 1 },
      { productId: "p-does-not-exist", quantity: 1 },
    ]);
    expect(q.lines.map((l) => l.issue)).toEqual(["unavailable", "unknown_product"]);
    expect(q.purchasable).toBe(false);
    expect(q.totals.total).toBe(0);
  });
});
