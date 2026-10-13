"""Stock Adjustment workspace regression checks."""

from test_app import app, client  # noqa: F401
from models import AuditLog, InventoryMovement, Product, db


def _move(app, pid=1):
    with app.app_context():
        return (
            InventoryMovement.query.filter_by(product_id=pid)
            .order_by(InventoryMovement.id.desc())
            .first()
        )


def test_workspace_renders(client):
    page = client.get("/inventory/adjust").data.decode()
    for token in [
            "Stock Adjustments",
            "Manage inventory increases",
            "Current Product Stock",
            "Total Inventory Value",
            "Today&#39;s Adjustments",
            "Low Stock Products",
            "Stock Adjustment",
            "Product Snapshot",
            "Quick Actions",
            "Recent Adjustments",
            "adjustment_type",
            "save_and_new",
            "Reference Number",
            "Current Stock",
            "New Stock",
            "Receive Stock",
            "View Product",
            "Inventory Report",
            "Low Stock Report",
            "adjust.js",
            "adjust.css",
        ]:
        assert token in page, token
    assert "Stock Transfer" not in page


def test_typed_adjustment_and_audit(app, client):
    r = client.post(
        "/inventory/adjust",
        data={
            "product_id": "1",
            "adjustment_type": "Damaged Items",
            "qty": "3",
            "quantity": "-3",
            "reason": "Broken",
            "reference": "REF-1",
            "notes": "Shelf fall",
        },
    )
    assert r.status_code == 302, r.data[:200]
    m = _move(app)
    assert (m.quantity, m.balance, m.kind) == (-3, 7, "Damaged Items")
    assert m.reference == "Broken"
    with app.app_context():
        log = AuditLog.query.filter_by(action="Adjust stock").first()
        assert "REF-1" in log.details and "Shelf fall" in log.details
        assert db.session.get(Product, 1).stock == 7


def test_correction_keeps_sign_and_save_and_new(app, client):
    r = client.post(
        "/inventory/adjust",
        data={
            "product_id": "1",
            "adjustment_type": "Inventory Correction",
            "qty": "2",
            "quantity": "2",
            "reason": "Recount",
            "save_and_new": "1",
        },
    )
    assert r.status_code == 302 and "product_id=1" in r.location
    assert _move(app).kind == "Inventory Correction"
    r = client.post(
        "/inventory/adjust",
        data={
            "product_id": "1",
            "adjustment_type": "Manual Count Adjustment",
            "qty": "1",
            "quantity": "-1",
            "reason": "Recount",
        },
    )
    assert r.status_code == 302
    assert _move(app).kind == "Manual Count Adjustment"


def test_invalid_type_rejected(client):
    r = client.post(
        "/inventory/adjust",
        data={"product_id": "1", "adjustment_type": "Hacked", "quantity": "1", "reason": "x"},
    )
    assert r.status_code == 400


def test_admin_override_clamps_at_zero(app, client):
    r = client.post(
        "/inventory/adjust",
        data={
            "product_id": "1",
            "adjustment_type": "Remove Stock",
            "qty": "25",
            "quantity": "-25",
            "reason": "Clear",
            "allow_override": "1",
        },
    )
    assert r.status_code == 302, r.data[:200]
    with app.app_context():
        assert db.session.get(Product, 1).stock == 0
        log = AuditLog.query.filter_by(action="Adjust stock").first()
        assert "clamped at zero by admin override" in log.details
    m = _move(app)
    assert (m.quantity, m.balance) == (-10, 0)


def test_override_denied_without_admin(app):
    c = app.test_client()
    c.post("/login", data={"username": "manager", "password": "test-password-123"})
    r = c.post(
        "/inventory/adjust",
        data={
            "product_id": "1",
            "adjustment_type": "Remove Stock",
            "qty": "25",
            "quantity": "-25",
            "reason": "Clear",
            "allow_override": "1",
        },
    )
    assert r.status_code == 400
    r = c.post(
        "/inventory/adjust",
        data={
            "product_id": "1",
            "adjustment_type": "Add Stock",
            "qty": "2",
            "quantity": "2",
            "reason": "Restock",
        },
    )
    assert r.status_code == 302


def test_cashier_cannot_adjust(app):
    c = app.test_client()
    c.post("/login", data={"username": "cashier", "password": "test-password-123"})
    assert c.post(
        "/inventory/adjust", data={"product_id": "1", "quantity": "1", "reason": "x"}
    ).status_code == 403


def test_recent_table_and_today_count(app, client):
    client.post(
        "/inventory/adjust",
        data={"product_id": "1", "quantity": "1", "reason": "Morning count"},
    )
    page = client.get("/inventory/adjust").data.decode()
    assert "Morning count" in page
    assert "Add Stock" in page
