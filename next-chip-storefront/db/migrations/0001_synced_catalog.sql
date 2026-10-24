-- Next Chip synchronized catalog (StorePro -> website push).
-- Rows are never deleted by synchronization: products, categories and brands
-- that leave the catalog are unpublished so links, carts and future web orders
-- keep resolving to the right StorePro record.

CREATE TABLE catalog_categories (
  id            text PRIMARY KEY,                 -- e.g. "spc-3" (StorePro categories.id)
  slug          text NOT NULL,
  name_en       text NOT NULL,
  name_ar       text NOT NULL,
  description_en text NOT NULL DEFAULT '',
  description_ar text NOT NULL DEFAULT '',
  icon          text NOT NULL DEFAULT 'box',
  sort_order    integer NOT NULL DEFAULT 0,
  published     boolean NOT NULL DEFAULT true,
  first_seen_snapshot text NOT NULL,
  last_seen_snapshot  text NOT NULL,
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX catalog_categories_slug_published ON catalog_categories (slug) WHERE published;

CREATE TABLE catalog_brands (
  id            text PRIMARY KEY,                 -- e.g. "spb-logitech"
  slug          text NOT NULL,
  name          text NOT NULL,
  published     boolean NOT NULL DEFAULT true,
  first_seen_snapshot text NOT NULL,
  last_seen_snapshot  text NOT NULL,
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX catalog_brands_slug_published ON catalog_brands (slug) WHERE published;

CREATE TABLE catalog_products (
  id            text PRIMARY KEY,                 -- stable external id, e.g. "sp-12" (StorePro products.id)
  sku           text NOT NULL,                    -- StorePro products.sku
  slug          text NOT NULL,
  name_en       text NOT NULL,
  name_ar       text NOT NULL,
  description_en text NOT NULL DEFAULT '',
  description_ar text NOT NULL DEFAULT '',
  category_id   text NOT NULL REFERENCES catalog_categories (id),
  brand_id      text REFERENCES catalog_brands (id),
  currency      text NOT NULL DEFAULT 'EGP' CHECK (currency = 'EGP'),
  price         bigint NOT NULL CHECK (price > 0),          -- piastres
  compare_at    bigint CHECK (compare_at IS NULL OR compare_at > 0),
  sale_ends_at  timestamptz,
  availability  text NOT NULL CHECK (availability IN ('in_stock', 'low_stock', 'out_of_stock')),
  orderable_quantity integer NOT NULL CHECK (orderable_quantity >= 0),  -- capped by max_per_order; exact stock stays in StorePro
  max_per_order integer NOT NULL CHECK (max_per_order BETWEEN 1 AND 99),
  images        jsonb NOT NULL DEFAULT '[]'::jsonb,         -- [{hash, contentType, width, height}]
  published     boolean NOT NULL DEFAULT true,
  source_created_at timestamptz NOT NULL,
  source_updated_at timestamptz NOT NULL,
  first_seen_snapshot text NOT NULL,
  last_seen_snapshot  text NOT NULL,
  unpublished_at timestamptz,
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX catalog_products_slug_published ON catalog_products (slug) WHERE published;
CREATE UNIQUE INDEX catalog_products_sku_published ON catalog_products (sku) WHERE published;
CREATE INDEX catalog_products_category ON catalog_products (category_id) WHERE published;

-- Product images pushed by StorePro, addressed by the SHA-256 of their bytes.
CREATE TABLE catalog_media (
  hash          text PRIMARY KEY CHECK (hash ~ '^[0-9a-f]{64}$'),
  content_type  text NOT NULL CHECK (content_type IN ('image/jpeg', 'image/png', 'image/webp')),
  bytes         bytea NOT NULL,
  size          integer NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- One row per accepted or rejected snapshot (no payloads stored).
CREATE TABLE catalog_snapshots (
  snapshot_id   text PRIMARY KEY,
  source        text NOT NULL,
  schema_version integer NOT NULL,
  sequence      bigint NOT NULL,
  generated_at  timestamptz NOT NULL,
  received_at   timestamptz NOT NULL DEFAULT now(),
  complete      boolean NOT NULL,
  content_hash  text NOT NULL,
  product_count integer NOT NULL,
  status        text NOT NULL CHECK (status IN ('applied', 'unchanged', 'rejected')),
  error         text
);
CREATE INDEX catalog_snapshots_received ON catalog_snapshots (received_at DESC);

-- Current synchronization state per source (one row: 'storepro').
CREATE TABLE catalog_sync_state (
  source        text PRIMARY KEY,
  last_success_at timestamptz,
  last_snapshot_id text,
  last_sequence bigint,
  last_content_hash text,
  last_complete_at timestamptz,
  published_products integer NOT NULL DEFAULT 0,
  last_attempt_at timestamptz,
  last_error_at timestamptz,
  last_error    text
);

-- Request nonces seen recently (replay protection for signed requests).
CREATE TABLE catalog_sync_nonces (
  nonce         text PRIMARY KEY,
  seen_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX catalog_sync_nonces_seen ON catalog_sync_nonces (seen_at);
