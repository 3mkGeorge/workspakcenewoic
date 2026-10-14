import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { Gallery } from "@/components/client/gallery";
import { BuyBox } from "@/components/client/product-actions";
import { JsonLd } from "@/components/JsonLd";
import { Price, ProductGrid, purchasableQuantity, StockLabel } from "@/components/Product";
import { getDictionary } from "@/i18n";
import { localePath } from "@/i18n/config";
import { dateLocale, fill, pick } from "@/i18n/format";
import { discountPercent, effectiveSale } from "@/lib/commerce/pricing";
import { safeImageSrc } from "@/lib/commerce/safe-image";
import { absoluteUrl, alternates, liveStorefront, resolveLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[locale]/products/[slug]">): Promise<Metadata> {
  const locale = await resolveLocale(params);
  const { slug } = await params;
  const data = await (await liveStorefront()).getProduct(slug);
  if (!data) return { title: getDictionary(locale).product.notFoundTitle };
  const { item } = data;
  const image = item.images[0];
  return {
    title: item.name,
    description: pick(item.summary, locale),
    alternates: alternates(locale, `/products/${item.slug}`),
    openGraph: {
      title: item.name,
      description: pick(item.summary, locale),
      images: image ? [{ url: safeImageSrc(image.src), width: image.width, height: image.height, alt: pick(image.alt, locale) }] : undefined,
    },
  };
}

export default async function ProductPage({ params }: PageProps<"/[locale]/products/[slug]">) {
  const locale = await resolveLocale(params);
  const { slug } = await params;
  const t = getDictionary(locale);
  const data = await (await liveStorefront()).getProduct(slug);
  if (!data) notFound();
  const { item, related } = data;
  const sale = effectiveSale(item.price);
  const percent = discountPercent(item.price);
  const max = purchasableQuantity(item);
  const url = absoluteUrl(localePath(locale, `/products/${item.slug}`));
  const categoryName = pick(item.category.name, locale);
  const dateFmt = new Intl.DateTimeFormat(dateLocale(locale), { day: "numeric", month: "long", year: "numeric", timeZone: "Africa/Cairo" });

  const crumbs = [
    { href: localePath(locale), label: t.product.home },
    { href: localePath(locale, `/categories/${item.category.slug}`), label: categoryName },
    { label: item.name },
  ];

  return (
    <>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "Product",
          name: item.name,
          sku: item.sku,
          description: pick(item.description, locale),
          image: item.images.map((img) => absoluteUrl(safeImageSrc(img.src))),
          brand: { "@type": "Brand", name: item.brand.name },
          category: categoryName,
          url,
          offers: {
            "@type": "Offer",
            url,
            priceCurrency: "EGP",
            price: (sale.amount / 100).toFixed(2),
            ...(sale.onSale && item.price.saleEndsAt ? { priceValidUntil: item.price.saleEndsAt.slice(0, 10) } : {}),
            availability: max > 0 ? "https://schema.org/InStock" : "https://schema.org/OutOfStock",
            itemCondition: "https://schema.org/NewCondition",
          },
        }}
      />
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "BreadcrumbList",
          itemListElement: crumbs.map((c, i) => ({
            "@type": "ListItem",
            position: i + 1,
            name: c.label,
            ...(c.href ? { item: absoluteUrl(c.href) } : {}),
          })),
        }}
      />
      <div className="container">
        <div style={{ paddingTop: "var(--sp-6)" }}>
          <Breadcrumbs items={crumbs} label={t.common.breadcrumbs} />
        </div>
        <div className="pdp">
          <Gallery
            name={item.name}
            images={item.images.map((img) => ({ src: safeImageSrc(img.src), alt: pick(img.alt, locale), width: img.width, height: img.height }))}
          />
          <div className="pdp-buy">
            <div>
              <span className="pdp-brand">{item.brand.name}</span>
              <h1>{item.name}</h1>
            </div>
            <p className="pdp-summary">{pick(item.summary, locale)}</p>
            <div className="pdp-meta">
              <StockLabel availability={item.availability} t={t} />
              <span>
                {t.product.sku}: <span className="mono" dir="ltr">{item.sku}</span>
              </span>
            </div>
            <div className="pdp-price">
              <Price price={item.price} locale={locale} t={t} size="lg" />
              {percent !== null && (
                <div className="pdp-meta">
                  <span className="badge badge-accent">{fill(t.product.save, { percent })}</span>
                  {item.price.saleEndsAt && (
                    <span className="sale-ends">
                      {t.product.saleEnds} <time dateTime={item.price.saleEndsAt}>{dateFmt.format(new Date(item.price.saleEndsAt))}</time>
                    </span>
                  )}
                </div>
              )}
            </div>
            <BuyBox productId={item.id} name={item.name} max={max} maxPerOrder={item.maxPerOrder} />
          </div>
        </div>

        <div className="pdp-details">
          <section className="pdp-section" aria-labelledby="desc">
            <h2 id="desc">{t.product.description}</h2>
            <div className="prose">
              <p>{pick(item.description, locale)}</p>
            </div>
          </section>
          {item.specs.length > 0 && (
            <section className="pdp-section" aria-labelledby="specs">
              <h2 id="specs">{t.product.specs}</h2>
              <table className="specs">
                <tbody>
                  <tr>
                    <th scope="row">{t.product.brand}</th>
                    <td>{item.brand.name}</td>
                  </tr>
                  {item.specs.map((spec, i) => (
                    <tr key={i}>
                      <th scope="row">{pick(spec.label, locale)}</th>
                      <td>{pick(spec.value, locale)}</td>
                    </tr>
                  ))}
                  <tr>
                    <th scope="row">{t.product.sku}</th>
                    <td>
                      <span className="mono" dir="ltr">
                        {item.sku}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </section>
          )}
        </div>

        {related.length > 0 && (
          <section className="section" aria-labelledby="related">
            <div className="section-head">
              <h2 id="related">{t.product.related}</h2>
            </div>
            <ProductGrid items={related} locale={locale} t={t} cols4 />
          </section>
        )}
      </div>
    </>
  );
}
