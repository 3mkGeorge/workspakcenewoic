import Link from "next/link";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { CatalogLink, CatalogShell, FiltersButton, FilterPanel, Results, SortSelect, ViewToggle, type FilterData } from "@/components/client/catalog";
import { Icon } from "@/components/Icon";
import { ProductGrid } from "@/components/Product";
import type { Dictionary } from "@/i18n/dictionaries/en";
import { countText, fill } from "@/i18n/format";
import { localePath } from "@/i18n/config";
import { activeFilterCount, catalogHref, pageWindow, type CatalogContext } from "@/lib/catalog-urls";
import { formatEGP } from "@/lib/commerce/money";
import type { CatalogResult } from "@/lib/commerce/types";

interface Props {
  ctx: CatalogContext;
  t: Dictionary;
  result: CatalogResult;
  filters: FilterData;
  title: string;
  intro?: React.ReactNode;
  crumbs: { href?: string; label: string }[];
  headExtra?: React.ReactNode;
}

function ActiveChips({ ctx, t, filters }: { ctx: CatalogContext; t: Dictionary; filters: FilterData }) {
  const q = ctx.query;
  const chips: { key: string; label: string; href: string }[] = [];
  if (q.category && !ctx.fixedCategory) {
    const name = filters.categories.find((c) => c.slug === q.category)?.name ?? q.category;
    chips.push({ key: "cat", label: name, href: catalogHref(ctx, { category: undefined, page: undefined }) });
  }
  for (const slug of q.brands ?? []) {
    const name = filters.brands.find((b) => b.brand.slug === slug)?.brand.name ?? slug;
    chips.push({ key: `b-${slug}`, label: name, href: catalogHref(ctx, { brands: q.brands!.filter((b) => b !== slug), page: undefined }) });
  }
  if (q.minPrice !== undefined || q.maxPrice !== undefined) {
    const lo = q.minPrice !== undefined ? formatEGP(q.minPrice * 100, ctx.locale) : "…";
    const hi = q.maxPrice !== undefined ? formatEGP(q.maxPrice * 100, ctx.locale) : "…";
    chips.push({ key: "price", label: `${lo} – ${hi}`, href: catalogHref(ctx, { minPrice: undefined, maxPrice: undefined, page: undefined }) });
  }
  if (q.stock === "in-stock") chips.push({ key: "stock", label: t.catalog.inStockOnly, href: catalogHref(ctx, { stock: "all", page: undefined }) });
  if (q.onSale) chips.push({ key: "sale", label: t.catalog.onSaleOnly, href: catalogHref(ctx, { onSale: false, page: undefined }) });
  if (!chips.length) return null;
  return (
    <div className="chips" aria-label={t.catalog.activeFilters} role="group">
      {chips.map((chip) => (
        <CatalogLink key={chip.key} className="chip" href={chip.href} aria-label={fill(t.catalog.removeFilter, { name: chip.label })}>
          <span dir="auto">{chip.label}</span>
          <Icon name="close" />
        </CatalogLink>
      ))}
      {chips.length > 1 && (
        <CatalogLink className="chip chip-clear" href={catalogHref(ctx, { category: undefined, brands: [], minPrice: undefined, maxPrice: undefined, stock: "all", onSale: false, page: undefined })}>
          {t.catalog.clearAll}
        </CatalogLink>
      )}
    </div>
  );
}

function Pagination({ ctx, t, result }: { ctx: CatalogContext; t: Dictionary; result: CatalogResult }) {
  if (result.pageCount <= 1) return null;
  const { page, pageCount } = result;
  return (
    <nav className="pagination" aria-label={fill(t.catalog.page, { page, count: pageCount })}>
      {page > 1 ? (
        <CatalogLink className="btn btn-outline" href={catalogHref(ctx, { page: page - 1 })} scroll rel="prev">
          <Icon name="chevronLeft" className="flip-rtl" />
          {t.catalog.prev}
        </CatalogLink>
      ) : (
        <span className="btn btn-outline" aria-disabled="true">
          <Icon name="chevronLeft" className="flip-rtl" />
          {t.catalog.prev}
        </span>
      )}
      {pageWindow(page, pageCount).map((p, i) =>
        p === null ? (
          <span key={`gap-${i}`} className="muted" aria-hidden="true">
            …
          </span>
        ) : (
          <CatalogLink
            key={p}
            className={`btn btn-outline page-num${p === page ? " is-current" : ""}`}
            href={catalogHref(ctx, { page: p })}
            aria-current={p === page ? "page" : undefined}
            aria-label={fill(t.catalog.page, { page: p, count: pageCount })}
            scroll
          >
            <span className="num">{p}</span>
          </CatalogLink>
        ),
      )}
      {page < pageCount ? (
        <CatalogLink className="btn btn-outline" href={catalogHref(ctx, { page: page + 1 })} scroll rel="next">
          {t.catalog.next}
          <Icon name="chevronRight" className="flip-rtl" />
        </CatalogLink>
      ) : (
        <span className="btn btn-outline" aria-disabled="true">
          {t.catalog.next}
          <Icon name="chevronRight" className="flip-rtl" />
        </span>
      )}
    </nav>
  );
}

/** Shared listing for /products, /categories/[slug] and /search. All state lives in the URL. */
export function CatalogView({ ctx, t, result, filters, title, intro, crumbs, headExtra }: Props) {
  const filtered = activeFilterCount(ctx) > 0;
  return (
    <CatalogShell ctx={ctx}>
      <div className="container">
        <header className="page-head">
          <Breadcrumbs items={crumbs} label={t.common.breadcrumbs} />
          {headExtra ?? <h1>{title}</h1>}
          {intro}
        </header>
        <div className="catalog">
          <aside className="filters-aside" aria-label={t.catalog.filters}>
            <FilterPanel data={filters} />
          </aside>
          <section aria-label={title}>
            <div className="toolbar">
              <FiltersButton data={filters} total={result.total} />
              <p className="result-count" aria-live="polite">
                {countText(t.catalog.results, result.total, ctx.locale)}
              </p>
              <SortSelect />
              <ViewToggle />
            </div>
            <ActiveChips ctx={ctx} t={t} filters={filters} />
            <Results>
              {result.items.length ? (
                <>
                  <ProductGrid items={result.items} locale={ctx.locale} t={t} view={ctx.view} priorityCount={2} headingLevel={2} />
                  <Pagination ctx={ctx} t={t} result={result} />
                </>
              ) : (
                <div className="empty card">
                  <span className="empty-icon">
                    <Icon name="search" />
                  </span>
                  <h2>{t.catalog.emptyTitle}</h2>
                  <p>{t.catalog.emptyBody}</p>
                  {filtered ? (
                    <CatalogLink
                      className="btn btn-primary"
                      href={catalogHref(ctx, { category: undefined, brands: [], minPrice: undefined, maxPrice: undefined, stock: "all", onSale: false, page: undefined })}
                    >
                      {t.catalog.clearAll}
                    </CatalogLink>
                  ) : (
                    <Link className="btn btn-primary" href={localePath(ctx.locale, "/products")}>
                      {t.nav.browseAll}
                    </Link>
                  )}
                </div>
              )}
            </Results>
          </section>
        </div>
      </div>
    </CatalogShell>
  );
}
