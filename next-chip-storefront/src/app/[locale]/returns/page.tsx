import type { Metadata } from "next";
import { Configured, ContentPage } from "@/components/ContentPage";
import { SITE } from "@/content/site";
import { getDictionary } from "@/i18n";
import { alternates, resolveLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[locale]/returns">): Promise<Metadata> {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  return { title: t.pages.returnsTitle, alternates: alternates(locale, "/returns") };
}

export default async function ReturnsPage({ params }: PageProps<"/[locale]/returns">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  const p = SITE.policies;
  const rows = [
    [t.pages.returnWindow, p.returnWindow],
    [t.pages.condition, p.returnCondition],
    [t.pages.refundMethod, p.refundMethod],
    [t.pages.warranty, p.warranty],
  ] as const;
  return (
    <ContentPage locale={locale} t={t} title={t.pages.returnsTitle} intro={t.pages.returnsIntro} draft>
      {rows.map(([label, value]) => (
        <section key={label}>
          <h2>{label}</h2>
          <p>
            <Configured value={value} locale={locale} t={t} />
          </p>
        </section>
      ))}
    </ContentPage>
  );
}
