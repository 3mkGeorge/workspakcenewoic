"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useId, useState, useTransition, type MouseEvent, type ReactNode } from "react";
import { Icon } from "@/components/Icon";
import { countText } from "@/i18n/format";
import { activeFilterCount, catalogHref, categoryHref, type CatalogContext } from "@/lib/catalog-urls";
import { normalizeDigits } from "@/lib/commerce/checkout-validation";
import type { Brand, CatalogSort } from "@/lib/commerce/types";
import { useModal } from "@/lib/client/hooks";
import { useI18n } from "./I18nProvider";

interface Nav {
  ctx: CatalogContext;
  pending: boolean;
  navigate: (href: string, opts?: { scroll?: boolean }) => void;
}
const NavCtx = createContext<Nav | null>(null);
const useCatalog = () => {
  const v = useContext(NavCtx);
  if (!v) throw new Error("Catalog components must be inside CatalogShell");
  return v;
};

/**
 * Wraps a listing: every filter, sort, view and page change goes through one
 * transition so results dim while the server renders the new URL, and the
 * browser history gets one entry per change (Back/Forward restore filters).
 */
export function CatalogShell({ ctx, children }: { ctx: CatalogContext; children: ReactNode }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const navigate = (href: string, opts?: { scroll?: boolean }) => start(() => router.push(href, { scroll: opts?.scroll ?? false }));
  return <NavCtx.Provider value={{ ctx, pending, navigate }}>{children}</NavCtx.Provider>;
}

/** A real link (works without JS, middle-click, copy) that navigates inside the catalog transition. */
export function CatalogLink({ href, scroll, children, ...rest }: { href: string; scroll?: boolean; children: ReactNode } & Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href">) {
  const { navigate } = useCatalog();
  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    rest.onClick?.(e);
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigate(href, { scroll });
  };
  return (
    <a href={href} {...rest} onClick={onClick}>
      {children}
    </a>
  );
}

export function Results({ children }: { children: ReactNode }) {
  const { pending } = useCatalog();
  const { t } = useI18n();
  return (
    <div className="results" aria-busy={pending} data-testid="results">
      {pending && (
        <div className="results-status" role="status">
          <span>
            <span className="spinner" aria-hidden="true" />
            {t.catalog.updating}
          </span>
        </div>
      )}
      {children}
    </div>
  );
}

export interface FilterData {
  categories: { slug: string; name: string }[];
  brands: { brand: Brand; count: number }[];
  priceRange: { min: number; max: number };
}

export function FilterPanel({ data, onDone }: { data: FilterData; onDone?: () => void }) {
  const { ctx, navigate } = useCatalog();
  const { t } = useI18n();
  const id = useId();
  const q = ctx.query;
  const [min, setMin] = useState(q.minPrice?.toString() ?? "");
  const [max, setMax] = useState(q.maxPrice?.toString() ?? "");
  useEffect(() => {
    setMin(q.minPrice?.toString() ?? "");
    setMax(q.maxPrice?.toString() ?? "");
  }, [q.minPrice, q.maxPrice]);

  // Optimistic toggles: checkboxes respond instantly, then follow the URL once the server answers.
  const [brands, setBrands] = useState(q.brands ?? []);
  const [inStock, setInStock] = useState(q.stock === "in-stock");
  const [onSale, setOnSale] = useState(!!q.onSale);
  const brandKey = (q.brands ?? []).join(",");
  useEffect(() => {
    setBrands(brandKey ? brandKey.split(",") : []);
    setInStock(q.stock === "in-stock");
    setOnSale(!!q.onSale);
  }, [brandKey, q.stock, q.onSale]);

  const reset = { page: undefined };
  const toggleBrand = (slug: string) => {
    const next = brands.includes(slug) ? brands.filter((b) => b !== slug) : [...brands, slug];
    setBrands(next);
    navigate(catalogHref(ctx, { ...reset, brands: next }));
  };
  const digits = (v: string) => normalizeDigits(v).replace(/\D/g, "").slice(0, 7);
  const applyPrice = (e: React.FormEvent) => {
    e.preventDefault();
    const lo = min === "" ? undefined : Number(min);
    const hi = max === "" ? undefined : Number(max);
    const [a, b] = lo !== undefined && hi !== undefined && lo > hi ? [hi, lo] : [lo, hi];
    navigate(catalogHref(ctx, { ...reset, minPrice: a, maxPrice: b }));
    onDone?.();
  };
  const currentCategory = ctx.fixedCategory ?? q.category;

  return (
    <div className="filters">
      <div className="filter-group">
        <span className="legend" id={`${id}-cat`}>
          {t.catalog.category}
        </span>
        <ul className="filter-cats" aria-labelledby={`${id}-cat`}>
          <li>
            <CatalogLink href={categoryHref(ctx, undefined)} aria-current={!currentCategory ? "page" : undefined} scroll onClick={onDone}>
              {t.catalog.allCategories}
            </CatalogLink>
          </li>
          {data.categories.map((c) => (
            <li key={c.slug}>
              <CatalogLink href={categoryHref(ctx, c.slug)} aria-current={currentCategory === c.slug ? "page" : undefined} scroll onClick={onDone}>
                {c.name}
              </CatalogLink>
            </li>
          ))}
        </ul>
      </div>

      {data.brands.length > 0 && (
        <fieldset className="filter-group">
          <legend>{t.catalog.brand}</legend>
          {data.brands.map(({ brand, count }) => (
            <label key={brand.slug} className="check">
              <input type="checkbox" checked={brands.includes(brand.slug)} onChange={() => toggleBrand(brand.slug)} />
              <span>{brand.name}</span>
              <span className="count">{count}</span>
            </label>
          ))}
        </fieldset>
      )}

      <form className="filter-group" onSubmit={applyPrice} aria-labelledby={`${id}-price`}>
        <span className="legend" id={`${id}-price`}>
          {t.catalog.price}
        </span>
        <div className="price-range">
          <label className="visually-hidden" htmlFor={`${id}-min`}>
            {t.catalog.min}
          </label>
          <input
            id={`${id}-min`}
            className="input"
            inputMode="numeric"
            autoComplete="off"
            placeholder={`${t.catalog.min} ${data.priceRange.min}`}
            value={min}
            onChange={(e) => setMin(digits(e.target.value))}
          />
          <label className="visually-hidden" htmlFor={`${id}-max`}>
            {t.catalog.max}
          </label>
          <input
            id={`${id}-max`}
            className="input"
            inputMode="numeric"
            autoComplete="off"
            placeholder={`${t.catalog.max} ${data.priceRange.max}`}
            value={max}
            onChange={(e) => setMax(digits(e.target.value))}
          />
          <button type="submit" className="btn btn-outline btn-sm">
            {t.catalog.apply}
          </button>
        </div>
      </form>

      <fieldset className="filter-group">
        <legend>{t.catalog.availability}</legend>
        <label className="check">
          <input
            type="checkbox"
            checked={inStock}
            onChange={(e) => {
              setInStock(e.target.checked);
              navigate(catalogHref(ctx, { ...reset, stock: e.target.checked ? "in-stock" : "all" }));
            }}
          />
          <span>{t.catalog.inStockOnly}</span>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={onSale}
            onChange={(e) => {
              setOnSale(e.target.checked);
              navigate(catalogHref(ctx, { ...reset, onSale: e.target.checked }));
            }}
          />
          <span>{t.catalog.onSaleOnly}</span>
        </label>
      </fieldset>
    </div>
  );
}

/** Mobile/tablet: filters in a drawer. Results update live behind it. */
export function FiltersButton({ data, total }: { data: FilterData; total: number }) {
  const { ctx, pending } = useCatalog();
  const { t } = useI18n();
  const { ref, open, show, hide } = useModal();
  const count = activeFilterCount(ctx);
  return (
    <>
      <button type="button" className="btn btn-outline filters-toggle" aria-haspopup="dialog" aria-expanded={open} onClick={show}>
        <Icon name="sliders" />
        {t.catalog.filters}
        {count > 0 && <span className="badge badge-accent">{count}</span>}
      </button>
      <dialog ref={ref} className="drawer from-end" aria-labelledby="filters-title">
        <div className="drawer-head">
          <h2 id="filters-title" style={{ fontSize: "var(--fs-lg)" }}>
            {t.catalog.filters}
          </h2>
          <button type="button" className="icon-btn" aria-label={t.common.close} onClick={hide}>
            <Icon name="close" />
          </button>
        </div>
        <div className="drawer-body">{open && <FilterPanel data={data} onDone={hide} />}</div>
        <div className="drawer-foot">
          <button type="button" className="btn btn-primary btn-block" onClick={hide} aria-busy={pending}>
            {pending ? t.catalog.updating : countText(t.catalog.showResults, total, ctx.locale)}
          </button>
          {count > 0 && (
            <CatalogLink className="btn btn-ghost btn-block" href={catalogHref(ctx, { page: undefined, brands: [], minPrice: undefined, maxPrice: undefined, stock: "all", onSale: false, category: undefined })}>
              {t.catalog.clearAll}
            </CatalogLink>
          )}
        </div>
      </dialog>
    </>
  );
}

export function SortSelect() {
  const { ctx, navigate } = useCatalog();
  const { t } = useI18n();
  const id = useId();
  const current = ctx.query.sort ?? "featured";
  const [sort, setSort] = useState<CatalogSort>(current);
  useEffect(() => setSort(current), [current]);
  const options: [CatalogSort, string][] = [
    ["featured", t.catalog.sortFeatured],
    ["newest", t.catalog.sortNewest],
    ["price-asc", t.catalog.sortPriceAsc],
    ["price-desc", t.catalog.sortPriceDesc],
  ];
  return (
    <div className="sort">
      <label htmlFor={id}>{t.catalog.sort}</label>
      <select
        id={id}
        className="select"
        value={sort}
        onChange={(e) => {
          const next = e.target.value as CatalogSort;
          setSort(next);
          navigate(catalogHref(ctx, { sort: next, page: undefined }));
        }}
      >
        {options.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
    </div>
  );
}

export function ViewToggle() {
  const { ctx } = useCatalog();
  const { t } = useI18n();
  return (
    <div className="segmented" role="group" aria-label={t.catalog.view}>
      <CatalogLink href={catalogHref(ctx, { view: "grid" })} aria-label={t.catalog.grid} aria-current={ctx.view === "grid" ? "true" : undefined} title={t.catalog.grid}>
        <Icon name="grid" />
      </CatalogLink>
      <CatalogLink href={catalogHref(ctx, { view: "list" })} aria-label={t.catalog.list} aria-current={ctx.view === "list" ? "true" : undefined} title={t.catalog.list}>
        <Icon name="list" />
      </CatalogLink>
    </div>
  );
}
