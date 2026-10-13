"""Unit tests for services/core.py business logic and edge cases."""

import pytest
from decimal import Decimal
from werkzeug.datastructures import MultiDict

from test_app import app  # noqa: F401
from models import db, Product, Purchase, PurchaseItem, InventoryMovement, Setting
from services.core import (
    cents,
    integer,
    required,
    settings,
    save_setting,
    move,
    next_number,
    lines_from_form,
    receive_purchase,
)


def test_cents_valid():
    assert cents(0) == 0
    assert cents("0") == 0
    assert cents("0.00") == 0
    assert cents("10") == 1000
    assert cents("10.50") == 1050
    assert cents("0.99") == 99
    assert cents("0.01") == 1
    # Check half-up rounding
    assert cents("10.005") == 1001
    assert cents("10.004") == 1000
    assert cents(Decimal("123.45")) == 12345


def test_cents_invalid():
    invalid_cases = [
        "-1",
        "-0.01",
        "abc",
        "",
        None,
        float("inf"),
        float("-inf"),
        float("nan"),
        1000000001,
        "1000000001",
    ]
    for case in invalid_cases:
        with pytest.raises(ValueError, match="Enter a valid non-negative amount"):
            cents(case)


def test_integer_valid():
    assert integer(0) == 0
    assert integer("0") == 0
    assert integer("123") == 123
    assert integer(1000000) == 1000000
    assert integer("50", minimum=10, maximum=100) == 50
    assert integer("-5", minimum=-10, maximum=0) == -5


def test_integer_invalid():
    with pytest.raises(ValueError, match="Enter a whole number"):
        integer(-1, minimum=0)
    with pytest.raises(ValueError, match="Enter a whole number"):
        integer(1001, minimum=0, maximum=1000)
    with pytest.raises(ValueError, match="Enter a whole number"):
        integer("abc")
    with pytest.raises(ValueError, match="Enter a whole number"):
        integer("")
    with pytest.raises(ValueError, match="Enter a whole number"):
        integer(None)
    with pytest.raises(ValueError, match="Enter a whole number"):
        integer("12.5")


def test_required_validation():
    assert required("hello", "Name") == "hello"
    assert required("  spaced  ", "Field") == "spaced"

    with pytest.raises(ValueError, match="Name is required"):
        required("", "Name")
    with pytest.raises(ValueError, match="Name is required"):
        required("   ", "Name")
    with pytest.raises(ValueError, match="Name is required"):
        required(None, "Name")
    with pytest.raises(ValueError, match="maximum 5 characters"):
        required("toolongstring", "Code", limit=5)


def test_settings_and_save_setting(app):
    with app.app_context():
        cfg = settings()
        assert "store_name" in cfg
        assert cfg["currency"] == "EGP"

        save_setting("custom_test_key", "custom_test_value")
        db.session.commit()

        updated = settings()
        assert updated["custom_test_key"] == "custom_test_value"

        # Overwrite existing setting
        save_setting("custom_test_key", "modified_value")
        db.session.commit()
        assert settings()["custom_test_key"] == "modified_value"


def test_move_inventory(app):
    with app.app_context():
        product = db.session.get(Product, 1)
        initial_stock = product.stock

        # Add 5 units
        move(product, 5, "Stock in", "PO-1001", user_id=1)
        db.session.commit()
        assert product.stock == initial_stock + 5

        # Check movement record
        movement = (
            InventoryMovement.query.filter_by(product_id=product.id)
            .order_by(InventoryMovement.id.desc())
            .first()
        )
        assert movement.quantity == 5
        assert movement.balance == initial_stock + 5
        assert movement.kind == "Stock in"
        assert movement.reference == "PO-1001"

        # Remove 3 units
        move(product, -3, "Sale", "INV-1001", user_id=1)
        db.session.commit()
        assert product.stock == initial_stock + 2

        # Oversell attempt must raise ValueError and not change stock
        with pytest.raises(ValueError, match="Insufficient stock"):
            move(product, -(initial_stock + 100), "Sale", "INV-1002", user_id=1)
        assert product.stock == initial_stock + 2


def test_receive_purchase(app):
    with app.app_context():
        product = db.session.get(Product, 1)
        product.stock = 10
        product.cost = 5000  # 50.00
        db.session.commit()

        purchase = Purchase(
            invoice="PO-9999",
            supplier_id=1,
            supplier_name="Supplier",
            status="Pending",
            total=30000,
            currency="EGP",
            token="purchase-test-token-1",
        )
        db.session.add(purchase)
        db.session.flush()

        # Add 5 units at cost 80.00 (8000 cents)
        item = PurchaseItem(
            purchase_id=purchase.id,
            product_id=product.id,
            name=product.name,
            quantity=5,
            cost=8000,
        )
        db.session.add(item)
        db.session.commit()

        receive_purchase(purchase)
        db.session.commit()

        assert purchase.status == "Received"
        assert purchase.received_at is not None
        assert product.stock == 15
        # Weighted average: (10 * 5000 + 5 * 8000) / 15 = (50000 + 40000) / 15 = 90000 / 15 = 6000
        assert product.cost == 6000

        # Cannot receive twice
        with pytest.raises(ValueError, match="cannot be received again"):
            receive_purchase(purchase)


def test_next_number(app):
    with app.app_context():
        num1 = next_number(Purchase, "PO-")
        assert num1.startswith("PO-")

        # Create a purchase with this number
        p = Purchase(
            invoice=num1,
            supplier_id=1,
            supplier_name="Supplier",
            status="Pending",
            total=1000,
            currency="EGP",
            token="token-next-number-test",
        )
        db.session.add(p)
        db.session.commit()

        # The subsequent number must be different
        num2 = next_number(Purchase, "PO-")
        assert num2.startswith("PO-")
        assert num2 != num1


def test_lines_from_form_validation(app):
    with app.app_context():
        # Valid sale form
        form_sale = MultiDict([
            ("product_id", "1"),
            ("quantity", "2"),
        ])
        lines = lines_from_form(form_sale, purchase=False)
        assert len(lines) == 1
        p, q, price = lines[0]
        assert p.id == 1
        assert q == 2
        assert price == p.price

        # Valid purchase form
        form_purchase = MultiDict([
            ("product_id", "1"),
            ("quantity", "3"),
            ("unit_cost", "45.00"),
        ])
        lines_purch = lines_from_form(form_purchase, purchase=True)
        assert len(lines_purch) == 1
        p, q, cost = lines_purch[0]
        assert p.id == 1
        assert q == 3
        assert cost == 4500

        # Purchase missing unit_cost
        form_purch_missing_cost = MultiDict([
            ("product_id", "1"),
            ("quantity", "3"),
        ])
        with pytest.raises(ValueError, match="Every purchase item needs a cost"):
            lines_from_form(form_purch_missing_cost, purchase=True)

        # Duplicate product IDs
        form_dup = MultiDict([
            ("product_id", "1"),
            ("quantity", "1"),
            ("product_id", "1"),
            ("quantity", "2"),
        ])
        with pytest.raises(ValueError, match="Each product can appear once"):
            lines_from_form(form_dup)

        # Unknown product ID
        form_unknown = MultiDict([
            ("product_id", "99999"),
            ("quantity", "1"),
        ])
        with pytest.raises(ValueError, match="Choose an active product"):
            lines_from_form(form_unknown)

        # Empty product IDs
        with pytest.raises(ValueError, match="Add between 1 and 100 products"):
            lines_from_form(MultiDict([]))
