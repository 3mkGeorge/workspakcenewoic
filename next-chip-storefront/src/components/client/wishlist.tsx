"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { ProductGrid } from "@/components/Product";
import { localePath } from "@/i18n/config";
import type { CatalogItem } from "@/lib/commerce/types";
import { useStore } from "@/lib/client/store";
import { useI18n } from "./I18nProvider";

export function WishlistView() {
  const { locale, t } = useI18n();
  const store = useStore();
  const [items, setItems] = useState<CatalogItem[] | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const ids = store.wishlist.join(",");

  useEffect(() => {
    if (!store.ready) return;
    if (!ids) {
      setItems([]);
      return;
    }
    const ctrl = new AbortController();
    setError(false);
    fetch(`/api/products?ids=${encodeURIComponent(ids)}`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: { items: CatalogItem[] }) => {
        // Keep the shopper's order (most recently saved first).
        const order = ids.split(",");
        setItems([...data.items].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id)));
      })
      .catch((e: unknown) => {
        if ((e as Error).name !== "AbortError") setError(true);
      });
    return () => ctrl.abort();
  }, [ids, store.ready, attempt]);

  if (error) {
    return (
      <div className="alert alert-error" role="alert">
        <Icon name="alert" />
        <div className="stack" style={{ gap: "var(--sp-2)" }}>
          <span>{t.wishlist.loadError}</span>
          <button type="button" className="btn btn-sm btn-outline" style={{ justifySelf: "start" }} onClick={() => setAttempt((a) => a + 1)}>
            {t.common.retry}
          </button>
        </div>
      </div>
    );
  }
  if (!store.ready || items === null) {
    return (
      <div className="product-grid cols-4" aria-busy="true" aria-label={t.common.loading}>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="skeleton" style={{ aspectRatio: "0.72" }} />
        ))}
      </div>
    );
  }
  // Items removed from the wishlist in this view disappear without a refetch.
  const visible = items.filter((i) => store.wishlist.includes(i.id));
  if (!visible.length) {
    return (
      <div className="card empty">
        <span className="empty-icon">
          <Icon name="heart" />
        </span>
        <h2>{t.wishlist.empty}</h2>
        <p>{t.wishlist.emptyBody}</p>
        <Link className="btn btn-primary" href={localePath(locale, "/products")}>
          {t.cart.continue}
        </Link>
      </div>
    );
  }
  return <ProductGrid items={visible} locale={locale} t={t} cols4 headingLevel={2} />;
}
