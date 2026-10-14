import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Icon } from "@/components/Icon";
import { getDictionary } from "@/i18n";
import { localePath } from "@/i18n/config";
import { dateLocale, pick } from "@/i18n/format";
import { formatEGP } from "@/lib/commerce/money";
import { safeImageSrc } from "@/lib/commerce/safe-image";
import { liveStorefront, resolveLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[locale]/order/[id]">): Promise<Metadata> {
  const t = getDictionary(await resolveLocale(params));
  return { title: t.order.pageTitle, robots: { index: false, follow: false } };
}

export default async function OrderPage({ params }: PageProps<"/[locale]/order/[id]">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  const { id } = await params;
  if (!/^[A-Za-z0-9-]{1,40}$/.test(id)) notFound();
  const sf = await liveStorefront();
  const order = await sf.getOrder(id);
  if (!order) notFound();
  const [govs, methods] = await Promise.all([sf.listGovernorates(), sf.listPaymentMethods()]);
  const gov = govs.find((g) => g.id === order.customer.governorate);
  const method = methods.find((m) => m.id === order.paymentMethod);
  const dateFmt = new Intl.DateTimeFormat(dateLocale(locale), { dateStyle: "long", timeStyle: "short", timeZone: "Africa/Cairo" });

  // Wording follows the provider's status. A demo order is never described as placed or on its way.
  const heading = order.demo
    ? { title: t.order.demoTitle, body: t.order.demoBody, icon: "info" as const }
    : order.status === "confirmed"
      ? { title: t.order.confirmedTitle, body: t.order.confirmedBody, icon: "checkCircle" as const }
      : order.status === "failed"
        ? { title: t.order.failedTitle, body: t.order.failedBody, icon: "alert" as const }
        : { title: t.order.pendingTitle, body: t.order.pendingBody, icon: "clock" as const };

  return (
    <div className="container">
      <section className="order-hero" aria-labelledby="order-title">
        <span className="seal">
          <Icon name={heading.icon} />
        </span>
        {order.demo && <span className="badge badge-soft">{t.demo.badge}</span>}
        <h1 id="order-title">{heading.title}</h1>
        <p>{heading.body}</p>
        <span className="order-ref">
          {order.demo ? t.order.number : t.order.realNumber}:{" "}
          <span className="mono" dir="ltr">
            {order.id}
          </span>
        </span>
      </section>
      <div className="order-grid">
        <div className="stack">
          <section className="card summary" aria-labelledby="order-items">
            <h2 id="order-items">{t.order.items}</h2>
            <ul className="summary-lines">
              {order.lines.map((line) => (
                <li key={line.productId}>
                  <Image src={safeImageSrc(line.image?.src)} alt="" width={52} height={52} sizes="52px" />
                  <div style={{ minWidth: 0 }}>
                    <Link className="name" href={localePath(locale, `/products/${line.slug}`)} style={{ display: "block" }}>
                      {line.name}
                    </Link>
                    <span className="qty-x">
                      {line.quantity} × {formatEGP(line.unitPrice, locale)} · <span className="mono" dir="ltr">{line.sku}</span>
                    </span>
                  </div>
                  <span className="amt">{formatEGP(line.lineTotal, locale)}</span>
                </li>
              ))}
            </ul>
            <dl>
              <div className="row">
                <dt>{t.cart.subtotal}</dt>
                <dd>{formatEGP(order.totals.subtotal, locale)}</dd>
              </div>
              {order.totals.discount > 0 && (
                <div className="row is-discount">
                  <dt>{t.cart.discount}</dt>
                  <dd>−{formatEGP(order.totals.discount, locale)}</dd>
                </div>
              )}
              <div className="row">
                <dt>{t.cart.shipping}</dt>
                <dd>{formatEGP(order.totals.shipping, locale)}</dd>
              </div>
              <div className="row is-total">
                <dt>{t.cart.total}</dt>
                <dd>{formatEGP(order.totals.total, locale)}</dd>
              </div>
            </dl>
          </section>
        </div>
        <aside className="card summary" aria-labelledby="order-details">
          <h2 id="order-details">{t.order.deliverTo}</h2>
          <dl className="kv">
            <div>
              <dt>{t.order.placedAt}</dt>
              <dd>{dateFmt.format(new Date(order.createdAt))}</dd>
            </div>
            <div>
              <dt>{t.checkout.name}</dt>
              <dd dir="auto">{order.customer.name}</dd>
            </div>
            <div>
              <dt>{t.checkout.phone}</dt>
              <dd>
                <span dir="ltr">{order.customer.phone}</span>
              </dd>
            </div>
            <div>
              <dt>{t.checkout.delivery}</dt>
              <dd dir="auto">
                {[order.customer.address, order.customer.city, gov ? pick(gov.name, locale) : order.customer.governorate].filter(Boolean).join(locale === "ar" ? "، " : ", ")}
              </dd>
            </div>
            {order.customer.notes && (
              <div>
                <dt>{t.checkout.notes}</dt>
                <dd dir="auto">{order.customer.notes}</dd>
              </div>
            )}
            <div>
              <dt>{t.order.paymentMethod}</dt>
              <dd>{method ? pick(method.label, locale) : order.paymentMethod}</dd>
            </div>
          </dl>
          <Link className="btn btn-primary btn-block" href={localePath(locale, "/products")}>
            {t.order.continue}
          </Link>
        </aside>
      </div>
    </div>
  );
}
