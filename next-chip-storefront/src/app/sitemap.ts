import type { MetadataRoute } from "next";
import { SITE } from "@/content/site";
import { LOCALES, localePath } from "@/i18n/config";
import { storefront } from "@/lib/storefront";

export const dynamic = "force-dynamic";

const STATIC = ["/", "/products", "/about", "/contact", "/shipping-policy", "/returns", "/privacy", "/terms"];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const url = (path: string) => new URL(path, SITE.url).toString();
  const entry = (path: string, lastModified?: string): MetadataRoute.Sitemap[number] => ({
    url: url(localePath("en", path)),
    lastModified,
    alternates: { languages: Object.fromEntries(LOCALES.map((l) => [l, url(localePath(l, path))])) },
  });
  let dynamicPaths: MetadataRoute.Sitemap = [];
  try {
    const sf = await storefront();
    const [categories, catalog] = await Promise.all([sf.listCategories(), sf.queryCatalog({ perPage: 1000 })]);
    dynamicPaths = [
      ...categories.map((c) => entry(`/categories/${c.slug}`)),
      ...catalog.items.map((p) => entry(`/products/${p.slug}`, p.publishedAt)),
    ];
  } catch {
    // Catalog unavailable: publish the static pages only.
  }
  return [...STATIC.map((p) => entry(p)), ...dynamicPaths];
}
