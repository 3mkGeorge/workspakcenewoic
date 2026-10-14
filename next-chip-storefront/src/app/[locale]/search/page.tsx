import type { Metadata } from "next";
import { CatalogView } from "@/components/catalog/CatalogView";
import { SearchBox } from "@/components/client/header";
import { Icon } from "@/components/Icon";
import { getDictionary } from "@/i18n";
import { localePath } from "@/i18n/config";
import { fill } from "@/i18n/format";
import { loadCatalog } from "@/lib/catalog-page";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { resolveLocale } from "@/lib/page";

export async function generateMetadata({ params, searchParams }: PageProps<"/[locale]/search">): Promise<Metadata> {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  const q = (await searchParams).q;
  const term = (Array.isArray(q) ? q[0] : q)?.trim().slice(0, 80);
  // Search result pages are never indexed.
  return { title: term ? fill(t.catalog.searchFor, { q: term }) : t.catalog.searchTitle, robots: { index: false, follow: true } };
}

export default async function SearchPage({ params, searchParams }: PageProps<"/[locale]/search">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  const sp = await searchParams;
  const crumbs = [{ href: localePath(locale), label: t.product.home }, { label: t.catalog.searchTitle }];
  const raw = (Array.isArray(sp.q) ? sp.q[0] : sp.q)?.trim();
  if (!raw) {
    return (
      <div className="container">
        <header className="page-head">
          <Breadcrumbs items={crumbs} label={t.common.breadcrumbs} />
          <h1>{t.catalog.searchTitle}</h1>
        </header>
        <div className="card empty">
          <span className="empty-icon">
            <Icon name="search" />
          </span>
          <p>{t.catalog.searchEmpty}</p>
          <div style={{ width: "min(100%, 480px)" }}>
            <SearchBox />
          </div>
        </div>
      </div>
    );
  }
  const { ctx, result, filters } = await loadCatalog(locale, "/search", sp);
  const title = fill(t.catalog.searchFor, { q: ctx.query.q ?? raw });
  return (
    <CatalogView
      ctx={ctx}
      t={t}
      result={result}
      filters={filters}
      title={title}
      crumbs={crumbs}
      intro={
        <div style={{ marginTop: "var(--sp-4)", maxWidth: 480 }}>
          <SearchBox key={ctx.query.q} defaultValue={ctx.query.q} />
        </div>
      }
    />
  );
}
