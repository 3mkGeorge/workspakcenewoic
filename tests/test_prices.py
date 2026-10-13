from test_app import backup_response, finish_restore

"""Price ledger, UI, exports, security, and backwards-compatible upgrades."""

from contextlib import closing
from decimal import Decimal
from io import BytesIO
import sqlite3
import zipfile
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import MultiDict
from test_app import app, client  # noqa: F401
from models import db, Product, PriceHistory, User
from services.migrations import upgrade_sqlite


def edit(client, price="125", cost="65", **kwargs):
    return client.post(
        "/products/1/edit",
        data={
            "name": "Test Product",
            "sku": "TEST-001",
            "category_id": "1",
            "supplier_id": "1",
            "price": price,
            "cost": cost,
            "minimum": "5",
            **kwargs,
        },
    )


def test_price_edit_snapshots_and_unchanged(app, client):
    response = edit(client)
    assert response.status_code == 302 and response.location == "/products?selected=1"
    assert edit(client).status_code == 302
    with app.app_context():
        row = PriceHistory.query.one()
        assert (row.old_cost, row.new_cost, row.old_price, row.new_price) == (
            5000,
            6500,
            10000,
            12500,
        )
        assert row.change_amount == 2500 and row.change_percentage == Decimal("25")
        assert row.cost_change_amount == 1500 and row.cost_change_percentage == Decimal(
            "30"
        )
        assert (
            row.user_id == 1
            and row.changed_by == "Admin"
            and row.product_name == "Test Product"
        )
        db.session.get(User, 1).name = "Renamed Admin"
        db.session.commit()
        assert PriceHistory.query.one().changed_by == "Admin"
    assert (
        edit(client, price="110", cost="65", name="Renamed Product").status_code == 302
    )
    with app.app_context():
        rows = PriceHistory.query.order_by(PriceHistory.id).all()
        assert len(rows) == 2 and rows[0].product_name == "Test Product"
        assert rows[1].old_price == 12500 and rows[1].change_amount == -1500


def test_price_analytics_kpi_header(client):
    """Analytics header: 8 full-width KPI cards (incl. images) with value ids."""
    import re

    html = client.get("/products").data.decode()
    cards = re.findall(r'class="ph-kpi ([^"]+)"', html)
    assert cards == [
        "ph-blue",
        "ph-orange",
        "ph-green",
        "ph-red",
        "ph-purple",
        "ph-cyan",
        "ph-emerald",
        "ph-slate",
    ]
    for token in (
        "pm-current",
        "pm-cost",
        "pm-high",
        "pm-low",
        "pm-avg",
        "pm-last",
        "pm-pct",
        "pm-last-trend",
        "pm-pct-trend",
        "pm-image-count",
        "pm-view-gallery",
        "Current Selling Price",
        "Price Change Percentage",
    ):
        assert token in html, token


def test_history_api_analytics_and_alerts(app, client):
    edit(client)
    data = client.get("/api/products/1/price-history").json
    assert data["summary"]["current"] == 12500 and data["summary"]["lowest"] == 10000
    assert data["summary"]["highest"] == 12500 and data["summary"]["average"] == 11250
    assert data["summary"]["alert"] is True and data["items"][0]["date"][2] == "/"
    assert len(data["items"][0]["date"]) == 16
    response = client.post("/products/1/price-alerts", data={"enabled": "0"})
    assert response.status_code == 302 and response.location == "/products?selected=1"
    assert client.get("/api/products/1/price-history").json["summary"]["alert"] is False
    with app.app_context():
        assert PriceHistory.query.count() == 1
    page = client.get("/products?selected=1").data
    for word in (
        b"Price History",
        b"Price Trend",
        b"Last Price Change",
        b"25.00%",
        b"price-history.js",
    ):
        assert word in page
    assert "ج.م".encode() in page


def test_zero_base_and_exact_twenty(app, client):
    edit(client, price="120", cost="50")
    assert not client.get("/api/products/1/price-history").json["summary"]["alert"]
    edit(client, price="0", cost="0")
    edit(client, price="100", cost="50")
    data = client.get("/api/products/1/price-history").json
    assert data["items"][0]["change_percentage"] is None
    assert data["items"][0]["cost_change_percentage"] is None
    assert client.get("/products?selected=1").status_code == 200


def test_cost_only_purchase_record(app, client):
    data = MultiDict(
        [
            ("token", "price-purchase"),
            ("supplier_id", "1"),
            ("product_id", "1"),
            ("quantity", "10"),
            ("unit_cost", "70"),
        ]
    )
    assert client.post("/purchases/new", data=data).status_code == 302
    assert client.post("/purchases/1/receive").status_code == 302
    with app.app_context():
        row = PriceHistory.query.one()
        assert row.old_cost == 5000 and row.new_cost == 6000
        assert row.old_price == row.new_price == 10000 and row.change_amount == 0
        assert row.changed_by == "Admin" and row.source == "Purchase receipt"
    assert client.post("/purchases/1/receive").status_code == 400
    with app.app_context():
        assert PriceHistory.query.count() == 1


def test_rollback_retains_no_history(app, client):
    with app.app_context():
        p = db.session.get(Product, 1)
        p.price = 13000
        db.session.flush()
        assert PriceHistory.query.count() == 1
        db.session.rollback()
        assert (
            PriceHistory.query.count() == 0
            and db.session.get(Product, 1).price == 10000
        )
    assert edit(client, price="120", minimum="-1").status_code == 400
    with app.app_context():
        assert PriceHistory.query.count() == 0


@pytest.mark.parametrize(
    "statement", ["UPDATE price_history SET new_price=1", "DELETE FROM price_history"]
)
def test_history_cannot_be_rewritten(app, client, statement):
    edit(client)
    with app.app_context():
        with pytest.raises(IntegrityError):
            db.session.execute(text(statement))
        db.session.rollback()
        assert PriceHistory.query.one().new_price == 12500


def test_pagination_and_chart_limit(app, client):
    with app.app_context():
        p = db.session.get(Product, 1)
        for i in range(35):
            p.price = 10100 + i
            db.session.commit()
    data = client.get("/api/products/1/price-history").json
    assert len(data["items"]) == 10 and len(data["summary"]["trend"]) == 30
    assert (
        data["summary"]["count"] == 35
        and data["summary"]["trend"][-1]["new_price"] == 10134
    )
    ids = [r["id"] for r in data["items"]]
    while data["next_cursor"]:
        data = client.get(
            "/api/products/1/price-history?before=" + str(data["next_cursor"])
        ).json
        ids.extend(r["id"] for r in data["items"])
    assert ids == list(range(35, 0, -1))
    assert client.get("/api/products/1/price-history?before=bad").status_code == 400


def test_history_export_and_formula_safety(app, client):
    from openpyxl import load_workbook

    edit(client, name="=1+1")
    xlsx = client.get("/products/1/price-history/export/xlsx")
    assert xlsx.status_code == 200
    book = load_workbook(BytesIO(xlsx.data))
    sheet = book.active
    assert sheet["C3"].value == "=1+1" and sheet["C3"].data_type == "s"
    assert (
        sheet["G3"].value == 100
        and sheet["H3"].value == 125
        and sheet["J3"].value == 0.25
    )
    assert (
        sheet["D3"].number_format == "dd/mm/yyyy hh:mm" and sheet["O3"].value == "EGP"
    )
    pdf = client.get("/products/1/price-history/export/pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    assert client.get("/products/1/price-history/export/invalid").status_code == 404


def test_history_auth_and_csrf(app, client):
    assert app.test_client().get("/api/products/1/price-history").status_code == 401
    client.post("/logout")
    client.post("/login", data={"username": "cashier", "password": "test-password-123"})
    assert client.get("/api/products/1/price-history").status_code == 200
    assert edit(client).status_code == 403
    assert (
        client.post("/products/1/price-alerts", data={"enabled": "0"}).status_code
        == 403
    )
    assert client.get("/products/1/price-history/export/xlsx").status_code == 403
    client.post("/logout")
    client.post("/login", data={"username": "admin", "password": "test-password-123"})
    app.config["WTF_CSRF_ENABLED"] = True
    assert (
        client.post("/products/1/price-alerts", data={"enabled": "0"}).status_code
        == 400
    )


def test_price_backup_and_restore(app, client):
    edit(client)
    backup = backup_response(app, client)
    result = client.post(
        "/settings/restore",
        data={
            "password": "test-password-123",
            "confirm": "RESTORE",
            "backup": (BytesIO(backup.data), "prices.zip"),
        },
    )
    assert result.status_code == 202
    assert finish_restore(app)["restored"] is True
    with app.app_context():
        assert PriceHistory.query.one().new_price == 12500
        with pytest.raises(IntegrityError):
            db.session.execute(text("DELETE FROM price_history"))
        db.session.rollback()


def test_upgrade_pre_price_database(app, client, tmp_path):
    backup = backup_response(app, client)
    with zipfile.ZipFile(BytesIO(backup.data)) as original:
        entries = {n: original.read(n) for n in original.namelist()}
    path = tmp_path / "old.db"
    path.write_bytes(entries["store.db"])
    with closing(sqlite3.connect(path)) as c:
        c.executescript(
            "DROP TABLE price_history; ALTER TABLE products DROP COLUMN price_alerts;"
        )
    upgrade_sqlite(path, backup=True)
    upgrade_sqlite(path, backup=True)
    with closing(sqlite3.connect(path)) as c:
        assert c.execute(
            "SELECT price,cost,price_alerts FROM products WHERE id=1"
        ).fetchone() == (10000, 5000, 1)
        assert c.execute("SELECT COUNT(*) FROM price_history").fetchone() == (0,)
    assert len(list(tmp_path.glob("pre-prices-*.sqlite3"))) == 1
    with closing(sqlite3.connect(path)) as c:
        c.executescript("DROP TRIGGER price_history_no_update;")
    upgrade_sqlite(path)
    with closing(sqlite3.connect(path)) as c:
        assert c.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'"
        ).fetchone() == (2,)
