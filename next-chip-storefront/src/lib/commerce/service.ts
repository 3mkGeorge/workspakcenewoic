/**
 * Storefront use-cases on top of the provider interfaces. Everything money-related
 * is recomputed here from provider data; request bodies only contribute ids,
 * quantities and customer details.
 */
import { computeTotals, normalizeLines, priceLines } from "./cart-math";
import { runCatalogQuery } from "./catalog-query";
import { validateCustomer, validatePaymentMethod, type CheckoutErrors } from "./checkout-validation";
import { isPromotionValid } from "./pricing";
import type { Commerce } from "./providers";
import { ShippingUnavailableError } from "./providers";
import type {
  CartQuote,
  CatalogItem,
  CatalogQuery,
  CatalogResult,
  Category,
  Order,
  PaymentMethodId,
  Product,
  Promotion,
} from "./types";

export type PlaceOrderResult =
  | { ok: true; order: Order }
  | { ok: false; reason: "invalid"; errors: CheckoutErrors }
  | { ok: false; reason: "cart"; quote: CartQuote }
  | { ok: false; reason: "shipping" };

export function createStorefrontService(commerce: Commerce, now: () => Date = () => new Date()) {
  async function join(products: Product[]): Promise<CatalogItem[]> {
    const ids = products.map((p) => p.id);
    const [categories, brands, prices, stock] = await Promise.all([
      commerce.categories.listCategories(),
      commerce.categories.listBrands(),
      commerce.pricing.getPrices(ids),
      commerce.availability.getAvailability(ids),
    ]);
    const cat = new Map(categories.map((c) => [c.id, c]));
    const brand = new Map(brands.map((b) => [b.id, b]));
    return products.flatMap((p) => {
      const price = prices.get(p.id);
      const category = cat.get(p.categoryId);
      // A product without a price or category is not shown rather than shown wrong.
      // A missing brand only hides the brand label.
      if (!price || !category) return [];
      return [
        {
          ...p,
          category,
          brand: (p.brandId && brand.get(p.brandId)) || null,
          price,
          availability: stock.get(p.id) ?? { productId: p.id, status: "out_of_stock", quantity: 0 },
        },
      ];
    });
  }

  async function allItems() {
    return join(await commerce.catalog.listProducts());
  }

  /** Authoritative cart pricing for display. `governorate` is optional until checkout. */
  async function quoteCart(rawLines: unknown, governorate?: string): Promise<CartQuote> {
    const lines = normalizeLines(rawLines);
    const ids = lines.map((l) => l.productId);
    const [products, prices, stock] = await Promise.all([
      commerce.catalog.getProductsByIds(ids),
      commerce.pricing.getPrices(ids),
      commerce.availability.getAvailability(ids),
    ]);
    const priced = priceLines(lines, new Map(products.map((p) => [p.id, p])), prices, stock, now());
    let shipping;
    let shippingFee = 0;
    if (governorate) {
      const base = computeTotals(priced, 0);
      shipping = await commerce.shipping.quote({ governorate, itemCount: base.itemCount, subtotal: base.subtotal - base.discount });
      shippingFee = shipping.fee;
    }
    const totals = computeTotals(priced, shippingFee);
    return {
      lines: priced,
      totals,
      shipping,
      purchasable: priced.length > 0 && priced.every((l) => !l.issue),
      currency: "EGP",
    };
  }

  return {
    mode: commerce.mode,
    capabilities: commerce.capabilities,
    /** Synchronized catalogs: when StorePro last delivered a snapshot (null for demo). */
    freshness: async () => (commerce.freshness ? commerce.freshness() : null),

    listCategories: () => commerce.categories.listCategories(),
    getCategory: (slug: string) => commerce.categories.getCategory(slug),
    listGovernorates: () => commerce.shipping.listGovernorates(),
    listShippingZones: () => commerce.shipping.listZones(),

    async listPaymentMethods() {
      return (await commerce.payments.listMethods()).filter((m) => m.enabled);
    },

    async queryCatalog(query: CatalogQuery): Promise<CatalogResult> {
      return runCatalogQuery(await allItems(), query, now());
    },

    async getProduct(slug: string): Promise<{ item: CatalogItem; related: CatalogItem[] } | null> {
      const product = await commerce.catalog.getProductBySlug(slug);
      if (!product) return null;
      const items = await allItems();
      const item = items.find((i) => i.id === product.id);
      if (!item || item.availability.status === "discontinued") return null;
      const related = items
        .filter((i) => i.id !== item.id && i.availability.status !== "discontinued")
        .map((i) => ({ i, score: (i.categoryId === item.categoryId ? 2 : 0) + (i.brandId === item.brandId ? 1 : 0) }))
        .filter((r) => r.score > 0)
        .sort((a, b) => b.score - a.score || (a.i.bestSellerRank ?? 99) - (b.i.bestSellerRank ?? 99))
        .slice(0, 4)
        .map((r) => r.i);
      return { item, related };
    },

    async getProductsByIds(ids: string[]): Promise<CatalogItem[]> {
      return join(await commerce.catalog.getProductsByIds(ids.slice(0, 100)));
    },

    async getHome(): Promise<{
      categories: (Category & { count: number })[];
      featured: CatalogItem[];
      newArrivals: CatalogItem[];
      bestSellers: CatalogItem[];
      promotions: Promotion[];
      heroItem: CatalogItem | null;
    }> {
      const [items, categories, promos] = await Promise.all([
        allItems(),
        commerce.categories.listCategories(),
        commerce.promotions.listPromotions(),
      ]);
      const live = items.filter((i) => i.availability.status !== "discontinued");
      const prices = new Map(live.map((i) => [i.id, i.price]));
      const t = now();
      const newest = [...live].sort((a, b) => b.publishedAt.localeCompare(a.publishedAt));
      return {
        categories: categories.map((c) => ({ ...c, count: live.filter((i) => i.categoryId === c.id).length })),
        featured: live.filter((i) => i.featured).slice(0, 8),
        newArrivals: newest.slice(0, 4),
        bestSellers: live
          .filter((i) => i.bestSellerRank !== undefined)
          .sort((a, b) => a.bestSellerRank! - b.bestSellerRank!)
          .slice(0, 4),
        promotions: promos.filter((p) => isPromotionValid(p, prices, t)),
        heroItem: live.find((i) => i.bestSellerRank === 1) ?? live[0] ?? null,
      };
    },

    quoteCart,

    /** Validate, re-price and submit. Client-sent prices or totals are never read. */
    async placeOrder(body: unknown): Promise<PlaceOrderResult> {
      const input = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
      const governorates = (await commerce.shipping.listGovernorates()).map((g) => g.id);
      const { errors, value: customer } = validateCustomer(
        (input.customer && typeof input.customer === "object" ? input.customer : {}) as Record<string, unknown>,
        governorates,
      );
      const methods = (await commerce.payments.listMethods()).filter((m) => m.enabled).map((m) => m.id);
      if (!validatePaymentMethod(input.paymentMethod, methods)) errors.paymentMethod = "invalid";
      const requestId = typeof input.requestId === "string" && /^[A-Za-z0-9-]{16,64}$/.test(input.requestId) ? input.requestId : null;
      const lines = normalizeLines(input.lines);
      if (!lines.length) errors.lines = "required";
      if (!requestId) errors.lines = errors.lines ?? "invalid";
      if (Object.keys(errors).length || !customer || !requestId) return { ok: false, reason: "invalid", errors };

      let quote: CartQuote;
      try {
        quote = await quoteCart(lines, customer.governorate);
      } catch (e) {
        if (e instanceof ShippingUnavailableError) return { ok: false, reason: "shipping" };
        throw e;
      }
      if (!quote.purchasable || !quote.shipping) return { ok: false, reason: "cart", quote };
      const order = await commerce.orders.createOrder({
        customer,
        lines,
        paymentMethod: input.paymentMethod as PaymentMethodId,
        requestId,
        pricedLines: quote.lines,
        totals: quote.totals,
        shipping: quote.shipping,
      });
      return { ok: true, order };
    },

    getOrder: (id: string) => commerce.orders.getOrder(id),
  };
}

export type StorefrontService = ReturnType<typeof createStorefrontService>;
