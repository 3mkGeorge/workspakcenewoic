"""Regression tests for UI input/output bugs fixed together."""

import io

from test_app import app, client  # noqa: F401
from test_orders import delivery_invoice
from models import InventoryMovement, Product, Sale, ShippingOrder, db


def test_partial_refund_keeps_invoice_discount_and_vat_on_net(app, client):
    payload = delivery_invoice(
        items=[dict(product_id=1, quantity=2, discount=5000, unit_price=10000)],
        invoice_discount=1000,
        payments=[dict(method="Cash", amount=15960)],
    )
    response = client.post("/api/pos/sales", json=payload)
    assert response.status_code == 200, response.json
    with app.app_context():
        sale = Sale.query.one()
        assert sale.total == 15960
        item_id = sale.items[0].id
    response = client.post(
        f"/sales/{sale.id}/refund", json={"items": [{"item_id": item_id, "quantity": 1}]}
    )
    assert response.status_code in (200, 302)
    with app.app_context():
        sale = Sale.query.one()
        assert (sale.subtotal, sale.discount, sale.tax, sale.total) == (10000, 3000, 980, 7980)


def test_partial_refund_with_uneven_line_discount(app, client):
    with app.app_context():
        db.session.get(Product, 1).price = 1000
        db.session.commit()
    payload = delivery_invoice(
        items=[dict(product_id=1, quantity=3, discount=2999, unit_price=1000)],
        payments=[dict(method="Cash", amount=1)],
    )
    response = client.post("/api/pos/sales", json=payload)
    assert response.status_code == 200, response.json
    with app.app_context():
        sale = Sale.query.one()
        item_id = sale.items[0].id
    response = client.post(
        f"/sales/{sale.id}/refund", json={"items": [{"item_id": item_id, "quantity": 2}]}
    )
    assert response.status_code in (200, 302), response.data
    with app.app_context():
        item = Sale.query.one().items[0]
        assert item.quantity == 1 and item.discount <= item.price


def test_voided_invoice_cannot_ship(app, client):
    assert client.post("/api/pos/sales", json=delivery_invoice()).status_code == 200
    with app.app_context():
        oid = ShippingOrder.query.one().id
    assert client.post("/sales/1/delete", data={"cancel_reason": "Customer Request"}).status_code == 302
    response = client.post(f"/api/shipping/{oid}/status", json={"status": "Packed"})
    assert response.status_code == 400
    assert "voided" in response.json["error"]
    cancel = {"status": "Cancelled", "cancel_reason": "Customer Request"}
    assert client.post(f"/api/shipping/{oid}/status", json=cancel).status_code == 200


def test_ship_dialog_ships_with_existing_tracking_code(app, client):
    assert client.post("/api/pos/sales", json=delivery_invoice()).status_code == 200
    with app.app_context():
        oid = ShippingOrder.query.one().id
    assert client.post(f"/api/shipping/{oid}", json={"tracking_code": "TRK123456"}).status_code == 200
    for target in ("Packed", "Ready For Shipment"):
        assert client.post(f"/api/shipping/{oid}/status", json={"status": target}).status_code == 200
    response = client.post(f"/api/shipping/{oid}", json={"tracking_code": "TRK123456", "ship": True})
    assert response.status_code == 200, response.json
    with app.app_context():
        assert db.session.get(ShippingOrder, oid).status == "Shipped"


def test_closed_shipments_and_required_address_fields_are_protected(app, client):
    assert client.post("/api/pos/sales", json=delivery_invoice()).status_code == 200
    with app.app_context():
        oid = ShippingOrder.query.one().id
    assert client.post(f"/api/shipping/{oid}", json={"city": "  "}).status_code == 400
    cancel = {"status": "Cancelled", "cancel_reason": "Customer Request"}
    assert client.post(f"/api/shipping/{oid}/status", json=cancel).status_code == 200
    assert client.post(f"/api/shipping/{oid}", json={"courier": "Aramex"}).status_code == 400


def test_delivered_time_is_store_local(app, client):
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    assert client.post("/api/pos/sales", json=delivery_invoice()).status_code == 200
    with app.app_context():
        oid = ShippingOrder.query.one().id
    assert client.post(f"/api/shipping/{oid}", json={"tracking_code": "TRK999999"}).status_code == 200
    for target in ("Packed", "Ready For Shipment", "Shipped", "Out For Delivery"):
        assert client.post(f"/api/shipping/{oid}/status", json={"status": target}).status_code == 200
    local = datetime.now(ZoneInfo("Africa/Cairo")) - timedelta(minutes=10)
    response = client.post(
        f"/api/shipping/{oid}/status",
        json={
            "status": "Delivered",
            "delivered_by": "Courier",
            "delivered_date": local.strftime("%Y-%m-%d"),
            "delivered_time": local.strftime("%H:%M"),
        },
    )
    assert response.status_code == 200, response.json
    with app.app_context():
        stored = db.session.get(ShippingOrder, oid).delivered_at
    expected = local.astimezone(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    assert stored == expected


def test_product_edit_does_not_revert_concurrent_stock_change(app, client):
    form = {
        "name": "Test Product",
        "sku": "TEST-001",
        "category_id": "1",
        "cost": "50",
        "price": "100",
        "minimum": "5",
        "current_stock": "10",
        "stock_baseline": "10",
    }
    with app.app_context():
        db.session.get(Product, 1).stock = 7
        db.session.commit()
    assert client.post("/products/1/edit", data=form).status_code == 302
    with app.app_context():
        assert db.session.get(Product, 1).stock == 7
    assert client.post("/products/1/edit", data=form | {"current_stock": "12"}).status_code == 400
    form |= {"current_stock": "12", "stock_baseline": "7"}
    assert client.post("/products/1/edit", data=form).status_code == 302
    with app.app_context():
        assert db.session.get(Product, 1).stock == 12


def test_csv_import_only_updates_present_columns(app, client):
    csv = "Name,SKU,Selling Price\nRenamed,TEST-001,120\nNew A,NEW-A,5\nNew B,NEW-B,6\n"
    data = {"file": (io.BytesIO(csv.encode()), "products.csv")}
    client.post("/products/import/csv", data=data, content_type="multipart/form-data")
    with app.app_context():
        p = db.session.get(Product, 1)
        assert (p.name, p.price, p.cost, p.stock, p.minimum, p.barcode) == (
            "Renamed", 12000, 5000, 10, 5, "12345678"
        )
        assert Product.query.filter(Product.sku.in_(["NEW-A", "NEW-B"])).count() == 2
    csv = "Name,SKU,Selling Price,Stock Units\nRenamed,TEST-001,120,4\n"
    data = {"file": (io.BytesIO(csv.encode()), "products.csv")}
    client.post("/products/import/csv", data=data, content_type="multipart/form-data")
    with app.app_context():
        assert db.session.get(Product, 1).stock == 4
        assert InventoryMovement.query.filter_by(product_id=1, reference="CSV import").count() == 1


def test_http_errors_keep_their_status(client):
    assert client.get("/products/1/delete").status_code == 405


def test_inventory_panels_list_low_stock_products(app, client):
    with app.app_context():
        db.session.get(Product, 1).stock = 2
        db.session.commit()
    html = client.get("/inventory").data.decode()
    assert "No low stock products." not in html


def test_adjust_page_exposes_barcodes(client):
    assert '"barcode": "12345678"' in client.get("/inventory/adjust").data.decode()
