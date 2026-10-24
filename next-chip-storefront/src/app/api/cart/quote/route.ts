import type { NextRequest } from "next/server";
import { failure, json, readJson } from "@/lib/api";
import { ShippingUnavailableError } from "@/lib/commerce/providers";
import { storefront } from "@/lib/storefront";

/** Authoritative cart pricing. Body: { lines: [{ productId, quantity }], governorate? }. */
export async function POST(request: NextRequest) {
  const parsed = await readJson(request);
  if (!parsed.ok) return parsed.response;
  const body = (parsed.body && typeof parsed.body === "object" ? parsed.body : {}) as Record<string, unknown>;
  const governorate = typeof body.governorate === "string" && /^[a-z-]{1,40}$/.test(body.governorate) ? body.governorate : undefined;
  try {
    const sf = await storefront();
    if (governorate && !(await sf.listGovernorates()).some((g) => g.id === governorate)) {
      return json({ quote: await sf.quoteCart(body.lines), shippingError: "unknown_governorate" });
    }
    try {
      return json({ quote: await sf.quoteCart(body.lines, governorate) });
    } catch (e) {
      if (e instanceof ShippingUnavailableError) return json({ quote: await sf.quoteCart(body.lines), shippingError: "unavailable" });
      throw e;
    }
  } catch (e) {
    return failure(e);
  }
}
