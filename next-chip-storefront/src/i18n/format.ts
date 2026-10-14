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
