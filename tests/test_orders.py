"""Orders hub: tabs, counters, pickup/cancelled/returns derived views."""

from test_app import app, client  # noqa: F401
from models import Sale, ShippingOrder, db


def delivery_invoice(**changes):
    data = dict(
        token="d" * 48,
        items=[dict(product_id=1, quantity=1, discount=0, unit_price=10000)],
        invoice_discount=0,
        customer_id=1,
        note="",
        tax_rate=1400,
        currency="EGP",
        payments=[dict(method="Cash", amount=11400)],
        fulfillment={
            "method": "delivery",
            "address": {
                "customer_name": "Test Customer",
                "phone": "+201001234567",
                "governorate": "Cairo",
                "city": "Nasr City",
                "street": "123 Main St",
            },
            "courier": "",
            "shipping_cost": 0,
        },
    )
    data.update(changes)
    return data


def pickup_invoice(**changes):
    data = delivery_invoice(**changes)
    data["fulfillment"] = {
        "method": "pickup",
        "pickup_date": "2026-09-30",
        "pickup_notes": "After 5pm",
    }
    return data


def test_hub_tabs_and_counters(client):
    html = client.get("/orders").data.decode()
    for token in (
        "Orders",
        "orders-counters",
        "orders-tabs",
        "Shipping Orders",
        "Pickup Orders",
        "Cancelled Orders",
        "Returns &amp; Refunds",
        "ship-table",
    ):
        assert token in html, token
    assert client.get("/orders?tab=bogus").data.decode().count("orders-tabs") == 1
    assert "/orders?tab=pickup" in html


def test_pickup_tab_lists_pickup_sales(app, client):
    assert client.post("/api/pos/sales", json=pickup_invoice(token="c" * 48)).status_code == 200
    assert client.post("/api/pos/sales", json=delivery_invoice(token="e" * 48)).status_code == 200
    with app.app_context():
        from models import Sale as _Sale

        assert _Sale.query.filter_by(invoice="INV-1001").one().pickup_status == "Pending Pickup"
    html = client.get("/orders?tab=pickup").data.decode()
    assert "Pending Pickup" in html
    assert "INV-1001" in html and "INV-1002" not in html
    assert "Pickup Date" in html
    assert 'data-customer-profile="1"' in html
    assert client.get("/orders?tab=pickup&pickup_status=Ready+For+Pickup").data.decode().count("INV-1001") == 0


def test_cancelled_tab_lists_voids_and_cancelled(app, client):
    assert client.post("/api/pos/sales", json=delivery_invoice()).status_code == 200
    with app.app_context():
        oid = ShippingOrder.query.one().id
    assert client.post("/sales/1/delete", data={"cancel_reason": "Customer Request"}).status_code == 302
    assert client.post(f"/api/shipping/{oid}/status", json={"status": "Cancelled", "cancel_reason": "Customer Request"}).status_code == 200
    html = client.get("/orders?tab=cancelled").data.decode()
    assert "Cancelled Orders" in html
    assert "Voided" in html and "Cancelled" in html
    assert html.count("Customer Request") >= 2  # void reason + shipping reason
    assert 'data-ship-view="1"' in html
    assert 'data-customer-profile="1"' in html


def test_returns_tab_lists_returned_and_refunded(app, client):
    assert client.post("/api/pos/sales", json=delivery_invoice()).status_code == 200
    with app.app_context():
        oid = ShippingOrder.query.one().id
    assert client.post("/sales/1/refund").status_code == 302
    assert client.post("/api/pos/sales", json=delivery_invoice(token="f" * 48)).status_code == 200
    with app.app_context():
        oid2 = ShippingOrder.query.order_by(ShippingOrder.id.desc()).first().id
    for target in ["Packed", "Ready For Shipment"]:
        assert client.post(f"/api/shipping/{oid2}/status", json={"status": target}).status_code == 200
    assert client.post(
        f"/api/shipping/{oid2}/status",
        json={"status": "Shipped", "tracking_code": "RET-1"},
    ).status_code == 200
    assert client.post(
        f"/api/shipping/{oid2}/status", json={"status": "Out For Delivery"}
    ).status_code == 200
    assert client.post(
        f"/api/shipping/{oid2}/status", json={"status": "Returned"}
    ).status_code == 200
    html = client.get("/orders?tab=returns").data.decode()
    assert "Returns &amp; Refunds" in html
    assert "Returned" in html and "Refunded" in html
    assert "RET-1" not in html  # tracking not shown here; statuses + amounts are
    assert "114.00" in html
    assert 'data-customer-profile="1"' in html


def test_sidebar_points_to_orders_hub(client):
    html = client.get("/").data.decode()
    assert 'href="/orders"' in html
    assert ">Orders<" in html
    assert client.get("/shipping").status_code == 200


def test_pickup_status_transitions(app, client):
    assert client.post("/api/pos/sales", json=pickup_invoice(token="c" * 48)).status_code == 200
    with app.app_context():
        from models import Sale as _Sale

        sid = _Sale.query.filter_by(invoice="INV-1001").one().id
    assert client.post(f"/api/sales/{sid}/pickup-status", json={"status": "Collected"}).status_code == 400
    response = client.post(f"/api/sales/{sid}/pickup-status", json={"status": "Ready For Pickup"})
    assert response.status_code == 200, response.json
    assert response.json == {"status": "Ready For Pickup", "transitions": ["Collected"]}
    html = client.get("/orders?tab=pickup").data.decode()
    assert "Ready For Pickup" in html
    assert client.post(f"/api/sales/{sid}/pickup-status", json={"status": "Collected"}).status_code == 200
    assert client.post("/logout").status_code in (200, 302)
    client.post("/login", data={"username": "cashier", "password": "test-password-123"})
    assert client.post(f"/api/sales/{sid}/pickup-status", json={"status": "Ready For Pickup"}).status_code == 403


def test_no_order_in_multiple_tabs(app, client):
    """Refunding a shipped order moves it shipping → returns exclusively."""
    assert client.post("/api/pos/sales", json=delivery_invoice()).status_code == 200
    with app.app_context():
        oid = ShippingOrder.query.one().id
    for target in ["Packed", "Ready For Shipment"]:
        assert client.post(f"/api/shipping/{oid}/status", json={"status": target}).status_code == 200
    assert "SHP-" in client.get("/orders?tab=shipping").data.decode()
    assert client.post("/sales/1/refund").status_code == 302
    shipping = client.get("/orders?tab=shipping").data.decode()
    assert "SHP-" not in shipping.split("<tbody>")[1].split("</tbody>")[0]
    returns = client.get("/orders?tab=returns").data.decode()
    assert "Refunded" in returns
    pickup = client.get("/orders?tab=pickup").data.decode()
    assert "INV-1001" not in pickup.split("<tbody>")[1].split("</tbody>")[0]
    cancelled = client.get("/orders?tab=cancelled").data.decode()
    assert "INV-1001" not in cancelled.split("<tbody>")[1].split("</tbody>")[0]


def test_void_moves_to_cancelled_with_date(app, client):
    assert client.post("/api/pos/sales", json=delivery_invoice()).status_code == 200
    assert client.post("/sales/1/delete", data={"cancel_reason": "Customer Request"}).status_code == 302
    with app.app_context():
        from models import Sale as _Sale

        sale = _Sale.query.one()
        assert sale.status == "Voided" and sale.cancelled_at is not None
    html = client.get("/orders?tab=cancelled").data.decode()
    assert "Voided" in html and "INV-1001" in html
    assert "Customer Request" in html  # recorded reason, not a placeholder
    shipping = client.get("/orders?tab=shipping").data.decode()
    assert "SHP-" not in shipping.split("<tbody>")[1].split("</tbody>")[0]


def test_customer_profile_endpoint(app, client):
    data = client.get("/api/customers/1/profile").json
    assert data["profile"]["name"] == "Customer"
    assert data["stats"] == {"shipments": 0, "delivered": 0, "open": 0}
    assert client.get("/api/customers/9999/profile").status_code == 404
    client.post("/logout")
    assert client.get("/api/customers/1/profile").status_code == 401
    client.post("/login", data={"username": "cashier", "password": "test-password-123"})
    assert client.get("/api/customers/1/profile").status_code == 200


def test_hub_permissions(client):
    client.post("/logout")
    assert client.get("/orders").status_code in (302, 401)
    client.post("/login", data={"username": "cashier", "password": "test-password-123"})
    assert client.get("/orders").status_code == 200
    assert client.get("/orders?tab=returns").status_code == 200


def test_cancel_reason_required_and_stored(app, client):
    assert client.post("/api/pos/sales", json=delivery_invoice()).status_code == 200
    with app.app_context():
        oid = ShippingOrder.query.one().id
    assert client.post(
        f"/api/shipping/{oid}/status", json={"status": "Cancelled"}
    ).status_code == 400
    response = client.post(
        f"/api/shipping/{oid}/status",
        json={"status": "Cancelled", "cancel_reason": "Courier Problem"},
    )
    assert response.status_code == 200, response.json
    with app.app_context():
        order = ShippingOrder.query.one()
        assert order.cancel_reason == "Courier Problem"
        assert order.cancelled_at is not None
        assert "Cancelled" in [e.action for e in order.events]
    html = client.get("/orders?tab=cancelled").data.decode()
    assert "Courier Problem" in html
    assert "cancel_reason" in html or "All Reasons" in html
    filtered = client.get("/orders?tab=cancelled&cancel_reason=Courier+Problem").data.decode()
    assert "SHP-" in filtered
    empty = client.get("/orders?tab=cancelled&cancel_reason=Wrong+Order").data.decode()
    assert "SHP-" not in empty.split("<tbody>")[1].split("</tbody>")[0]
    page = client.get(f"/shipping/{oid}").data.decode()
    assert "Courier Problem" in page
    assert "cancelled-reason-view" in page
    assert "cancelReasonModal" in page
    assert "cancel-reason.js" in page


def test_void_requires_reason(app, client):
    assert client.post("/api/pos/sales", json=delivery_invoice()).status_code == 200
    assert client.post("/sales/1/delete", data={}).status_code == 400
    assert client.post(
        "/sales/1/delete", data={"cancel_reason": "Duplicate Order"}
    ).status_code == 302
    with app.app_context():
        from models import Sale as _Sale

        sale = _Sale.query.one()
        assert sale.cancel_reason == "Duplicate Order"
        assert sale.cancelled_at is not None
    html = client.get("/orders?tab=cancelled").data.decode()
    assert "Duplicate Order" in html


def test_cancel_dialog_wired_on_all_surfaces(client):
    for url in ("/shipping", "/orders", "/orders?tab=pickup", "/sales"):
        html = client.get(url).data.decode()
        assert "cancelReasonModal" in html, url
        assert "cancel-reason.js" in html, url
        assert "cancel-reason-preset" in html, url
