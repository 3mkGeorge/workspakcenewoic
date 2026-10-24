/**
 * Persistent synchronized catalog (PostgreSQL). Writes happen only through
 * applySnapshot (one transaction per snapshot); reads serve published rows.
 * Nothing here ever deletes catalog rows: removal means published = false.
 */
import { createHash } from "node:crypto";
import type { Db, Queryable } from "./db.ts";
import type { SyncSnapshot } from "../sync/protocol.ts";

export const SOURCE = "storepro";
const NONCE_TTL_MINUTES = 15;

export class SyncRejected extends Error {
  constructor(
    public readonly code: "stale_snapshot" | "snapshot_conflict" | "invalid_reference" | "conflict",
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "SyncRejected";
  }
}

export interface ApplyResult {
  status: "applied" | "unchanged" | "duplicate";
  snapshotId: string;
  publishedProducts: number;
  unpublishedProducts: number;
  missingMedia: string[];
}

export interface SyncState {
  lastSuccessAt: string | null;
  lastSnapshotId: string | null;
  lastSequence: number | null;
  lastCompleteAt: string | null;
  publishedProducts: number;
  lastAttemptAt: string | null;
  lastErrorAt: string | null;
  lastError: string | null;
}

export interface ProductRow {
  id: string;
  sku: string;
  slug: string;
  name_en: string;
  name_ar: string;
  description_en: string;
  description_ar: string;
  category_id: string;
  brand_id: string | null;
  price: string;
  compare_at: string | null;
  sale_ends_at: Date | null;
  availability: "in_stock" | "low_stock" | "out_of_stock";
  orderable_quantity: number;
  max_per_order: number;
  images: { hash: string; contentType: string; width: number; height: number }[];
  source_created_at: Date;
}

export interface CategoryRow {
  id: string;
  slug: string;
  name_en: string;
  name_ar: string;
  description_en: string;
  description_ar: string;
  icon: string;
  sort_order: number;
}

export interface BrandRow {
  id: string;
  slug: string;
  name: string;
}

/** Hash of the catalog content (not the envelope) so unchanged re-syncs are cheap. */
export function contentHash(s: SyncSnapshot): string {
  return createHash("sha256").update(JSON.stringify([s.categories, s.brands, s.products])).digest("hex");
}

const iso = (d: Date | string | null | undefined) => (d ? new Date(d).toISOString() : null);

// Images are kept as sent; reads return only those whose bytes have arrived.
const PRESENT_IMAGES = `COALESCE((
  SELECT jsonb_agg(img ORDER BY ord)
  FROM jsonb_array_elements(p.images) WITH ORDINALITY AS t(img, ord)
  WHERE EXISTS (SELECT 1 FROM catalog_media m WHERE m.hash = img->>'hash')
), '[]'::jsonb) AS images`;

const PRODUCT_COLUMNS = `p.id, p.sku, p.slug, p.name_en, p.name_ar, p.description_en, p.description_ar, p.category_id, p.brand_id,
  p.price, p.compare_at, p.sale_ends_at, p.availability, p.orderable_quantity, p.max_per_order, p.source_created_at, ${PRESENT_IMAGES}`;

export function createCatalogStore(db: Db) {
  async function lockState(tx: Queryable) {
    await tx.query("INSERT INTO catalog_sync_state (source) VALUES ($1) ON CONFLICT (source) DO NOTHING", [SOURCE]);
    const r = await tx.query<{ last_sequence: string | null; last_content_hash: string | null; last_complete_at: Date | null }>(
      "SELECT last_sequence, last_content_hash, last_complete_at FROM catalog_sync_state WHERE source = $1 FOR UPDATE",
      [SOURCE],
    );
    return r.rows[0]!;
  }

  async function missingMedia(q: Queryable, hashes: string[]): Promise<string[]> {
    if (!hashes.length) return [];
    const r = await q.query<{ hash: string }>(
      "SELECT h AS hash FROM unnest($1::text[]) AS h WHERE NOT EXISTS (SELECT 1 FROM catalog_media m WHERE m.hash = h)",
      [[...new Set(hashes)]],
    );
    return r.rows.map((x) => x.hash);
  }

  return {
    /** Record a nonce; false means it was already used (replay). Old nonces are purged. */
    async useNonce(nonce: string): Promise<boolean> {
      await db.query(`DELETE FROM catalog_sync_nonces WHERE seen_at < now() - interval '${NONCE_TTL_MINUTES} minutes'`);
      const r = await db.query("INSERT INTO catalog_sync_nonces (nonce) VALUES ($1) ON CONFLICT (nonce) DO NOTHING RETURNING nonce", [nonce]);
      return r.rows.length === 1;
    },

    async noteAttempt() {
      await db.query(
        "INSERT INTO catalog_sync_state (source, last_attempt_at) VALUES ($1, now()) ON CONFLICT (source) DO UPDATE SET last_attempt_at = now()",
        [SOURCE],
      );
    },

    /** Record a rejected or failed sync without touching the published catalog. */
    async recordFailure(message: string, snapshot?: SyncSnapshot, hash?: string) {
      const reason = message.slice(0, 500);
      await db.query(
        `INSERT INTO catalog_sync_state (source, last_attempt_at, last_error_at, last_error) VALUES ($1, now(), now(), $2)
         ON CONFLICT (source) DO UPDATE SET last_attempt_at = now(), last_error_at = now(), last_error = $2`,
        [SOURCE, reason],
      );
      if (snapshot) {
        await db.query(
          `INSERT INTO catalog_snapshots (snapshot_id, source, schema_version, sequence, generated_at, complete, content_hash, product_count, status, error)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'rejected', $9)
           ON CONFLICT (snapshot_id) DO UPDATE SET status = 'rejected', error = $9, received_at = now()
           WHERE catalog_snapshots.status = 'rejected'`,
          [snapshot.snapshot.id, SOURCE, snapshot.schemaVersion, snapshot.snapshot.sequence, snapshot.snapshot.generatedAt, snapshot.snapshot.complete, hash ?? "", snapshot.products.length, reason],
        );
      }
    },

    /**
     * Apply a validated snapshot atomically. Complete snapshots unpublish
     * anything they don't list; partial snapshots only touch listed records.
     */
    async applySnapshot(s: SyncSnapshot): Promise<ApplyResult> {
      const hash = contentHash(s);
      const allHashes = s.products.filter((p) => p.published).flatMap((p) => p.images.map((i) => i.hash));
      return db.transaction(async (tx) => {
        const state = await lockState(tx);
        const prior = await tx.query<{ content_hash: string; status: string }>(
          "SELECT content_hash, status FROM catalog_snapshots WHERE snapshot_id = $1",
          [s.snapshot.id],
        );
        const previous = prior.rows[0];
        if (previous && previous.status !== "rejected") {
          if (previous.content_hash !== hash) throw new SyncRejected("snapshot_conflict", "Snapshot id was already used for different content.", 409);
          const count = await tx.query<{ n: string }>("SELECT count(*) AS n FROM catalog_products WHERE published");
          return { status: "duplicate", snapshotId: s.snapshot.id, publishedProducts: Number(count.rows[0]!.n), unpublishedProducts: 0, missingMedia: await missingMedia(tx, allHashes) };
        }
        if (state.last_sequence !== null && s.snapshot.sequence <= Number(state.last_sequence)) {
          throw new SyncRejected("stale_snapshot", "A newer snapshot has already been applied.", 409);
        }

        const recordSnapshot = async (status: "applied" | "unchanged", productCount: number) => {
          await tx.query(
            `INSERT INTO catalog_snapshots (snapshot_id, source, schema_version, sequence, generated_at, complete, content_hash, product_count, status)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
             ON CONFLICT (snapshot_id) DO UPDATE SET status = $9, error = NULL, received_at = now(), product_count = $8`,
            [s.snapshot.id, SOURCE, s.schemaVersion, s.snapshot.sequence, s.snapshot.generatedAt, s.snapshot.complete, hash, productCount, status],
          );
          await tx.query(
            `UPDATE catalog_sync_state SET last_success_at = now(), last_attempt_at = now(), last_snapshot_id = $2, last_sequence = $3,
               last_content_hash = CASE WHEN $4 THEN $5 ELSE last_content_hash END,
               last_complete_at = CASE WHEN $4 THEN now() ELSE last_complete_at END,
               published_products = $6, last_error = NULL, last_error_at = NULL
             WHERE source = $1`,
            [SOURCE, s.snapshot.id, s.snapshot.sequence, s.snapshot.complete, hash, productCount],
          );
        };

        // Fast path: same complete catalog as last time. Still refreshes freshness.
        if (s.snapshot.complete && state.last_complete_at && state.last_content_hash === hash) {
          const count = await tx.query<{ n: string }>("SELECT count(*) AS n FROM catalog_products WHERE published");
          const n = Number(count.rows[0]!.n);
          await recordSnapshot("unchanged", n);
          return { status: "unchanged", snapshotId: s.snapshot.id, publishedProducts: n, unpublishedProducts: 0, missingMedia: await missingMedia(tx, allHashes) };
        }

        const sid = s.snapshot.id;
        const publishedIds = s.products.filter((p) => p.published).map((p) => p.id);
        let unpublished = 0;
        if (s.snapshot.complete) {
          // Free slugs/SKUs first: anything not in a complete snapshot is no longer offered.
          const r = await tx.query(
            "UPDATE catalog_products SET published = false, unpublished_at = now(), updated_at = now() WHERE published AND NOT (id = ANY($1::text[])) RETURNING id",
            [publishedIds],
          );
          unpublished += r.rows.length;
          await tx.query("UPDATE catalog_categories SET published = false, updated_at = now() WHERE published AND NOT (id = ANY($1::text[]))", [s.categories.map((c) => c.id)]);
          await tx.query("UPDATE catalog_brands SET published = false, updated_at = now() WHERE published AND NOT (id = ANY($1::text[]))", [s.brands.map((b) => b.id)]);
        }

        if (s.categories.length) {
          await tx.query(
            `INSERT INTO catalog_categories (id, slug, name_en, name_ar, description_en, description_ar, icon, sort_order, published, first_seen_snapshot, last_seen_snapshot)
             SELECT x.id, x.slug, x.name_en, x.name_ar, x.description_en, x.description_ar, x.icon, x.sort_order, true, $2, $2
             FROM jsonb_to_recordset($1::jsonb) AS x(id text, slug text, name_en text, name_ar text, description_en text, description_ar text, icon text, sort_order int)
             ON CONFLICT (id) DO UPDATE SET slug = EXCLUDED.slug, name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar,
               description_en = EXCLUDED.description_en, description_ar = EXCLUDED.description_ar, icon = EXCLUDED.icon,
               sort_order = EXCLUDED.sort_order, published = true, last_seen_snapshot = $2, updated_at = now()`,
            [
              JSON.stringify(
                s.categories.map((c) => ({
                  id: c.id, slug: c.slug, name_en: c.name.en, name_ar: c.name.ar,
                  description_en: c.description.en, description_ar: c.description.ar, icon: c.icon || "box", sort_order: c.sortOrder,
                })),
              ),
              sid,
            ],
          );
        }
        if (s.brands.length) {
          await tx.query(
            `INSERT INTO catalog_brands (id, slug, name, published, first_seen_snapshot, last_seen_snapshot)
             SELECT x.id, x.slug, x.name, true, $2, $2 FROM jsonb_to_recordset($1::jsonb) AS x(id text, slug text, name text)
             ON CONFLICT (id) DO UPDATE SET slug = EXCLUDED.slug, name = EXCLUDED.name, published = true, last_seen_snapshot = $2, updated_at = now()`,
            [JSON.stringify(s.brands), sid],
          );
        }

        if (!s.snapshot.complete) {
          // Partial snapshots may reference existing rows; they must exist and be published.
          const cats = [...new Set(s.products.filter((p) => p.published).map((p) => p.categoryId))];
          const brandIds = [...new Set(s.products.filter((p) => p.published && p.brandId).map((p) => p.brandId!))];
          const okCats = await tx.query<{ id: string }>("SELECT id FROM catalog_categories WHERE published AND id = ANY($1::text[])", [cats]);
          const okBrands = await tx.query<{ id: string }>("SELECT id FROM catalog_brands WHERE published AND id = ANY($1::text[])", [brandIds]);
          const badCat = cats.find((id) => !okCats.rows.some((r) => r.id === id));
          const badBrand = brandIds.find((id) => !okBrands.rows.some((r) => r.id === id));
          if (badCat) throw new SyncRejected("invalid_reference", `Unknown or unpublished category "${badCat}".`, 422);
          if (badBrand) throw new SyncRejected("invalid_reference", `Unknown or unpublished brand "${badBrand}".`, 422);
        }

        if (s.products.length) {
          const before = await tx.query<{ id: string }>("SELECT id FROM catalog_products WHERE published AND id = ANY($1::text[])", [s.products.filter((p) => !p.published).map((p) => p.id)]);
          unpublished += before.rows.length;
          await tx.query(
            `INSERT INTO catalog_products (id, sku, slug, name_en, name_ar, description_en, description_ar, category_id, brand_id, currency, price,
               compare_at, sale_ends_at, availability, orderable_quantity, max_per_order, images, published, source_created_at, source_updated_at,
               first_seen_snapshot, last_seen_snapshot, unpublished_at)
             SELECT x.id, x.sku, x.slug, x.name_en, x.name_ar, x.description_en, x.description_ar, x.category_id, x.brand_id, 'EGP', x.price,
               x.compare_at, x.sale_ends_at, x.availability, x.orderable_quantity, x.max_per_order, x.images, x.published, x.created_at, x.updated_at,
               $2, $2, CASE WHEN x.published THEN NULL ELSE now() END
             FROM jsonb_to_recordset($1::jsonb) AS x(id text, sku text, slug text, name_en text, name_ar text, description_en text, description_ar text,
               category_id text, brand_id text, price bigint, compare_at bigint, sale_ends_at timestamptz, availability text,
               orderable_quantity int, max_per_order int, images jsonb, published boolean, created_at timestamptz, updated_at timestamptz)
             ON CONFLICT (id) DO UPDATE SET sku = EXCLUDED.sku, slug = EXCLUDED.slug, name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar,
               description_en = EXCLUDED.description_en, description_ar = EXCLUDED.description_ar, category_id = EXCLUDED.category_id,
               brand_id = EXCLUDED.brand_id, price = EXCLUDED.price, compare_at = EXCLUDED.compare_at, sale_ends_at = EXCLUDED.sale_ends_at,
               availability = EXCLUDED.availability, orderable_quantity = EXCLUDED.orderable_quantity, max_per_order = EXCLUDED.max_per_order,
               images = EXCLUDED.images, published = EXCLUDED.published, source_created_at = EXCLUDED.source_created_at,
               source_updated_at = EXCLUDED.source_updated_at, last_seen_snapshot = $2,
               unpublished_at = CASE WHEN EXCLUDED.published THEN NULL ELSE COALESCE(catalog_products.unpublished_at, now()) END,
               updated_at = now()`,
            [
              JSON.stringify(
                s.products.map((p) => ({
                  id: p.id, sku: p.sku, slug: p.slug, name_en: p.name.en, name_ar: p.name.ar,
                  description_en: p.description.en, description_ar: p.description.ar, category_id: p.categoryId, brand_id: p.brandId,
                  price: p.price, compare_at: p.compareAt, sale_ends_at: p.saleEndsAt, availability: p.availability,
                  orderable_quantity: p.orderableQuantity, max_per_order: p.maxPerOrder, images: p.images, published: p.published,
                  created_at: p.createdAt, updated_at: p.updatedAt,
                })),
              ),
              sid,
            ],
          );
        }

        const count = await tx.query<{ n: string }>("SELECT count(*) AS n FROM catalog_products WHERE published");
        const n = Number(count.rows[0]!.n);
        await recordSnapshot("applied", n);
        return { status: "applied", snapshotId: sid, publishedProducts: n, unpublishedProducts: unpublished, missingMedia: await missingMedia(tx, allHashes) };
      });
    },

    missingMedia: (hashes: string[]) => missingMedia(db, hashes),

    async putMedia(hash: string, contentType: string, bytes: Uint8Array): Promise<"stored" | "exists"> {
      const r = await db.query(
        "INSERT INTO catalog_media (hash, content_type, bytes, size) VALUES ($1, $2, $3, $4) ON CONFLICT (hash) DO NOTHING RETURNING hash",
        [hash, contentType, Buffer.from(bytes), bytes.byteLength],
      );
      return r.rows.length ? "stored" : "exists";
    },

    async getMedia(hash: string): Promise<{ contentType: string; bytes: Uint8Array } | null> {
      const r = await db.query<{ content_type: string; bytes: Buffer }>("SELECT content_type, bytes FROM catalog_media WHERE hash = $1", [hash]);
      const row = r.rows[0];
      return row ? { contentType: row.content_type, bytes: new Uint8Array(row.bytes) } : null;
    },

    async syncState(): Promise<SyncState> {
      const r = await db.query<Record<string, unknown>>("SELECT * FROM catalog_sync_state WHERE source = $1", [SOURCE]);
      const row = r.rows[0];
      return {
        lastSuccessAt: iso(row?.last_success_at as Date | null),
        lastSnapshotId: (row?.last_snapshot_id as string | null) ?? null,
        lastSequence: row?.last_sequence != null ? Number(row.last_sequence) : null,
        lastCompleteAt: iso(row?.last_complete_at as Date | null),
        publishedProducts: Number(row?.published_products ?? 0),
        lastAttemptAt: iso(row?.last_attempt_at as Date | null),
        lastErrorAt: iso(row?.last_error_at as Date | null),
        lastError: (row?.last_error as string | null) ?? null,
      };
    },

    // ---- reads for the storefront (published rows only) ----

    async listProducts(): Promise<ProductRow[]> {
      return (await db.query<ProductRow>(`SELECT ${PRODUCT_COLUMNS} FROM catalog_products p WHERE p.published ORDER BY p.id`)).rows;
    },

    async getProductsByIds(ids: string[]): Promise<ProductRow[]> {
      if (!ids.length) return [];
      return (await db.query<ProductRow>(`SELECT ${PRODUCT_COLUMNS} FROM catalog_products p WHERE p.published AND p.id = ANY($1::text[])`, [ids])).rows;
    },

    /** Exact slug, or the trailing StorePro id of a renamed product ("old-name-12" → sp-12). */
    async getProductBySlug(slug: string): Promise<ProductRow | null> {
      const exact = await db.query<ProductRow>(`SELECT ${PRODUCT_COLUMNS} FROM catalog_products p WHERE p.published AND p.slug = $1`, [slug]);
      if (exact.rows[0]) return exact.rows[0];
      const id = /-(\d{1,12})$/.exec(slug)?.[1];
      if (!id) return null;
      const byId = await db.query<ProductRow>(`SELECT ${PRODUCT_COLUMNS} FROM catalog_products p WHERE p.published AND p.id = $1`, [`sp-${id}`]);
      return byId.rows[0] ?? null;
    },

    async listCategories(): Promise<CategoryRow[]> {
      return (await db.query<CategoryRow>("SELECT id, slug, name_en, name_ar, description_en, description_ar, icon, sort_order FROM catalog_categories WHERE published ORDER BY sort_order, name_en")).rows;
    },

    async getCategory(slug: string): Promise<CategoryRow | null> {
      const cols = "id, slug, name_en, name_ar, description_en, description_ar, icon, sort_order";
      const exact = await db.query<CategoryRow>(`SELECT ${cols} FROM catalog_categories WHERE published AND slug = $1`, [slug]);
      if (exact.rows[0]) return exact.rows[0];
      const id = /-(\d{1,12})$/.exec(slug)?.[1];
      if (!id) return null;
      return (await db.query<CategoryRow>(`SELECT ${cols} FROM catalog_categories WHERE published AND id = $1`, [`spc-${id}`])).rows[0] ?? null;
    },

    async listBrands(): Promise<BrandRow[]> {
      return (await db.query<BrandRow>("SELECT id, slug, name FROM catalog_brands WHERE published ORDER BY name")).rows;
    },
  };
}

export type CatalogStore = ReturnType<typeof createCatalogStore>;
