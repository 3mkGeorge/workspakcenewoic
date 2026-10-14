import type { Metadata } from "next";
import { ContentPage } from "@/components/ContentPage";
import { getDictionary } from "@/i18n";
import { alternates, resolveLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[locale]/terms">): Promise<Metadata> {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  return { title: t.pages.termsTitle, alternates: alternates(locale, "/terms") };
}

export default async function TermsPage({ params }: PageProps<"/[locale]/terms">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  const sections = [
    [t.pages.termsPricing, t.pages.termsPricingBody],
    [t.pages.termsOrders, t.pages.termsOrdersBody],
  ] as const;
  return (
    <ContentPage locale={locale} t={t} title={t.pages.termsTitle} draft>
      {sections.map(([title, body]) => (
        <section key={title}>
          <h2>{title}</h2>
          <p>{body}</p>
        </section>
      ))}
    </ContentPage>
  );
}
