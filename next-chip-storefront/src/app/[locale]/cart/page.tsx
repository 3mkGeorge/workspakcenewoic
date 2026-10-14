import type { Metadata } from "next";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { CartView } from "@/components/client/cart";
import { getDictionary } from "@/i18n";
import { localePath } from "@/i18n/config";
import { pick } from "@/i18n/format";
import { liveStorefront, resolveLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[locale]/cart">): Promise<Metadata> {
  const t = getDictionary(await resolveLocale(params));
  return { title: t.cart.title, robots: { index: false, follow: false } };
}

export default async function CartPage({ params }: PageProps<"/[locale]/cart">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  const governorates = (await (await liveStorefront()).listGovernorates()).map((g) => ({ id: g.id, name: pick(g.name, locale) }));
  return (
    <div className="container">
      <header className="page-head">
        <Breadcrumbs items={[{ href: localePath(locale), label: t.product.home }, { label: t.cart.title }]} label={t.common.breadcrumbs} />
        <h1>{t.cart.title}</h1>
      </header>
      <CartView governorates={governorates} />
    </div>
  );
}
