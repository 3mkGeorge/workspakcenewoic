"use client";

import Link from "next/link";
import { useEffect, useId, useState } from "react";
import { Icon } from "@/components/Icon";
import { localePath } from "@/i18n/config";
import { fill } from "@/i18n/format";
import { normalizeDigits } from "@/lib/commerce/checkout-validation";
import { addToCart, quantityInCart, toggleWishlist, useStore } from "@/lib/client/store";
import { useI18n } from "./I18nProvider";
import { useToast } from "./Toaster";

export function WishlistButton({ productId, name, className, withLabel = false }: { productId: string; name: string; className: string; withLabel?: boolean }) {
  const { locale, t } = useI18n();
  const notify = useToast();
  const store = useStore();
  const saved = store.wishlist.includes(productId);
  const label = saved ? t.product.removeFromWishlist : t.product.addToWishlist;
  return (
    <button
      type="button"
      className={`${className}${saved ? " is-active" : ""}`}
      aria-pressed={saved}
      aria-label={withLabel ? undefined : `${label}: ${name}`}
      title={withLabel ? undefined : label}
      data-testid="wishlist-toggle"
      onClick={() => {
        const now = toggleWishlist(productId);
        notify(now ? t.product.savedToWishlist : t.product.removedFromWishlist, {
          action: now ? { href: localePath(locale, "/wishlist"), label: t.nav.wishlist } : undefined,
        });
      }}
    >
      <Icon name="heart" filled={saved} />
      {withLabel && <span>{label}</span>}
    </button>
  );
}

function useAdd(productId: string, name: string, max: number) {
  const { locale, t } = useI18n();
  const notify = useToast();
  return (quantity: number) => {
    const before = quantityInCart(productId);
    const result = addToCart(productId, quantity, max);
    const viewCart = { href: localePath(locale, "/cart"), label: t.product.viewCart };
    if (result.quantity === before) {
      notify(fill(t.product.limitReached, { count: max }), { kind: "error", action: viewCart });
    } else if (result.capped) {
      notify(fill(t.product.addedCapped, { count: result.quantity, name }), { action: viewCart });
    } else {
      notify(fill(t.product.addedNamed, { name }), { action: viewCart });
    }
  };
}

/** Compact "Add to cart" used on product cards. */
export function QuickAdd({ productId, name, max }: { productId: string; name: string; max: number }) {
  const { t } = useI18n();
  const add = useAdd(productId, name, max);
  if (max <= 0) {
    return (
      <button type="button" className="btn btn-outline btn-sm btn-block" disabled>
        {t.product.soldOut}
      </button>
    );
  }
  return (
    <button type="button" className="btn btn-outline btn-sm btn-block" onClick={() => add(1)} data-testid="quick-add">
      <Icon name="bag" />
      {t.product.addToCart}
    </button>
  );
}

/** Numeric stepper that never yields a value outside [min, max]. */
export function QtyStepper({
  value,
  min = 1,
  max,
  onChange,
  label,
  size,
  disabled = false,
  id,
}: {
  value: number;
  min?: number;
  max: number;
  onChange: (value: number) => void;
  label: string;
  size?: "sm";
  disabled?: boolean;
  id?: string;
}) {
  const { t } = useI18n();
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const clamp = (n: number) => Math.min(Math.max(n, min), Math.max(min, max));
  const commit = (raw: string) => {
    const n = Number.parseInt(normalizeDigits(raw), 10);
    const next = Number.isFinite(n) ? clamp(n) : value;
    setText(String(next));
    if (next !== value) onChange(next);
  };
  return (
    <div className={`qty${size === "sm" ? " qty-sm" : ""}`} role="group" aria-label={label}>
      <button type="button" aria-label={t.product.decrease} disabled={disabled || value <= min} onClick={() => onChange(clamp(value - 1))}>
        <Icon name="minus" />
      </button>
      <input
        id={id}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        aria-label={label}
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value.replace(/[^\d٠-٩۰-۹]/g, "").slice(0, 2))}
        onBlur={(e) => commit(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit(e.currentTarget.value);
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            onChange(clamp(value + 1));
          } else if (e.key === "ArrowDown") {
            e.preventDefault();
            onChange(clamp(value - 1));
          }
        }}
      />
      <button type="button" aria-label={t.product.increase} disabled={disabled || value >= max} onClick={() => onChange(clamp(value + 1))}>
        <Icon name="plus" />
      </button>
    </div>
  );
}

/** Product page purchase controls. */
export function BuyBox({ productId, name, max, maxPerOrder }: { productId: string; name: string; max: number; maxPerOrder: number }) {
  const { locale, t } = useI18n();
  const store = useStore();
  const inCart = store.cart.find((l) => l.productId === productId)?.quantity ?? 0;
  const remaining = Math.max(0, max - inCart);
  const [qty, setQty] = useState(1);
  const [busy, setBusy] = useState(false);
  const add = useAdd(productId, name, max);
  const qtyId = useId();

  useEffect(() => {
    if (store.ready && qty > Math.max(1, remaining)) setQty(Math.max(1, remaining));
  }, [store.ready, remaining, qty]);

  if (max <= 0) {
    return (
      <div className="stack">
        <div className="buy-row">
          <button type="button" className="btn btn-primary btn-lg" disabled>
            {t.product.soldOut}
          </button>
          <WishlistButton productId={productId} name={name} className="btn btn-outline btn-lg" withLabel />
        </div>
        <p className="buy-hint">{t.product.soldOutHint}</p>
      </div>
    );
  }

  return (
    <div className="stack">
      <div className="buy-row">
        <div className="field">
          <label className="label" htmlFor={qtyId}>
            {t.product.quantity}
          </label>
          <QtyStepper id={qtyId} value={qty} max={Math.max(1, remaining)} onChange={setQty} label={t.product.quantity} disabled={remaining === 0} />
        </div>
        <button
          type="button"
          className="btn btn-primary btn-lg"
          disabled={remaining === 0 || busy}
          aria-busy={busy}
          data-testid="add-to-cart"
          onClick={() => {
            setBusy(true);
            add(qty);
            setQty(1);
            // Brief lock against accidental double taps.
            setTimeout(() => setBusy(false), 400);
          }}
        >
          <Icon name="bag" />
          {remaining === 0 ? t.product.maxInCart : t.product.addToCart}
        </button>
      </div>
      <div className="buy-row">
        <WishlistButton productId={productId} name={name} className="btn btn-outline" withLabel />
        {inCart > 0 && (
          <Link className="btn btn-ghost" href={localePath(locale, "/cart")}>
            {fill(t.product.inCart, { count: inCart })}
            <Icon name="arrowRight" className="flip-rtl" />
          </Link>
        )}
      </div>
      <p className="buy-hint">{fill(t.product.maxPerOrder, { count: maxPerOrder })}</p>
    </div>
  );
}
