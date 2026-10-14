import type { Metadata } from "next";
import { CatalogView } from "@/components/catalog/CatalogView";
import { getDictionary } from "@/i18n";
import { localePath } from "@/i18n/config";
import { pick } from "@/i18n/format";
import { loadCatalog } from "@/lib/catalog-page";
import { alternates, resolveLocale } from "@/lib/page";

export async function generateMetadata({ params, searchParams }: PageProps<"/[locale]/products">): Promise<Metadata> {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  const sp = await searchParams;
  return {
    title: sp.sale === "1" ? t.nav.deals : t.catalog.title,
    description: t.meta.description,
    alternates: alternates(locale, "/products"),
  };
}

export default async function ProductsPage({ params, searchParams }: PageProps<"/[locale]/products">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  const { ctx, result, filters, categories } = await loadCatalog(locale, "/products", await searchParams);
  const category = categories.find((c) => c.slug === ctx.query.category);
  const title = category ? pick(category.name, locale) : ctx.query.onSale ? t.nav.deals : t.catalog.title;
  return (
    <CatalogView
      ctx={ctx}
      t={t}
      result={result}
      filters={filters}
      title={title}
      intro={ctx.query.onSale ? <p>{t.catalog.dealsIntro}</p> : undefined}
      crumbs={[{ href: localePath(locale), label: t.product.home }, { label: title }]}
    />
  );
}
