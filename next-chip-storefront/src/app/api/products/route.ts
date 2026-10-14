import type { NextRequest } from "next/server";
import { failure, json } from "@/lib/api";
import { storefront } from "@/lib/storefront";

/** Public product data for client views (wishlist). GET /api/products?ids=a,b,c */
export async function GET(request: NextRequest) {
  const ids = (request.nextUrl.searchParams.get("ids") ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter((s) => /^[a-z0-9-]{1,64}$/.test(s))
    .slice(0, 100);
  if (!ids.length) return json({ items: [] });
  try {
    const items = await storefront().getProductsByIds(ids);
    return json({ items: items.filter((i) => i.availability.status !== "discontinued") });
  } catch (e) {
    return failure(e);
  }
}
