import Link from "next/link";
import { LangSwitch, type NavCategory } from "@/components/client/header";
import { LogoMark } from "@/components/Icon";
import { SITE } from "@/content/site";
import type { Dictionary } from "@/i18n/dictionaries/en";
import { fill, pick } from "@/i18n/format";
import { localePath } from "@/i18n/config";
import type { CommerceMode } from "@/lib/commerce/providers";
import type { Locale } from "@/lib/commerce/types";

export function Footer({ locale, t, categories, mode }: { locale: Locale; t: Dictionary; categories: NavCategory[]; mode: CommerceMode | "misconfigured" }) {
  const p = (path: string) => localePath(locale, path);
  const contact = SITE.contact;
  const published = [
    contact.phone && { label: t.pages.contactPhone, value: contact.phone, href: `tel:${contact.phone}` },
    contact.whatsapp && { label: t.pages.contactWhatsapp, value: contact.whatsapp },
    contact.email && { label: t.pages.contactEmail, value: contact.email, href: `mailto:${contact.email}` },
    contact.address && { label: t.pages.contactAddress, value: pick(contact.address, locale) },
  ].filter(Boolean) as { label: string; value: string; href?: string }[];

  return (
    <footer className="site-footer">
      <div className="container footer-grid">
        <div className="footer-brand">
          <Link className="logo" href={p("/")} aria-label={t.nav.home}>
            <LogoMark />
            <span dir="ltr">
              NEXT <b>CHIP</b>
            </span>
          </Link>
          <p>{t.footer.tagline}</p>
          {mode === "demo" && <span className="badge badge-soft">{t.footer.demo}</span>}
          {mode === "synced" && <span className="badge badge-soft">{t.footer.synced}</span>}
        </div>
        <nav className="footer-col" aria-labelledby="footer-shop">
          <h2 id="footer-shop">{t.footer.shop}</h2>
          <ul>
            <li>
              <Link href={p("/products")}>{t.nav.allProducts}</Link>
            </li>
            {categories.map((c) => (
              <li key={c.slug}>
                <Link href={p(`/categories/${c.slug}`)}>{c.name}</Link>
              </li>
            ))}
            <li>
              <Link href={p("/products?sale=1")}>{t.nav.deals}</Link>
            </li>
          </ul>
        </nav>
        <nav className="footer-col" aria-labelledby="footer-help">
          <h2 id="footer-help">{t.footer.help}</h2>
          <ul>
            <li>
              <Link href={p("/contact")}>{t.footer.contact}</Link>
            </li>
            <li>
              <Link href={p("/shipping-policy")}>{t.footer.shippingPolicy}</Link>
            </li>
            <li>
              <Link href={p("/returns")}>{t.footer.returns}</Link>
            </li>
            <li>
              <Link href={p("/privacy")}>{t.footer.privacy}</Link>
            </li>
            <li>
              <Link href={p("/terms")}>{t.footer.terms}</Link>
            </li>
            <li>
              <Link href={p("/about")}>{t.footer.about}</Link>
            </li>
            <li>
              <Link href={p("/account")}>{t.nav.account}</Link>
            </li>
          </ul>
        </nav>
        <div className="footer-col">
          <h2>{t.footer.contact}</h2>
          {published.length ? (
            <dl>
              {published.map((item) => (
                <div key={item.label}>
                  <dt>{item.label}</dt>
                  <dd dir="auto">{item.href ? <a href={item.href}>{item.value}</a> : item.value}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="muted">{t.pages.contactPending}</p>
          )}
        </div>
      </div>
      <div className="container footer-bottom">
        <span>{fill(t.footer.rights, { year: new Date().getFullYear() })}</span>
        <LangSwitch />
      </div>
    </footer>
  );
}
