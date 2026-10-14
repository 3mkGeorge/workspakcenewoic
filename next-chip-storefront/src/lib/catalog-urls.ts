import { localePath } from "@/i18n/config";
import { catalogQueryToParams } from "@/lib/commerce/catalog-query";
import type { CatalogQuery, Locale } from "@/lib/commerce/types";

export type CatalogViewMode = "grid" | "list";

/** Where a catalog listing lives and what it currently shows. Serializable (passed to client components). */
export interface CatalogContext {
  locale: Locale;
  /** "/products", "/search" or "/categories/<slug>". */
  basePath: string;
  /** Set on category pages, where the category is part of the path rather than the query. */
  fixedCategory?: string;
  view: CatalogViewMode;
  query: CatalogQuery;
}

export type CatalogPatch = Partial<CatalogQuery> & { view?: CatalogViewMode };

/** Build a catalog URL from the current state plus a patch. Filter changes should pass page: undefined. */
export function catalogHref(ctx: CatalogContext, patch: CatalogPatch = {}): string {
  const { view = ctx.view, ...rest } = patch;
  const query: CatalogQuery = { ...ctx.query, ...rest };
  if (ctx.fixedCategory) query.category = undefined;
  const params = catalogQueryToParams(query);
  if (view === "list") params.set("view", "list");
  const search = params.toString();
  return localePath(ctx.locale, ctx.basePath) + (search ? `?${search}` : "");
}

/** Link to a category, keeping search, sort, stock/sale toggles and view; dropping brand/price/page. */
export function categoryHref(ctx: CatalogContext, slug: string | undefined): string {
  const reset: CatalogPatch = { brands: [], minPrice: undefined, maxPrice: undefined, page: undefined };
  if (ctx.basePath === "/search") return catalogHref(ctx, { ...reset, category: slug });
  if (!slug) return catalogHref({ ...ctx, basePath: "/products", fixedCategory: undefined }, { ...reset, category: undefined });
  return catalogHref({ ...ctx, basePath: `/categories/${slug}`, fixedCategory: slug }, reset);
}

/** Number of filters a shopper has applied (category pages don't count their own category). */
export function activeFilterCount(ctx: CatalogContext): number {
  const q = ctx.query;
  return (
    (q.brands?.length ?? 0) +
    (q.minPrice !== undefined || q.maxPrice !== undefined ? 1 : 0) +
    (q.stock === "in-stock" ? 1 : 0) +
    (q.onSale ? 1 : 0) +
    (q.category && !ctx.fixedCategory ? 1 : 0)
  );
}

/** Page numbers to show: first, last, and a window around the current page; null = gap. */
export function pageWindow(page: number, count: number): (number | null)[] {
  const pages = new Set([1, count, page - 1, page, page + 1].filter((p) => p >= 1 && p <= count));
  const sorted = [...pages].sort((a, b) => a - b);
  const out: (number | null)[] = [];
  sorted.forEach((p, i) => {
    if (i > 0 && p - sorted[i - 1]! > 1) out.push(null);
    out.push(p);
  });
  return out;
}
