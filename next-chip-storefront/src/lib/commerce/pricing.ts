import type { Price, Promotion } from "./types";

/**
 * The price a shopper pays right now. A sale (compareAt) counts only while it
 * is genuinely lower than the regular price and has not ended.
 */
export function effectiveSale(price: Price, now = new Date()): { amount: number; regular: number; onSale: boolean } {
  const active =
    price.compareAt !== undefined &&
    price.compareAt > price.amount &&
    (!price.saleEndsAt || Date.parse(price.saleEndsAt) > now.getTime());
  return active
    ? { amount: price.amount, regular: price.compareAt!, onSale: true }
    : { amount: price.amount, regular: price.amount, onSale: false };
}

export function discountPercent(price: Price, now = new Date()): number | null {
  const s = effectiveSale(price, now);
  if (!s.onSale) return null;
  return Math.round(((s.regular - s.amount) / s.regular) * 100);
}

/** A promotion is shown only inside its window and while one of its products is really on sale. */
export function isPromotionValid(promo: Promotion, salePrices: Map<string, Price>, now = new Date()): boolean {
  const t = now.getTime();
  if (!(Date.parse(promo.startsAt) <= t && t < Date.parse(promo.endsAt))) return false;
  return promo.productIds.some((id) => {
    const p = salePrices.get(id);
    return p ? effectiveSale(p, now).onSale : false;
  });
}
