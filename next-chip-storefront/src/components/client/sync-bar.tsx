"use client";

import { useEffect, useState } from "react";
import { relativeTime } from "@/i18n/format";
import { useI18n } from "./I18nProvider";

interface Status {
  available?: boolean;
  lastUpdatedAt?: string | null;
  published?: boolean;
  stale?: boolean;
}

/**
 * Synced-catalog notice: real products, demo checkout (Stage 1). Adds an
 * explicit warning when StorePro hasn't delivered a fresh snapshot recently,
 * so stale prices or stock are never presented as current.
 */
export function SyncBar() {
  const { locale, t } = useI18n();
  const [status, setStatus] = useState<Status | null>(null);
  useEffect(() => {
    const ctrl = new AbortController();
    fetch("/api/catalog/status", { signal: ctrl.signal, cache: "no-store" })
      .then((r) => r.json())
      .then((s: Status) => setStatus(s))
      .catch(() => {});
    return () => ctrl.abort();
  }, []);
  const stale = status?.available && status.stale;
  return (
    <div className={`demo-bar${stale ? " is-stale" : ""}`} role="note" aria-label={t.demo.syncedBadge} data-testid="sync-bar">
      <div className="container">
        <span className="badge badge-soft">{t.demo.syncedBadge}</span>
        <p>
          {t.demo.syncedBanner}
          {status?.available === false && <> {t.demo.catalogUnavailable}</>}
          {stale && status?.lastUpdatedAt && <> {t.demo.staleNotice.replace("{time}", relativeTime(status.lastUpdatedAt, locale))}</>}
          {stale && !status?.lastUpdatedAt && <> {t.demo.neverSynced}</>}
        </p>
      </div>
    </div>
  );
}
