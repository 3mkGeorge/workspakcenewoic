/**
 * Synchronized catalog providers: products, categories, brands, prices and
 * availability come from the catalog StorePro pushes (PostgreSQL). Stage 1
 * keeps shipping rates, payment methods and orders on the demo providers, and
 * the storefront labels them as such: no order reaches StorePro yet.
 */
import type { CatalogStore, CategoryRow, ProductRow } from "@/lib/catalog-db/store";
import { createDemoCommerce } from "../demo/providers";
import type { Commerce } from "../providers";
import type { Availability, Category, CategoryIcon, Price, Product } from "../types";

const EXT: Record<string, string> = { "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp" };
const ICONS: CategoryIcon[] = ["mouse", "mousepad", "skates", "keyboard", "headset", "microphone", "cable", "box"];
// StorePro category icons use Lucide names; map the ones we draw, the rest get a generic box.
const ICON_ALIASES: Record<string, CategoryIcon> = {
  "mouse-pointer": "mouse",
  "mouse-pointer-2": "mouse",
  headphones: "headset",
  "headset": "headset",
  mic: "microphone",
  "mic-vocal": "microphone",
  cable: "cable",
  usb: "cable",
  plug: "cable",
  keyboard: "keyboard",
};

export const mediaUrl = (hash: string, contentType: string) => `/media/${hash}.${EXT[contentType] ?? "bin"}`;

function summaryOf(text: string): string {
  const first = text.split(/(?<=[.!?؟])\s/)[0] ?? "";
  return first.length > 160 ? `${first.slice(0, 157).trimEnd()}…` : first;
}

export function toProduct(r: ProductRow): Product {
  const name = { en: r.name_en, ar: r.name_ar };
  return {
    id: r.id,
    sku: r.sku,
    slug: r.slug,
    name,
    brandId: r.brand_id,
    categoryId: r.category_id,
    summary: { en: summaryOf(r.description_en), ar: summaryOf(r.description_ar) },
    description: { en: r.description_en, ar: r.description_ar },
    specs: [],
    keywords: [],
    images: r.images.map((img, i) => ({
      src: mediaUrl(img.hash, img.contentType),
      alt: { en: i ? `${name.en} (${i + 1})` : name.en, ar: i ? `${name.ar} (${i + 1})` : name.ar },
      width: img.width,
      height: img.height,
    })),
    featured: false,
    publishedAt: new Date(r.source_created_at).toISOString().slice(0, 10),
    maxPerOrder: r.max_per_order,
  };
}

export const toPrice = (r: ProductRow): Price => ({
  productId: r.id,
  currency: "EGP",
  amount: Number(r.price),
  ...(r.compare_at !== null ? { compareAt: Number(r.compare_at) } : {}),
  ...(r.sale_ends_at ? { saleEndsAt: new Date(r.sale_ends_at).toISOString() } : {}),
});

export const toAvailability = (r: ProductRow): Availability => ({
  productId: r.id,
  status: r.availability,
  quantity: r.availability === "out_of_stock" ? 0 : r.orderable_quantity,
});

export function toCategory(r: CategoryRow): Category {
  const icon = (ICONS as string[]).includes(r.icon) ? (r.icon as CategoryIcon) : (ICON_ALIASES[r.icon] ?? "box");
  return {
    id: r.id,
    slug: r.slug,
    name: { en: r.name_en, ar: r.name_ar },
    description: { en: r.description_en, ar: r.description_ar },
    icon,
    sortOrder: r.sort_order,
  };
}

export function createSyncedCommerce(store: CatalogStore): Commerce {
  const demo = createDemoCommerce();
  const rowsByIds = async (ids: string[]) => store.getProductsByIds([...new Set(ids)].slice(0, 500));
  return {
    mode: "synced",
    capabilities: { catalog: "synced", shipping: "demo", orders: "demo" },
    catalog: {
      listProducts: async () => (await store.listProducts()).map(toProduct),
      getProductBySlug: async (slug) => {
        const r = await store.getProductBySlug(slug);
        return r ? toProduct(r) : null;
      },
      getProductsByIds: async (ids) => (await rowsByIds(ids)).map(toProduct),
    },
    categories: {
      listCategories: async () => (await store.listCategories()).map(toCategory),
      getCategory: async (slug) => {
        const r = await store.getCategory(slug);
        return r ? toCategory(r) : null;
      },
      listBrands: async () => (await store.listBrands()).map((b) => ({ id: b.id, slug: b.slug, name: b.name })),
    },
    pricing: {
      getPrices: async (ids) => new Map((await rowsByIds(ids)).map((r) => [r.id, toPrice(r)])),
    },
    availability: {
      getAvailability: async (ids) => new Map((await rowsByIds(ids)).map((r) => [r.id, toAvailability(r)])),
    },
    // Stage 1: illustrative rates, payment options and in-memory demo orders.
    shipping: demo.shipping,
    payments: demo.payments,
    promotions: { listPromotions: async () => [] },
    orders: demo.orders,
    freshness: async () => {
      const s = await store.syncState();
      return { lastSuccessAt: s.lastSuccessAt, lastCompleteAt: s.lastCompleteAt, publishedProducts: s.publishedProducts };
    },
  };
}
