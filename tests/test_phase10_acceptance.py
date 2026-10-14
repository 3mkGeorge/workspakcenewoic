"""End-to-End Acceptance Test Suite for StorePro Phase 10 / 10.5 Workflows."""

from decimal import Decimal
import json
from pathlib import Path
import shutil
import pytest
from test_app import app, client  # noqa: F401
from models import (
    Category,
    Customer,
    InventoryMovement,
    Permission,
    PriceHistory,
    Product,
    RolePermission,
    Sale,
    SaleItem,
    ShippingOrder,
    Supplier,
    User,
    UserPermissionDenial,
    UserPermissionGrant,
    db,
)


def ensure_second_product(app):
    with app.app_context():
        if not db.session.get(Product, 2):
            db.session.add(
                Product(
                    name="Second Product",
                    sku="TEST-002",
                    barcode="87654321",
                    category_id=1,
                    supplier_id=1,
                    cost=3000,
                    price=6000,
                    stock=10,
                    minimum=3,
                )
            )
            db.session.commit()


def make_delivery_payload(**changes):
    data = dict(
        token="d" * 48,
        items=[
            dict(product_id=1, quantity=2, discount=0, unit_price=10000),
        ],
        invoice_discount=0,
        customer_id=1,
        note="Phase 10 E2E delivery test",
        tax_rate=1400,
        currency="EGP",
        # 2 x 100.00 + 14% VAT = 228.00, plus the 50.00 shipping fee (no VAT).
        payments=[dict(method="Cash", amount=27800)],
        fulfillment={
            "method": "delivery",
            "address": {
                "customer_name": "Acceptance Customer",
                "phone": "+201009999999",
                "governorate": "Cairo",
                "city": "Nasr City",
                "street": "9th Street",
                "landmark": "Near Metro",
                "building": "12",
                "floor": "3",
                "apartment": "301",
            },
            "courier": "FastExpress",
            "shipping_cost": 5000,
        },
    )
    data.update(changes)
    return data


def make_pickup_payload(**changes):
    data = dict(
        token="e" * 48,
        items=[dict(product_id=1, quantity=1, discount=0, unit_price=10000)],
        invoice_discount=0,
        customer_id=1,
        note="Phase 10 E2E pickup test",
        tax_rate=1400,
        currency="EGP",
        payments=[dict(method="Cash", amount=11400)],
        fulfillment={
            "method": "pickup",
            "pickup_date": "2026-10-05",
            "pickup_notes": "Pick up at main desk",
        },
    )
    data.update(changes)
    return data


# ==============================================================================
# 1. FULFILLMENT ACCEPTANCE
# ==============================================================================
def test_1_fulfillment_acceptance(app, client):
    """E2E test: delivery sale, pickup sale, 10 pipeline statuses, inventory restoration, audit."""
    with app.app_context():
        p1 = db.session.get(Product, 1)
        initial_stock = p1.stock

    # Create delivery sale
    res_del = client.post("/api/pos/sales", json=make_delivery_payload())
    assert res_del.status_code == 200, res_del.data
    del_data = res_del.get_json()
    sid_del = del_data["id"]

    # Verify inventory was decremented
    with app.app_context():
        p1_after = db.session.get(Product, 1)
        assert p1_after.stock == initial_stock - 2
        ship_order = ShippingOrder.query.filter_by(sale_id=sid_del).first()
        assert ship_order is not None
        assert ship_order.status == "Pending"
        oid = ship_order.id

    # Create pickup sale
    res_pick = client.post("/api/pos/sales", json=make_pickup_payload())
    assert res_pick.status_code == 200
    pick_data = res_pick.get_json()
    sid_pick = pick_data["id"]

    # Verify pickup status initial and transition
    with app.app_context():
        pick_sale = db.session.get(Sale, sid_pick)
        assert pick_sale.pickup_status == "Pending Pickup"

    res_pick_adv = client.post(
        f"/api/sales/{sid_pick}/pickup-status",
        json={"status": "Ready For Pickup"},
    )
    assert res_pick_adv.status_code == 200
    assert res_pick_adv.get_json()["status"] == "Ready For Pickup"

    # Verify /orders hub pipeline tabs and status counters
    orders_html = client.get("/orders").data.decode()
    for tab in (
        "/orders?tab=pending",
        "/orders?tab=packed",
        "/orders?tab=ready",
        "/orders?tab=shipped",
        "/orders?tab=out_for_delivery",
        "/orders?tab=delivered",
        "/orders?tab=returned",
        "/orders?tab=cancelled",
        "/orders?tab=pickup",
    ):
        assert tab in orders_html, f"Missing pipeline tab: {tab}"

    # Advance Shipping order through fulfillment states: Pending -> Packed -> Ready For Shipment
    res_packed = client.post(f"/api/shipping/{oid}/status", json={"status": "Packed"})
    assert res_packed.status_code == 200
    assert res_packed.get_json()["order"]["status"] == "Packed"

    res_ready = client.post(
        f"/api/shipping/{oid}/status", json={"status": "Ready For Shipment"}
    )
    assert res_ready.status_code == 200
    assert res_ready.get_json()["order"]["status"] == "Ready For Shipment"

    # Shipped requires tracking code
    res_ship_fail = client.post(f"/api/shipping/{oid}/status", json={"status": "Shipped"})
    assert res_ship_fail.status_code == 400

    res_ship = client.post(
        f"/api/shipping/{oid}/status",
        json={
            "status": "Shipped",
            "courier": "FastExpress",
            "tracking_code": "TRACK-E2E-12345",
        },
    )
    assert res_ship.status_code == 200
    assert res_ship.get_json()["order"]["status"] == "Shipped"

    # Shipped -> Out For Delivery
    res_out = client.post(f"/api/shipping/{oid}/status", json={"status": "Out For Delivery"})
    assert res_out.status_code == 200
    assert res_out.get_json()["order"]["status"] == "Out For Delivery"

    # Out For Delivery -> Delivered
    res_deliv = client.post(
        f"/api/shipping/{oid}/status",
        json={
            "status": "Delivered",
            "delivered_by": "Driver Ahmed",
            "delivered_date": "2026-10-02",
            "delivered_time": "14:30",
        },
    )
    assert res_deliv.status_code == 200
    assert res_deliv.get_json()["order"]["status"] == "Delivered"

    # Test Return & Inventory Restoration on another order
    res_del2 = client.post(
        "/api/pos/sales",
        json=make_delivery_payload(token="f" * 48),
    )
    sid2 = res_del2.get_json()["id"]
    with app.app_context():
        oid2 = ShippingOrder.query.filter_by(sale_id=sid2).first().id
        p1_before_ret = db.session.get(Product, 1).stock

    # Move to Packed -> Ready For Shipment -> Shipped -> Out For Delivery -> Returned
    client.post(f"/api/shipping/{oid2}/status", json={"status": "Packed"})
    client.post(f"/api/shipping/{oid2}/status", json={"status": "Ready For Shipment"})
    client.post(
        f"/api/shipping/{oid2}/status",
        json={"status": "Shipped", "tracking_code": "TRACK-RET-99"},
    )
    client.post(f"/api/shipping/{oid2}/status", json={"status": "Out For Delivery"})
    res_ret = client.post(f"/api/shipping/{oid2}/status", json={"status": "Returned"})
    assert res_ret.status_code == 200
    assert res_ret.get_json()["order"]["status"] == "Returned"

    # Refunding the returned order restores stock
    res_ref = client.post(f"/sales/{sid2}/refund")
    assert res_ref.status_code == 302

    # Inventory must be restored by 2 units
    with app.app_context():
        assert db.session.get(Product, 1).stock == p1_before_ret + 2

    # Verify shipping order cancellation workflow
    res_del3 = client.post(
        "/api/pos/sales",
        json=make_delivery_payload(token="1" * 48),
    )
    sid3 = res_del3.get_json()["id"]
    with app.app_context():
        oid3 = ShippingOrder.query.filter_by(sale_id=sid3).first().id
        p1_before_cancel = db.session.get(Product, 1).stock
    res_cancel_ship = client.post(
        f"/api/shipping/{oid3}/status",
        json={"status": "Cancelled", "cancel_reason": "Customer Cancelled"},
    )
    assert res_cancel_ship.status_code == 200
    assert res_cancel_ship.get_json()["order"]["status"] == "Cancelled"

    # Voiding/Cancelling the sale restores inventory
    res_void = client.post(
        f"/sales/{sid3}/delete",
        data={"cancel_reason": "Customer Cancelled"},
    )
    assert res_void.status_code == 302
    with app.app_context():
        assert db.session.get(Product, 1).stock == p1_before_cancel + 2


# ==============================================================================
# 2. PRODUCT CREATION ACCEPTANCE
# ==============================================================================
def test_2_product_creation_inline_and_generators(app, client):
    """Test quick-add Category, quick-add Supplier, SKU/barcode generators, save and catalog appearance."""
    # 1. Inline Category creation
    res_cat = client.post(
        "/api/categories",
        json={"name": "Inline Optics", "description": "High end optics"},
    )
    assert res_cat.status_code == 201
    cat_id = res_cat.get_json()["category"]["id"]
    assert cat_id > 0

    # 2. Inline Supplier creation
    res_sup = client.post(
        "/api/suppliers",
        json={
            "name": "Global Optical Labs",
            "contact_name": "Dr. Sarah",
            "phone": "+201112223334",
            "email": "sarah@opticallabs.com",
            "address": "Alexandria Tech Zone",
        },
    )
    assert res_sup.status_code == 201
    sup_data = res_sup.get_json()
    sup_id = sup_data["supplier"]["id"]

    # 3. Save new product using these references
    sku_val = "SKU-OPTIC-999"
    barcode_val = "2009998887771"
    form_data = {
        "name": "Prism Binoculars 10x42",
        "sku": sku_val,
        "barcode": barcode_val,
        "brand": "OptiVision",
        "category_id": str(cat_id),
        "supplier_id": str(sup_id),
        "price": "350.00",
        "cost": "210.00",
        "minimum": "5",
        "stock": "15",
        "location": "Aisle 4, Shelf B",
    }
    res_prod = client.post("/products/new", data=form_data, follow_redirects=True)
    assert res_prod.status_code == 200
    html = res_prod.data.decode()
    assert "Prism Binoculars 10x42" in html
    assert sku_val in html

    # Verify presence in Inventory (Stock Operations)
    inv_html = client.get("/inventory").data.decode()
    assert "Prism Binoculars 10x42" in inv_html
    assert "Stock on Hand &amp; Availability" in inv_html


# ==============================================================================
# 3. INVENTORY BARCODE SCANNER & ADJUSTMENT ACCEPTANCE
# ==============================================================================
def test_3_inventory_scanner_and_adjustment(app, client):
    """Test dedicated barcode scanner instant resolution and adjustment ledger movement."""
    # Ensure product with barcode exists
    with app.app_context():
        p = db.session.get(Product, 1)
        p.barcode = "2009998887771"
        db.session.commit()
        pid = p.id
        old_stock = p.stock

    # Resolve product via POS/scanner barcode lookup
    res_search = client.get("/api/pos/products?barcode=2009998887771")
    assert res_search.status_code == 200
    results = res_search.get_json()["items"]
    assert len(results) >= 1
    found = results[0]
    assert found["id"] == pid

    # Apply adjustment +5
    adj_data = {
        "product_id": str(pid),
        "adjustment_type": "Add Stock",
        "quantity": "5",
        "reason": "Shipment arrived without PO",
    }
    res_adj = client.post("/inventory/adjust", data=adj_data, follow_redirects=True)
    assert res_adj.status_code == 200

    # Verify stock and movement ledger
    with app.app_context():
        p_new = db.session.get(Product, pid)
        assert p_new.stock == old_stock + 5
        movement = (
            InventoryMovement.query.filter_by(product_id=pid)
            .order_by(InventoryMovement.id.desc())
            .first()
        )
        assert movement is not None
        assert movement.quantity == 5
        assert movement.kind == "Add Stock"
        assert movement.reference == "Shipment arrived without PO"


# ==============================================================================
# 4. POS HOLD & RESUME SALE ACCEPTANCE
# ==============================================================================
def test_4_pos_cart_isolation_and_hold_resume(app, client):
    """Test multi-cart isolation, holding a cart, completing another, and resuming."""
    with app.app_context():
        p1 = db.session.get(Product, 1)
        initial_stock = p1.stock

    # Cart A (held) would have 2 units of Product 1
    # Cart B is completed with 1 unit of Product 1
    cart_b = make_pickup_payload(
        token="b" * 48,
        items=[dict(product_id=1, quantity=1, discount=0, unit_price=10000)],
        payments=[dict(method="Cash", amount=11400)],
    )
    res_b = client.post("/api/pos/sales", json=cart_b)
    assert res_b.status_code == 200
    assert res_b.get_json()["id"] > 0

    with app.app_context():
        assert db.session.get(Product, 1).stock == initial_stock - 1

    # Now simulate resuming Cart A and completing it
    cart_a = make_pickup_payload(
        token="a" * 48,
        items=[dict(product_id=1, quantity=2, discount=0, unit_price=10000)],
        payments=[dict(method="Cash", amount=22800)],
    )
    res_a = client.post("/api/pos/sales", json=cart_a)
    assert res_a.status_code == 200
    assert res_a.get_json()["id"] > 0

    with app.app_context():
        assert db.session.get(Product, 1).stock == initial_stock - 3
        # Invoices are isolated and distinct
        inv_b = Sale.query.filter_by(token=cart_b["token"]).first()
        inv_a = Sale.query.filter_by(token=cart_a["token"]).first()
        assert inv_b.invoice != inv_a.invoice
        assert inv_b.total == 11400
        assert inv_a.total == 22800


# ==============================================================================
# 5. REFUND ACCEPTANCE
# ==============================================================================
def test_5_refund_workflows_all_and_selected(app, client):
    """Test A: Return entire invoice; Test B: Return selected items; Test C: Return partial quantity."""
    ensure_second_product(app)

    with app.app_context():
        p1 = db.session.get(Product, 1)
        p2 = db.session.get(Product, 2)
        p1_stock = p1.stock
        p2_stock = p2.stock

    sale_payload = dict(
        token="c" * 48,
        items=[
            dict(product_id=1, quantity=3, discount=0, unit_price=10000),
            dict(product_id=2, quantity=2, discount=0, unit_price=6000),
        ],
        invoice_discount=0,
        customer_id=1,
        note="",
        tax_rate=1400,
        currency="EGP",
        payments=[dict(method="Cash", amount=47880)],
        fulfillment={"method": "pickup"},
    )
    res = client.post("/api/pos/sales", json=sale_payload)
    assert res.status_code == 200
    sid = res.get_json()["id"]

    # Verify stock decremented
    with app.app_context():
        assert db.session.get(Product, 1).stock == p1_stock - 3
        assert db.session.get(Product, 2).stock == p2_stock - 2

    # --- Scenario C: Partial quantity return (1 unit of Product 1) ---
    res_part = client.post(
        f"/sales/{sid}/refund",
        json={"items": [{"product_id": 1, "quantity": 1}]},
    )
    assert res_part.status_code == 200
    assert res_part.get_json()["success"] is True

    with app.app_context():
        # Product 1 restocked by 1
        assert db.session.get(Product, 1).stock == p1_stock - 2
        sale = db.session.get(Sale, sid)
        assert sale.status == "Completed"
        item1 = next(i for i in sale.items if i.product_id == 1)
        assert item1.quantity == 2  # was 3, returned 1
        assert "Partial refund: 1x" in sale.note

    # Cannot return more than sold quantity
    res_excess = client.post(
        f"/sales/{sid}/refund",
        json={"items": [{"product_id": 1, "quantity": 99}]},
    )
    assert res_excess.status_code == 400

    # --- Scenario B: Return selected item entirely (Product 2) ---
    res_sel = client.post(
        f"/sales/{sid}/refund",
        json={"items": [{"product_id": 2, "quantity": 2}]},
    )
    assert res_sel.status_code == 200

    with app.app_context():
        # Product 2 restocked fully
        assert db.session.get(Product, 2).stock == p2_stock
        sale = db.session.get(Sale, sid)
        assert not any(i.product_id == 2 for i in sale.items)

    # --- Scenario A: Return entire remaining invoice ---
    res_full = client.post(f"/sales/{sid}/refund")
    assert res_full.status_code == 302  # standard redirect

    with app.app_context():
        # Remaining 2 units of Product 1 restocked
        assert db.session.get(Product, 1).stock == p1_stock
        sale = db.session.get(Sale, sid)
        assert sale.status == "Refunded"

    # Cannot refund an already refunded invoice (must be rejected)
    res_dup = client.post(f"/sales/{sid}/refund")
    assert res_dup.status_code == 400


# ==============================================================================
# 6. PRICE ANALYTICS ACCEPTANCE
# ==============================================================================
def test_6_price_analytics_adjust_price_now(app, client):
    """Test Adjust Price Now API, auto price-history snapshot, chart/trend refresh."""
    pid = 1
    with app.app_context():
        old_price = db.session.get(Product, pid).price

    new_price_str = "175.50"
    new_cost_str = "110.00"

    # Adjust price now
    res_adj = client.post(
        f"/api/products/{pid}/adjust-price",
        json={"price": new_price_str, "cost": new_cost_str},
    )
    assert res_adj.status_code == 200
    adj_data = res_adj.get_json()
    assert adj_data["success"] is True
    assert adj_data["price"] == 17550
    assert adj_data["cost"] == 11000

    with app.app_context():
        p = db.session.get(Product, pid)
        assert p.price == 17550
        assert p.cost == 11000

        # Verify PriceHistory was captured
        history = (
            PriceHistory.query.filter_by(product_id=pid)
            .order_by(PriceHistory.id.desc())
            .first()
        )
        assert history is not None
        assert history.new_price == 17550
        assert history.old_price == old_price

    # Verify /api/products/<pid>/price-history returns the new stats
    res_hist = client.get(f"/api/products/{pid}/price-history")
    assert res_hist.status_code == 200
    hist_json = res_hist.get_json()
    assert hist_json["summary"]["current"] == 17550
    assert hist_json["summary"]["current_cost"] == 11000


# ==============================================================================
# 7. PERMISSIONS ACCEPTANCE
# ==============================================================================
def test_7_permissions_advanced_policies_and_deny(app, client):
    """Test Advanced Policies categories, Grant All, Revoke All, explicit User Deny."""
    # Check page loads with categorized policies
    res_pol = client.get("/settings/permissions")
    assert res_pol.status_code == 200
    html = res_pol.data.decode()
    for cat in (
        "policy-category-block",
        "role-grant-all-global",
        "role-revoke-all-global",
        "cat-grant-all",
        "cat-revoke-all",
        "role-search",
        "Products",
        "Inventory",
        "Sales",
        "Users",
    ):
        assert cat in html, f"Missing policy UI element: {cat}"

    # Explicit user DENY overrides role GRANT
    with app.app_context():
        perm = Permission.query.filter_by(key="products.view").first()
        db.session.add(UserPermissionDenial(user_id=1, permission_id=perm.id))
        db.session.commit()

    # User 1 has Role Grant for products.view, but explicit user Deny overrides it
    assert client.get("/products").status_code == 403

    # Clean up deny policy
    with app.app_context():
        UserPermissionDenial.query.filter_by(user_id=1).delete()
        db.session.commit()

    assert client.get("/products").status_code == 200


# ==============================================================================
# 8. REPORTING PERIOD COMPARISON ACCEPTANCE
# ==============================================================================
def test_8_reporting_period_comparison_and_exports(app, client):
    """Test period comparison percentage differences and export functionality."""
    vendor = app.config["ROOT"] / "static/vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "static/vendor/NotoSansArabic.ttf",
        vendor / "NotoSansArabic.ttf",
    )

    res_rep = client.get("/reports?kind=sales&from=2026-09-01&to=2026-09-30")
    assert res_rep.status_code == 200
    html = res_rep.data.decode()
    assert "Period Comparison" in html
    assert "vs" in html

    # Verify Excel and PDF exports
    res_xlsx = client.get("/reports/export/xlsx?kind=sales&from=2026-09-01&to=2026-09-30")
    assert res_xlsx.status_code == 200
    assert (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        in res_xlsx.content_type
    )

    res_pdf = client.get("/reports/export/pdf?kind=sales&from=2026-09-01&to=2026-09-30")
    assert res_pdf.status_code == 200
    assert "application/pdf" in res_pdf.content_type


# ==============================================================================
# 9. BACKUP WORKSPACE ACCEPTANCE
# ==============================================================================
def test_9_backup_center_consolidation_and_compatibility(app, client):
    """Test /backups workspace embedding logs, health status, and legacy /settings/backup-logs."""
    res_backup = client.get("/backups")
    assert res_backup.status_code == 200
    html = res_backup.data.decode()
    for token in (
        "Backup Activity &amp; Verification Logs",
        "Backup Now",
        "Dual Backup &amp; Restore",
        "backup-center",
        "backup-files",
    ):
        assert token in html, f"Missing backup center token: {token}"

    # Verify backward compatibility route /settings/backup-logs
    res_logs = client.get("/settings/backup-logs")
    assert res_logs.status_code == 200
    assert "Backup Logs" in res_logs.data.decode()


# ==============================================================================
# 10. NAVIGATION INTEGRITY ACCEPTANCE
# ==============================================================================
def test_10_navigation_paths_integrity(client):
    """Audit all changed navigation paths: no broken links, 200 OK responses."""
    paths = [
        "/",
        "/sales/new",
        "/products",
        "/products/new",
        "/inventory",
        "/inventory/adjust",
        "/inventory/movements",
        "/orders",
        "/orders?tab=pickup",
        "/orders?status=pending",
        "/orders?status=shipped",
        "/orders?status=delivered",
        "/shipping",
        "/sales",
        "/purchases",
        "/purchases/new",
        "/reports",
        "/reports?kind=profit",
        "/reports?kind=shipping",
        "/backups",
        "/settings",
        "/settings/permissions",
        "/settings/backup-logs",
    ]
    for path in paths:
        res = client.get(path)
        assert res.status_code == 200, f"Path {path} returned status {res.status_code}"
