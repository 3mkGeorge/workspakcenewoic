import "server-only";

import { pick } from "@/i18n/format";
import type { CatalogContext } from "@/lib/catalog-urls";
import type { FilterData } from "@/components/client/catalog";
import { parseCatalogQuery } from "@/lib/commerce/catalog-query";
import type { Locale } from "@/lib/commerce/types";
import { liveStorefront } from "./page";

type SearchParams = Record<string, string | string[] | undefined>;

/** Run a catalog listing for a page: parse the URL, query the providers, build filter data. */
export async function loadCatalog(locale: Locale, basePath: string, searchParams: SearchParams, fixedCategory?: string) {
  const query = parseCatalogQuery(searchParams);
  if (fixedCategory) query.category = fixedCategory;
  const view = (Array.isArray(searchParams.view) ? searchParams.view[0] : searchParams.view) === "list" ? "list" : "grid";
  const sf = await liveStorefront();
  const [result, categories] = await Promise.all([sf.queryCatalog(query), sf.listCategories()]);
  const ctx: CatalogContext = { locale, basePath, fixedCategory, view, query: { ...query, page: result.page } };
  const filters: FilterData = {
    categories: categories.map((c) => ({ slug: c.slug, name: pick(c.name, locale) })),
    brands: result.facets.brands,
    priceRange: result.facets.priceRange,
  };
  return { ctx, result, filters, categories };
}
