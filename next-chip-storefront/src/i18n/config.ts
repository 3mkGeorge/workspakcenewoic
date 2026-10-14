import type { Locale } from "@/lib/commerce/types";

export const LOCALES: Locale[] = ["en", "ar"];
export const DEFAULT_LOCALE: Locale = "en";
export const LOCALE_COOKIE = "NEXT_LOCALE";

export const isLocale = (value: unknown): value is Locale => value === "en" || value === "ar";
export const dirOf = (locale: Locale) => (locale === "ar" ? "rtl" : "ltr");
export const otherLocale = (locale: Locale): Locale => (locale === "ar" ? "en" : "ar");

/** Prefix a site path (starting with "/") with the locale. */
export const localePath = (locale: Locale, path = "/") => `/${locale}${path === "/" ? "" : path}`;
