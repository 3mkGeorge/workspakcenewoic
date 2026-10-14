import type { NextRequest } from "next/server";
import { failure, json, readJson } from "@/lib/api";
import { storefront } from "@/lib/storefront";

/**
 * Place an order with the active provider. The body supplies customer details,
 * product ids, quantities, payment method and an idempotency key; prices and
 * totals are recomputed server-side and anything else in the body is ignored.
 */
export async function POST(request: NextRequest) {
  const parsed = await readJson(request);
  if (!parsed.ok) return parsed.response;
  try {
    const result = await storefront().placeOrder(parsed.body);
    if (result.ok) {
      const { order } = result;
      return json({ ok: true, order: { id: order.id, status: order.status, demo: order.demo, createdAt: order.createdAt, totals: order.totals } }, 201);
    }
    if (result.reason === "invalid") return json({ ok: false, reason: "invalid", errors: result.errors }, 422);
    if (result.reason === "cart") return json({ ok: false, reason: "cart", quote: result.quote }, 409);
    return json({ ok: false, reason: "shipping" }, 422);
  } catch (e) {
    return failure(e);
  }
}
