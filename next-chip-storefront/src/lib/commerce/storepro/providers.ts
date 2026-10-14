/**
 * Placeholder for the future StorePro-backed providers.
 *
 * Intentionally NOT implemented: StorePro has no public storefront API yet.
 * Selecting COMMERCE_MODE=storepro fails loudly instead of silently showing
 * demo data as if it were live. Implement each provider against the contract
 * in STStorePro_INTEGRATION.md, server-side only, using STOREPRO_API_URL and
 * STOREPRO_API_TOKEN (never NEXT_PUBLIC_*). Do not read StorePro's SQLite file.
 */
import type { Commerce } from "../providers";
import { ProviderUnavailableError } from "../providers";

export function createStoreProCommerce(): Commerce {
  const fail = async (): Promise<never> => {
    throw new ProviderUnavailableError(
      "The StorePro storefront API is not implemented yet. Set COMMERCE_MODE=demo or implement the providers in src/lib/commerce/storepro.",
    );
  };
  return {
    mode: "storepro",
    catalog: { listProducts: fail, getProductBySlug: fail, getProductsByIds: fail },
    categories: { listCategories: fail, getCategory: fail, listBrands: fail },
    pricing: { getPrices: fail },
    availability: { getAvailability: fail },
    shipping: { listGovernorates: fail, listZones: fail, quote: fail },
    payments: { listMethods: fail },
    promotions: { listPromotions: fail },
    orders: { createOrder: fail, getOrder: fail },
  };
}
