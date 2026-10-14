import type { Metadata } from "next";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { WishlistView } from "@/components/client/wishlist";
import { getDictionary } from "@/i18n";
import { localePath } from "@/i18n/config";
import { resolveLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[locale]/wishlist">): Promise<Metadata> {
  const t = getDictionary(await resolveLocale(params));
  return { title: t.wishlist.title, robots: { index: false, follow: false } };
}

export default async function WishlistPage({ params }: PageProps<"/[locale]/wishlist">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  return (
    <div className="container">
      <header className="page-head">
        <Breadcrumbs items={[{ href: localePath(locale), label: t.product.home }, { label: t.wishlist.title }]} label={t.common.breadcrumbs} />
        <h1>{t.wishlist.title}</h1>
        <p>{t.wishlist.intro}</p>
      </header>
      <WishlistView />
    </div>
  );
}
