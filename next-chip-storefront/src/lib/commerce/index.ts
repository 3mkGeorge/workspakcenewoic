import "server-only";

import { getCatalogStore } from "@/lib/catalog-db/server";
import { createDemoCommerce } from "./demo/providers";
import { ProviderUnavailableError, type Commerce, type CommerceMode } from "./providers";
import { createSyncedCommerce } from "./synced/providers";

/**
 * COMMERCE_MODE: "demo" (default when unset) or "synced". Any other value is a
 * configuration error: the site must never quietly fall back to demo products.
 */
export function commerceMode(): CommerceMode | "misconfigured" {
  const raw = (process.env.COMMERCE_MODE ?? "").trim();
  if (raw === "" || raw === "demo") return "demo";
  if (raw === "synced") return "synced";
  return "misconfigured";
}

let demo: Commerce | null = null;
let synced: Commerce | null = null;

/** The one place that decides which backend the storefront talks to. */
export async function getCommerce(): Promise<Commerce> {
  const mode = commerceMode();
  if (mode === "demo") return (demo ??= createDemoCommerce());
  if (mode === "synced") {
    // Throws ProviderUnavailableError (error page, never demo data) if the database is missing.
    const store = await getCatalogStore();
    return (synced ??= createSyncedCommerce(store));
  }
  throw new ProviderUnavailableError(`Unknown COMMERCE_MODE "${process.env.COMMERCE_MODE}". Use "demo" or "synced".`);
}
