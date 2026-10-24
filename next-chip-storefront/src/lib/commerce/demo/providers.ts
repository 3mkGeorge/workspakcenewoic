/**
 * DEMO providers backed by local fixtures. Orders are kept in this server
 * process's memory only: nothing is sent to StorePro and nothing is fulfilled.
 */
import {
  DEMO_BRANDS,
  DEMO_CATEGORIES,
  DEMO_PAYMENT_METHODS,
  DEMO_PROMOTIONS,
  DEMO_SHIPPING_ZONES,
  GOVERNORATES,
} from "@/data/demo/catalog-meta";
import { DEMO_AVAILABILITY, DEMO_PRICES, DEMO_PRODUCTS } from "@/data/demo";
import type { Commerce, PricedOrderRequest } from "../providers";
import { ShippingUnavailableError } from "../providers";
import type { Order } from "../types";

const clone = <T>(v: T): T => structuredClone(v);

/**
 * Demo orders survive only as long as the server process. Next.js bundles route
 * handlers and pages separately, so the store hangs off globalThis to be one
 * per process rather than one per bundle.
 */
interface DemoOrderStore {
  orders: Map<string, Order>;
  byRequest: Map<string, string>;
  sequence: number;
}
const g = globalThis as typeof globalThis & { __nextChipDemoOrders?: DemoOrderStore };
const store: DemoOrderStore = (g.__nextChipDemoOrders ??= { orders: new Map(), byRequest: new Map(), sequence: 1000 });
const { orders, byRequest } = store;

export function createDemoCommerce(): Commerce {
  return {
    mode: "demo",
    capabilities: { catalog: "demo", shipping: "demo", orders: "demo" },
    catalog: {
      async listProducts() {
        return clone(DEMO_PRODUCTS);
      },
      async getProductBySlug(slug) {
        return clone(DEMO_PRODUCTS.find((p) => p.slug === slug) ?? null);
      },
      async getProductsByIds(ids) {
        const wanted = new Set(ids);
        return clone(DEMO_PRODUCTS.filter((p) => wanted.has(p.id)));
      },
    },
    categories: {
      async listCategories() {
        return clone([...DEMO_CATEGORIES].sort((a, b) => a.sortOrder - b.sortOrder));
      },
      async getCategory(slug) {
        return clone(DEMO_CATEGORIES.find((c) => c.slug === slug) ?? null);
      },
      async listBrands() {
        return clone(DEMO_BRANDS);
      },
    },
    pricing: {
      async getPrices(ids) {
        return new Map(ids.filter((id) => DEMO_PRICES.has(id)).map((id) => [id, clone(DEMO_PRICES.get(id)!)]));
      },
    },
    availability: {
      async getAvailability(ids) {
        return new Map(ids.filter((id) => DEMO_AVAILABILITY.has(id)).map((id) => [id, clone(DEMO_AVAILABILITY.get(id)!)]));
      },
    },
    shipping: {
      async listGovernorates() {
        return clone(GOVERNORATES);
      },
      async listZones() {
        return clone(DEMO_SHIPPING_ZONES);
      },
      async quote({ governorate }) {
        const zone = DEMO_SHIPPING_ZONES.find((z) => z.governorates.includes(governorate));
        if (!zone) throw new ShippingUnavailableError(governorate);
        return { governorate, zoneId: zone.id, fee: zone.fee, demo: true };
      },
    },
    payments: {
      async listMethods() {
        return clone(DEMO_PAYMENT_METHODS);
      },
    },
    promotions: {
      async listPromotions() {
        return clone(DEMO_PROMOTIONS);
      },
    },
    orders: {
      async createOrder(request: PricedOrderRequest) {
        const existing = byRequest.get(request.requestId);
        if (existing) return clone(orders.get(existing)!);
        // A random suffix keeps demo order URLs unguessable (they show delivery details).
        const suffix = Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => b.toString(16).padStart(2, "0")).join("");
        const id = `DEMO-${++store.sequence}-${suffix}`;
        const order: Order = {
          id,
          requestId: request.requestId,
          createdAt: new Date().toISOString(),
          status: "demo",
          demo: true,
          customer: request.customer,
          paymentMethod: request.paymentMethod,
          lines: request.pricedLines,
          totals: request.totals,
        };
        orders.set(id, order);
        byRequest.set(request.requestId, id);
        return clone(order);
      },
      async getOrder(id) {
        return clone(orders.get(id) ?? null);
      },
    },
  };
}

/** Test helper: forget demo orders. */
export function resetDemoOrders() {
  orders.clear();
  byRequest.clear();
}
