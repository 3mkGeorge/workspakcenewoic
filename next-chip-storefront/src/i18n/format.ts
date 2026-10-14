import type { Locale } from "@/lib/commerce/types";

/** Fill "{name}" placeholders. */
export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (m, k: string) => (k in values ? String(values[k]) : m));
}

/** Pick the right language from a LocalizedText. */
export const pick = (text: Record<Locale, string>, locale: Locale) => text[locale] || text.en;

/**
 * Intl locale tags. Arabic uses Latin digits (as Egyptian online stores do) so
 * prices, counts, SKUs and phone numbers all read the same way.
 */
export const numberLocale = (locale: Locale) => (locale === "ar" ? "ar-EG-u-nu-latn" : "en-EG");
export const dateLocale = (locale: Locale) => (locale === "ar" ? "ar-EG-u-nu-latn" : "en-GB");

export function formatDate(value: string | Date, locale: Locale, options: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(dateLocale(locale), { timeZone: "Africa/Cairo", ...options }).format(new Date(value));
}

/** A count-dependent message. Arabic needs zero/one/two/few/many/other; English one/other. */
export type Plural = Partial<Record<Intl.LDMLPluralRule, string>> & { other: string };
export const plural = (forms: Plural): Plural => forms;

/** Pick the CLDR plural form for `count` and fill "{count}". */
export function countText(forms: Plural, count: number, locale: Locale): string {
  const rule = new Intl.PluralRules(locale === "ar" ? "ar-EG" : "en").select(count);
  return fill(forms[rule] ?? forms.other, { count });
}

/** "5 minutes ago" / "منذ 5 دقائق" for a past timestamp. */
export function relativeTime(iso: string, locale: Locale, now = Date.now()): string {
  const seconds = Math.round((Date.parse(iso) - now) / 1000);
  const rtf = new Intl.RelativeTimeFormat(locale === "ar" ? "ar-EG-u-nu-latn" : "en", { numeric: "auto" });
  const abs = Math.abs(seconds);
  if (abs < 60) return rtf.format(seconds, "second");
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), "hour");
  return rtf.format(Math.round(seconds / 86400), "day");
}
