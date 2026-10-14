import type { Metadata } from "next";
import { Configured, ContentPage } from "@/components/ContentPage";
import { Icon, type IconName } from "@/components/Icon";
import { SITE } from "@/content/site";
import { getDictionary } from "@/i18n";
import { alternates, resolveLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[locale]/contact">): Promise<Metadata> {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  return { title: t.pages.contactTitle, alternates: alternates(locale, "/contact") };
}

export default async function ContactPage({ params }: PageProps<"/[locale]/contact">) {
  const locale = await resolveLocale(params);
  const t = getDictionary(locale);
  const c = SITE.contact;
  const anyPublished = Object.values(c).some(Boolean);
  const rows: { icon: IconName; label: string; value: React.ReactNode }[] = [
    { icon: "phone", label: t.pages.contactPhone, value: c.phone ? <a href={`tel:${c.phone}`} dir="ltr">{c.phone}</a> : <Configured value={null} locale={locale} t={t} /> },
    { icon: "message", label: t.pages.contactWhatsapp, value: <span dir="ltr"><Configured value={c.whatsapp} locale={locale} t={t} /></span> },
    { icon: "mail", label: t.pages.contactEmail, value: c.email ? <a href={`mailto:${c.email}`}>{c.email}</a> : <Configured value={null} locale={locale} t={t} /> },
    { icon: "pin", label: t.pages.contactAddress, value: <Configured value={c.address} locale={locale} t={t} /> },
    { icon: "clock", label: t.pages.contactHours, value: <Configured value={c.hours} locale={locale} t={t} /> },
  ];
  return (
    <ContentPage locale={locale} t={t} title={t.pages.contactTitle} intro={anyPublished ? t.pages.contactBody : t.pages.contactPending} draft={!anyPublished}>
      <dl className="contact-grid">
        {rows.map((row) => (
          <div key={row.label} className="card">
            <Icon name={row.icon} />
            <div>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          </div>
        ))}
      </dl>
    </ContentPage>
  );
}
