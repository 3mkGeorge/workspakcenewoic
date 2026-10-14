import type { Metadata } from "next";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { DemoOrders } from "@/components/client/account";
import { Icon } from "@/components/Icon";
import { getDictionary } from "@/i18n";
import { localePath } from "@/i18n/config";
import { resolveLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[locale]/account">): Promise<Metadata> {
  const t = getDictionary(await resolveLocale(params));
  return { title: t.account.title, robots: { index: false, follow: false } };
}

/**
 * Account structure. Sign-in and order history will come from StorePro customer
 * accounts (see STStorePro_INTEGRATION.md); nothing here pretends to log in.
 */
export default async function AccountPage({ params }: PageProps<"/[locale]/account">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  return (
    <div className="container">
      <header className="page-head">
        <Breadcrumbs items={[{ href: localePath(locale), label: t.product.home }, { label: t.account.title }]} label={t.common.breadcrumbs} />
        <h1>{t.account.title}</h1>
      </header>
      <div className="content">
        <div className="alert alert-demo">
          <Icon name="info" />
          <div>
            <strong>{t.account.signInUnavailable}</strong>
            <p style={{ marginTop: "var(--sp-1)" }}>{t.account.signInBody}</p>
          </div>
        </div>
        <section aria-labelledby="orders">
          <h2 id="orders">{t.account.demoOrders}</h2>
          <DemoOrders />
        </section>
      </div>
    </div>
  );
}
