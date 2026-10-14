import Link from "next/link";
import { CountLink, LangSwitch, MobileNav, NavLink, SearchBox, SearchSheet, ShopMenu, type NavCategory } from "@/components/client/header";
import { Icon, LogoMark } from "@/components/Icon";
import type { Dictionary } from "@/i18n/dictionaries/en";
import { localePath } from "@/i18n/config";
import type { Locale } from "@/lib/commerce/types";

export function Header({ locale, t, categories }: { locale: Locale; t: Dictionary; categories: NavCategory[] }) {
  return (
    <header className="site-header">
      <div className="container header-row">
        <MobileNav categories={categories} />
        <Link className="logo" href={localePath(locale)} aria-label={t.nav.home}>
          <LogoMark />
          <span dir="ltr">
            NEXT <b>CHIP</b>
          </span>
        </Link>
        <nav className="main-nav" aria-label={t.nav.primary}>
          <ShopMenu categories={categories} />
          <Link className="nav-link" href={localePath(locale, "/products?sale=1")}>
            {t.nav.deals}
          </Link>
          <NavLink path="/about">{t.nav.about}</NavLink>
          <NavLink path="/contact">{t.nav.support}</NavLink>
        </nav>
        <div className="header-search">
          <SearchBox />
        </div>
        <div className="header-actions">
          <SearchSheet />
          <LangSwitch />
          <Link className="icon-btn hide-md" href={localePath(locale, "/account")} aria-label={t.nav.account}>
            <Icon name="user" />
          </Link>
          <CountLink kind="wishlist" />
          <CountLink kind="cart" />
        </div>
      </div>
    </header>
  );
}

export function DemoBar({ t }: { t: Dictionary }) {
  return (
    <div className="demo-bar" role="note" aria-label={t.demo.badge}>
      <div className="container">
        <span className="badge badge-soft">{t.demo.badge}</span>
        <p>{t.demo.banner}</p>
      </div>
    </div>
  );
}
