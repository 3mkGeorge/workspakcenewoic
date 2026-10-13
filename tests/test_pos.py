from test_app import backup_response, finish_restore

"""Transactional POS regression checks; every test uses an isolated database."""

import io
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from test_app import app, client  # noqa: F401
from models import db, Product, Sale, SaleItem, SalePayment, InventoryMovement
from services.migrations import upgrade_sqlite


def invoice(**changes):
    data = dict(
        token="f" * 48,
        items=[dict(product_id=1, quantity=2, discount=1000, unit_price=10000)],
        invoice_discount=500,
        customer_id=1,
        note="POS regression",
        tax_rate=1400,
        currency="EGP",
        payments=[dict(method="Cash", amount=10000), dict(method="Visa", amount=11090)],
    )
    data.update(changes)
    return data


def test_new_sale_and_search(client):
    page = client.get("/sales/new")
    assert (
        page.status_code == 200
        and b"pos.js" in page.data
        and b"product-search" in page.data
    )
    for q in ["Test", "TEST-001", "12345678"]:
        result = client.get("/api/pos/products", query_string={"q": q}).json
        assert result["items"][0]["id"] == 1
        assert result["items"][0]["stock"] == 10
    assert (
        client.get("/api/pos/products?barcode=12345678").json["items"][0]["price"]
        == 10000
    )
    assert client.get("/api/pos/products?barcode=missing").json["items"] == []


def test_quote_and_split_sale(app, client):
    data = invoice()
    quote = client.post("/api/pos/quote", json=data).json
    assert quote["valid"] and quote["total"] == 21090 and quote["tax"] == 2590
    assert quote["profit"] == 8500 and quote["discount"] == 1500
    result = client.post("/api/pos/sales", json=data)
    assert result.status_code == 200, result.json
    with app.app_context():
        sale = Sale.query.one()
        assert sale.payment == "Split" and sale.invoice_discount == 500
        assert sale.items[0].discount == 1000 and sale.total == 21090
        assert sum(p.amount for p in sale.payments) == sale.total
        assert db.session.get(Product, 1).stock == 8
        assert SalePayment.query.count() == 2
    printed = client.get(result.json["invoice_url"])
    assert b"Visa" in printed.data and b"Line discount:" in printed.data
    assert client.get("/sales?payment=Card").status_code == 200


def test_auto_merge_and_idempotency(app, client):
    data = invoice(
        items=[dict(product_id=1, quantity=1, discount=500, unit_price=10000)] * 2
    )
    first = client.post("/api/pos/sales", json=data)
    second = client.post("/api/pos/sales", json=data)
    assert (
        first.status_code == second.status_code == 200
        and first.json["id"] == second.json["id"]
    )
    recovery = client.post("/api/pos/quote", json=data).json
    assert recovery["saved_invoice"]["id"] == first.json["id"]
    with app.app_context():
        assert Sale.query.count() == 1 and SaleItem.query.count() == 1
        assert (
            SaleItem.query.one().quantity == 2 and SaleItem.query.one().discount == 1000
        )
        assert db.session.get(Product, 1).stock == 8


@pytest.mark.parametrize(
    "changes",
    [
        {"payments": [{"method": "Visa", "amount": 1}]},
        {"payments": [{"method": "Crypto", "amount": 21090}]},
        {
            "payments": [
                {"method": "Cash", "amount": 21090},
                {"method": "Visa", "amount": 0},
            ]
        },
        {"items": [dict(product_id=1, quantity=11, discount=0, unit_price=10000)]},
        {"items": [dict(product_id=1, quantity=True, discount=0, unit_price=10000)]},
        {"items": [dict(product_id=1, quantity=2, discount=0, unit_price=1)]},
        {"items": [dict(product_id=1, quantity=2, discount=20001, unit_price=10000)]},
        {"tax_rate": 0},
        {"currency": "USD"},
        {"customer_id": 999},
        {"token": "invalid"},
        {"invoice_discount": 1.5},
        {"invoice_discount": 20001},
    ],
)
def test_invalid_sale_is_atomic(app, client, changes):
    response = client.post("/api/pos/sales", json=invoice(**changes))
    assert response.status_code == 400 and response.is_json
    with app.app_context():
        assert (
            Sale.query.count()
            == SalePayment.query.count()
            == InventoryMovement.query.count()
            == 0
        )
        assert db.session.get(Product, 1).stock == 10


def test_stock_changes_and_inactive_products(app, client):
    with app.app_context():
        p = db.session.get(Product, 1)
        p.stock = 1
        db.session.commit()
    quote = client.post("/api/pos/quote", json=invoice()).json
    assert not quote["valid"] and quote["items"][0]["product"]["stock"] == 1
    with app.app_context():
        p = db.session.get(Product, 1)
        p.active = False
        db.session.commit()
    assert client.get("/api/pos/products?q=Test").json["items"] == []
    assert client.get("/api/pos/products?ids=1").json["items"][0]["active"] is False
    assert client.post("/api/pos/sales", json=invoice()).status_code == 400


def test_ajax_customer_and_shortcuts(app, client):
    result = client.post(
        "/api/pos/customers",
        json=dict(name="POS Customer", phone="01000000000", email="pos@example.test"),
    )
    assert result.status_code == 201
    cid = result.json["id"]
    assert client.get("/api/pos/customers?q=01000000000").json["items"][0]["id"] == cid
    assert (
        client.post("/api/pos/sales", json=invoice(customer_id=cid)).status_code == 200
    )
    data = client.get("/api/pos/shortcuts").json
    assert data["frequent"][0]["id"] == data["recent"][0]["id"] == 1
    with app.app_context():
        assert Sale.query.one().customer_name == "POS Customer"


def test_edit_preserves_allocations_and_stock(app, client):
    first = client.post("/api/pos/sales", json=invoice()).json
    sid = first["id"]
    assert b"pos.js" in client.get(f"/sales/{sid}/edit").data
    assert (
        client.get(f"/api/pos/products?ids=1&editing={sid}").json["items"][0]["stock"]
        == 10
    )
    data = invoice(
        sale_id=sid,
        revision=1,
        items=[dict(product_id=1, quantity=3, discount=1000, unit_price=10000)],
        payments=[dict(method="Wallet", amount=32490)],
    )
    result = client.post("/api/pos/sales", json=data)
    assert result.status_code == 200, result.json
    assert client.post("/api/pos/sales", json=data).status_code == 400
    with app.app_context():
        sale = db.session.get(Sale, sid)
        assert (
            sale.revision == 2 and len(sale.payments) == 1 and sale.payment == "Wallet"
        )
        assert db.session.get(Product, 1).stock == 7
    assert client.post(f"/sales/{sid}/refund").status_code == 302
    client.post(f"/sales/{sid}/refund")
    with app.app_context():
        assert db.session.get(Product, 1).stock == 10
    assert client.get("/api/pos/shortcuts").json["recent"] == []


def test_pos_auth_and_csrf(app, client):
    guest = app.test_client()
    assert guest.get("/api/pos/products").status_code == 401
    client.post("/logout")
    client.post("/login", data=dict(username="cashier", password="test-password-123"))
    assert (
        client.post(
            "/api/pos/customers", json=dict(name="Counter customer")
        ).status_code
        == 201
    )
    assert client.post("/api/pos/sales", json=invoice()).status_code == 200
    assert client.get("/api/pos/products?editing=1").status_code == 403
    app.config["WTF_CSRF_ENABLED"] = True
    response = client.post("/api/pos/sales", json=invoice(token="a" * 48))
    assert response.status_code == 400 and response.json["code"] == "csrf_expired"


def test_discounted_product_reporting(app, client):
    assert client.post("/api/pos/sales", json=invoice()).status_code == 200
    with app.test_request_context("/reports"):
        from services.analytics import report_data, date_range

        _, rows, _, _ = report_data("products", *date_range())
        assert rows[0][3] == 18500 and rows[0][4] == 8500


def test_zero_total_and_duplicate_payment_methods(app, client):
    result = client.post(
        "/api/pos/sales",
        json=invoice(invoice_discount=19000, payments=[dict(method="Cash", amount=0)]),
    )
    assert result.status_code == 200 and result.json["total"] == 0
    result = client.post(
        "/api/pos/sales",
        json=invoice(
            token="e" * 48,
            payments=[
                dict(method="Visa", amount=10000),
                dict(method="Visa", amount=11090),
            ],
        ),
    )
    assert result.status_code == 200
    with app.app_context():
        sale = db.session.get(Sale, result.json["id"])
        assert sale.payment == "Visa" and len(sale.payments) == 1


def test_concurrent_last_stock(app, client):
    with app.app_context():
        db.session.get(Product, 1).stock = 1
        db.session.commit()

    def sell(token):
        c = app.test_client()
        c.post("/login", data=dict(username="admin", password="test-password-123"))
        data = invoice(
            token=token * 48,
            items=[dict(product_id=1, quantity=1, unit_price=10000, discount=0)],
            invoice_discount=0,
            payments=[dict(method="Mastercard", amount=11400)],
        )
        return c.post("/api/pos/sales", json=data).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(sell, ["a", "b"]))
    assert sorted(results) == [200, 400]
    with app.app_context():
        assert Sale.query.count() == 1 and db.session.get(Product, 1).stock == 0


def test_migration_is_safe_and_repeatable(tmp_path):
    path = tmp_path / "legacy.db"
    with closing(sqlite3.connect(path)) as c:
        c.executescript(
            "CREATE TABLE sales(id INTEGER PRIMARY KEY);CREATE TABLE sale_items(id INTEGER PRIMARY KEY, quantity INTEGER, price INTEGER);INSERT INTO sales VALUES(1);INSERT INTO sale_items VALUES(1,2,500);"
        )
    upgrade_sqlite(path, backup=True)
    upgrade_sqlite(path, backup=True)
    with closing(sqlite3.connect(path)) as c:
        assert c.execute("SELECT discount FROM sale_items").fetchone() == (0,)
        assert c.execute("SELECT count(*) FROM sales").fetchone() == (1,)
        assert c.execute("SELECT count(*) FROM sale_payments").fetchone() == (0,)
    assert len(list(tmp_path.glob("pre-pos-*.sqlite3"))) == 1


def test_restore_legacy_backup(app, client, tmp_path):
    response = backup_response(app, client)
    old = tmp_path / "legacy.sqlite3"
    with zipfile.ZipFile(io.BytesIO(response.data)) as original:
        entries = {n: original.read(n) for n in original.namelist()}
    db_name = next(n for n in entries if n.endswith((".db", ".sqlite3", ".sqlite")))
    old.write_bytes(entries[db_name])
    with closing(sqlite3.connect(old)) as c:
        c.executescript("""DROP TABLE backup_logs; DROP TABLE sale_payments;
        CREATE TABLE legacy_items (id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(id), product_id INTEGER NOT NULL REFERENCES products(id), name VARCHAR(160) NOT NULL, category_name VARCHAR(80) NOT NULL, quantity INTEGER NOT NULL, price INTEGER NOT NULL, cost INTEGER NOT NULL);
        INSERT INTO legacy_items SELECT id,sale_id,product_id,name,category_name,quantity,price,cost FROM sale_items;
        DROP TABLE sale_items;
        ALTER TABLE legacy_items RENAME TO sale_items;""")
    entries[db_name] = old.read_bytes()
    entries["manifest.json"] = b'{"format":"StorePro","version":1}'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    buffer.seek(0)
    restored = client.post(
        "/settings/restore",
        data={
            "password": "test-password-123",
            "confirm": "RESTORE",
            "backup": (buffer, "legacy.zip"),
        },
    )
    assert restored.status_code == 202, restored.data.decode()[:300]
    assert finish_restore(app)["restored"] is True
    with app.app_context():
        assert SalePayment.query.count() == 0
