import "server-only";

import { getCommerce } from "./commerce";
import { createStorefrontService, type StorefrontService } from "./commerce/service";
import type { Commerce } from "./commerce/providers";

const services = new WeakMap<Commerce, StorefrontService>();

/** Server-side entry point used by pages and route handlers. */
export async function storefront(): Promise<StorefrontService> {
  const commerce = await getCommerce();
  let service = services.get(commerce);
  if (!service) {
    service = createStorefrontService(commerce);
    services.set(commerce, service);
  }
  return service;
}
