/**
 * Storefront domain types. Money is always an integer number of piastres
 * (1 EGP = 100 piastres), the same unit StorePro stores, so values map across
 * the integration boundary without floating-point rounding.
 */

export type Locale = "en" | "ar";
export type LocalizedText = Record<Locale, string>;
export type Piastres = number;

export type CategoryIcon = "mouse" | "mousepad" | "skates" | "keyboard" | "headset" | "microphone" | "cable";

export interface Category {
  /** Stable storefront id; mapped to a StorePro category id in the integration. */
  id: string;
  slug: string;
  name: LocalizedText;
  description: LocalizedText;
  icon: CategoryIcon;
  sortOrder: number;
}

export interface Brand {
  id: string;
  slug: string;
  name: string;
}

export interface ProductImage {
  /** Site-relative path ("/images/...") or an https URL on an allow-listed host. */
  src: string;
  alt: LocalizedText;
  width: number;
  height: number;
}

export interface ProductSpec {
  label: LocalizedText;
  value: LocalizedText;
}

export interface Product {
  /** Stable storefront id. */
  id: string;
  /** StorePro SKU: the key used to map storefront products to StorePro inventory. */
  sku: string;
  slug: string;
  name: string;
  brandId: string;
  categoryId: string;
  summary: LocalizedText;
  description: LocalizedText;
  specs: ProductSpec[];
  /** Extra search terms (model aliases, switch types, connectivity…). */
  keywords: string[];
  images: ProductImage[];
  featured: boolean;
  /** 1 = best seller. Undefined = not ranked. */
  bestSellerRank?: number;
  /** ISO date the product was published on the storefront ("newest" sort). */
  publishedAt: string;
  /** Hard per-order cap (in addition to stock). */
  maxPerOrder: number;
}

export interface Price {
  productId: string;
  currency: "EGP";
  /** Current selling price. */
  amount: Piastres;
  /** Regular price, shown struck through only while a sale is valid. */
  compareAt?: Piastres;
  /** ISO timestamp; after it the sale is over and compareAt is ignored. */
  saleEndsAt?: string;
}

export type StockStatus = "in_stock" | "low_stock" | "out_of_stock" | "discontinued";

export interface Availability {
  productId: string;
  status: StockStatus;
  /** Units that can be sold right now (0 when unavailable). */
  quantity: number;
}

/** A product joined with everything a page needs to render it. */
export interface CatalogItem extends Product {
  brand: Brand;
  category: Category;
  price: Price;
  availability: Availability;
}

export type CatalogSort = "featured" | "newest" | "price-asc" | "price-desc";
export type StockFilter = "all" | "in-stock";

export interface CatalogQuery {
  q?: string;
  category?: string;
  brands?: string[];
  /** Inclusive bounds in whole EGP (as typed by shoppers). */
  minPrice?: number;
  maxPrice?: number;
  stock?: StockFilter;
  /** Only products with a valid (unexpired, genuinely lower) sale price. */
  onSale?: boolean;
  sort?: CatalogSort;
  page?: number;
  perPage?: number;
}

export interface CatalogResult {
  items: CatalogItem[];
  total: number;
  page: number;
  pageCount: number;
  perPage: number;
  facets: {
    brands: { brand: Brand; count: number }[];
    /** Whole EGP bounds of the matching items before price filtering. */
    priceRange: { min: number; max: number };
  };
}

export interface Promotion {
  id: string;
  title: LocalizedText;
  body: LocalizedText;
  /** Where the promotion links to (a catalog URL path without locale, e.g. "/products?category=gaming-mice"). */
  href: string;
  startsAt: string;
  endsAt: string;
  /** The promotion is only valid while at least one of these products is on a valid sale. */
  productIds: string[];
}

export interface ShippingZone {
  id: string;
  name: LocalizedText;
  governorates: string[];
  fee: Piastres;
}

export interface Governorate {
  id: string;
  name: LocalizedText;
}

export interface ShippingQuote {
  governorate: string;
  zoneId: string;
  fee: Piastres;
  /** True for demo fixtures: rates are illustrative, not a commitment. */
  demo: boolean;
}

export type PaymentMethodId = "cod" | "card" | "wallet";

export interface PaymentMethod {
  id: PaymentMethodId;
  label: LocalizedText;
  description: LocalizedText;
  enabled: boolean;
}

export interface CartLineInput {
  productId: string;
  quantity: number;
}

export type LineIssue = "unavailable" | "insufficient_stock" | "max_per_order" | "unknown_product" | "invalid_quantity";

export interface PricedLine {
  productId: string;
  sku: string;
  name: string;
  slug: string;
  image?: ProductImage;
  quantity: number;
  unitPrice: Piastres;
  /** Regular unit price when a valid sale applies, otherwise equal to unitPrice. */
  regularUnitPrice: Piastres;
  lineTotal: Piastres;
  maxQuantity: number;
  issue?: LineIssue;
}

export interface CartTotals {
  /** Sum of regular prices × quantity. */
  subtotal: Piastres;
  /** Savings from valid sale prices. */
  discount: Piastres;
  /** Shipping fee for the chosen governorate (0 until one is chosen). */
  shipping: Piastres;
  /** subtotal − discount + shipping. */
  total: Piastres;
  itemCount: number;
}

export interface CartQuote {
  lines: PricedLine[];
  totals: CartTotals;
  shipping?: ShippingQuote;
  /** False when any line has an issue: checkout must not proceed. */
  purchasable: boolean;
  currency: "EGP";
}

export interface CheckoutCustomer {
  name: string;
  phone: string;
  governorate: string;
  city: string;
  address: string;
  notes: string;
}

export interface CheckoutRequest {
  customer: CheckoutCustomer;
  lines: CartLineInput[];
  paymentMethod: PaymentMethodId;
  /** Client idempotency key: a resubmitted request returns the same order. */
  requestId: string;
}

export type OrderStatus = "demo" | "pending" | "confirmed" | "failed";

export interface Order {
  id: string;
  requestId: string;
  createdAt: string;
  status: OrderStatus;
  /** True when the order exists only in demo mode and was never sent anywhere. */
  demo: boolean;
  customer: CheckoutCustomer;
  paymentMethod: PaymentMethodId;
  lines: PricedLine[];
  totals: CartTotals;
}
