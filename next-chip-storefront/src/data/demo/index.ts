/**
 * DEMO FIXTURES loader. Turns the compact products.json into storefront types.
 * Images are generated SVG renders (scripts/generate-product-art.mjs), not photos.
 */
import type { Availability, LocalizedText, Price, Product, ProductSpec, StockStatus } from "@/lib/commerce/types";
import raw from "./products.json";

interface RawProduct {
  id: string;
  sku: string;
  slug: string;
  name: string;
  brand: string;
  category: string;
  summary: LocalizedText;
  description: LocalizedText;
  specs: string[][];
  keywords: string[];
  featured: boolean;
  rank: number | null;
  published: string;
  max: number;
  price: number;
  compareAt: number | null;
  saleEnds: string | null;
  stock: number;
  discontinued: boolean;
}

const SPEC_LABELS: Record<string, LocalizedText> = {
  weight: { en: "Weight", ar: "الوزن" },
  sensor: { en: "Sensor", ar: "الحساس" },
  polling: { en: "Polling rate", ar: "معدل الاستجابة" },
  connectivity: { en: "Connectivity", ar: "الاتصال" },
  battery: { en: "Battery", ar: "البطارية" },
  shape: { en: "Shape", ar: "الشكل" },
  surface: { en: "Surface", ar: "السطح" },
  size: { en: "Size", ar: "المقاس" },
  thickness: { en: "Thickness", ar: "السُمك" },
  base: { en: "Base", ar: "القاعدة" },
  material: { en: "Material", ar: "الخامة" },
  count: { en: "In the box", ar: "محتوى العلبة" },
  compatibility: { en: "Compatibility", ar: "التوافق" },
  layout: { en: "Layout", ar: "التخطيط" },
  switches: { en: "Switches", ar: "المفاتيح" },
  keycaps: { en: "Keycaps", ar: "أغطية المفاتيح" },
  driver: { en: "Driver", ar: "المشغل" },
  mic: { en: "Microphone", ar: "الميكروفون" },
  frequency: { en: "Frequency response", ar: "الاستجابة الترددية" },
  connector: { en: "Connector", ar: "الموصل" },
  type: { en: "Type", ar: "النوع" },
  sampleRate: { en: "Sample rate", ar: "معدل العينة" },
  mount: { en: "Mount", ar: "التثبيت" },
  length: { en: "Length", ar: "الطول" },
};

const IMAGE_VIEWS: LocalizedText[] = [
  { en: "front view", ar: "منظر أمامي" },
  { en: "angled view", ar: "منظر مائل" },
  { en: "detail view", ar: "منظر تفصيلي" },
];

const rows = raw as unknown as RawProduct[];

function toProduct(p: RawProduct): Product {
  const specs: ProductSpec[] = p.specs.map(([key, en, ar]) => ({
    label: SPEC_LABELS[key!] ?? { en: key!, ar: key! },
    value: { en: en!, ar: ar ?? en! },
  }));
  return {
    id: p.id,
    sku: p.sku,
    slug: p.slug,
    name: p.name,
    brandId: p.brand,
    categoryId: p.category,
    summary: p.summary,
    description: p.description,
    specs,
    keywords: p.keywords,
    images: IMAGE_VIEWS.map((view, i) => ({
      src: `/images/products/${p.slug}-${i + 1}.svg`,
      alt: { en: `${p.name}, ${view.en}`, ar: `${p.name}، ${view.ar}` },
      width: 800,
      height: 800,
    })),
    featured: p.featured,
    bestSellerRank: p.rank ?? undefined,
    publishedAt: p.published,
    maxPerOrder: p.max,
  };
}

function toAvailability(p: RawProduct): Availability {
  let status: StockStatus = "in_stock";
  if (p.discontinued) status = "discontinued";
  else if (p.stock <= 0) status = "out_of_stock";
  else if (p.stock <= 5) status = "low_stock";
  return { productId: p.id, status, quantity: p.discontinued ? 0 : Math.max(0, p.stock) };
}

function toPrice(p: RawProduct): Price {
  return {
    productId: p.id,
    currency: "EGP",
    amount: p.price,
    ...(p.compareAt ? { compareAt: p.compareAt } : {}),
    ...(p.saleEnds ? { saleEndsAt: p.saleEnds } : {}),
  };
}

/** Published = everything except discontinued items. */
export const DEMO_PRODUCTS: Product[] = rows.filter((p) => !p.discontinued).map(toProduct);
export const DEMO_ALL_PRODUCTS: Product[] = rows.map(toProduct);
export const DEMO_PRICES = new Map(rows.map((p) => [p.id, toPrice(p)]));
export const DEMO_AVAILABILITY = new Map(rows.map((p) => [p.id, toAvailability(p)]));
