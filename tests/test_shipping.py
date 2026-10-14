"""Delivery/shipping regression checks; every test uses an isolated database."""

import sqlite3
from contextlib import closing
from pathlib import Path

from test_app import app, client  # noqa: F401
from models import (
    Customer,
    Sale,
    ShippingEvent,
    ShippingOrder,
    db,
)


def invoice(**changes):
    data = dict(
        token="d" * 48,
        items=[dict(product_id=1, quantity=1, discount=0, unit_price=10000)],
        invoice_discount=0,
        customer_id=1,
        note="",
        tax_rate=1400,
        currency="EGP",
        payments=None,
        fulfillment={
            "method": "delivery",
            "address": {
                "customer_name": "Test Customer",
                "phone": "+201001234567",
                "alt_phone": "",
                "governorate": "Cairo",
                "city": "Nasr City",
                "district": "District 1",
                "landmark": "Near City Stars",
                "street": "123 Main St",
                "building": "4",
                "floor": "2",
                "apartment": "5",
                "postal_code": "12345",
                "notes": "Ring twice",
            },
            "courier": "Bosta",
            "shipping_cost": 5000,
            "update_profile": True,
        },
    )
    data.update(changes)
    if data["payments"] is None:
        # Products 100.00 + 14% VAT = 114.00, plus the billed shipping fee (no VAT).
        f = data["fulfillment"]
        fee = f.get("shipping_cost", 0) if isinstance(f, dict) and f.get("method") == "delivery" else 0
        data["payments"] = [dict(method="Cash", amount=11400 + fee)]
    return data


def test_delivery_sale_creates_shipping_order(app, client):
    assert client.post("/api/pos/sales", json=invoice()).status_code == 200
    with app.app_context():
        order = ShippingOrder.query.one()
        assert order.order_number.startswith("SHP-")
        assert not order.tracking_code
        assert order.status == "Pending"
        assert order.city == "Nasr City" and order.courier == "Bosta"
        assert order.shipping_cost == 5000
        assert order.landmark == "Near City Stars"
        assert order.sale.invoice.startswith("INV")
        assert [e.action for e in order.events] == ["Order Created"]
        customer = db.session.get(Customer, 1)
        assert customer.phone == "+201001234567"
        assert "Nasr City" in customer.address


def test_compact_delivery_payload_with_landmark(app, client):
    """Frontend compact form sends landmark + empty legacy fields."""
    data = invoice()
    data["token"] = "e" * 48
    data["fulfillment"]["address"] = {
        "customer_name": "Test Customer",
        "phone": "+201001234567",
        "alt_phone": "",
        "governorate": "Cairo",
        "city": "Nasr City",
        "district": "",
        "landmark": "Near City Stars",
        "street": "12 Mossadak St",
        "building": "",
        "floor": "",
        "apartment": "",
        "postal_code": "",
        "notes": "",
    }
    assert client.post("/api/pos/sales", json=data).status_code == 200
    with app.app_context():
        order = ShippingOrder.query.one()
        assert order.landmark == "Near City Stars"
        assert order.street == "12 Mossadak St"


def test_pickup_sale_creates_no_shipping_order(app, client):
    data = invoice(
        fulfillment={
            "method": "pickup",
            "pickup_date": "2026-09-30",
            "pickup_notes": "After 5pm",
        }
    )
    assert client.post("/api/pos/sales", json=data).status_code == 200
    with app.app_context():
        assert ShippingOrder.query.count() == 0
        sale = Sale.query.one()
        assert sale.pickup_date == "2026-09-30" and sale.pickup_notes == "After 5pm"


def test_invalid_fulfillment_is_atomic(app, client):
    bad_phone = invoice()
    bad_phone["fulfillment"]["address"]["phone"] = "abc"
    assert client.post("/api/pos/sales", json=bad_phone).status_code == 400
    bad_cost = invoice()
    bad_cost["fulfillment"]["shipping_cost"] = -5
    assert client.post("/api/pos/sales", json=bad_cost).status_code == 400
    with app.app_context():
        assert Sale.query.count() == 0 and ShippingOrder.query.count() == 0


def test_status_flow_and_timeline(app, client):
    client.post("/api/pos/sales", json=invoice())
    with app.app_context():
        oid = ShippingOrder.query.one().id
    assert (
        client.post(
            f"/api/shipping/{oid}/status", json={"status": "Shipped"}
        ).status_code
        == 400
    )
    for target in ["Packed", "Ready For Shipment"]:
        response = client.post(f"/api/shipping/{oid}/status", json={"status": target})
        assert response.status_code == 200, response.json
    assert (
        client.post(
            f"/api/shipping/{oid}/status",
            json={"status": "Shipped", "tracking_code": "MANUAL-1"},
        ).status_code
        == 200
    )
    with app.app_context():
        assert db.session.get(ShippingOrder, oid).tracking_code == "MANUAL-1"
    assert (
        client.post(f"/api/shipping/{oid}/status", json={"status": "Out For Delivery"}).status_code
        == 200
    )
    assert (
        client.post(f"/api/shipping/{oid}/status", json={"status": "Packed"}).status_code
        == 400
    )
    from datetime import datetime, timedelta

    past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert (
        client.post(
            f"/api/shipping/{oid}/status",
            json={
                "status": "Delivered",
                "delivered_by": "Karim",
                "delivered_date": past,
                "delivered_time": "14:30",
            },
        ).status_code
        == 200
    )
    with app.app_context():
        order = db.session.get(ShippingOrder, oid)
        assert order.status == "Delivered" and order.delivered_by == "Karim"
        actions = [e.action for e in order.events]
        assert actions == [
            "Order Created",
            "Packed",
            "Ready For Shipment",
            "Tracking code added",
            "Shipped",
            "Out For Delivery",
            "Delivered",
        ]
        assert all(e.actor for e in order.events)


def test_shipped_requires_tracking_code(app, client):
    """Tracking codes come from the courier — never generated, never at creation."""
    client.post("/api/pos/sales", json=invoice())
    with app.app_context():
        oid = ShippingOrder.query.one().id
        assert ShippingOrder.query.one().tracking_code is None
    assert (
        client.post(
            f"/api/shipping/{oid}/status", json={"status": "Packed"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/shipping/{oid}/status", json={"status": "Ready For Shipment"}
        ).status_code
        == 200
    )
    missing = client.post(f"/api/shipping/{oid}/status", json={"status": "Shipped"})
    assert missing.status_code == 400
    assert "tracking code" in missing.json["error"].lower()
    generated = client.post(
        f"/api/shipping/{oid}/status",
        json={"status": "Shipped", "generate_tracking": True},
    )
    assert generated.status_code == 400
    assert "courier" in generated.json["error"].lower()
    manual = client.post(
        f"/api/shipping/{oid}/status",
        json={"status": "Shipped", "tracking_code": "BOSTA-123"},
    )
    assert manual.status_code == 200, manual.json
    with app.app_context():
        assert db.session.get(ShippingOrder, oid).tracking_code == "BOSTA-123"
    # Manual codes must stay unique across orders.
    client.post("/api/pos/sales", json=invoice(token="f" * 48))
    with app.app_context():
        oid2 = ShippingOrder.query.order_by(ShippingOrder.id.desc()).first().id
    client.post(f"/api/shipping/{oid2}/status", json={"status": "Packed"})
    client.post(f"/api/shipping/{oid2}/status", json={"status": "Ready For Shipment"})
    dup = client.post(
        f"/api/shipping/{oid2}/status",
        json={"status": "Shipped", "tracking_code": "bosta-123"},
    )
    assert dup.status_code == 400
    assert "already used" in dup.json["error"]


def test_tracking_save_auto_ships_ready_order(app, client):
    """Entering a courier code on a Ready order moves it to Shipped."""
    client.post("/api/pos/sales", json=invoice())
    with app.app_context():
        oid = ShippingOrder.query.one().id
    assert (
        client.post(
            f"/api/shipping/{oid}/status", json={"status": "Packed"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/shipping/{oid}/status", json={"status": "Ready For Shipment"}
        ).status_code
        == 200
    )
    response = client.post(
        f"/api/shipping/{oid}",
        json={
            "courier": "Bosta",
            "tracking_code": "BST-987",
            "tracking_url": "https://tracking.bosta.co/BST-987",
        },
    )
    assert response.status_code == 200, response.json
    assert "status Shipped" in response.json["changed"]
    assert response.json["order"]["status"] == "Shipped"
    assert response.json["order"]["tracking_url"] == "https://tracking.bosta.co/BST-987"
    assert response.json["transitions"] == ["Out For Delivery", "Cancelled"]
    with app.app_context():
        order = db.session.get(ShippingOrder, oid)
        assert order.status == "Shipped" and order.tracking_code == "BST-987"
        assert [e.action for e in order.events].count("Tracking code added") == 1
    bad_url = client.post(
        f"/api/shipping/{oid}", json={"tracking_url": "not-a-url"}
    )
    assert bad_url.status_code == 400


def test_delivered_shipments_are_locked(app, client):
    client.post("/api/pos/sales", json=invoice())
    with app.app_context():
        oid = ShippingOrder.query.one().id
    client.post(f"/api/shipping/{oid}/status", json={"status": "Packed"})
    client.post(f"/api/shipping/{oid}/status", json={"status": "Ready For Shipment"})
    client.post(
        f"/api/shipping/{oid}",
        json={"tracking_code": "BST-1", "tracking_url": ""},
    )
    from datetime import datetime, timedelta

    past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    client.post(f"/api/shipping/{oid}/status", json={"status": "Out For Delivery"})
    assert (
        client.post(
            f"/api/shipping/{oid}/status",
            json={
                "status": "Delivered",
                "delivered_by": "Karim",
                "delivered_date": past,
                "delivered_time": "14:30",
            },
        ).status_code
        == 200
    )
    locked = client.post(f"/api/shipping/{oid}", json={"courier": "Aramex"})
    assert locked.status_code == 400
    assert "locked" in locked.json["error"].lower()


def test_tracking_update_and_last_address(app, client):
    free = invoice()
    free["fulfillment"]["shipping_cost"] = 0  # free delivery: nothing billed, cost may be recorded later
    free["payments"] = [dict(method="Cash", amount=11400)]
    assert client.post("/api/pos/sales", json=free).status_code == 200
    with app.app_context():
        oid = ShippingOrder.query.one().id
    response = client.post(
        f"/api/shipping/{oid}",
        json={"courier": "Aramex", "tracking_code": "ABC123", "shipping_cost": 6000},
    )
    assert response.status_code == 200, response.json
    with app.app_context():
        order = db.session.get(ShippingOrder, oid)
        assert order.courier == "Aramex" and order.tracking_code == "ABC123"
        assert order.shipping_cost == 6000
        assert "Tracking code added" in [e.action for e in order.events]
    last = client.get("/api/shipping/last-address?customer_id=1").json
    assert last["address"]["city"] == "Nasr City"
    assert last["address"]["landmark"] == "Near City Stars"
    assert client.get("/api/shipping/last-address?customer_id=999").json == {
        "address": None
    }


def test_shipping_pages_filters_reports_dashboard(app, client):
    new_sale = client.get("/sales/new")
    assert new_sale.status_code == 200
    assert b"Delivery &amp; Fulfillment" in new_sale.data
    assert b"fulfill-method" in new_sale.data and b"ship-name" in new_sale.data
    # compact segmented redesign: summary pill, fee badge, landmark replace legacy fields
    for token in (
        b"pos-segmented",
        b"pos-compact-grid",
        b"pos-fulfill-customer-grid",
        b"fulfill-summary",
        b"ship-fee-badge",
        b"ship-landmark",
        b"Recipient Name",
        b"Full Address",
        b"Landmark",
        b"Shipping Fee",
        b"Courier Company",
    ):
        assert token in new_sale.data, token
    for legacy in (b"ship-alt", b"ship-district", b"ship-building", b"ship-floor", b"ship-apt", b"ship-postal", b"ship-notes"):
        assert legacy not in new_sale.data, legacy
    assert b'href="/orders"' in client.get("/").data
    assert client.post("/api/pos/sales", json=invoice()).status_code == 200
    for url in ["/shipping", "/shipping?status=Pending", "/shipping?city=Nasr+City"]:
        page = client.get(url)
        assert page.status_code == 200 and b"SHP-" in page.data
    with app.app_context():
        oid = ShippingOrder.query.one().id
    page = client.get(f"/shipping/{oid}")
    assert page.status_code == 200 and b"Timeline" in page.data
    assert b"Not assigned yet" in page.data
    assert "Not Assigned Yet".encode() not in page.data
    assert "\u2014".encode() not in page.data
    assert b"Mark Packed" in page.data
    assert b"ship-steps" in page.data and b"ship-modal" in page.data
    for token in (
        b"Shipping Order",
        b"ship-info-strip",
        b"ship-info-grid",
        b"courier-edit-toggle",
        b"data-sale-modal",
        b"data-business-modal",
        b"js/modal-manager.js",
        b"Discount",
    ):
        assert token in page.data, token
    dashboard = client.get("/")
    assert b"Business Overview" in dashboard.data
    assert b"Shipping Operations" in dashboard.data and b"Packed" in dashboard.data
    assert b"Inventory Health" in dashboard.data and b"Recent Activity" in dashboard.data
    assert b"12 Months" in dashboard.data and b"Compared to yesterday" in dashboard.data
    alerts = client.get("/notifications")
    assert alerts.status_code == 200 and b"SHP-" in alerts.data
    report = client.get("/reports?kind=shipping")
    assert report.status_code == 200 and b"Delivery Success Rate" in report.data
    export = client.get("/reports/export/xlsx?kind=shipping")
    assert export.status_code == 200


def test_dashboard_control_center(app, client):
    assert client.post("/api/pos/sales", json=invoice()).status_code == 200
    page = client.get("/").data
    for token in [
        b"Business Overview",
        b"Sales Today",
        b"Profit Today",
        b"Expenses Today",
        b"Purchases Today",
        b"New Sale",
        b"New Product",
        b"Receive Stock",
        b"New Purchase",
        b"New Customer",
        b"Shipping Order",
        b"Inventory Health",
        b"Low Stock",
        b"Out of Stock",
        b"Shipping Operations",
        b"Packed",
        b"Notifications",
        b"Recent Activity",
        b"Analytics",
        b"Top Selling Products",
        b"View All",
    ]:
        assert token in page, token
    assert b"Total Categories" not in page
    assert b"Manage product categories" not in page
    # activity feed shows the sale + shipping creation
    assert b"Create shipping order" in page or b"Save POS invoice" in page
    # ops board counts the pending order
    assert b"/shipping?status=Pending" in page


def test_landmark_migration_repairs_pre_landmark_db(app, tmp_path):
    """A DB that is current per the old guard but lacks landmark must heal."""
    from services.migrations import SCHEMA_VERSION, upgrade_sqlite

    path = tmp_path / "pre-landmark.db"
    with app.app_context():
        src = sqlite3.connect(db.engine.url.database)
        with closing(sqlite3.connect(path)) as dst:
            src.backup(dst)
        src.close()
    with closing(sqlite3.connect(path)) as c:
        c.execute("ALTER TABLE shipping_orders DROP COLUMN landmark")
        c.execute("PRAGMA user_version = 0")
        c.commit()
        assert (
            "landmark"
            not in {r[1] for r in c.execute("PRAGMA table_info(shipping_orders)")}
        )
    upgrade_sqlite(path, backup=True)
    upgrade_sqlite(path, backup=True)  # second run must be a no-op
    with closing(sqlite3.connect(path)) as c:
        assert (
            "landmark"
            in {r[1] for r in c.execute("PRAGMA table_info(shipping_orders)")}
        )
        assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert len(list(tmp_path.glob("pre-*.sqlite3"))) == 1


def test_shipping_permissions(client):
    client.post("/logout")
    client.post(
        "/login", data={"username": "cashier", "password": "test-password-123"}
    )
    assert client.get("/shipping").status_code == 200
    assert client.post("/api/pos/sales", json=invoice()).status_code == 200
    with client.application.app_context():
        from models import ShippingOrder as SO

        oid = SO.query.one().id
    assert (
        client.post(f"/api/shipping/{oid}/status", json={"status": "Packed"}).status_code
        == 403
    )
    assert client.get("/reports?kind=shipping").status_code == 403


def test_interactive_table_markup(app, client):
    assert client.post("/api/pos/sales", json=invoice()).status_code == 200
    html = client.get("/shipping").data.decode()
    with app.app_context():
        oid = ShippingOrder.query.one().id
    for token in (
        'data-ship-view="1"',
        'data-sale-modal="1"',
        'data-ship-customer="1"',
        'data-ship-status="1"',
        'data-transitions="Packed|Cancelled"',
        "data-row-menu-trigger",
        "data-ship-menu-view",
        "data-ship-menu-status",
        "data-ship-menu-copy",
        "View Shipment",
        "Edit Shipment",
        "Update Status",
        "Copy Tracking Code",
        "Print Shipping Label",
        "Print Invoice",
        "js/row-menu.js",
        "js/sale-modal.js",
        "js/shipment-modal.js",
        "js/shipping-index.js",
        "css/shipment-modal.css",
        "shipmentModal",
        "shipCustomerModal",
        "shipDeliverModal",
        "ship-table-count",
        "shipmentModalSteps",
        "shipmentModalRows",
        "shipmentModalSummary",
        "shipmentModalPrev",
        "shipmentModalCourierEdit",
        "shipmentModalInfoEdit",
        "shipmentModalAddressEdit",
        "shipmentModalOpenInvoice",
        "shipmentModalOpenSummary",
        "shipmentEditModal",
        "shipmentAddressModal",
        "shipmentEditTracking",
        "shipmentAddrStreet",
        "sm-foot-actions",
        "sm-progress",
        "Products (From Invoice)",
        "Invoice Summary",
        "Not assigned yet",
    ):
        assert token in html, token
    # No tracking yet: copy button is replaced by the empty state.
    assert 'data-copy-tracking="' not in html
    with app.app_context():
        order = ShippingOrder.query.one()
        order.tracking_code = "TRK-123"
        db.session.commit()
    html = client.get("/shipping").data.decode()
    assert 'data-copy-tracking="TRK-123"' in html
    assert ">TRK-123</code>" in html
    # Pending orders cannot be marked delivered: item renders conditionally.
    assert "data-ship-menu-deliver" not in html
    assert f"/shipping/{oid}/label" in html
    assert "Actions</a>" not in html
    # Menus are floating overlays: sources stay hidden, nothing renders inline.
    assert '<div class="row-menu-items" hidden>' in html
    assert "row-floating-menu" not in html.split("<tbody>")[1].split("</tbody>")[0]


def test_floating_menus_are_global_and_absolute():
    """Row/status menus must not depend on per-page CSS (the inline-menu bug)."""
    import re
    from pathlib import Path

    block = re.search(
        r"\.row-floating-menu\s*\{(.*?)\}",
        Path("static/css/app.css").read_text(),
        re.S,
    ).group(1)
    assert "position: absolute" in block and "z-index: 9999" in block
    status = re.search(
        r"\.ship-status-menu\s*\{(.*?)\}",
        Path("static/css/shipping.css").read_text(),
        re.S,
    ).group(1)
    assert "position: absolute" in status and "z-index: 9999" in status
    assert "row-floating-menu" not in Path("static/css/price-history.css").read_text()


def test_order_detail_and_customer_api(app, client):
    assert client.post("/api/pos/sales", json=invoice()).status_code == 200
    with app.app_context():
        oid = ShippingOrder.query.one().id
    data = client.get(f"/api/shipping/{oid}").json
    assert data["order"]["order_number"].startswith("SHP-")
    assert data["order"]["sale_id"] == 1
    assert data["address"]["city"] == "Nasr City"
    assert "Nasr City" in data["address_lines"]
    assert data["items"] and data["items"][0]["name"] == "Test Product"
    (event,) = data["events"]
    assert event["action"] == "Order Created" and event["actor"]
    assert data["transitions"] == ["Packed", "Cancelled"]
    assert data["order"]["tracking_code"] == ""
    assert client.get("/api/shipping/9999").status_code == 404
    customer = client.get(f"/api/shipping/{oid}/customer").json
    assert customer["profile"]["name"] == "Customer"
    assert customer["profile"]["phone"] == "+201001234567"
    assert customer["stats"] == {"shipments": 1, "delivered": 0, "open": 1}
    assert client.get("/shipping/1/label").status_code == 200


def test_delete_shipment_guards(app, client):
    assert client.post("/api/pos/sales", json=invoice()).status_code == 200
    with app.app_context():
        oid = ShippingOrder.query.one().id
    assert client.delete(f"/api/shipping/{oid}").status_code == 200
    with app.app_context():
        assert ShippingOrder.query.count() == 0
    assert client.post("/api/pos/sales", json=invoice(token="e" * 48)).status_code == 200
    with app.app_context():
        oid = ShippingOrder.query.one().id
    assert client.post(f"/api/shipping/{oid}/status", json={"status": "Packed"}).status_code == 200
    assert client.post(f"/api/shipping/{oid}/status", json={"status": "Ready For Shipment"}).status_code == 200
    blocked = client.delete(f"/api/shipping/{oid}")
    assert blocked.status_code == 400
    assert "Pending" in blocked.json["error"]
    with app.app_context():
        assert ShippingOrder.query.count() == 1


def test_shipment_modal_viewport_fit():
    """Modal fits viewport (scroll only when genuinely exceeding), content-
    driven cards, 4-col info grid, fluid products table, single Current Stage."""
    from pathlib import Path

    css = Path("static/css/shipment-modal.css").read_text(encoding="utf-8")
    for token in (
        "max-height: calc(100vh - 32px)",
        "height: auto",
        "min-height: 0",
        "minmax(120px, 150px) minmax(180px, 1fr)",
        "display: contents",
        "repeat(12, minmax(0, 1fr))",
        "grid-column: span 8",
        "grid-column: span 4",
        "align-items: start",
        "justify-content: space-between",
        "overflow-y: auto",
        "white-space: nowrap",
        "word-break: normal",
    ):
        assert token in css, token
    for banned in (
        "min-width: 620px",
        "height: fit-content",
        "height: 100%",
        "transform: scale(",
        "word-break: break-all",
    ):
        assert banned not in css, banned
    for token in (
        ".sm-pairs",
        "minmax(110px, 150px) minmax(0, 1fr)",
        "gap: 14px 20px",
        "align-self: start",
        "width: 56px",
        "text-align: end",
    ):
        assert token in css, token
    js = Path("static/js/shipment-modal.js").read_text(encoding="utf-8")
    assert js.count('textContent = "Current Stage"') == 1
    assert 'openExclusive("saleDetailsModal"' in js  # invoice opens via manager


def test_tracking_code_synchronized_everywhere(app, client):
    """One state per field: TRK-123 in strip, courier card, table, modal."""
    client.post("/api/pos/sales", json=invoice())
    with app.app_context():
        oid = ShippingOrder.query.one().id
    client.post(f"/api/shipping/{oid}/status", json={"status": "Packed"})
    client.post(f"/api/shipping/{oid}/status", json={"status": "Ready For Shipment"})
    client.post(f"/api/shipping/{oid}", json={"tracking_code": "TRK-123"})
    page = client.get(f"/shipping/{oid}").data.decode()
    assert page.count("TRK-123") >= 2  # strip + courier card
    assert 'id="ship-tracking-view">TRK-123</code>' in page
    assert "<code>TRK-123</code>" in page
    assert 'ship-tracking-view">Not assigned yet' not in page
    table = client.get("/shipping").data.decode()
    assert "TRK-123" in table
    assert "Not assigned yet" not in table.split("<tbody>")[1].split("</tbody>")[0]
    data = client.get(f"/api/shipping/{oid}").json
    assert data["order"]["tracking_code"] == "TRK-123"


def test_missing_tracking_code_everywhere(app, client):
    """Null tracking renders as 'Not assigned yet' on every surface."""
    client.post("/api/pos/sales", json=invoice())
    with app.app_context():
        oid = ShippingOrder.query.one().id
    page = client.get(f"/shipping/{oid}").data.decode()
    assert "Not assigned yet" in page
    assert "TRK-" not in page
    table = client.get("/shipping").data.decode()
    assert "Not assigned yet" in table
    data = client.get(f"/api/shipping/{oid}").json
    assert data["order"]["tracking_code"] == ""


def test_shipping_interactive_permissions(app, client):
    assert client.post("/api/pos/sales", json=invoice()).status_code == 200
    with app.app_context():
        oid = ShippingOrder.query.one().id
    client.post("/logout")
    assert client.get(f"/api/shipping/{oid}").status_code == 401
    assert client.delete(f"/api/shipping/{oid}").status_code == 401
    client.post(
        "/login", data={"username": "cashier", "password": "test-password-123"}
    )
    assert client.get(f"/api/shipping/{oid}").status_code == 200
    assert client.delete(f"/api/shipping/{oid}").status_code == 403


def test_case_d_ship_flow_updates_dashboard(app, client):
    """CASE D: manual ship updates timeline, table source and dashboard."""
    client.post("/api/pos/sales", json=invoice())
    with app.app_context():
        oid = ShippingOrder.query.one().id
    client.post(f"/api/shipping/{oid}/status", json={"status": "Packed"})
    client.post(f"/api/shipping/{oid}/status", json={"status": "Ready For Shipment"})
    response = client.post(
        f"/api/shipping/{oid}",
        json={
            "courier": "Aramex",
            "tracking_code": "ARX-555",
            "tracking_url": "https://track.aramex.com/ARX-555",
            "shipment_date": "2026-09-23",
        },
    )
    assert response.status_code == 200, response.json
    assert response.json["order"]["status"] == "Shipped"
    assert response.json["order"]["tracking_url"] == "https://track.aramex.com/ARX-555"
    with app.app_context():
        events = [e.action for e in ShippingOrder.query.one().events]
        assert "Tracking code added" in events
        assert events[-1] == "Shipped"
    dashboard = client.get("/").data.decode()
    assert "Shipping Operations" in dashboard
    assert "Shipped" in dashboard


def test_case_e_invoice_switching_wired(app, client):
    """CASE E: shipment modal carries the linked sale id; sale modal opens
    exclusively via the shared manager (no stacking)."""
    client.post("/api/pos/sales", json=invoice())
    with app.app_context():
        order = ShippingOrder.query.one()
        oid, sale_id = order.id, order.sale_id
    data = client.get(f"/api/shipping/{oid}").json
    assert data["order"]["sale_id"] == sale_id
    assert data["order"]["invoice"].startswith("INV-")
    with app.app_context():
        sale = db.session.get(Sale, sale_id)
        assert sale is not None
        assert data["order"]["invoice"] == sale.invoice
        assert data["order"]["customer"] == sale.customer_name
        assert data["order"]["total"] == sale.total
        assert data["items"] and all(
            item["name"] == row.name and item["quantity"] == row.quantity
            for item, row in zip(data["items"], sale.items)
        )
    js = Path("static/js/sale-modal.js").read_text(encoding="utf-8")
    assert 'openExclusive("saleDetailsModal"' in js
    manager = Path("static/js/modal-manager.js").read_text(encoding="utf-8")
    assert "hidden.bs.modal" in manager and "activeModal" in manager


def test_case_f_tracking_edit_syncs_surfaces(app, client):
    """CASE F: changing a code updates timeline and every surface at once."""
    client.post("/api/pos/sales", json=invoice())
    with app.app_context():
        oid = ShippingOrder.query.one().id
    client.post(f"/api/shipping/{oid}/status", json={"status": "Packed"})
    client.post(f"/api/shipping/{oid}/status", json={"status": "Ready For Shipment"})
    client.post(f"/api/shipping/{oid}", json={"tracking_code": "FIRST-1"})
    second = client.post(f"/api/shipping/{oid}", json={"tracking_code": "SECOND-2"})
    assert second.status_code == 200, second.json
    with app.app_context():
        actions = [e.action for e in ShippingOrder.query.one().events]
        assert "Tracking code added" in actions
        assert "Tracking code updated" in actions
    page = client.get(f"/shipping/{oid}").data.decode()
    assert page.count("SECOND-2") >= 2
    assert "FIRST-1" not in page
    table = client.get("/shipping").data.decode()
    assert "SECOND-2" in table
    assert "FIRST-1" not in table.split("<tbody>")[1].split("</tbody>")[0]


def test_address_edit_updates_destination_only(app, client):
    """Delivery Address edit changes shipment destination, never invoice data."""
    client.post("/api/pos/sales", json=invoice())
    with app.app_context():
        order = ShippingOrder.query.one()
        oid, sale_id = order.id, order.sale_id
    response = client.post(
        f"/api/shipping/{oid}",
        json={
            "city": "Giza",
            "street": "99 New St",
            "landmark": "Near Mall",
            "postal_code": "99999",
        },
    )
    assert response.status_code == 200, response.json
    assert "delivery address" in response.json["changed"]
    with app.app_context():
        order = db.session.get(ShippingOrder, oid)
        assert (order.city, order.street) == ("Giza", "99 New St")
        sale = db.session.get(Sale, sale_id)
        assert sale.customer_name == "Customer"
    data = client.get(f"/api/shipping/{oid}").json
    assert data["address"]["city"] == "Giza"
    bad = client.post(f"/api/shipping/{oid}", json={"city": 123})
    assert bad.status_code == 400
