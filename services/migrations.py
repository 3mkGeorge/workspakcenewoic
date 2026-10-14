"""Idempotent, transactional upgrade for the POS extension. Never rewrites sales."""

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

# Additive schema generation. Bump when a new ALTER TABLE branch is added and
# include the new column in the early-return guard below, otherwise databases
# that are current per the old guard will skip the new migration forever.
# Stored in SQLite PRAGMA user_version (no schema footprint, backup-safe).
#   1 = pre-landmark baseline (POS/shipping/pickup migrations)
#   2 = shipping_orders.landmark
#   3 = shipping_orders.tracking_code nullable (no code generated at creation)
#   4 = shipping_orders.tracking_url (courier-supplied link, optional)
#   6 = web_listings (opt-in Next Chip website publication; additive table)
SCHEMA_VERSION = 6

PAYMENTS_DDL = """CREATE TABLE IF NOT EXISTS sale_payments (
 id INTEGER PRIMARY KEY,
 sale_id INTEGER NOT NULL REFERENCES sales(id),
 method VARCHAR(30) NOT NULL,
 amount INTEGER NOT NULL CHECK (amount >= 0),
 CONSTRAINT uq_sale_payment_method UNIQUE(sale_id, method),
 CHECK (method IN ('Cash','Visa','Mastercard','Bank Transfer','Wallet','Card','Mobile Wallet'))
);
"""

PRICE_TRIGGERS = {
    "price_history_no_update": "CREATE TRIGGER IF NOT EXISTS price_history_no_update BEFORE UPDATE ON price_history BEGIN SELECT RAISE(ABORT, 'Price history is append-only'); END",
    "price_history_no_delete": "CREATE TRIGGER IF NOT EXISTS price_history_no_delete BEFORE DELETE ON price_history BEGIN SELECT RAISE(ABORT, 'Price history is append-only'); END",
}

PRODUCT_IMAGES_DDL = """
CREATE TABLE IF NOT EXISTS product_images (
  id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  file_path VARCHAR(255) NOT NULL,
  file_name VARCHAR(120) NOT NULL,
  is_primary BOOLEAN NOT NULL DEFAULT 0,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL
);
"""

PRODUCT_IMAGES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_product_images_product_id ON product_images(product_id)",
    "CREATE INDEX IF NOT EXISTS ix_product_images_product_order ON product_images(product_id, sort_order)",
]

SHIPPING_DDL = """
CREATE TABLE IF NOT EXISTS shipping_orders (
  id INTEGER PRIMARY KEY,
  order_number VARCHAR(30) NOT NULL UNIQUE,
  sale_id INTEGER NOT NULL UNIQUE REFERENCES sales(id),
  tracking_code VARCHAR(40) UNIQUE,
  tracking_url VARCHAR(300) NOT NULL DEFAULT '',
  status VARCHAR(20) NOT NULL DEFAULT 'Pending',
  customer_id INTEGER REFERENCES customers(id),
  customer_name VARCHAR(120) NOT NULL DEFAULT '',
  phone VARCHAR(40) NOT NULL DEFAULT '',
  alt_phone VARCHAR(40) NOT NULL DEFAULT '',
  governorate VARCHAR(80) NOT NULL DEFAULT '',
  city VARCHAR(80) NOT NULL DEFAULT '',
  district VARCHAR(80) NOT NULL DEFAULT '',
  landmark VARCHAR(80) NOT NULL DEFAULT '',
  street VARCHAR(160) NOT NULL DEFAULT '',
  building VARCHAR(40) NOT NULL DEFAULT '',
  floor VARCHAR(20) NOT NULL DEFAULT '',
  apartment VARCHAR(20) NOT NULL DEFAULT '',
  postal_code VARCHAR(20) NOT NULL DEFAULT '',
  address_snapshot TEXT NOT NULL DEFAULT '{}',
  notes VARCHAR(500) NOT NULL DEFAULT '',
  courier VARCHAR(80) NOT NULL DEFAULT '',
  cancel_reason VARCHAR(200) NOT NULL DEFAULT '',
  cancelled_at DATETIME,
  shipping_cost INTEGER NOT NULL DEFAULT 0,
  shipment_date VARCHAR(10) NOT NULL DEFAULT '',
  delivered_by VARCHAR(120) NOT NULL DEFAULT '',
  delivered_at DATETIME,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  CHECK (shipping_cost >= 0)
);
"""

SHIPPING_TRACKING_REBUILD = """
CREATE TABLE shipping_orders_new (
  id INTEGER PRIMARY KEY,
  order_number VARCHAR(30) NOT NULL UNIQUE,
  sale_id INTEGER NOT NULL UNIQUE REFERENCES sales(id),
  tracking_code VARCHAR(40) UNIQUE,
  tracking_url VARCHAR(300) NOT NULL DEFAULT '',
  status VARCHAR(20) NOT NULL DEFAULT 'Pending',
  customer_id INTEGER REFERENCES customers(id),
  customer_name VARCHAR(120) NOT NULL DEFAULT '',
  phone VARCHAR(40) NOT NULL DEFAULT '',
  alt_phone VARCHAR(40) NOT NULL DEFAULT '',
  governorate VARCHAR(80) NOT NULL DEFAULT '',
  city VARCHAR(80) NOT NULL DEFAULT '',
  district VARCHAR(80) NOT NULL DEFAULT '',
  landmark VARCHAR(80) NOT NULL DEFAULT '',
  street VARCHAR(160) NOT NULL DEFAULT '',
  building VARCHAR(40) NOT NULL DEFAULT '',
  floor VARCHAR(20) NOT NULL DEFAULT '',
  apartment VARCHAR(20) NOT NULL DEFAULT '',
  postal_code VARCHAR(20) NOT NULL DEFAULT '',
  address_snapshot TEXT NOT NULL DEFAULT '{}',
  notes VARCHAR(500) NOT NULL DEFAULT '',
  courier VARCHAR(80) NOT NULL DEFAULT '',
  cancel_reason VARCHAR(200) NOT NULL DEFAULT '',
  cancelled_at DATETIME,
  shipping_cost INTEGER NOT NULL DEFAULT 0,
  shipment_date VARCHAR(10) NOT NULL DEFAULT '',
  delivered_by VARCHAR(120) NOT NULL DEFAULT '',
  delivered_at DATETIME,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  CHECK (shipping_cost >= 0)
);
"""

SHIPPING_EVENT_DDL = """
CREATE TABLE IF NOT EXISTS shipping_events (
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES shipping_orders(id),
  action VARCHAR(120) NOT NULL,
  actor VARCHAR(100) NOT NULL,
  created_at DATETIME NOT NULL
);
"""

SHIPPING_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_shipping_orders_sale_id ON shipping_orders(sale_id)",
    "CREATE INDEX IF NOT EXISTS ix_shipping_orders_status ON shipping_orders(status)",
    "CREATE INDEX IF NOT EXISTS ix_shipping_orders_created ON shipping_orders(created_at)",
    "CREATE INDEX IF NOT EXISTS ix_shipping_events_order_id ON shipping_events(order_id)",
]

SALES_PICKUP_COLUMNS = (
    "ALTER TABLE sales ADD COLUMN pickup_date VARCHAR(10) NOT NULL DEFAULT ''",
    "ALTER TABLE sales ADD COLUMN pickup_notes VARCHAR(300) NOT NULL DEFAULT ''",
)

LIFECYCLE_COLUMNS = (
    "ALTER TABLE sales ADD COLUMN pickup_status VARCHAR(20) NOT NULL DEFAULT ''",
    "ALTER TABLE sales ADD COLUMN cancel_reason VARCHAR(200) NOT NULL DEFAULT ''",
    "ALTER TABLE sales ADD COLUMN cancelled_at DATETIME",
    "ALTER TABLE shipping_orders ADD COLUMN cancel_reason VARCHAR(200) NOT NULL DEFAULT ''",
    "ALTER TABLE shipping_orders ADD COLUMN cancelled_at DATETIME",
)


def validate_database_objects(connection):
    def normalized(sql):
        return " ".join(sql.replace("IF NOT EXISTS ", "").strip().rstrip(";").split())

    for kind, name, sql in connection.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE type IN ('trigger','view')"
    ):
        if (
            kind != "trigger"
            or name not in PRICE_TRIGGERS
            or normalized(sql) != normalized(PRICE_TRIGGERS[name])
        ):
            raise ValueError("Unexpected database objects in backup.")


def install_price_triggers(connection):
    for sql in PRICE_TRIGGERS.values():
        connection.exec_driver_sql(sql)


def upgrade_sqlite(path, backup=False):
    path = Path(path)
    if not path.exists():
        return
    with closing(sqlite3.connect(path, timeout=15)) as connection:
        tables = {
            r[0]
            for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "sale_items" not in tables or "sales" not in tables:
            return
        columns = {r[1] for r in connection.execute("PRAGMA table_info(sale_items)")}
        sales_columns = (
            {r[1] for r in connection.execute("PRAGMA table_info(sales)")}
            if "sales" in tables
            else set()
        )
        shipping_columns = (
            {r[1] for r in connection.execute("PRAGMA table_info(shipping_orders)")}
            if "shipping_orders" in tables
            else set()
        )
        # Tracking codes are assigned at shipment, so the column must accept
        # NULL (SQLite enforces UNIQUE but allows repeated NULLs). notnull=1
        # means the pre-v3 schema is still live and needs a table rebuild.
        tracking_nullable = True
        if "shipping_orders" in tables:
            tracking_nullable = not any(
                r[1] == "tracking_code" and r[3]
                for r in connection.execute("PRAGMA table_info(shipping_orders)")
            )
        product_columns = {
            r[1] for r in connection.execute("PRAGMA table_info(products)")
        }
        category_columns = (
            {r[1] for r in connection.execute("PRAGMA table_info(categories)")}
            if "categories" in tables
            else set()
        )
        triggers = {
            r[0]
            for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
        if (
            "backup_logs" in tables
            and {
                "permissions",
                "role_permissions",
                "user_permission_grants",
                "user_permission_denials",
                "endpoint_permissions",
            }.issubset(tables)
            and "discount" in columns
            and "sale_payments" in tables
            and "price_history" in tables
            and set(PRICE_TRIGGERS).issubset(triggers)
            and ("price_alerts" in product_columns or "products" not in tables)
            and "product_images" in tables
            and {"description", "color", "icon", "created_at", "updated_at"}.issubset(
                category_columns
            )
            and "shipping_orders" in tables
            and "shipping_events" in tables
            and {"pickup_date", "pickup_notes"}.issubset(sales_columns)
            and "landmark" in shipping_columns
            and "tracking_url" in shipping_columns
            and tracking_nullable
            and {"pickup_status", "cancel_reason", "cancelled_at"}.issubset(
                sales_columns
            )
            and {"cancel_reason", "cancelled_at"}.issubset(shipping_columns)
            and ("web_listings" in tables or "products" not in tables)
            and connection.execute("PRAGMA user_version").fetchone()[0]
            >= SCHEMA_VERSION
        ):
            return
        if backup:
            destination = path.with_name(
                f"pre-{'prices' if 'sale_payments' in tables else 'pos'}-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3"
            )
            with closing(sqlite3.connect(destination)) as snapshot:
                connection.backup(snapshot)
        try:
            connection.execute("BEGIN IMMEDIATE")
            from services.permissions import install_schema

            install_schema(connection)
            if "backup_logs" not in tables:
                from sqlalchemy.schema import CreateTable, CreateIndex
                from sqlalchemy.dialects.sqlite import dialect
                from models import BackupLog

                connection.execute(
                    str(CreateTable(BackupLog.__table__).compile(dialect=dialect()))
                )
                for index in BackupLog.__table__.indexes:
                    connection.execute(
                        str(CreateIndex(index).compile(dialect=dialect()))
                    )
            if "discount" not in columns:
                connection.execute(
                    "ALTER TABLE sale_items ADD COLUMN discount INTEGER NOT NULL DEFAULT 0 CHECK(discount >= 0 AND discount <= quantity * price)"
                )
            connection.execute(PAYMENTS_DDL)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_sale_payments_sale_id ON sale_payments(sale_id)"
            )
            if "products" in tables and "price_alerts" not in product_columns:
                connection.execute(
                    "ALTER TABLE products ADD COLUMN price_alerts BOOLEAN NOT NULL DEFAULT 1"
                )
            if "products" in tables and "web_listings" not in tables:
                # Additive: older databases and backups gain the empty table;
                # no existing row is touched.
                from sqlalchemy.schema import CreateTable, CreateIndex
                from sqlalchemy.dialects.sqlite import dialect
                from models import WebListing

                connection.execute(
                    str(CreateTable(WebListing.__table__).compile(dialect=dialect()))
                )
                for index in WebListing.__table__.indexes:
                    connection.execute(
                        str(CreateIndex(index).compile(dialect=dialect()))
                    )
            if "price_history" not in tables:
                from sqlalchemy.schema import CreateTable, CreateIndex
                from sqlalchemy.dialects.sqlite import dialect
                from models import PriceHistory

                connection.execute(
                    str(CreateTable(PriceHistory.__table__).compile(dialect=dialect()))
                )
                for index in PriceHistory.__table__.indexes:
                    connection.execute(
                        str(CreateIndex(index).compile(dialect=dialect()))
                    )
            for sql in PRICE_TRIGGERS.values():
                connection.execute(sql)
            connection.execute(PRODUCT_IMAGES_DDL)
            for sql in PRODUCT_IMAGES_INDEXES:
                connection.execute(sql)
            connection.execute(SHIPPING_DDL)
            connection.execute(SHIPPING_EVENT_DDL)
            for sql in SHIPPING_INDEXES:
                connection.execute(sql)
            if "shipping_orders" in tables:
                try:
                    connection.execute(
                        "ALTER TABLE shipping_orders ADD COLUMN landmark VARCHAR(80) NOT NULL DEFAULT ''"
                    )
                except Exception as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            if "shipping_orders" in tables and not tracking_nullable:
                # One-way rebuild for nullable tracking_code (data-preserving;
                # indexes recreated explicitly: SQLite drops them with the table).
                # Pre-v3 tables lack columns that later steps add (tracking_url,
                # cancel_reason, cancelled_at): copy the columns that exist and
                # let the new table's defaults fill the rest, as those steps would.
                existing = {
                    r[1]
                    for r in connection.execute("PRAGMA table_info(shipping_orders)")
                }
                cols = ", ".join(
                    c
                    for c in (
                        "id", "order_number", "sale_id", "tracking_code", "tracking_url",
                        "status", "customer_id", "customer_name", "phone", "alt_phone",
                        "governorate", "city", "district", "landmark", "street",
                        "building", "floor", "apartment", "postal_code",
                        "address_snapshot", "notes", "courier", "cancel_reason",
                        "cancelled_at", "shipping_cost", "shipment_date",
                        "delivered_by", "delivered_at", "user_id", "created_at",
                        "updated_at",
                    )
                    if c in existing
                )
                connection.execute(SHIPPING_TRACKING_REBUILD)
                connection.execute(
                    f"INSERT INTO shipping_orders_new ({cols}) SELECT {cols}"
                    " FROM shipping_orders"
                )
                connection.execute("DROP TABLE shipping_orders")
                connection.execute(
                    "ALTER TABLE shipping_orders_new RENAME TO shipping_orders"
                )
                for sql in SHIPPING_INDEXES:
                    connection.execute(sql)
            if "shipping_orders" in tables:
                try:
                    connection.execute(
                        "ALTER TABLE shipping_orders ADD COLUMN tracking_url VARCHAR(300) NOT NULL DEFAULT ''"
                    )
                except Exception as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            if "sales" in tables:
                for ddl in SALES_PICKUP_COLUMNS:
                    try:
                        connection.execute(ddl)
                    except Exception as exc:
                        if "duplicate column name" not in str(exc).lower():
                            raise
            for ddl in LIFECYCLE_COLUMNS:
                try:
                    connection.execute(ddl)
                except Exception as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            if "sales" in tables:
                # Existing pickup sales start life as Pending Pickup.
                connection.execute(
                    "UPDATE sales SET pickup_status = 'Pending Pickup' "
                    "WHERE pickup_status = '' "
                    "AND (pickup_date != '' OR pickup_notes != '')"
                )
            if "categories" in tables:
                for ddl in (
                    "ALTER TABLE categories ADD COLUMN description VARCHAR(500) NOT NULL DEFAULT ''",
                    "ALTER TABLE categories ADD COLUMN color VARCHAR(7) NOT NULL DEFAULT ''",
                    "ALTER TABLE categories ADD COLUMN icon VARCHAR(40) NOT NULL DEFAULT ''",
                    "ALTER TABLE categories ADD COLUMN created_at DATETIME",
                    "ALTER TABLE categories ADD COLUMN updated_at DATETIME",
                ):
                    try:
                        connection.execute(ddl)
                    except Exception as exc:
                        if "duplicate column name" not in str(exc).lower():
                            raise
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS ix_products_category_id ON products(category_id)"
                )
            for idx_sql in (
                "CREATE INDEX IF NOT EXISTS ix_products_supplier_id ON products(supplier_id)",
                "CREATE INDEX IF NOT EXISTS ix_sales_status_created ON sales(status, created_at)",
                "CREATE INDEX IF NOT EXISTS ix_sale_items_sale_id ON sale_items(sale_id)",
                "CREATE INDEX IF NOT EXISTS ix_sale_items_product_id ON sale_items(product_id)",
                "CREATE INDEX IF NOT EXISTS ix_purchase_items_purchase_id ON purchase_items(purchase_id)",
                "CREATE INDEX IF NOT EXISTS ix_purchase_items_product_id ON purchase_items(product_id)",
                "CREATE INDEX IF NOT EXISTS ix_inventory_movements_product_id ON inventory_movements(product_id)",
            ):
                try:
                    connection.execute(idx_sql)
                except Exception:
                    pass
            connection.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
