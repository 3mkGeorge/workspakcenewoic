"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Fragment, useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { Icon, LogoMark, type IconName } from "@/components/Icon";
import { localePath, otherLocale } from "@/i18n/config";
import { formatEGP } from "@/lib/commerce/money";
import { safeImageSrc } from "@/lib/commerce/safe-image";
import { cartCount, useStore } from "@/lib/client/store";
import { useDebounced, useDismiss, useModal } from "@/lib/client/hooks";
import { useI18n } from "./I18nProvider";

export interface NavCategory {
  slug: string;
  name: string;
  description: string;
  icon: IconName;
}

/** Path without the leading locale segment ("/en/products" -> "/products"). */
function stripLocale(pathname: string) {
  const rest = pathname.replace(/^\/(en|ar)(?=\/|$)/, "");
  return rest || "/";
}

/* ---------------- Language switch ---------------- */

export function LangSwitch({ className = "lang-link" }: { className?: string }) {
  const { locale, t } = useI18n();
  const pathname = usePathname() ?? "/";
  const other = otherLocale(locale);
  const href = localePath(other, stripLocale(pathname));
  // Keep filters and the current hash when switching languages.
  const carryQuery = (e: MouseEvent<HTMLAnchorElement>) => {
    e.currentTarget.search = window.location.search;
    e.currentTarget.hash = window.location.hash;
  };
  return (
    <a className={className} href={href} hrefLang={other} lang={other} aria-label={t.nav.languageLabel} onClick={carryQuery}>
      {t.nav.language}
    </a>
  );
}

/* ---------------- Counters ---------------- */

export function CountLink({ kind }: { kind: "cart" | "wishlist" }) {
  const { locale, t } = useI18n();
  const store = useStore();
  const pathname = usePathname();
  const count = kind === "cart" ? cartCount(store) : store.wishlist.length;
  const label = kind === "cart" ? t.nav.cart : t.nav.wishlist;
  const href = localePath(locale, kind === "cart" ? "/cart" : "/wishlist");
  return (
    <Link
      className="icon-btn"
      href={href}
      aria-label={count ? `${label} (${count})` : label}
      aria-current={pathname === href ? "page" : undefined}
      data-testid={`${kind}-link`}
    >
      <Icon name={kind === "cart" ? "bag" : "heart"} />
      {count > 0 && (
        <span className="count" aria-hidden="true">
          {count > 99 ? "99+" : count}
        </span>
      )}
    </Link>
  );
}

/* ---------------- Primary nav links ---------------- */

export function NavLink({ path, children }: { path: string; children: React.ReactNode }) {
  const { locale } = useI18n();
  const pathname = usePathname();
  const href = localePath(locale, path);
  return (
    <Link className="nav-link" href={href} aria-current={pathname === href ? "page" : undefined}>
      {children}
    </Link>
  );
}

/* ---------------- Shop menu (disclosure) ---------------- */

export function ShopMenu({ categories }: { categories: NavCategory[] }) {
  const { locale, t } = useI18n();
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const refs = useMemo(() => [button, panel], []);
  const pathname = usePathname();
  const id = useId();

  const close = useCallback((opts?: { restoreFocus?: boolean }) => {
    setOpen(false);
    if (opts?.restoreFocus) button.current?.focus();
  }, []);
  useDismiss(open, close, refs);
  useEffect(() => setOpen(false), [pathname]);

  const items = () => Array.from(panel.current?.querySelectorAll<HTMLElement>("a") ?? []);
  const focusItem = (index: number) => {
    const all = items();
    if (!all.length) return;
    all[(index + all.length) % all.length]?.focus();
  };

  const onButtonKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      requestAnimationFrame(() => focusItem(0));
    }
  };
  const onPanelKey = (e: KeyboardEvent) => {
    const all = items();
    const index = all.indexOf(document.activeElement as HTMLElement);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      focusItem(index + 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      focusItem(index - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      focusItem(0);
    } else if (e.key === "End") {
      e.preventDefault();
      focusItem(all.length - 1);
    }
  };

  return (
    <>
      <button
        ref={button}
        type="button"
        className="nav-link"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={onButtonKey}
      >
        {t.nav.shop}
        <Icon name="chevronDown" />
      </button>
      <div ref={panel} id={id} className="popover mega" hidden={!open} onKeyDown={onPanelKey} onClick={(e) => (e.target as HTMLElement).closest("a") && close()}>
        <nav aria-label={t.nav.shopByCategory}>
          <div className="mega-grid">
            {categories.map((c) => (
              <Link key={c.slug} className="menu-item" href={localePath(locale, `/categories/${c.slug}`)}>
                <span className="menu-icon">
                  <Icon name={c.icon} />
                </span>
                <span>
                  {c.name}
                  <small>{c.description}</small>
                </span>
              </Link>
            ))}
          </div>
          <div className="mega-foot">
            <Link className="link-arrow" href={localePath(locale, "/products")}>
              {t.nav.browseAll}
              <Icon name="arrowRight" className="flip-rtl" />
            </Link>
            <Link className="link-arrow" href={localePath(locale, "/products?sale=1")}>
              {t.nav.deals}
            </Link>
          </div>
        </nav>
      </div>
    </>
  );
}

/* ---------------- Search with suggestions (combobox) ---------------- */

interface Suggestion {
  id: string;
  slug: string;
  name: string;
  brand: string;
  sku: string;
  image: string;
  price: number;
}

export function SearchBox({ autoFocus = false, defaultValue = "", onNavigate }: { autoFocus?: boolean; defaultValue?: string; onNavigate?: () => void }) {
  const { locale, t } = useI18n();
  const router = useRouter();
  const [value, setValue] = useState(defaultValue);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [results, setResults] = useState<Suggestion[] | null>(null);
  const [loading, setLoading] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const refs = useMemo(() => [box], []);
  const id = useId();
  const listId = `${id}-list`;
  const query = useDebounced(value.trim(), 180);
  const pathname = usePathname();

  const close = useCallback((opts?: { restoreFocus?: boolean }) => {
    setOpen(false);
    setActive(-1);
    if (opts?.restoreFocus) input.current?.focus();
  }, []);
  useDismiss(open, close, refs);
  useEffect(() => close(), [pathname, close]);

  useEffect(() => {
    if (query.length < 2) {
      setResults(null);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    fetch(`/api/search?q=${encodeURIComponent(query)}&locale=${locale}`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: { items: Suggestion[] }) => {
        setResults(data.items);
        setActive(-1);
      })
      .catch((e: unknown) => {
        if ((e as Error).name !== "AbortError") setResults([]);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [query, locale]);

  const searchHref = (q: string) => `${localePath(locale, "/search")}?q=${encodeURIComponent(q)}`;
  const productHref = (slug: string) => localePath(locale, `/products/${slug}`);
  const optionCount = results && query.length >= 2 ? results.length + 1 : 0;
  const showList = open && optionCount > 0;

  const go = (href: string) => {
    close();
    onNavigate?.();
    router.push(href);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = value.trim();
    if (active >= 0 && results && active < results.length) return go(productHref(results[active]!.slug));
    if (!q) return input.current?.focus();
    go(searchHref(q));
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!optionCount) return;
      e.preventDefault();
      setOpen(true);
      setActive((i) => {
        const next = e.key === "ArrowDown" ? i + 1 : i - 1;
        return next < -1 ? optionCount - 1 : next >= optionCount ? -1 : next;
      });
    } else if (e.key === "Escape") {
      if (showList) {
        e.preventDefault();
        e.stopPropagation();
        close();
      } else if (value) {
        // Inside the mobile sheet the first Escape clears, the next one closes the sheet.
        e.preventDefault();
        e.stopPropagation();
        setValue("");
      }
    }
  };

  return (
    <form role="search" className="search-form" action={localePath(locale, "/search")} method="get" onSubmit={submit}>
      <div className="search" ref={box}>
        <label className="visually-hidden" htmlFor={`${id}-input`}>
          {t.nav.searchLabel}
        </label>
        <div className="search-field">
          <Icon name="search" />
          <input
            ref={input}
            id={`${id}-input`}
            className="input"
            type="search"
            name="q"
            value={value}
            maxLength={80}
            autoComplete="off"
            spellCheck={false}
            enterKeyHint="search"
            placeholder={t.nav.searchPlaceholder}
            autoFocus={autoFocus}
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={showList}
            aria-controls={listId}
            aria-activedescendant={showList && active >= 0 ? `${listId}-${active}` : undefined}
            onChange={(e) => {
              setValue(e.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKey}
          />
          {value && (
            <button
              type="button"
              className="icon-btn clear"
              aria-label={t.common.clearSearch}
              onClick={() => {
                setValue("");
                input.current?.focus();
              }}
            >
              <Icon name="close" />
            </button>
          )}
        </div>
        <div className="popover suggest" id={listId} role="listbox" aria-label={t.nav.searchLabel} hidden={!showList}>
          {results?.length === 0 && !loading && <p className="suggest-empty">{t.catalog.noSuggestions}</p>}
          {results?.map((item, i) => (
            <a
              key={item.id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              tabIndex={-1}
              className="suggest-item"
              href={productHref(item.slug)}
              onMouseEnter={() => setActive(i)}
              onClick={(e) => {
                e.preventDefault();
                go(productHref(item.slug));
              }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={safeImageSrc(item.image)} alt="" width={44} height={44} loading="lazy" />
              <span className="s-name">
                {item.name}
                <span className="s-meta">
                  {item.brand ? `${item.brand} · ` : ""}
                  <span className="mono">{item.sku}</span>
                </span>
              </span>
              <span className="num">{formatEGP(item.price, locale)}</span>
            </a>
          ))}
          {results && (
            <a
              id={`${listId}-${results.length}`}
              role="option"
              aria-selected={active === results.length}
              tabIndex={-1}
              className="suggest-all"
              href={searchHref(query)}
              onMouseEnter={() => setActive(results.length)}
              onClick={(e) => {
                e.preventDefault();
                go(searchHref(query));
              }}
            >
              <span>{t.catalog.allResultsFor.replace("{q}", query)}</span>
              <Icon name="arrowRight" className="flip-rtl" />
            </a>
          )}
        </div>
      </div>
    </form>
  );
}

/** Small screens: a search button that opens a top sheet with the same combobox. */
export function SearchSheet() {
  const { t } = useI18n();
  const { ref, open, show, hide } = useModal();
  return (
    <>
      <button type="button" className="icon-btn search-toggle" aria-label={t.nav.search} aria-haspopup="dialog" aria-expanded={open} onClick={show}>
        <Icon name="search" />
      </button>
      <dialog ref={ref} className="search-sheet" aria-label={t.nav.search}>
        {open && (
          <div className="search-sheet-row">
            <SearchBox autoFocus onNavigate={hide} />
            <button type="button" className="icon-btn" aria-label={t.common.close} onClick={hide}>
              <Icon name="close" />
            </button>
          </div>
        )}
      </dialog>
    </>
  );
}

/* ---------------- Mobile navigation drawer ---------------- */

export function MobileNav({ categories }: { categories: NavCategory[] }) {
  const { locale, t } = useI18n();
  const { ref, open, show, hide } = useModal();
  const pathname = usePathname();
  const store = useStore();
  const count = cartCount(store);

  useEffect(() => hide(), [pathname, hide]);

  const link = (path: string, label: string, icon: IconName, extra?: React.ReactNode) => {
    const href = localePath(locale, path);
    return (
      <Link className="menu-item" href={href} aria-current={pathname === href ? "page" : undefined}>
        <Icon name={icon} />
        <span>{label}</span>
        {extra}
      </Link>
    );
  };

  return (
    <>
      <button type="button" className="icon-btn nav-toggle" aria-label={t.nav.openMenu} aria-haspopup="dialog" aria-expanded={open} onClick={show}>
        <Icon name="menu" />
      </button>
      <dialog ref={ref} className="drawer" aria-label={t.nav.menu}>
        <div className="drawer-head">
          <Link className="logo" href={localePath(locale)} aria-label={t.nav.home}>
            <LogoMark />
            <span>
              NEXT <b>CHIP</b>
            </span>
          </Link>
          <button type="button" className="icon-btn" aria-label={t.nav.closeMenu} onClick={hide}>
            <Icon name="close" />
          </button>
        </div>
        <div className="drawer-body" onClick={(e) => (e.target as HTMLElement).closest("a") && hide()}>
          <nav className="drawer-nav" aria-label={t.nav.menu}>
            <h2>{t.nav.shop}</h2>
            {link("/products", t.nav.allProducts, "grid")}
            {link("/products?sale=1", t.nav.deals, "tag")}
            {categories.map((c) => (
              <Fragment key={c.slug}>{link(`/categories/${c.slug}`, c.name, c.icon)}</Fragment>
            ))}
            <h2>{t.nav.yourStuff}</h2>
            {link("/cart", t.nav.cart, "bag", count > 0 ? <span className="count">{count}</span> : null)}
            {link("/wishlist", t.nav.wishlist, "heart", store.wishlist.length > 0 ? <span className="count">{store.wishlist.length}</span> : null)}
            {link("/account", t.nav.account, "user")}
            <h2>{t.nav.store}</h2>
            {link("/about", t.nav.about, "info")}
            {link("/contact", t.nav.support, "message")}
            {link("/shipping-policy", t.footer.shippingPolicy, "truck")}
          </nav>
        </div>
        <div className="drawer-foot">
          <LangSwitch className="btn btn-outline btn-block" />
        </div>
      </dialog>
    </>
  );
}
