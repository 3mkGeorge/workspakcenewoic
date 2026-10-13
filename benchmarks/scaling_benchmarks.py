"""High-volume scaling benchmarks for StorePro (10k, 50k, 100k products).

Evaluates database latency, memory footprint, pagination, search, and aggregation
across large catalog volumes.
"""

import time
import os
import sys
import sqlite3
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from models import db, Product, Sale, SaleItem
from sqlalchemy.orm import joinedload


def run_benchmark_for_size(size: int):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_file = tf.name

    try:
        app = create_app({"SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_file}", "BACKUP_WORKER": False})
        with app.app_context():
            db.create_all()
            db.session.remove()
            db.engine.dispose()

        con = sqlite3.connect(db_file)
        cur = con.cursor()
        cur.executemany(
            "INSERT INTO categories(id, name, description, color, icon) VALUES(?,?,?,?,?)",
            [(i, f"Category {i}", "", "#0865ff", "box") for i in range(1, 21)],
        )
        cur.executemany(
            "INSERT INTO suppliers(id, name, active) VALUES(?,?,1)",
            [(i, f"Supplier {i}") for i in range(1, 21)],
        )

        # Batch generate products
        batch = [
            (
                i,
                f"Product {i:06d}",
                f"SKU-{i:06d}",
                f"BAR-{i:08d}",
                "",
                (i % 20) + 1,
                (i % 20) + 1,
                5000,
                7500,
                (i % 100) + 1,
                10,
                "Aisle 1",
                "",
                1,
                "2026-01-01",
                "2026-01-01",
                1,
            )
            for i in range(1, size + 1)
        ]
        t_gen_start = time.perf_counter()
        cur.executemany(
            "INSERT INTO products(id, name, sku, barcode, brand, category_id, supplier_id, cost, price, stock, minimum, location, image, active, created_at, updated_at, price_alerts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            batch,
        )
        con.commit()
        t_gen = time.perf_counter() - t_gen_start

        # Seed 2,000 sales and 6,000 line items
        sale_batch = [
            (
                i,
                f"INV-{i:05d}",
                None,
                "Walk-in",
                1,
                "admin",
                "2026-10-01 10:00:00",
                "Completed",
                "Cash",
                15000,
                0,
                2100,
                1400,
                17100,
                10000,
                "EGP",
                "{}",
                "",
                f"tok-{i}",
                1,
            )
            for i in range(1, 2001)
        ]
        cur.executemany(
            "INSERT INTO sales(id, invoice, customer_id, customer_name, user_id, cashier, created_at, status, payment, subtotal, discount, tax, tax_rate, total, cost, currency, store_snapshot, note, token, revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            sale_batch,
        )

        items_batch = []
        item_id = 1
        for sid in range(1, 2001):
            for p_offset in range(3):
                pid = ((sid * 3 + p_offset) % size) + 1
                items_batch.append((item_id, sid, pid, f"Product {pid:06d}", "Category", 1, 7500, 5000, 0))
                item_id += 1
        cur.executemany(
            "INSERT INTO sale_items(id, sale_id, product_id, name, category_name, quantity, price, cost, discount) VALUES(?,?,?,?,?,?,?,?,?)",
            items_batch,
        )
        con.commit()
        con.close()

        with app.app_context():
            # Benchmark 1: Exact SKU Lookup (Indexed)
            t0 = time.perf_counter()
            for s_id in [100, 500, size // 2, size - 10]:
                _ = Product.query.filter_by(sku=f"SKU-{s_id:06d}").first()
            t_sku = (time.perf_counter() - t0) / 4 * 1000

            # Benchmark 2: Substring Search (LIKE %term%)
            t0 = time.perf_counter()
            _ = Product.query.filter(Product.name.contains("999")).limit(20).all()
            t_search = (time.perf_counter() - t0) * 1000

            # Benchmark 3: Inventory Page 100 (Offset 2000, limit 20 with eager joinedload)
            t0 = time.perf_counter()
            page = (
                Product.query.options(joinedload(Product.category), joinedload(Product.supplier))
                .filter_by(active=True)
                .order_by(Product.id)
                .offset(2000)
                .limit(20)
                .all()
            )
            _ = [(p.name, p.category.name, p.supplier.name) for p in page]
            t_page = (time.perf_counter() - t0) * 1000

            # Benchmark 4: Top 5 Best Selling Products (Aggregated Join over line items)
            t0 = time.perf_counter()
            _ = (
                db.session.execute(
                    db.select(
                        SaleItem.name,
                        db.func.sum(SaleItem.quantity).label("units"),
                        db.func.sum(SaleItem.quantity * SaleItem.price).label("revenue"),
                    )
                    .join(Sale, SaleItem.sale_id == Sale.id)
                    .where(Sale.status == "Completed")
                    .group_by(SaleItem.product_id, SaleItem.name)
                    .order_by(db.desc("units"))
                    .limit(5)
                ).all()
            )
            t_top = (time.perf_counter() - t0) * 1000

            db_size_mb = os.path.getsize(db_file) / (1024 * 1024)
            db.session.remove()
            db.engine.dispose()

            return {
                "size": size,
                "db_size_mb": db_size_mb,
                "t_gen": t_gen,
                "t_sku": t_sku,
                "t_search": t_search,
                "t_page": t_page,
                "t_top": t_top,
            }
    finally:
        try:
            os.remove(db_file)
        except OSError:
            pass


def main():
    print("=" * 70)
    print("StorePro Large-Scale Dataset Benchmarking")
    print("=" * 70)
    for target in [10000, 50000, 100000]:
        res = run_benchmark_for_size(target)
        print(f"\n--- Catalog Volume: {res['size']:,} Products (Database: {res['db_size_mb']:.1f} MB) ---")
        print(f"  Population Time:            {res['t_gen']:.2f} s")
        print(f"  Exact SKU Lookup (Indexed): {res['t_sku']:.3f} ms")
        print(f"  Substring Search (Limit 20):{res['t_search']:.2f} ms")
        print(f"  Inventory Page 100 (Offset):{res['t_page']:.2f} ms")
        print(f"  Top Selling Aggregation:    {res['t_top']:.2f} ms")


if __name__ == "__main__":
    main()
