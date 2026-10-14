import type { Metadata } from "next";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { CheckoutView } from "@/components/client/checkout";
import { getDictionary } from "@/i18n";
import { localePath } from "@/i18n/config";
import { pick } from "@/i18n/format";
import { liveStorefront, resolveLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[locale]/checkout">): Promise<Metadata> {
  const t = getDictionary(await resolveLocale(params));
  return { title: t.checkout.title, robots: { index: false, follow: false } };
}

export default async function CheckoutPage({ params }: PageProps<"/[locale]/checkout">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  const sf = await liveStorefront();
  const [govs, methods] = await Promise.all([sf.listGovernorates(), sf.listPaymentMethods()]);
  return (
    <div className="container">
      <header className="page-head">
        <Breadcrumbs
          items={[{ href: localePath(locale), label: t.product.home }, { href: localePath(locale, "/cart"), label: t.cart.title }, { label: t.checkout.title }]}
          label={t.common.breadcrumbs}
        />
        <h1>{t.checkout.title}</h1>
      </header>
      <CheckoutView
        mode={sf.mode}
        governorates={govs.map((g) => ({ id: g.id, name: pick(g.name, locale) }))}
        payments={methods.map((m) => ({ id: m.id, label: pick(m.label, locale), description: pick(m.description, locale) }))}
      />
    </div>
  );
}
