/**
 * Server-side cart pricing. The browser only ever sends product ids and
 * quantities; every price, limit and total below comes from the providers.
 */
import { effectiveSale } from "./pricing";
import type { Availability, CartLineInput, CartTotals, LineIssue, Price, PricedLine, Product } from "./types";

export const MAX_LINES = 50;
export const MAX_QUANTITY = 99;

/** Merge duplicate product lines and drop malformed ones (ids are opaque strings). */
export function normalizeLines(raw: unknown): CartLineInput[] {
  if (!Array.isArray(raw)) return [];
  const merged = new Map<string, number>();
  for (const entry of raw.slice(0, MAX_LINES * 2)) {
    if (!entry || typeof entry !== "object") continue;
    const { productId, quantity } = entry as Record<string, unknown>;
    if (typeof productId !== "string" || !/^[a-z0-9-]{1,64}$/.test(productId)) continue;
    if (typeof quantity !== "number" || !Number.isInteger(quantity) || quantity < 1) continue;
    merged.set(productId, Math.min(MAX_QUANTITY, (merged.get(productId) ?? 0) + quantity));
  }
  return [...merged].slice(0, MAX_LINES).map(([productId, quantity]) => ({ productId, quantity }));
}

export function priceLines(
  lines: CartLineInput[],
  products: Map<string, Product>,
  prices: Map<string, Price>,
  availability: Map<string, Availability>,
  now = new Date(),
): PricedLine[] {
  return lines.map((line) => {
    const product = products.get(line.productId);
    const price = prices.get(line.productId);
    const stock = availability.get(line.productId);
    if (!product || !price) {
      return {
        productId: line.productId,
        sku: "",
        name: "",
        slug: "",
        quantity: line.quantity,
        unitPrice: 0,
        regularUnitPrice: 0,
        lineTotal: 0,
        maxQuantity: 0,
        issue: "unknown_product" as LineIssue,
      };
    }
    const sale = effectiveSale(price, now);
    const sellable =
      stock && (stock.status === "in_stock" || stock.status === "low_stock") ? Math.max(0, stock.quantity) : 0;
    const maxQuantity = Math.min(sellable, product.maxPerOrder, MAX_QUANTITY);
    let issue: LineIssue | undefined;
    if (sellable === 0) issue = "unavailable";
    else if (line.quantity > sellable) issue = "insufficient_stock";
    else if (line.quantity > product.maxPerOrder) issue = "max_per_order";
    return {
      productId: product.id,
      sku: product.sku,
      name: product.name,
      slug: product.slug,
      image: product.images[0],
      quantity: line.quantity,
      unitPrice: sale.amount,
      regularUnitPrice: sale.regular,
      lineTotal: sale.amount * line.quantity,
      maxQuantity,
      issue,
    };
  });
}

/**
 * Totals shown in cart and checkout. Only lines without issues count, so a
 * total is never displayed for items that cannot actually be bought.
 * total = subtotal (regular prices) − discount (valid sale savings) + shipping.
 */
export function computeTotals(lines: PricedLine[], shippingFee: number): CartTotals {
  const counted = lines.filter((l) => !l.issue);
  const subtotal = counted.reduce((s, l) => s + l.regularUnitPrice * l.quantity, 0);
  const discount = counted.reduce((s, l) => s + (l.regularUnitPrice - l.unitPrice) * l.quantity, 0);
  const itemCount = counted.reduce((s, l) => s + l.quantity, 0);
  const shipping = itemCount > 0 ? shippingFee : 0;
  return { subtotal, discount, shipping, total: subtotal - discount + shipping, itemCount };
}
