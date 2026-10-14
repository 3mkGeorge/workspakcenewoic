import type { Metadata } from "next";
import { ContentPage } from "@/components/ContentPage";
import { getDictionary } from "@/i18n";
import { alternates, resolveLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[locale]/privacy">): Promise<Metadata> {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  return { title: t.pages.privacyTitle, alternates: alternates(locale, "/privacy") };
}

export default async function PrivacyPage({ params }: PageProps<"/[locale]/privacy">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  const sections = [
    [t.pages.privacyCollect, t.pages.privacyCollectBody],
    [t.pages.privacyUse, t.pages.privacyUseBody],
    [t.pages.privacyStorage, t.pages.privacyStorageBody],
  ] as const;
  return (
    <ContentPage locale={locale} t={t} title={t.pages.privacyTitle} draft>
      {sections.map(([title, body]) => (
        <section key={title}>
          <h2>{title}</h2>
          <p>{body}</p>
        </section>
      ))}
    </ContentPage>
  );
}
