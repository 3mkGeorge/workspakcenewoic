import "server-only";

import pg from "pg";
import { ProviderUnavailableError } from "@/lib/commerce/providers";
import { fromPgPool, type Db } from "./db";
import { createCatalogStore, type CatalogStore } from "./store";

/** Must equal the newest file in db/migrations (asserted by a unit test). */
export const EXPECTED_SCHEMA_VERSION = "0001_synced_catalog";

interface Holder {
  db: Db;
  store: CatalogStore;
  schemaChecked: boolean;
}
// One pool per server process (route handlers and pages are bundled separately).
const g = globalThis as typeof globalThis & { __nextChipCatalog?: Holder };

function holder(): Holder {
  if (g.__nextChipCatalog) return g.__nextChipCatalog;
  const url = process.env.DATABASE_URL?.trim();
  if (!url) throw new ProviderUnavailableError("DATABASE_URL is not configured for the synchronized catalog.");
  const pool = new pg.Pool({
    connectionString: url,
    max: Number(process.env.DATABASE_POOL_MAX ?? 5),
    connectionTimeoutMillis: 5_000,
    idleTimeoutMillis: 30_000,
    ssl: process.env.DATABASE_SSL === "require" ? { rejectUnauthorized: true } : undefined,
  });
  // Never let an idle-connection error crash the server; the next query reconnects.
  pool.on("error", (e) => console.error("[catalog-db] idle client error:", e.message));
  const db = fromPgPool(pool);
  g.__nextChipCatalog = { db, store: createCatalogStore(db), schemaChecked: false };
  return g.__nextChipCatalog;
}

/** The synchronized catalog store. Throws ProviderUnavailableError when unreachable or not migrated. */
export async function getCatalogStore(): Promise<CatalogStore> {
  const h = holder();
  if (!h.schemaChecked) {
    try {
      const r = await h.db.query<{ version: string }>("SELECT version FROM schema_migrations WHERE version = $1", [EXPECTED_SCHEMA_VERSION]);
      if (!r.rows.length) throw new Error("missing");
    } catch {
      throw new ProviderUnavailableError(`Catalog database is not reachable or not migrated to ${EXPECTED_SCHEMA_VERSION} (run npm run db:migrate).`);
    }
    h.schemaChecked = true;
  }
  return h.store;
}
