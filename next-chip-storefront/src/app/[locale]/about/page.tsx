import type { Metadata } from "next";
import Link from "next/link";
import { ContentPage } from "@/components/ContentPage";
import { getDictionary } from "@/i18n";
import { localePath } from "@/i18n/config";
import { alternates, resolveLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[locale]/about">): Promise<Metadata> {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  return { title: t.pages.aboutTitle, description: t.pages.aboutBody, alternates: alternates(locale, "/about") };
}

export default async function AboutPage({ params }: PageProps<"/[locale]/about">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  return (
    <ContentPage locale={locale} t={t} title={t.pages.aboutTitle}>
      <section>
        <p>{t.pages.aboutBody}</p>
        <p>{t.pages.aboutBody2}</p>
      </section>
      <section>
        <h2>{t.pages.aboutHowTitle}</h2>
        <ul>
          <li>{t.pages.aboutHow1}</li>
          <li>{t.pages.aboutHow2}</li>
          <li>{t.pages.aboutHow3}</li>
        </ul>
      </section>
      <div>
        <Link className="btn btn-primary" href={localePath(locale, "/products")}>
          {t.home.heroPrimary}
        </Link>
      </div>
    </ContentPage>
  );
}
