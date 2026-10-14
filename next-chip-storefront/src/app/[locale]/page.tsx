import Link from "next/link";
import { Icon } from "@/components/Icon";
import { JsonLd } from "@/components/JsonLd";
import { Price, ProductGrid, ProductPicture } from "@/components/Product";
import { SITE } from "@/content/site";
import { getDictionary } from "@/i18n";
import { localePath } from "@/i18n/config";
import { countText, dateLocale, fill, pick } from "@/i18n/format";
import type { CatalogItem, Locale } from "@/lib/commerce/types";
import type { Dictionary } from "@/i18n/dictionaries/en";
import { absoluteUrl, liveStorefront, resolveLocale } from "@/lib/page";

function Section({ id, title, body, href, t, children }: { id: string; title: string; body: string; href?: string; t: Dictionary; children: React.ReactNode }) {
  return (
    <section className="section" aria-labelledby={id}>
      <div className="container">
        <div className="section-head">
          <div>
            <h2 id={id}>{title}</h2>
            <p>{body}</p>
          </div>
          {href && (
            <Link className="link-arrow" href={href}>
              {t.common.viewAll}
              <Icon name="arrowRight" className="flip-rtl" />
            </Link>
          )}
        </div>
        {children}
      </div>
    </section>
  );
}

function HeroCard({ item, locale, t }: { item: CatalogItem; locale: Locale; t: Dictionary }) {
  return (
    <Link className="hero-card" href={localePath(locale, `/products/${item.slug}`)}>
      <div className="hero-card-media">
        <ProductPicture image={item.images[0]} locale={locale} sizes="(min-width: 900px) 520px, 100vw" priority />
      </div>
      <div className="hero-card-info">
        <div>
          <small>
            {item.brand ? `${item.brand.name} · ` : ""}
            {pick(item.category.name, locale)}
          </small>
          <strong>{pick(item.name, locale)}</strong>
          <Price price={item.price} locale={locale} t={t} />
        </div>
        <span className="go" aria-hidden="true">
          <Icon name="arrowRight" className="flip-rtl" />
        </span>
      </div>
    </Link>
  );
}

export default async function HomePage({ params }: PageProps<"/[locale]">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  const sf = await liveStorefront();
  const [home, zones, payments] = await Promise.all([sf.getHome(), sf.listShippingZones(), sf.listPaymentMethods()]);
  const p = (path: string) => localePath(locale, path);
  const productCount = home.categories.reduce((n, c) => n + c.count, 0);
  const served = new Set(zones.flatMap((z) => z.governorates)).size;
  const cod = payments.some((m) => m.id === "cod");
  const dateFmt = new Intl.DateTimeFormat(dateLocale(locale), { day: "numeric", month: "long", timeZone: "Africa/Cairo" });

  // A synchronized catalog that StorePro hasn't published yet (or emptied) is shown as such, never padded with samples.
  if (productCount === 0) {
    return (
      <section className="container section" aria-labelledby="empty-title">
        <div className="card empty" data-testid="catalog-empty">
          <span className="empty-icon">
            <Icon name="box" />
          </span>
          <h1 id="empty-title" style={{ fontSize: "var(--fs-2xl)" }}>
            {t.home.emptyTitle}
          </h1>
          <p>{t.home.emptyBody}</p>
        </div>
      </section>
    );
  }

  return (
    <>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "WebSite",
          name: SITE.name,
          url: absoluteUrl(p("/")),
          inLanguage: locale,
          potentialAction: {
            "@type": "SearchAction",
            target: `${absoluteUrl(p("/search"))}?q={search_term_string}`,
            "query-input": "required name=search_term_string",
          },
        }}
      />
      <section className="hero" aria-labelledby="hero-title">
        <div className="container hero-grid">
          <div>
            <span className="eyebrow">{t.home.eyebrow}</span>
            <h1 id="hero-title">{t.home.heroTitle}</h1>
            <p className="hero-body">{t.home.heroBody}</p>
            <div className="hero-actions">
              <Link className="btn btn-primary btn-lg" href={p("/products")}>
                {t.home.heroPrimary}
                <Icon name="arrowRight" className="flip-rtl" />
              </Link>
              {home.categories[0] && (
                <Link className="btn btn-outline btn-lg" href={p(`/categories/${home.categories[0].slug}`)}>
                  {fill(t.home.heroSecondary, { category: pick(home.categories[0].name, locale) })}
                </Link>
              )}
            </div>
            <ul className="hero-stats">
              <li>
                <strong className="num">{home.categories.length}</strong>
                <span>{t.home.heroStat1}</span>
              </li>
              <li>
                <strong className="num">{productCount}</strong>
                <span>{t.home.heroStat2}</span>
              </li>
              {served > 0 && (
                <li>
                  <strong className="num">{served}</strong>
                  <span>{t.home.heroStat3}</span>
                </li>
              )}
            </ul>
          </div>
          {home.heroItem && <HeroCard item={home.heroItem} locale={locale} t={t} />}
        </div>
      </section>

      <Section id="cats" title={t.home.categoriesTitle} body={t.home.categoriesBody} t={t}>
        <div className="cat-grid">
          {home.categories.map((c) => (
            <Link key={c.id} className="cat-tile" href={p(`/categories/${c.slug}`)}>
              <span className="cat-icon">
                <Icon name={c.icon} />
              </span>
              <h3>{pick(c.name, locale)}</h3>
              <p>{pick(c.description, locale)}</p>
              <span className="cat-count">{countText(t.home.itemsCount, c.count, locale)}</span>
            </Link>
          ))}
          <Link className="cat-tile is-all" href={p("/products")}>
            <span className="cat-icon">
              <Icon name="grid" />
            </span>
            <h3>{t.nav.allProducts}</h3>
            <span className="cat-count">{countText(t.home.itemsCount, productCount, locale)}</span>
          </Link>
        </div>
      </Section>

      {home.promotions.map((promo) => (
        <section key={promo.id} className="container" aria-labelledby={`promo-${promo.id}`}>
          <div className="promo">
            <div>
              <span className="eyebrow">{t.home.promoEyebrow}</span>
              <h2 id={`promo-${promo.id}`}>{pick(promo.title, locale)}</h2>
              <p>{pick(promo.body, locale)}</p>
              <p className="promo-ends">
                {t.home.promoEnds} <time dateTime={promo.endsAt}>{dateFmt.format(new Date(promo.endsAt))}</time>
              </p>
            </div>
            <Link className="btn btn-primary btn-lg" href={p(promo.href)}>
              {t.common.shopNow}
              <Icon name="arrowRight" className="flip-rtl" />
            </Link>
          </div>
        </section>
      ))}

      {home.featured.length > 0 && (
        <Section id="featured" title={t.home.featuredTitle} body={t.home.featuredBody} href={p("/products")} t={t}>
          <ProductGrid items={home.featured} locale={locale} t={t} cols4 />
        </Section>
      )}
      {home.newArrivals.length > 0 && (
        <Section id="new" title={t.home.newTitle} body={t.home.newBody} href={p("/products?sort=newest")} t={t}>
          <ProductGrid items={home.newArrivals} locale={locale} t={t} cols4 />
        </Section>
      )}
      {home.bestSellers.length > 0 && (
        <Section id="best" title={t.home.bestTitle} body={t.home.bestBody} t={t}>
          <ProductGrid items={home.bestSellers} locale={locale} t={t} cols4 />
        </Section>
      )}

      <section className="section" aria-labelledby="service">
        <div className="container">
          <div className="section-head">
            <h2 id="service">{t.home.serviceTitle}</h2>
          </div>
          <ul className="service-grid">
            {cod && (
              <li>
                <Icon name="cash" />
                <div>
                  <strong>{t.home.serviceCod}</strong>
                  <span>{t.home.serviceCodBody}</span>
                </div>
              </li>
            )}
            {served > 0 && (
              <li>
                <Icon name="truck" />
                <div>
                  <strong>{fill(t.home.serviceShip, { count: served })}</strong>
                  <span>{t.home.serviceShipBody}</span>
                </div>
              </li>
            )}
            <li>
              <Icon name="barcode" />
              <div>
                <strong>{t.home.serviceSku}</strong>
                <span>{t.home.serviceSkuBody}</span>
              </div>
            </li>
            <li>
              <Icon name="translate" />
              <div>
                <strong>{t.home.serviceLang}</strong>
                <span>{t.home.serviceLangBody}</span>
              </div>
            </li>
          </ul>
        </div>
      </section>
    </>
  );
}
