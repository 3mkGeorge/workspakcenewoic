"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { localePath } from "@/i18n/config";
import { validateCustomer, type CheckoutErrors, type FieldError } from "@/lib/commerce/checkout-validation";
import { formatEGP } from "@/lib/commerce/money";
import { safeImageSrc } from "@/lib/commerce/safe-image";
import type { CartQuote, CheckoutCustomer, PaymentMethodId } from "@/lib/commerce/types";
import { clearCart, rememberOrder, setGovernorate, useStore } from "@/lib/client/store";
import { GovernorateSelect, LineSkeleton, Totals, useQuote, type GovernorateOption } from "./cart";
import { useI18n } from "./I18nProvider";

export interface PaymentOption {
  id: PaymentMethodId;
  label: string;
  description: string;
}

const DRAFT_KEY = "nextchip:checkout-draft:v1";
type Draft = Omit<CheckoutCustomer, "governorate">;
const EMPTY: Draft = { name: "", phone: "", city: "", address: "", notes: "" };

/** 32 hex chars from the CSPRNG; works on plain http too (unlike randomUUID). */
function newRequestId() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
}

type SubmitState =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "error"; message: string; focus: "field" | "alert" }
  | { kind: "placed"; orderId: string };

export function CheckoutView({ governorates, payments, mode }: { governorates: GovernorateOption[]; payments: PaymentOption[]; mode: "demo" | "storepro" }) {
  const { locale, t } = useI18n();
  const router = useRouter();
  const store = useStore();
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [payment, setPayment] = useState<PaymentMethodId | "">(payments.length === 1 ? payments[0]!.id : "");
  const [errors, setErrors] = useState<CheckoutErrors>({});
  const [submit, setSubmit] = useState<SubmitState>({ kind: "idle" });
  const [cartChanged, setCartChanged] = useState<CartQuote | null>(null);
  const requestId = useRef<string>("");
  // Synchronous guard: state updates are async, so rapid repeat clicks could otherwise all pass.
  const inFlight = useRef(false);
  const formRef = useRef<HTMLFormElement>(null);
  const alertRef = useRef<HTMLDivElement>(null);

  const gov = store.governorate && governorates.some((g) => g.id === store.governorate) ? store.governorate : "";
  const hasItems = store.ready && store.cart.length > 0;
  const placed = submit.kind === "placed";
  const { status, quote, shippingError, retry } = useQuote(store.cart, gov || null, hasItems && !placed);
  const govName = governorates.find((g) => g.id === gov)?.name;
  const cartKey = JSON.stringify(store.cart);

  // Restore an unfinished form from this tab's session (never the payment choice).
  useEffect(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(DRAFT_KEY) ?? "null") as Partial<Draft> | null;
      if (saved && typeof saved === "object") {
        setDraft((d) => {
          const next = { ...d };
          for (const k of Object.keys(EMPTY) as (keyof Draft)[]) if (typeof saved[k] === "string") next[k] = saved[k]!.slice(0, 500);
          return next;
        });
      }
    } catch {
      /* ignore */
    }
  }, []);
  useEffect(() => {
    if (placed) return;
    try {
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    } catch {
      /* ignore */
    }
  }, [draft, placed]);

  // A new idempotency key whenever the cart contents change; retries of the same cart reuse it.
  useEffect(() => {
    requestId.current = newRequestId();
  }, [cartKey]);

  const messages: Record<FieldError, string> = {
    required: t.checkout.errorRequired,
    too_short: t.checkout.errorShort,
    too_long: t.checkout.errorLong,
    invalid_phone: t.checkout.errorPhone,
    unknown_governorate: t.checkout.errorGovernorate,
    invalid: t.checkout.errorPayment,
  };

  const update = (key: keyof Draft) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const value = e.target.value;
    setDraft((d) => ({ ...d, [key]: value }));
    if (errors[key]) setErrors((er) => ({ ...er, [key]: undefined }));
  };

  const focusFirstError = (errs: CheckoutErrors) => {
    const order: (keyof CheckoutErrors)[] = ["name", "phone", "governorate", "city", "address", "notes", "paymentMethod"];
    const first = order.find((k) => errs[k]);
    if (!first) return;
    const el = formRef.current?.querySelector<HTMLElement>(first === "paymentMethod" ? 'input[name="payment"]' : `[name="${first}"]`);
    el?.focus();
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (inFlight.current || placed) return; // duplicate-submit guard
    setCartChanged(null);
    // Same rules as the server, for instant feedback. The server re-validates everything.
    const customer = { ...draft, governorate: gov };
    const { errors: errs } = validateCustomer(customer, governorates.map((g) => g.id));
    if (!payment) errs.paymentMethod = "invalid";
    if (Object.keys(errs).length) {
      setErrors(errs);
      setSubmit({ kind: "error", message: t.checkout.errorSummary, focus: "field" });
      focusFirstError(errs);
      return;
    }
    if (!quote?.purchasable) {
      setSubmit({ kind: "error", message: t.checkout.errorCart, focus: "alert" });
      return;
    }
    setErrors({});
    inFlight.current = true;
    setSubmit({ kind: "submitting" });
    let response: Response;
    try {
      response = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ customer, lines: store.cart, paymentMethod: payment, requestId: requestId.current }),
      });
    } catch {
      inFlight.current = false;
      setSubmit({ kind: "error", message: t.checkout.errorNetwork, focus: "alert" });
      return;
    }
    let data: Record<string, unknown> = {};
    try {
      data = (await response.json()) as Record<string, unknown>;
    } catch {
      /* non-JSON error page */
    }
    if (response.status === 201 && data.ok === true && data.order && typeof data.order === "object") {
      const order = data.order as { id: string; createdAt: string; demo: boolean; totals: { total: number; itemCount: number } };
      // Only now — after the provider confirmed — is anything shown as placed.
      rememberOrder({ id: order.id, createdAt: order.createdAt, total: order.totals.total, itemCount: order.totals.itemCount, demo: order.demo });
      setSubmit({ kind: "placed", orderId: order.id });
      try {
        sessionStorage.removeItem(DRAFT_KEY);
      } catch {
        /* ignore */
      }
      router.replace(localePath(locale, `/order/${encodeURIComponent(order.id)}`));
      clearCart();
      return;
    }
    inFlight.current = false;
    if (data.reason === "invalid" && data.errors && typeof data.errors === "object") {
      const errs = data.errors as CheckoutErrors;
      setErrors(errs);
      setSubmit({ kind: "error", message: errs.lines ? t.checkout.errorCart : t.checkout.errorSummary, focus: errs.lines ? "alert" : "field" });
      focusFirstError(errs);
      return;
    }
    if (data.reason === "cart") {
      setCartChanged((data.quote as CartQuote) ?? null);
      setSubmit({ kind: "error", message: t.checkout.errorCart, focus: "alert" });
      retry();
      return;
    }
    if (data.reason === "shipping") {
      setErrors({ governorate: "unknown_governorate" });
      setSubmit({ kind: "error", message: t.checkout.errorShipping, focus: "field" });
      focusFirstError({ governorate: "unknown_governorate" });
      return;
    }
    setSubmit({ kind: "error", message: response.status === 503 ? t.pages.unavailableBody : t.checkout.errorServer, focus: "alert" });
  };

  useEffect(() => {
    // Field errors move focus to the first invalid field; other failures to the message.
    if (submit.kind === "error" && submit.focus === "alert") alertRef.current?.focus();
  }, [submit]);

  const fieldProps = (key: keyof CheckoutCustomer, hint = false) => ({
    id: `co-${key}`,
    name: key,
    "aria-invalid": errors[key] ? true : undefined,
    "aria-describedby": [errors[key] ? `co-${key}-error` : "", hint ? `co-${key}-hint` : ""].filter(Boolean).join(" ") || undefined,
  });
  const errorText = (key: keyof CheckoutErrors) =>
    errors[key] ? (
      <span className="error" id={`co-${key}-error`}>
        <Icon name="alert" />
        {messages[errors[key]!]}
      </span>
    ) : null;

  const busy = submit.kind === "submitting";
  const issues = useMemo(() => (cartChanged ?? quote)?.lines.filter((l) => l.issue) ?? [], [cartChanged, quote]);

  if (placed) {
    return (
      <div className="card empty" role="status">
        <span className="spinner" aria-hidden="true" />
        <p>{t.checkout.redirecting}</p>
      </div>
    );
  }
  if (!store.ready) {
    return (
      <ul className="cart-lines" aria-busy="true" aria-label={t.common.loading}>
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
        <h2>{t.checkout.emptyCart}</h2>
        <Link className="btn btn-primary" href={localePath(locale, "/products")}>
          {t.cart.continue}
        </Link>
      </div>
    );
  }

  return (
    <div className="checkout-layout">
      <form ref={formRef} className="checkout-form" noValidate onSubmit={onSubmit} aria-describedby="co-demo">
        {mode === "demo" && (
          <div className="alert alert-demo" id="co-demo">
            <Icon name="info" />
            <span>{t.checkout.demoNotice}</span>
          </div>
        )}
        {submit.kind === "error" && (
          <div className="alert alert-error" role="alert" tabIndex={-1} ref={alertRef}>
            <Icon name="alert" />
            <div className="stack" style={{ gap: "var(--sp-2)" }}>
              <span>{submit.message}</span>
              {issues.length > 0 && (
                <Link className="btn btn-sm btn-outline" href={localePath(locale, "/cart")} style={{ justifySelf: "start" }}>
                  {t.checkout.backToCart}
                </Link>
              )}
            </div>
          </div>
        )}
        <fieldset disabled={busy}>
          <div className="card form-section">
            <h2>
              <span className="step">1</span>
              {t.checkout.contact}
            </h2>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="co-name">{t.checkout.name}</label>
                <input className="input" autoComplete="name" maxLength={80} value={draft.name} onChange={update("name")} {...fieldProps("name")} />
                {errorText("name")}
              </div>
              <div className="field">
                <label htmlFor="co-phone">{t.checkout.phone}</label>
                <input
                  className="input"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  dir="ltr"
                  maxLength={20}
                  placeholder="01X XXXX XXXX"
                  value={draft.phone}
                  onChange={update("phone")}
                  {...fieldProps("phone", true)}
                />
                <span className="hint" id="co-phone-hint">
                  {t.checkout.phoneHint}
                </span>
                {errorText("phone")}
              </div>
            </div>
          </div>
        </fieldset>
        <fieldset disabled={busy}>
          <div className="card form-section">
            <h2>
              <span className="step">2</span>
              {t.checkout.delivery}
            </h2>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="co-governorate">{t.checkout.governorate}</label>
                <GovernorateSelect
                  id="co-governorate"
                  value={gov}
                  options={governorates}
                  invalid={!!errors.governorate}
                  describedBy={errors.governorate ? "co-governorate-error" : undefined}
                  onChange={(v) => {
                    setGovernorate(v || null);
                    if (errors.governorate) setErrors((er) => ({ ...er, governorate: undefined }));
                  }}
                />
                {errorText("governorate")}
              </div>
              <div className="field">
                <label htmlFor="co-city">{t.checkout.city}</label>
                <input className="input" autoComplete="address-level2" maxLength={60} value={draft.city} onChange={update("city")} {...fieldProps("city")} />
                {errorText("city")}
              </div>
              <div className="field span-2">
                <label htmlFor="co-address">{t.checkout.address}</label>
                <input className="input" autoComplete="street-address" maxLength={300} value={draft.address} onChange={update("address")} {...fieldProps("address")} />
                {errorText("address")}
              </div>
              <div className="field span-2">
                <label htmlFor="co-notes">{t.checkout.notes}</label>
                <textarea className="textarea" maxLength={500} rows={3} value={draft.notes} onChange={update("notes")} {...fieldProps("notes", true)} />
                <span className="hint" id="co-notes-hint">
                  {t.checkout.notesHint}
                </span>
                {errorText("notes")}
              </div>
            </div>
          </div>
        </fieldset>
        <fieldset disabled={busy}>
          <div className="card form-section" role="radiogroup" aria-labelledby="co-pay-title" aria-describedby={errors.paymentMethod ? "co-paymentMethod-error" : undefined}>
            <h2 id="co-pay-title">
              <span className="step">3</span>
              {t.checkout.payment}
            </h2>
            <div className="payment-options">
              {payments.map((m) => (
                <label key={m.id} className="radio-card">
                  <input type="radio" name="payment" value={m.id} checked={payment === m.id} onChange={() => setPayment(m.id)} />
                  <div>
                    <strong>{m.label}</strong>
                    <span>{m.description}</span>
                  </div>
                </label>
              ))}
            </div>
            {errorText("paymentMethod")}
          </div>
        </fieldset>
        <div className="stack" style={{ gap: "var(--sp-3)" }}>
          {quote?.shipping && quote.purchasable && (
            <p className="checkout-total" aria-live="polite">
              <span>{t.checkout.totalToPay}</span>
              <strong className="num" data-testid="checkout-total">
                {formatEGP(quote.totals.total, locale)}
              </strong>
            </p>
          )}
          <button
            type="submit"
            className="btn btn-primary btn-lg btn-block"
            disabled={busy || status === "error" || !quote || !quote.purchasable}
            aria-busy={busy}
            data-testid="place-order"
          >
            {busy && <span className="spinner" aria-hidden="true" />}
            {busy ? t.checkout.placing : mode === "demo" ? t.checkout.placeOrder : t.checkout.placeRealOrder}
          </button>
          <p className="buy-hint" style={{ textAlign: "center" }}>
            {t.checkout.secureNote}
          </p>
        </div>
      </form>

      <aside className="card summary" aria-labelledby="co-summary" aria-busy={status === "loading"}>
        <h2 id="co-summary">{t.cart.summary}</h2>
        {quote ? (
          <ul className="summary-lines">
            {quote.lines.map((line) => (
              <li key={line.productId}>
                <Image src={safeImageSrc(line.image?.src)} alt="" width={52} height={52} sizes="52px" />
                <div style={{ minWidth: 0 }}>
                  <span className="name">{line.name || t.cart.unknownItem}</span>
                  <span className="qty-x">
                    {line.quantity} × {formatEGP(line.unitPrice, locale)}
                  </span>
                  {line.issue && <span className="cart-line-issue">{t.cart.needsAttention}</span>}
                </div>
                <span className="amt">{line.issue ? "—" : formatEGP(line.lineTotal, locale)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="skeleton" style={{ height: 120 }} aria-hidden="true" />
        )}
        {status === "error" && (
          <div className="alert alert-error" role="alert">
            <Icon name="alert" />
            <div className="stack" style={{ gap: "var(--sp-2)" }}>
              <span>{t.cart.loadError}</span>
              <button type="button" className="btn btn-sm btn-outline" onClick={retry} style={{ justifySelf: "start" }}>
                {t.common.retry}
              </button>
            </div>
          </div>
        )}
        {quote && <Totals quote={quote} governorateName={govName} shippingError={shippingError} />}
        {quote && !quote.purchasable && (
          <p className="alert alert-warning">
            <Icon name="alert" />
            <span>
              {t.cart.blocked} <Link href={localePath(locale, "/cart")}>{t.checkout.backToCart}</Link>
            </span>
          </p>
        )}
        <Link className="link-arrow" href={localePath(locale, "/cart")}>
          <Icon name="arrowLeft" className="flip-rtl" />
          {t.checkout.editCart}
        </Link>
      </aside>
    </div>
  );
}
