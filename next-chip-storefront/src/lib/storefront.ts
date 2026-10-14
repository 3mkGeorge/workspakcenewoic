import "server-only";

import { getCommerce } from "./commerce";
import { createStorefrontService, type StorefrontService } from "./commerce/service";

let service: StorefrontService | null = null;

/** Server-side entry point used by pages and route handlers. */
export function storefront(): StorefrontService {
  if (!service) service = createStorefrontService(getCommerce());
  return service;
}
