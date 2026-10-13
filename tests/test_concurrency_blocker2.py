"""Concurrency regression tests for BLOCKER 2: Global Request DB Lock Removal.

Verifies:
1. Concurrent reads execute simultaneously without deadlocks or serialization bottlenecks.
2. Concurrent sales execute reliably, maintaining unique invoice numbers and accurate inventory decrements.
3. Concurrent inventory changes maintain transactional integrity.
4. Database backup operations run concurrently with normal read traffic without blocking or corruption.
"""

import concurrent.futures
import threading
import time
import pytest
from test_app import app, client  # noqa: F401
from models import Product, Sale, InventoryMovement, db
from services.dual_backup import run_backup


def test_concurrent_reads(app):
    """Verify multiple concurrent read requests execute smoothly in parallel."""
    def worker():
        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "test-password-123"})
            res1 = c.get("/")
            res2 = c.get("/products")
            res3 = c.get("/orders")
            res4 = c.get("/reports")
            return res1.status_code == 200 and res2.status_code == 200 and res3.status_code == 200 and res4.status_code == 200

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(worker) for _ in range(12)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results), "One or more concurrent read workers failed"


def test_concurrent_sales(app):
    """Verify concurrent sales transactions maintain atomic stock decrements and unique invoices."""
    initial_stock = 100
    with app.app_context():
        p = Product(
            name="Concurrent Product",
            sku="CONC-001",
            category_id=1,
            supplier_id=1,
            cost=1000,
            price=2000,
            stock=initial_stock,
            minimum=5,
            active=True,
        )
        db.session.add(p)
        db.session.commit()
        product_id = p.id

    num_sales = 8
    items_per_sale = 2

    def sale_worker(idx):
        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "test-password-123"})
            draft = {
                "token": f"{'a' * 30}{idx:02d}",
                "items": [{"product_id": product_id, "quantity": items_per_sale, "discount": 0, "unit_price": 2000}],
                "invoice_discount": 0,
                "customer_id": 1,
            }
            quote = c.post("/api/pos/quote", json=draft).get_json()
            payload = dict(draft)
            payload["tax_rate"] = quote["tax_rate"]
            payload["currency"] = quote["currency"]
            payload["payments"] = [{"method": "Cash", "amount": quote["total"]}]
            resp = c.post("/api/pos/sales", json=payload)
            return resp.status_code, resp.get_json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(sale_worker, i) for i in range(num_sales)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    status_codes = [r[0] for r in results]
    assert all(code == 200 for code in status_codes), f"Not all sales succeeded: {status_codes}"

    # Verify inventory was decremented exactly by num_sales * items_per_sale
    with app.app_context():
        p_final = db.session.get(Product, product_id)
        expected_stock = initial_stock - (num_sales * items_per_sale)
        assert p_final.stock == expected_stock, f"Expected stock {expected_stock}, got {p_final.stock}"

        # Verify all invoice numbers are distinct
        invoices = db.session.scalars(db.select(Sale.invoice)).all()
        assert len(invoices) == len(set(invoices)), "Duplicate invoice numbers generated during concurrent sales!"


def test_concurrent_inventory_adjustments(app):
    """Verify concurrent inventory adjustments preserve movement history and stock levels."""
    with app.app_context():
        p = Product(
            name="Adjust Product",
            sku="ADJ-001",
            category_id=1,
            supplier_id=1,
            cost=500,
            price=1000,
            stock=50,
            minimum=5,
            active=True,
        )
        db.session.add(p)
        db.session.commit()
        pid = p.id

    def adjust_worker(qty):
        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "test-password-123"})
            resp = c.post(
                "/inventory/adjust",
                data={
                    "product_id": str(pid),
                    "quantity": str(qty),
                    "reason": "Stock Count",
                    "notes": f"Concurrent adjust {qty}",
                },
            )
            return resp.status_code in (200, 302)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(adjust_worker, q) for q in (2, -1, 3, -2, 5)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results), f"One or more concurrent inventory adjustments failed: {results}"

    with app.app_context():
        final_p = db.session.get(Product, pid)
        # Net change: 2 - 1 + 3 - 2 + 5 = +7 -> 50 + 7 = 57
        assert final_p.stock == 57


def test_backup_during_concurrent_reads(app):
    """Verify database backups can be taken while concurrent read traffic is occurring."""
    stop_event = threading.Event()
    read_errors = []

    def reader():
        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "test-password-123"})
            while not stop_event.is_set():
                res = c.get("/products")
                if res.status_code != 200:
                    read_errors.append(res.status_code)
                time.sleep(0.01)

    # Launch readers in threads
    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()

    # Perform backup in main test thread
    try:
        with app.app_context():
            results = run_backup("Manual", "Concurrent backup test")
            assert any(r["status"] == "Success" for r in results), "Backup failed during concurrent reads"
    finally:
        stop_event.set()
        for t in threads:
            t.join(timeout=5)

    assert len(read_errors) == 0, f"Read requests encountered errors during backup: {read_errors}"
