import "server-only";

import { createDemoCommerce } from "./demo/providers";
import type { Commerce, CommerceMode } from "./providers";
import { createStoreProCommerce } from "./storepro/providers";

let instance: Commerce | null = null;

export function commerceMode(): CommerceMode {
  return process.env.COMMERCE_MODE === "storepro" ? "storepro" : "demo";
}

/** The one place that decides which backend the storefront talks to. */
export function getCommerce(): Commerce {
  if (!instance) instance = commerceMode() === "storepro" ? createStoreProCommerce() : createDemoCommerce();
  return instance;
}
