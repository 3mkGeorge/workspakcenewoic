import "@fontsource-variable/inter/wght.css";
import "@fontsource-variable/space-grotesk/wght.css";
import "@fontsource/ibm-plex-sans-arabic/arabic-400.css";
import "@fontsource/ibm-plex-sans-arabic/arabic-500.css";
import "@fontsource/ibm-plex-sans-arabic/arabic-600.css";
import "@fontsource/ibm-plex-sans-arabic/arabic-700.css";
import "@/styles/tokens.css";
import "@/styles/base.css";
import "@/styles/components.css";
import "@/styles/layout.css";
import "@/styles/pages.css";

import type { Metadata, Viewport } from "next";
import { I18nProvider } from "@/components/client/I18nProvider";
import { Toaster } from "@/components/client/Toaster";
import type { NavCategory } from "@/components/client/header";
import { Footer } from "@/components/Footer";
import { DemoBar, Header } from "@/components/Header";
import { SITE } from "@/content/site";
import { getDictionary } from "@/i18n";
import { dirOf, LOCALES } from "@/i18n/config";
import { pick } from "@/i18n/format";
import { commerceMode } from "@/lib/commerce";
import { alternates, indexable, resolveLocale } from "@/lib/page";
import { storefront } from "@/lib/storefront";

export const dynamicParams = false;

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

export const viewport: Viewport = {
  themeColor: "#0a0b0d",
  colorScheme: "dark",
};

export async function generateMetadata({ params }: LayoutProps<"/[locale]">): Promise<Metadata> {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  return {
    metadataBase: new URL(SITE.url),
    title: { default: t.meta.title, template: `%s · ${SITE.name}` },
    description: t.meta.description,
    applicationName: SITE.name,
    alternates: alternates(locale),
    openGraph: { siteName: SITE.name, type: "website", locale: locale === "ar" ? "ar_EG" : "en_EG" },
    robots: indexable() ? undefined : { index: false, follow: false },
    formatDetection: { telephone: false },
  };
}

export default async function LocaleLayout({ children, params }: LayoutProps<"/[locale]">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  const mode = commerceMode();
  // The shell must render even when the catalog backend is down; pages show their own error state.
  let categories: NavCategory[] = [];
  try {
    categories = (await storefront().listCategories()).map((c) => ({
      slug: c.slug,
      name: pick(c.name, locale),
      description: pick(c.description, locale),
      icon: c.icon,
    }));
  } catch {
    categories = [];
  }

  return (
    <html lang={locale} dir={dirOf(locale)}>
      <body>
        <a className="skip-link" href="#main">
          {t.common.skip}
        </a>
        <I18nProvider locale={locale} dict={t}>
          <Toaster>
            {mode === "demo" && <DemoBar t={t} />}
            <Header locale={locale} t={t} categories={categories} />
            <main id="main" tabIndex={-1}>
              {children}
            </main>
            <Footer locale={locale} t={t} categories={categories} mode={mode} />
          </Toaster>
        </I18nProvider>
      </body>
    </html>
  );
}
