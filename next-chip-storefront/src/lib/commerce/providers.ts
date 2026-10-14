/**
 * The integration boundary. Pages and route handlers only talk to these
 * interfaces (through `getCommerce()`), never to fixtures or HTTP clients
 * directly, so the demo providers can be swapped for StorePro-backed ones.
 * See STStorePro_INTEGRATION.md for the matching API contract.
 */
import type {
  Availability,
  Brand,
  Category,
  Governorate,
  Order,
  PaymentMethod,
  Price,
  PricedLine,
  Product,
  Promotion,
  ShippingQuote,
  ShippingZone,
  CheckoutRequest,
  CartTotals,
} from "./types";

export interface CatalogProvider {
  /** Published products only. */
  listProducts(): Promise<Product[]>;
  getProductBySlug(slug: string): Promise<Product | null>;
  getProductsByIds(ids: string[]): Promise<Product[]>;
}

export interface CategoryProvider {
  listCategories(): Promise<Category[]>;
  getCategory(slug: string): Promise<Category | null>;
  listBrands(): Promise<Brand[]>;
}

export interface PricingProvider {
  /** Authoritative current prices. Missing ids are simply absent from the map. */
  getPrices(productIds: string[]): Promise<Map<string, Price>>;
}

export interface AvailabilityProvider {
  getAvailability(productIds: string[]): Promise<Map<string, Availability>>;
}

export interface ShippingQuoteProvider {
  listGovernorates(): Promise<Governorate[]>;
  listZones(): Promise<ShippingZone[]>;
  /** Throws ShippingUnavailableError for governorates that cannot be served. */
  quote(input: { governorate: string; itemCount: number; subtotal: number }): Promise<ShippingQuote>;
}

export interface PaymentProvider {
  /** Methods the storefront may offer; only enabled ones are shown. */
  listMethods(): Promise<PaymentMethod[]>;
}

export interface PromotionProvider {
  listPromotions(): Promise<Promotion[]>;
}

/** A checkout request after the server has re-priced it. */
export interface PricedOrderRequest extends CheckoutRequest {
  pricedLines: PricedLine[];
  totals: CartTotals;
  shipping: ShippingQuote;
}

export interface OrderProvider {
  /**
   * Submit a re-priced order. Must be idempotent on `requestId`.
   * Demo providers keep the order in memory and mark it `demo: true`.
   */
  createOrder(request: PricedOrderRequest): Promise<Order>;
  getOrder(id: string): Promise<Order | null>;
}

export type CommerceMode = "demo" | "storepro";

export interface Commerce {
  mode: CommerceMode;
  catalog: CatalogProvider;
  categories: CategoryProvider;
  pricing: PricingProvider;
  availability: AvailabilityProvider;
  shipping: ShippingQuoteProvider;
  payments: PaymentProvider;
  promotions: PromotionProvider;
  orders: OrderProvider;
}

/** The active backend cannot be reached or is not configured. Pages show an error state. */
export class ProviderUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProviderUnavailableError";
  }
}

export class ShippingUnavailableError extends Error {
  constructor(public readonly governorate: string) {
    super(`Shipping is not available to ${governorate}.`);
    this.name = "ShippingUnavailableError";
  }
}
