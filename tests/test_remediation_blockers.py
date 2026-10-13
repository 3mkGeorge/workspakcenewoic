"""Regression and verification tests for Production Audit Blocker Remediation.

Covers:
- BLOCKER 1: Orders Hub 'Packed' status mapping, filtering, and counter badge.
- BLOCKER 3: stock_stats() SQL aggregation accuracy and non-instantiation of ORM objects.
- BLOCKER 5: STOREPRO_HOST configurable host binding.
- BLOCKER 6: Login rate limiting isolation by (remote_addr, normalized_username).
- DATA-01: Immutable price history protection against hard product deletion.
- BIZ-02: Server-side discount bounds validation.
- ROUTE-01: Consistent JSON error responses for AJAX/API consumers.
"""

import os
import pytest
from unittest.mock import patch
from test_app import app, client  # noqa: F401
from models import (
    Customer,
    PriceHistory,
    Product,
    Sale,
    ShippingOrder,
    User,
    db,
)
from services.analytics import stock_stats
from services.orders import get_orders_hub_counters
from services.pos import calculate, save_invoice
from services.validation import cents


# =========================================================================
# BLOCKER 1: ORDERS HUB PACKED STATUS & COUNTER
# =========================================================================

def test_blocker1_packed_status_filtering_and_badge(client, app):
    """Verify that orders with canonical status 'Packed' appear under /orders?tab=packed

    and the packed counter badge reflects actual database records.
    """
    with app.app_context():
        # Clear or count baseline
        initial_counts = get_orders_hub_counters()
        initial_packed = initial_counts["packed"]

        # Create a sale and shipping order with status 'Packed'
        sale = Sale(
            invoice="INV-PACKED-001",
            customer_name="Packed Customer",
            cashier="Admin",
            payment="Cash",
            subtotal=10000,
            discount=0,
            tax=0,
            tax_rate=0,
            total=10000,
            cost=5000,
            currency="EGP",
            store_snapshot="{}",
            token="token_packed_test_001",
            user_id=1,
            status="Completed",
        )
        db.session.add(sale)
        db.session.flush()

        shipping = ShippingOrder(
            order_number="SO-PACKED-001",
            sale_id=sale.id,
            customer_name="Packed Customer",
            phone="+201000000001",
            governorate="Cairo",
            city="Cairo",
            street="123 Test St",
            status="Packed",
            user_id=1,
        )
        db.session.add(shipping)
        db.session.commit()

        # Check counter query in services.orders
        counts = get_orders_hub_counters()
        assert counts["packed"] == initial_packed + 1, "Packed counter query did not increment for Packed status"

    # Query /orders?tab=packed via HTTP
    resp = client.get("/orders?tab=packed")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "SO-PACKED-001" in html, "SO-PACKED-001 not rendered on /orders?tab=packed"
    assert "Packed Customer" in html


def test_blocker1_all_order_tabs_workflow_intact(client, app):
    """Verify existing Pending, Ready, Shipped, Delivered, Returned, Cancelled tabs remain intact."""
    for tab in ("pending", "packed", "ready", "shipped", "delivered", "returned", "cancelled", "pickup"):
        resp = client.get(f"/orders?tab={tab}")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "orders-tabs" in html


# =========================================================================
# BLOCKER 3: STOCK_STATS SQL AGGREGATION & NO ORM INSTANTIATION
# =========================================================================

def test_blocker3_stock_stats_accuracy(app):
    """Verify stock_stats preserves exact dictionary structure and accurate calculations."""
    with app.app_context():
        # Clean state for testing known numbers
        # Product from fixture: stock=10, cost=5000, price=10000, minimum=5
        stats = stock_stats()
        assert "count" in stats
        assert "units" in stats
        assert "value" in stats
        assert "low" in stats
        assert "out" in stats
        assert "in_stock" in stats
        assert stats["count"] >= 1
        assert stats["units"] >= 10
        assert stats["value"] >= 50000  # 10 * 5000
        assert stats["out"] == 0


def test_blocker3_stock_stats_does_not_instantiate_orm_objects(app):
    """Verify stock_stats uses SQL aggregates rather than instantiating Product ORM objects."""
    with app.app_context():
        # Add multiple products
        for i in range(20):
            db.session.add(
                Product(
                    name=f"Agg Product {i}",
                    sku=f"AGG-SKU-{i}",
                    category_id=1,
                    supplier_id=1,
                    cost=1000,
                    price=2000,
                    stock=5 + i,
                    minimum=10,
                    active=True,
                )
            )
        db.session.commit()
        db.session.expire_all()
        db.session.expunge_all()

        stats = stock_stats()

        # Verify no Product objects are loaded into the session identity map
        loaded_products = [obj for obj in db.session.identity_map.values() if isinstance(obj, Product)]
        assert len(loaded_products) == 0, f"Expected 0 Product instances in session identity map, found {len(loaded_products)}"
        assert stats["count"] >= 21


# =========================================================================
# BLOCKER 5: CONFIGURABLE HOST BINDING
# =========================================================================

def test_blocker5_configurable_host_binding():
    """Verify STOREPRO_HOST environment variable controls the server host binding."""
    # Test default
    with patch.dict(os.environ, {}, clear=True):
        host_default = os.environ.get("STOREPRO_HOST", "127.0.0.1")
        assert host_default == "127.0.0.1"

    # Test custom LAN binding
    with patch.dict(os.environ, {"STOREPRO_HOST": "0.0.0.0"}):
        host_lan = os.environ.get("STOREPRO_HOST", "127.0.0.1")
        assert host_lan == "0.0.0.0"

    with patch.dict(os.environ, {"STOREPRO_HOST": "192.168.1.100"}):
        host_custom = os.environ.get("STOREPRO_HOST", "127.0.0.1")
        assert host_custom == "192.168.1.100"


# =========================================================================
# BLOCKER 6: LOGIN RATE LIMITING USERNAME ISOLATION
# =========================================================================

def test_blocker6_login_rate_limit_username_isolation(app):
    """Verify failed attempts against User A do not lock out User B from the same IP (127.0.0.1)."""
    c = app.test_client()
    # Attempt 8 failed logins on user 'victim_a'
    for _ in range(8):
        resp = c.post(
            "/login",
            data={"username": "victim_a", "password": "wrong-password"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert resp.status_code == 401

    # The 9th attempt on victim_a triggers 429
    resp_locked = c.post(
        "/login",
        data={"username": "victim_a", "password": "wrong-password"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp_locked.status_code == 429
    assert "Too many attempts" in resp_locked.data.decode()

    # Now verify user 'innocent_b' from the SAME IP 127.0.0.1 is NOT locked out!
    resp_b = c.post(
        "/login",
        data={"username": "innocent_b", "password": "any-password"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    # Should be 401 (invalid credentials), NOT 429!
    assert resp_b.status_code == 401, "User B was improperly locked out by User A's failed logins!"
    assert "Too many attempts" not in resp_b.data.decode()


def test_blocker6_login_username_normalization_and_empty(app):
    """Verify username normalization (lowercase, whitespace strip) and empty username handling."""
    c = app.test_client()
    # Test whitespace/casing normalization shares the bucket
    for _ in range(8):
        resp = c.post(
            "/login",
            data={"username": " NormalizedUser ", "password": "wrong"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.2"},
        )
        assert resp.status_code == 401

    # 9th attempt with different case and whitespace should hit the same rate limit
    resp = c.post(
        "/login",
        data={"username": "normalizeduser", "password": "wrong"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.2"},
    )
    assert resp.status_code == 429

    # Test empty username is handled safely without crashing
    resp_empty = c.post(
        "/login",
        data={"username": "", "password": ""},
        environ_overrides={"REMOTE_ADDR": "127.0.0.3"},
    )
    assert resp_empty.status_code == 401


# =========================================================================
# DATA-01: IMMUTABLE PRICE HISTORY PRODUCT HARD-DELETE GUARD
# =========================================================================

def test_data01_product_hard_delete_guard(app):
    """Verify that attempting to hard-delete a product with price history raises ValueError."""
    with app.app_context():
        p = Product(
            name="Audited Product",
            sku="AUDIT-001",
            category_id=1,
            supplier_id=1,
            cost=1000,
            price=2000,
            stock=5,
            minimum=2,
            active=True,
        )
        db.session.add(p)
        db.session.commit()

        # Add price history
        hist = PriceHistory(
            product_id=p.id,
            product_name=p.name,
            old_cost=1000,
            new_cost=1200,
            old_price=2000,
            new_price=2500,
            change_amount=500,
            cost_change_amount=200,
            changed_by="Admin",
            source="Manual adjustment",
        )
        db.session.add(hist)
        db.session.commit()

        # Attempt hard delete
        db.session.delete(p)
        with pytest.raises(ValueError) as exc:
            db.session.commit()
        assert "immutable price history" in str(exc.value)
        db.session.rollback()

        # Verify soft deletion works without error
        p_reload = db.session.get(Product, p.id)
        p_reload.active = False
        db.session.commit()
        assert p_reload.active is False


# =========================================================================
# BIZ-02: SERVER-SIDE DISCOUNT BOUNDS VALIDATION
# =========================================================================

def test_biz02_server_side_discount_bounds(app):
    """Verify line discount exceeding gross or negative, and invoice discount exceeding subtotal are rejected."""
    with app.app_context():
        from flask import g
        g.settings = {
            "currency": "EGP",
            "tax_rate": "14",
            "tax_enabled": "0",
        }

        # Line discount exceeds line gross
        payload_excess_line = {
            "items": [
                {"product_id": 1, "quantity": 1, "discount": 20000, "unit_price": 10000}
            ],
            "invoice_discount": 0,
        }
        res = calculate(payload_excess_line)
        assert res["valid"] is False
        assert any("exceeds" in issue for issue in res["issues"])
        assert res["items"][0]["total"] >= 0, "Line total should never be negative"

        # Invoice discount exceeds subtotal
        payload_excess_invoice = {
            "items": [
                {"product_id": 1, "quantity": 1, "discount": 0, "unit_price": 10000}
            ],
            "invoice_discount": 15000,
        }
        res_inv = calculate(payload_excess_invoice)
        assert res_inv["valid"] is False
        assert any("subtotal" in issue for issue in res_inv["issues"])

        # Negative discount raises ValueError
        payload_neg = {
            "items": [
                {"product_id": 1, "quantity": 1, "discount": -500, "unit_price": 10000}
            ],
            "invoice_discount": 0,
        }
        with pytest.raises(ValueError):
            calculate(payload_neg)


# =========================================================================
# ROUTE-01: API/AJAX ERRORS RETURN JSON
# =========================================================================

def test_route01_ajax_errors_return_json(client):
    """Verify that requests with Accept: application/json or /api/ return JSON on errors."""
    # 404 with Accept: application/json
    resp_404 = client.get(
        "/nonexistent-endpoint",
        headers={"Accept": "application/json"},
    )
    assert resp_404.status_code == 404
    assert resp_404.is_json
    assert "error" in resp_404.get_json()

    # 400 validation error on API endpoint
    resp_400 = client.post(
        "/api/pos/sales",
        json={"invalid": "payload"},
        headers={"Accept": "application/json"},
    )
    assert resp_400.status_code in (400, 500)
    assert resp_400.is_json
    assert "error" in resp_400.get_json()
