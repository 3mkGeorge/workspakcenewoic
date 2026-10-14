import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { CatalogView } from "@/components/catalog/CatalogView";
import { Icon } from "@/components/Icon";
import { getDictionary } from "@/i18n";
import { localePath } from "@/i18n/config";
import { pick } from "@/i18n/format";
import { loadCatalog } from "@/lib/catalog-page";
import { alternates, liveStorefront, resolveLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[locale]/categories/[slug]">): Promise<Metadata> {
  const locale = await resolveLocale(params);
  const { slug } = await params;
  const category = await (await liveStorefront()).getCategory(slug);
  if (!category) return {};
  return {
    title: pick(category.name, locale),
    description: pick(category.description, locale),
    alternates: alternates(locale, `/categories/${category.slug}`),
  };
}

export default async function CategoryPage({ params, searchParams }: PageProps<"/[locale]/categories/[slug]">) {
  const locale = await resolveLocale(params);
  const { slug } = await params;
  const t = getDictionary(locale);
  const category = await (await liveStorefront()).getCategory(slug);
  if (!category) notFound();
  const { ctx, result, filters } = await loadCatalog(locale, `/categories/${category.slug}`, await searchParams, category.slug);
  const name = pick(category.name, locale);
  return (
    <CatalogView
      ctx={ctx}
      t={t}
      result={result}
      filters={filters}
      title={name}
      crumbs={[
        { href: localePath(locale), label: t.product.home },
        { href: localePath(locale, "/products"), label: t.catalog.title },
        { label: name },
      ]}
      headExtra={
        <div className="cat-hero" style={{ marginTop: "var(--sp-3)" }}>
          <span className="cat-icon">
            <Icon name={category.icon} />
          </span>
          <div>
            <h1 style={{ marginTop: 0 }}>{name}</h1>
            <p>{pick(category.description, locale)}</p>
          </div>
        </div>
      }
    />
  );
}
