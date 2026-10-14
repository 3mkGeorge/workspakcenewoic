import { json } from "@/lib/api";
import { commerceMode } from "@/lib/commerce";
import { isStale, staleAfterMinutes } from "@/lib/freshness";
import { storefront } from "@/lib/storefront";

/**
 * Public catalog freshness for the storefront banner. Deliberately minimal:
 * no error text, snapshot ids or internals (those are on the signed status endpoint).
 */
export async function GET() {
  const mode = commerceMode();
  if (mode !== "synced") return json({ mode });
  try {
    const f = await (await storefront()).freshness();
    return json({
      mode,
      available: true,
      lastUpdatedAt: f?.lastSuccessAt ?? null,
      published: (f?.publishedProducts ?? 0) > 0,
      stale: isStale(f?.lastSuccessAt ?? null),
      staleAfterMinutes: staleAfterMinutes(),
    });
  } catch {
    return json({ mode, available: false }, 503);
  }
}
