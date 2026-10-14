import type { Locale, Piastres } from "./types";

const formatters = new Map<string, Intl.NumberFormat>();

/** Format piastres as EGP for the locale ("EGP 1,250.00" / "1,250.00 ج.م.‏" — Latin digits in both). */
export function formatEGP(amount: Piastres, locale: Locale): string {
  const key = locale;
  let fmt = formatters.get(key);
  if (!fmt) {
    fmt = new Intl.NumberFormat(locale === "ar" ? "ar-EG-u-nu-latn" : "en-EG", {
      style: "currency",
      currency: "EGP",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    formatters.set(key, fmt);
  }
  return fmt.format(amount / 100);
}

/** Whole EGP (as typed in a price filter) to piastres. */
export const egpToPiastres = (egp: number): Piastres => Math.round(egp * 100);

/** Piastres to whole EGP for filter bounds (rounded outwards by the caller). */
export const piastresToEgp = (amount: Piastres): number => amount / 100;

export function isValidPiastres(value: unknown): value is Piastres {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
