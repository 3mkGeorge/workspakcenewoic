import type { NextRequest } from "next/server";
import { failure, json } from "@/lib/api";
import { storefront } from "@/lib/storefront";

/** Header search suggestions. GET /api/search?q=… → top matches (public fields only). */
export async function GET(request: NextRequest) {
  const q = (request.nextUrl.searchParams.get("q") ?? "").trim().slice(0, 80);
  if (q.length < 2) return json({ items: [] });
  try {
    const result = await storefront().queryCatalog({ q, perPage: 6 });
    return json({
      total: result.total,
      items: result.items.map((i) => ({
        id: i.id,
        slug: i.slug,
        name: i.name,
        brand: i.brand.name,
        sku: i.sku,
        image: i.images[0]?.src ?? "",
        price: i.price.amount,
      })),
    });
  } catch (e) {
    return failure(e);
  }
}
