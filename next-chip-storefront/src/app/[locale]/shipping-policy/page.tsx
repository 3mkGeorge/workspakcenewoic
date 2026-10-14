import type { Metadata } from "next";
import { Configured, ContentPage } from "@/components/ContentPage";
import { SITE } from "@/content/site";
import { getDictionary } from "@/i18n";
import { pick } from "@/i18n/format";
import { formatEGP } from "@/lib/commerce/money";
import { alternates, liveStorefront, resolveLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[locale]/shipping-policy">): Promise<Metadata> {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  return { title: t.pages.shippingTitle, alternates: alternates(locale, "/shipping-policy") };
}

export default async function ShippingPolicyPage({ params }: PageProps<"/[locale]/shipping-policy">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  const sf = await liveStorefront();
  const [zones, govs] = await Promise.all([sf.listShippingZones(), sf.listGovernorates()]);
  const govName = new Map(govs.map((g) => [g.id, pick(g.name, locale)]));
  const demo = sf.capabilities.shipping === "demo";
  return (
    <ContentPage locale={locale} t={t} title={t.pages.shippingTitle} draft>
      <section>
        <h2>{t.pages.shippingFees}</h2>
        <p>{demo ? t.pages.shippingFeesDemo : t.pages.shippingFeesLive}</p>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">{t.pages.area}</th>
                <th scope="col">{t.pages.governorates}</th>
                <th scope="col">{t.pages.fee}</th>
              </tr>
            </thead>
            <tbody>
              {zones.map((z) => (
                <tr key={z.id}>
                  <td>{pick(z.name, locale)}</td>
                  <td>{z.governorates.map((g) => govName.get(g) ?? g).join(locale === "ar" ? "، " : ", ")}</td>
                  <td className="num">{formatEGP(z.fee, locale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted">{t.pages.shippingFeeNote}</p>
      </section>
      <section>
        <h2>{t.pages.deliveryTime}</h2>
        <p>
          <Configured value={SITE.policies.deliveryTime} locale={locale} t={t} />
        </p>
      </section>
    </ContentPage>
  );
}
