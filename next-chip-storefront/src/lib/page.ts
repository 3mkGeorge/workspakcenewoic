import "server-only";

import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { SITE } from "@/content/site";
import { isLocale, localePath } from "@/i18n/config";
import type { Locale } from "@/lib/commerce/types";
import { commerceMode } from "./commerce";
import { storefront } from "./storefront";

/** Validate the [locale] segment. */
export async function resolveLocale(params: Promise<{ locale: string }>): Promise<Locale> {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  return locale;
}

/**
 * Storefront access for pages that show prices or stock: opting into
 * request-time rendering so a cached page never shows stale prices.
 */
export async function liveStorefront() {
  await connection();
  return storefront();
}

/** Canonical + hreflang alternates for a locale-independent path. */
export function alternates(locale: Locale, path = "/"): Metadata["alternates"] {
  return {
    canonical: localePath(locale, path),
    languages: { en: localePath("en", path), ar: localePath("ar", path), "x-default": localePath("en", path) },
  };
}

/** Demo deployments must not be indexed: their products and prices are samples. */
export const indexable = () => commerceMode() !== "demo";

export const absoluteUrl = (path: string) => new URL(path, SITE.url).toString();
