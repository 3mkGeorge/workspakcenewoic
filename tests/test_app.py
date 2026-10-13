import io
import json
import re
import sys
import zipfile
from pathlib import Path
import pytest
from werkzeug.datastructures import MultiDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from models import *
from services.core import DEFAULTS
from werkzeug.security import generate_password_hash


@pytest.fixture
def app(tmp_path):
    (tmp_path / "backups").mkdir()
    (tmp_path / "static/uploads").mkdir(parents=True)
    app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "ROOT": tmp_path,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "test.db"),
        }
    )
    with app.app_context():
        roles = [Role(name=n) for n in ["Admin", "Manager", "Cashier"]]
        db.session.add_all(roles)
        db.session.flush()
        for i, r in enumerate(roles):
            db.session.add(
                User(
                    name=r.name,
                    username=r.name.lower(),
                    password_hash=generate_password_hash("test-password-123"),
                    role_id=r.id,
                )
            )
        db.session.add(Category(name="Electronics"))
        db.session.add(Supplier(name="Supplier"))
        db.session.add(Customer(name="Customer"))
        db.session.flush()
        db.session.add(
            Product(
                name="Test Product",
                sku="TEST-001",
                barcode="12345678",
                category_id=1,
                supplier_id=1,
                cost=5000,
                price=10000,
                stock=10,
                minimum=5,
            )
        )
        db.session.commit()
    yield app
    with app.app_context():
        from services.logging_service import shutdown_structured_logging

        shutdown_structured_logging(app)
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    client = app.test_client()
    assert (
        client.post(
            "/login", data={"username": "admin", "password": "test-password-123"}
        ).status_code
        == 302
    )
    return client


def sale_data(token="a", quantity="2", discount="10"):
    return MultiDict(
        [
            ("token", token),
            ("product_id", "1"),
            ("quantity", quantity),
            ("customer_id", "1"),
            ("payment", "Cash"),
            ("discount", discount),
        ]
    )


def test_all_pages(client):
    for url in [
        "/",
        "/products",
        "/inventory",
        "/sales",
        "/purchases",
        "/customers",
        "/suppliers",
        "/categories",
        "/reports",
        "/settings",
        "/settings/users",
        "/settings/audit",
        "/account",
        "/expenses",
        "/search?q=Test",
        "/notifications",
        "/products/new",
        "/products/1/edit",
        "/sales/new",
        "/purchases/new",
        "/inventory/adjust",
        "/inventory/movements",
    ]:
        response = client.get(url)
        assert response.status_code == 200, (url, response.data[:500])


def test_sale_vat_stock_and_idempotence(app, client):
    assert client.post("/sales/new", data=sale_data()).status_code == 302
    assert client.post("/sales/new", data=sale_data()).status_code == 302
    with app.app_context():
        s = Sale.query.one()
        assert (s.subtotal, s.discount, s.tax, s.total, s.cost) == (
            20000,
            1000,
            2660,
            21660,
            10000,
        )
        assert db.session.get(Product, 1).stock == 8
        assert InventoryMovement.query.count() == 1
    for url in [
        "/sales?selected=1",
        "/sales/1/edit",
        "/sales/1/invoice",
        "/sales/1/invoice?receipt=1",
    ]:
        assert client.get(url).status_code == 200


def test_oversell_rolls_back(app, client):
    assert client.post("/sales/new", data=sale_data(quantity="11")).status_code == 400
    with app.app_context():
        assert Sale.query.count() == 0
        assert db.session.get(Product, 1).stock == 10
        assert InventoryMovement.query.count() == 0


def test_refund_exactly_once(app, client):
    client.post("/sales/new", data=sale_data())
    assert client.post("/sales/1/refund").status_code == 302
    assert client.post("/sales/1/refund").status_code == 400
    with app.app_context():
        assert db.session.get(Product, 1).stock == 10
        assert Sale.query.one().status == "Refunded"


def test_edit_atomic_and_revision(app, client):
    client.post("/sales/new", data=sale_data())
    data = sale_data(quantity="4")
    data["revision"] = "1"
    assert client.post("/sales/1/edit", data=data).status_code == 302
    assert client.post("/sales/1/edit", data=data).status_code == 400
    data["revision"] = "2"
    data["quantity"] = "20"
    assert client.post("/sales/1/edit", data=data).status_code == 400
    with app.app_context():
        assert db.session.get(Product, 1).stock == 6
        assert Sale.query.one().items[0].quantity == 4


def test_purchase_receipt_weighted_cost(app, client):
    data = MultiDict(
        [
            ("token", "po1"),
            ("supplier_id", "1"),
            ("product_id", "1"),
            ("quantity", "10"),
            ("unit_cost", "70"),
        ]
    )
    assert client.post("/purchases/new", data=data).status_code == 302
    assert client.get("/purchases?selected=1").status_code == 200
    with app.app_context():
        assert db.session.get(Product, 1).stock == 10
    assert client.post("/purchases/1/receive").status_code == 302
    assert client.post("/purchases/1/receive").status_code == 400
    with app.app_context():
        p = db.session.get(Product, 1)
        assert (p.stock, p.cost) == (20, 6000)


def test_roles(app):
    c = app.test_client()
    c.post("/login", data={"username": "cashier", "password": "test-password-123"})
    for path in [
        "/settings",
        "/reports",
        "/settings/users",
        "/products/new",
        "/purchases/new",
        "/inventory/adjust",
    ]:
        assert c.get(path).status_code == 403, path
    for path in [
        "/sales/1/refund",
        "/products/1/delete",
        "/settings/backup",
        "/purchases/1/receive",
    ]:
        assert c.post(path).status_code == 403, path
    assert c.get("/sales/new").status_code == 200


def test_exports(app, client):
    client.post("/sales/new", data=sale_data())
    # Font resides with static app assets, not test database root.
    vendor = app.config["ROOT"] / "static/vendor"
    vendor.mkdir()
    import shutil

    shutil.copy2(
        Path(__file__).resolve().parents[1] / "static/vendor/NotoSansArabic.ttf",
        vendor / "NotoSansArabic.ttf",
    )
    for kind in [
        "sales",
        "purchases",
        "inventory",
        "products",
        "customers",
        "suppliers",
        "profit",
    ]:
        assert client.get("/reports?kind=" + kind).status_code == 200
        for fmt, magic in [("xlsx", b"PK"), ("pdf", b"%PDF")]:
            r = client.get(f"/reports/export/{fmt}?kind={kind}")
            assert r.status_code == 200
            assert r.data.startswith(magic)


def backup_response(app, client):
    assert client.post("/settings/backup").status_code == 202
    with app.app_context():
        app.extensions["backups"].tick()
    files = client.get("/api/backups/status").json["files"]
    first = next(f for f in files if f["source"] == "Primary")
    return client.get("/settings/backups/" + first["name"])


def finish_restore(app):
    with app.app_context():
        app.extensions["backups"].tick()
    return app.extensions["backups"].snapshot()


def test_backup_restore(app, client):
    backup = backup_response(app, client)
    assert backup.status_code == 200
    client.post("/sales/new", data=sale_data())
    result = client.post(
        "/settings/restore",
        data={
            "password": "test-password-123",
            "confirm": "RESTORE",
            "backup": (io.BytesIO(backup.data), "backup.zip"),
        },
        content_type="multipart/form-data",
    )
    assert result.status_code == 202
    assert finish_restore(app)["restored"] is True
    assert client.get("/sales").status_code == 302
    with app.app_context():
        assert Sale.query.count() == 0
        assert db.session.get(Product, 1).stock == 10


def test_reject_invalid_backup(app, client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", '{"version":1}')
        z.writestr("../evil", "bad")
    buf.seek(0)
    assert (
        client.post(
            "/settings/restore",
            data={
                "password": "test-password-123",
                "confirm": "RESTORE",
                "backup": (buf, "bad.zip"),
            },
        ).status_code
        == 202
    )
    assert finish_restore(app)["restored"] is False
    with app.app_context():
        assert db.session.get(Product, 1).stock == 10


def test_csrf(app):
    app.config["WTF_CSRF_ENABLED"] = True
    c = app.test_client()
    assert (
        c.post(
            "/login", data={"username": "admin", "password": "test-password-123"}
        ).status_code
        == 400
    )
    page = c.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    assert (
        c.post(
            "/login",
            data={
                "username": "admin",
                "password": "test-password-123",
                "csrf_token": token,
            },
        ).status_code
        == 302
    )


def test_validation_and_archive(app, client):
    assert (
        client.post(
            "/inventory/adjust",
            data={"product_id": "1", "quantity": "-11", "reason": "Count"},
        ).status_code
        == 400
    )
    assert client.post("/products/1/delete").status_code == 400
    assert (
        client.post(
            "/inventory/adjust",
            data={"product_id": "1", "quantity": "-10", "reason": "Count"},
        ).status_code
        == 302
    )
    assert client.post("/products/1/delete").status_code == 302
    with app.app_context():
        assert db.session.get(Product, 1).active is False


def test_currency_locked_and_arabic(app, client):
    config = DEFAULTS | {"currency": "USD"}
    assert client.post("/settings", data=config).status_code == 400
    config = DEFAULTS | {"language": "ar"}
    assert client.post("/settings", data=config).status_code == 302
    assert 'dir="rtl"' in client.get("/").text


def test_invalid_inputs_and_xss(client):
    for value in ["NaN", "Infinity", "-2", "1e100", "<script>"]:
        assert (
            client.post("/sales/new", data=sale_data(discount=value)).status_code == 400
        )
    assert (
        b"<script>alert(1)</script>"
        not in client.get("/search?q=%3Cscript%3Ealert(1)%3C/script%3E").data
    )


def test_first_run(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "ROOT": tmp_path,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "first.db"),
        }
    )
    try:
        c = app.test_client()
        assert c.get("/").status_code == 302
        assert c.get("/setup").status_code == 200
        assert (
            c.post(
                "/setup",
                data={
                    "name": "Owner",
                    "username": "owner",
                    "password": "secure-password-2026",
                },
            ).status_code
            == 302
        )
        assert c.get("/setup").status_code == 302
    finally:
        with app.app_context():
            db.engine.dispose()


def test_concurrent_sale_last_unit(app):
    from concurrent.futures import ThreadPoolExecutor

    with app.app_context():
        db.session.get(Product, 1).stock = 1
        db.session.commit()

    def sell(token):
        c = app.test_client()
        c.post("/login", data={"username": "admin", "password": "test-password-123"})
        return c.post(
            "/sales/new", data=sale_data(token=token, quantity="1", discount="0")
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(sell, ["first", "second"]))
    assert sorted(results) == [302, 400]
    with app.app_context():
        assert Sale.query.count() == 1
        assert db.session.get(Product, 1).stock == 0


def test_multiline_failure_atomic(app, client):
    with app.app_context():
        db.session.add(
            Product(
                name="Second",
                sku="SECOND",
                category_id=1,
                cost=100,
                price=200,
                stock=0,
                minimum=5,
            )
        )
        db.session.commit()
    data = sale_data()
    data.add("product_id", "2")
    data.add("quantity", "1")
    assert client.post("/sales/new", data=data).status_code == 400
    with app.app_context():
        assert db.session.get(Product, 1).stock == 10
        assert Sale.query.count() == 0
        assert InventoryMovement.query.count() == 0


def test_duplicate_product_rejected(client):
    data = sale_data()
    data.add("product_id", "1")
    data.add("quantity", "1")
    assert client.post("/sales/new", data=data).status_code == 400


def test_purchase_cancel_no_stock(app, client):
    data = MultiDict(
        [
            ("token", "cancelled-order"),
            ("supplier_id", "1"),
            ("product_id", "1"),
            ("quantity", "5"),
            ("unit_cost", "50"),
        ]
    )
    client.post("/purchases/new", data=data)
    assert client.post("/purchases/1/cancel").status_code == 302
    assert client.post("/purchases/1/receive").status_code == 400
    with app.app_context():
        assert db.session.get(Product, 1).stock == 10


def test_product_image_and_duplicate_sku(app, client):
    from PIL import Image

    image = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(image, "PNG")
    image.seek(0)
    data = {
        "name": "Image product",
        "sku": "IMAGE",
        "category_id": "1",
        "cost": "1",
        "price": "2",
        "minimum": "1",
        "stock": "5",
        "image": (image, "product.png"),
    }
    assert client.post("/products/new", data=data).status_code == 302
    with app.app_context():
        product = Product.query.filter_by(sku="IMAGE").one()
        assert (app.config["ROOT"] / "static/uploads" / product.image).exists()
        assert product.stock == 5
    data.pop("image")
    assert client.post("/products/new", data=data).status_code == 409


def test_session_disabled_immediately(app, client):
    with app.app_context():
        user = User.query.filter_by(username="admin").one()
        user.active = False
        db.session.commit()
    assert client.get("/").status_code == 302


def test_session_expiry(client):
    with client.session_transaction() as session:
        session["last_seen"] = 0
    assert client.get("/sales").status_code == 302


def test_expense_and_profit(app, client):
    client.post("/sales/new", data=sale_data())
    assert (
        client.post(
            "/expenses", data={"description": "Rent", "amount": "20"}
        ).status_code
        == 302
    )
    with app.test_request_context("/reports"):
        from services.analytics import date_range, report_data

        _, _, _, stats = report_data("profit", *date_range())
        assert stats["profit"] == 9000
        assert stats["net"] == 7000


def test_snapshot_and_invoice_edit_audit(app, client):
    client.post("/sales/new", data=sale_data())
    with app.app_context():
        db.session.get(Product, 1).name = "Renamed"
        db.session.get(Product, 1).price = 11000
        db.session.commit()
    assert b"Test Product" in client.get("/sales/1/invoice").data
    data = sale_data()
    data["revision"] = "1"
    client.post("/sales/1/edit", data=data)
    with app.app_context():
        log = AuditLog.query.filter_by(action="Invoice revision snapshot").one()
        snapshot = json.loads(log.details)
        assert snapshot["items"][0]["name"] == "Test Product"
        assert snapshot["items"][0]["price"] == 10000


def test_arabic_all_pages_and_exports(client, app):
    assert (
        client.post("/settings", data=DEFAULTS | {"language": "ar"}).status_code == 302
    )
    for path in [
        "/",
        "/products",
        "/inventory",
        "/purchases",
        "/sales",
        "/reports",
        "/settings",
        "/sales/new",
        "/purchases/new",
    ]:
        r = client.get(path)
        assert r.status_code == 200
        assert 'dir="rtl"' in r.text
    vendor = app.config["ROOT"] / "static/vendor"
    vendor.mkdir()
    import shutil

    shutil.copy2(
        Path(__file__).resolve().parents[1] / "static/vendor/NotoSansArabic.ttf",
        vendor / "NotoSansArabic.ttf",
    )
    with app.app_context():
        db.session.get(Product, 1).name = "منتج تجريبي"
        db.session.get(Customer, 1).name = "أحمد علي"
        db.session.commit()
    client.post("/sales/new", data=sale_data())
    for fmt, magic in [("pdf", b"%PDF"), ("xlsx", b"PK")]:
        response = client.get("/reports/export/" + fmt + "?kind=sales")
        assert response.status_code == 200
        assert response.data.startswith(magic)


def test_invalid_dates_and_report_filters(app, client):
    assert client.get("/reports?from=2026-09-30&to=2026-09-01").status_code == 400
    assert client.get("/reports?from=invalid").status_code == 400
    client.post("/sales/new", data=sale_data())
    assert (
        client.get(
            "/reports?product_id=1&customer_id=1&category_id=1&group=month"
        ).status_code
        == 200
    )
    with app.test_request_context("/reports?customer_id=999"):
        from services.analytics import date_range, report_data

        _, rows, _, stats = report_data("sales", *date_range())
        assert rows == []
        assert stats["total"] == 0


def test_no_external_frontend_assets(client):
    page = client.get("/").text
    assert not re.search(r'(?:src|href)=["\']https?://', page)


def test_optional_demo(app):
    with app.app_context():
        db.session.delete(db.session.get(Product, 1))
        db.session.commit()
        # Start from a completely empty demo catalog, including its directory categories.
        db.session.query(Category).delete()
        db.session.query(Customer).delete()
        db.session.query(Supplier).delete()
        db.session.commit()
        from services.demo import seed_demo

        seed_demo(User.query.filter_by(username="admin").one())
        assert Product.query.count() == 10
        assert Sale.query.count() > 20
        assert Purchase.query.count() == 8
        for p in Product.query.all():
            assert p.stock >= 0


def test_schema_matches_models(tmp_path):
    import sqlite3
    from contextlib import closing

    schema = (Path(__file__).resolve().parents[1] / "schema.sql").read_text(
        encoding="utf-8"
    )
    with closing(sqlite3.connect(tmp_path / "schema.db")) as connection:
        connection.executescript(schema)
        names = {
            r[0]
            for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert names == set(db.metadata.tables)


def test_inventory_report_filters(app, client):
    with app.test_request_context("/reports?product_id=999"):
        from services.analytics import date_range, report_data

        _, rows, _, _ = report_data("inventory", *date_range())
        assert rows == []


def test_money_rounding(app, client):
    with app.app_context():
        p = db.session.get(Product, 1)
        p.price = 1
        p.cost = 0
        db.session.commit()
        from services.core import save_setting

        save_setting("tax_rate", "50")
        db.session.commit()
    client.post("/sales/new", data=sale_data(quantity="1", discount="0"))
    with app.app_context():
        assert Sale.query.one().tax == 1
        assert Sale.query.one().total == 2


def test_settings_password_and_last_admin(client, app):
    assert (
        client.post(
            "/settings/users",
            data={
                "id": "1",
                "name": "Admin",
                "username": "admin",
                "role_id": "3",
                "active": "1",
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/settings/restore", data={"password": "wrong", "confirm": "RESTORE"}
        ).status_code
        == 400
    )
    with app.app_context():
        assert db.session.get(User, 1).role.name == "Admin"
