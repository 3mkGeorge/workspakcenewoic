"use client";

import Link from "next/link";
import { Icon } from "@/components/Icon";
import { localePath } from "@/i18n/config";
import { useI18n } from "./I18nProvider";

/** Not-found screens. Client-side so they can read the active locale from context. */
export function NotFoundView({ kind = "page" }: { kind?: "page" | "product" | "order" }) {
  const { locale, t } = useI18n();
  const copy =
    kind === "product"
      ? { title: t.product.notFoundTitle, body: t.product.notFoundBody }
      : kind === "order"
        ? { title: t.order.notFoundTitle, body: t.order.notFoundBody }
        : { title: t.pages.notFoundTitle, body: t.pages.notFoundBody };
  return (
    <div className="container status-page">
      <div className="empty">
        <span className="code" aria-hidden="true">
          404
        </span>
        <h1 style={{ fontSize: "var(--fs-2xl)" }}>{copy.title}</h1>
        <p>{copy.body}</p>
        <div style={{ display: "flex", gap: "var(--sp-3)", flexWrap: "wrap", justifyContent: "center" }}>
          <Link className="btn btn-primary" href={localePath(locale, kind === "order" ? "/account" : "/products")}>
            {kind === "order" ? t.account.title : t.nav.browseAll}
          </Link>
          <Link className="btn btn-outline" href={localePath(locale)}>
            {t.common.backHome}
          </Link>
        </div>
      </div>
    </div>
  );
}

export function ErrorView({ retry }: { retry: () => void }) {
  const { locale, t } = useI18n();
  return (
    <div className="container status-page">
      <div className="empty" role="alert">
        <span className="empty-icon">
          <Icon name="alert" />
        </span>
        <h1 style={{ fontSize: "var(--fs-2xl)" }}>{t.pages.errorTitle}</h1>
        <p>{t.pages.errorBody}</p>
        <div style={{ display: "flex", gap: "var(--sp-3)", flexWrap: "wrap", justifyContent: "center" }}>
          <button type="button" className="btn btn-primary" onClick={retry}>
            <Icon name="refresh" />
            {t.common.retry}
          </button>
          <Link className="btn btn-outline" href={localePath(locale)}>
            {t.common.backHome}
          </Link>
        </div>
      </div>
    </div>
  );
}
