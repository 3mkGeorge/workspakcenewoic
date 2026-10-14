"use client";

import Link from "next/link";
import { localePath } from "@/i18n/config";
import { formatEGP } from "@/lib/commerce/money";
import { useStore } from "@/lib/client/store";
import { countText, dateLocale } from "@/i18n/format";
import { useI18n } from "./I18nProvider";

export function DemoOrders() {
  const { locale, t } = useI18n();
  const store = useStore();
  const dateFmt = new Intl.DateTimeFormat(dateLocale(locale), { dateStyle: "medium", timeStyle: "short", timeZone: "Africa/Cairo" });
  if (!store.ready) return <div className="skeleton" style={{ height: 72 }} aria-hidden="true" />;
  if (!store.orders.length) return <p className="muted">{t.account.noOrders}</p>;
  return (
    <ul className="account-orders">
      {store.orders.map((o) => (
        <li key={o.id}>
          <Link className="card" href={localePath(locale, `/order/${encodeURIComponent(o.id)}`)}>
            <span>
              <span className="mono" dir="ltr">
                {o.id}
              </span>
              {o.demo && (
                <>
                  {" "}
                  <span className="badge badge-soft">{t.demo.badge}</span>
                </>
              )}
              <span className="muted" style={{ display: "block", fontSize: "var(--fs-xs)" }}>
                {o.createdAt ? dateFmt.format(new Date(o.createdAt)) : ""} · {countText(t.cart.itemsCount, o.itemCount, locale)}
              </span>
            </span>
            <span className="num">{formatEGP(o.total, locale)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
