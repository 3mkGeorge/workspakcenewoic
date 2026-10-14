"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { localePath } from "@/i18n/config";
import { countText, fill } from "@/i18n/format";
import { formatEGP } from "@/lib/commerce/money";
import { safeImageSrc } from "@/lib/commerce/safe-image";
import type { CartQuote, LineIssue, PricedLine } from "@/lib/commerce/types";
import { useModal } from "@/lib/client/hooks";
import { clearCart, removeFromCart, setGovernorate, setQuantity, useStore, type CartEntry } from "@/lib/client/store";
import { useI18n } from "./I18nProvider";
import { QtyStepper } from "./product-actions";
import { useToast } from "./Toaster";

export interface GovernorateOption {
  id: string;
  name: string;
}

export type QuoteState =
  | { status: "idle" | "loading"; quote: CartQuote | null; shippingError?: string }
  | { status: "ready"; quote: CartQuote; shippingError?: string }
  | { status: "error"; quote: CartQuote | null; shippingError?: string };

/**
 * Server-side cart pricing for whatever is in the browser cart. Re-runs when
 * lines or governorate change; stale responses are discarded.
 */
export function useQuote(lines: CartEntry[], governorate: string | null, enabled: boolean) {
  const [state, setState] = useState<QuoteState>({ status: "idle", quote: null });
  const [attempt, setAttempt] = useState(0);
  const key = JSON.stringify([lines, governorate]);

  useEffect(() => {
    if (!enabled) return;
    const ctrl = new AbortController();
    setState((s) => ({ ...s, status: "loading" }) as QuoteState);
    const timer = setTimeout(() => {
      const [l, g] = JSON.parse(key) as [CartEntry[], string | null];
      fetch("/api/cart/quote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lines: l, governorate: g ?? undefined }),
        signal: ctrl.signal,
      })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
        .then((data: { quote: CartQuote; shippingError?: string }) => setState({ status: "ready", quote: data.quote, shippingError: data.shippingError }))
        .catch((e: unknown) => {
          if ((e as Error).name !== "AbortError") setState((s) => ({ status: "error", quote: s.quote }));
        });
    }, 150);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [key, enabled, attempt]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  return { ...state, retry };
}

export function issueText(issue: LineIssue, line: PricedLine, t: ReturnType<typeof useI18n>["t"]) {
  switch (issue) {
    case "insufficient_stock":
      return fill(t.cart.issueStock, { count: line.maxQuantity });
    case "max_per_order":
      return fill(t.cart.issueMax, { count: line.maxQuantity });
    case "unknown_product":
      return t.cart.issueUnknown;
    default:
      return t.cart.issueUnavailable;
  }
}

export function GovernorateSelect({
  id,
  value,
  options,
  onChange,
  invalid,
  describedBy,
  required,
}: {
  id: string;
  value: string;
  options: GovernorateOption[];
  onChange: (value: string) => void;
  invalid?: boolean;
  describedBy?: string;
  required?: boolean;
}) {
  const { t } = useI18n();
  return (
    <select
      id={id}
      name="governorate"
      className="select"
      value={value}
      required={required}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">{t.checkout.chooseGovernorate}</option>
      {options.map((g) => (
        <option key={g.id} value={g.id}>
          {g.name}
        </option>
      ))}
    </select>
  );
}

/** Totals as priced by the server. Nothing here is computed in the browser. */
export function Totals({ quote, governorateName, shippingError }: { quote: CartQuote; governorateName?: string; shippingError?: string }) {
  const { locale, t } = useI18n();
  const { totals } = quote;
  return (
    <dl>
      <div className="row">
        <dt>{countText(t.cart.subtotalItems, totals.itemCount, locale)}</dt>
        <dd>{formatEGP(totals.subtotal, locale)}</dd>
      </div>
      {totals.discount > 0 && (
        <div className="row is-discount">
          <dt>{t.cart.discount}</dt>
          <dd>−{formatEGP(totals.discount, locale)}</dd>
        </div>
      )}
      <div className="row">
        <dt>
          {t.cart.shipping}
          {quote.shipping && governorateName ? ` · ${governorateName}` : ""}
        </dt>
        <dd data-testid="shipping-fee">{quote.shipping ? formatEGP(totals.shipping, locale) : "—"}</dd>
      </div>
      {!quote.shipping && <p className="note">{shippingError ? t.checkout.errorShipping : t.cart.shippingPick}</p>}
      {quote.shipping?.demo && <p className="note">{t.cart.shippingDemo}</p>}
      <div className="row is-total">
        <dt>{quote.shipping ? t.cart.total : t.cart.totalBeforeShipping}</dt>
        <dd data-testid="order-total">{formatEGP(totals.total, locale)}</dd>
      </div>
    </dl>
  );
}

function ConfirmClear({ onConfirm }: { onConfirm: () => void }) {
  const { t } = useI18n();
  const { ref, show, hide } = useModal();
  return (
    <>
      <button type="button" className="btn btn-ghost btn-sm" onClick={show}>
        <Icon name="trash" />
        {t.cart.clear}
      </button>
      <dialog ref={ref} className="modal" aria-labelledby="clear-title" aria-describedby="clear-body">
        <div className="modal-head">
          <h2 id="clear-title">{t.cart.clearTitle}</h2>
        </div>
        <p className="modal-body" id="clear-body">
          {t.cart.clearBody}
        </p>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" onClick={hide} autoFocus>
            {t.common.cancel}
          </button>
          <button
            type="button"
            className="btn btn-danger"
            onClick={() => {
              hide();
              onConfirm();
            }}
          >
            {t.cart.clearConfirm}
          </button>
        </div>
      </dialog>
    </>
  );
}

export function LineSkeleton() {
  return (
    <li className="card cart-line" aria-hidden="true">
      <div className="skeleton" style={{ aspectRatio: "1" }} />
      <div className="stack" style={{ gap: "var(--sp-2)" }}>
        <div className="skeleton" style={{ height: 18, width: "60%" }} />
        <div className="skeleton" style={{ height: 14, width: "35%" }} />
      </div>
    </li>
  );
}

function CartLine({ line, entry }: { line: PricedLine; entry: CartEntry }) {
  const { locale, t } = useI18n();
  const notify = useToast();
  const href = line.slug ? localePath(locale, `/products/${line.slug}`) : undefined;
  const name = line.name || t.cart.unknownItem;
  const remove = () => {
    removeFromCart(line.productId);
    notify(fill(t.cart.removed, { name }));
  };
  const canStep = line.maxQuantity > 0;
  return (
    <li className={`card cart-line${line.issue ? " has-issue" : ""}`} data-testid="cart-line" data-product={line.productId}>
      {href ? (
        <Link className="cart-line-media" href={href} tabIndex={-1} aria-hidden="true">
          <Image src={safeImageSrc(line.image?.src)} alt="" width={112} height={112} sizes="112px" />
        </Link>
      ) : (
        <span className="cart-line-media" aria-hidden="true">
          <Image src={safeImageSrc(undefined)} alt="" width={112} height={112} sizes="112px" />
        </span>
      )}
      <div className="cart-line-info">
        <h2>{href ? <Link href={href}>{name}</Link> : name}</h2>
        {line.sku && (
          <span className="cart-line-sku">
            {t.product.sku}: <span className="mono" dir="ltr">{line.sku}</span>
          </span>
        )}
        {!line.issue || line.issue === "insufficient_stock" || line.issue === "max_per_order" ? (
          <span className="cart-line-unit">
            {formatEGP(line.unitPrice, locale)} {t.cart.each}
            {line.regularUnitPrice > line.unitPrice && (
              <>
                {" "}
                <s className="muted">{formatEGP(line.regularUnitPrice, locale)}</s>
              </>
            )}
          </span>
        ) : null}
        {line.issue && (
          <p className="cart-line-issue" role="alert">
            <Icon name="alert" />
            {issueText(line.issue, line, t)}
            {(line.issue === "insufficient_stock" || line.issue === "max_per_order") && line.maxQuantity > 0 && (
              <button type="button" className="btn btn-sm btn-outline" onClick={() => setQuantity(line.productId, line.maxQuantity)}>
                {fill(t.cart.reduceTo, { count: line.maxQuantity })}
              </button>
            )}
          </p>
        )}
      </div>
      <div className="cart-line-actions">
        {!line.issue && <span className="cart-line-total">{formatEGP(line.lineTotal, locale)}</span>}
        <div className="cart-line-controls">
          {canStep && (
            <QtyStepper
              size="sm"
              value={entry.quantity}
              max={Math.max(line.maxQuantity, 1)}
              onChange={(q) => setQuantity(line.productId, q)}
              label={fill(t.cart.quantityFor, { name })}
            />
          )}
          <button type="button" className="icon-btn" aria-label={fill(t.cart.removeItem, { name })} title={t.cart.remove} onClick={remove}>
            <Icon name="trash" />
          </button>
        </div>
      </div>
    </li>
  );
}

export function CartView({ governorates }: { governorates: GovernorateOption[] }) {
  const { locale, t } = useI18n();
  const store = useStore();
  const notify = useToast();
  const hasItems = store.ready && store.cart.length > 0;
  const gov = store.governorate && governorates.some((g) => g.id === store.governorate) ? store.governorate : null;
  const { status, quote, shippingError, retry } = useQuote(store.cart, gov, hasItems);
  const govName = governorates.find((g) => g.id === gov)?.name;
  const entries = useMemo(() => new Map(store.cart.map((l) => [l.productId, l])), [store.cart]);
  const announced = useRef("");

  // Announce price/stock problems once per distinct set.
  useEffect(() => {
    const issues = quote?.lines.filter((l) => l.issue).map((l) => l.productId + l.issue).join();
    if (issues && issues !== announced.current && status === "ready") notify(t.cart.blocked, { kind: "error" });
    announced.current = issues ?? "";
  }, [quote, status, notify, t.cart.blocked]);

  if (!store.ready) {
    return (
      <ul className="cart-lines" aria-busy="true" aria-label={t.common.loading}>
        <LineSkeleton />
        <LineSkeleton />
      </ul>
    );
  }

  if (!hasItems) {
    return (
      <div className="card empty">
        <span className="empty-icon">
          <Icon name="bag" />
        </span>
        <h2>{t.cart.empty}</h2>
        <p>{t.cart.emptyBody}</p>
        <Link className="btn btn-primary" href={localePath(locale, "/products")}>
          {t.cart.continue}
        </Link>
      </div>
    );
  }

  // Only show lines that are still in the browser cart (removals apply instantly).
  const lines = quote?.lines.filter((l) => entries.has(l.productId)) ?? [];
  const stale = status === "loading" && !!quote;

  return (
    <div className="cart-layout">
      <section aria-labelledby="cart-items">
        <div className="cart-head">
          <h2 id="cart-items" className="visually-hidden">
            {t.cart.items}
          </h2>
          <span className="muted" aria-live="polite">
            {stale ? t.cart.updating : countText(t.cart.itemsCount, store.cart.reduce((n, l) => n + l.quantity, 0), locale)}
          </span>
          <ConfirmClear
            onConfirm={() => {
              clearCart();
              notify(t.cart.cleared);
            }}
          />
        </div>
        {status === "error" && (
          <div className="alert alert-error" role="alert" style={{ marginBottom: "var(--sp-4)" }}>
            <Icon name="alert" />
            <div className="stack" style={{ gap: "var(--sp-2)" }}>
              <span>{t.cart.loadError}</span>
              <button type="button" className="btn btn-sm btn-outline" onClick={retry} style={{ justifySelf: "start" }}>
                <Icon name="refresh" />
                {t.common.retry}
              </button>
            </div>
          </div>
        )}
        <ul className="cart-lines" aria-busy={status === "loading"}>
          {!quote && store.cart.map((l) => <LineSkeleton key={l.productId} />)}
          {lines.map((line) => (
            <CartLine key={line.productId} line={line} entry={entries.get(line.productId)!} />
          ))}
        </ul>
        <Link className="link-arrow" href={localePath(locale, "/products")} style={{ marginTop: "var(--sp-4)" }}>
          <Icon name="arrowLeft" className="flip-rtl" />
          {t.cart.continue}
        </Link>
      </section>
      <aside className="card summary" aria-labelledby="summary-title" aria-busy={status === "loading"}>
        <h2 id="summary-title">{t.cart.summary}</h2>
        <div className="field">
          <label htmlFor="cart-gov">{t.cart.shippingFor}</label>
          <GovernorateSelect id="cart-gov" value={gov ?? ""} options={governorates} onChange={(v) => setGovernorate(v || null)} />
        </div>
        {quote ? (
          <Totals quote={quote} governorateName={govName} shippingError={shippingError} />
        ) : (
          <div className="skeleton" style={{ height: 120 }} aria-hidden="true" />
        )}
        {quote && !quote.purchasable && (
          <p className="alert alert-warning" role="status">
            <Icon name="alert" />
            {t.cart.blocked}
          </p>
        )}
        {quote?.purchasable && status !== "error" ? (
          <Link className="btn btn-primary btn-lg btn-block" href={localePath(locale, "/checkout")} data-testid="go-checkout">
            {t.cart.checkout}
            <Icon name="arrowRight" className="flip-rtl" />
          </Link>
        ) : (
          <button type="button" className="btn btn-primary btn-lg btn-block" disabled>
            {t.cart.checkout}
          </button>
        )}
        <p className="note">{t.checkout.secureNote}</p>
      </aside>
    </div>
  );
}
