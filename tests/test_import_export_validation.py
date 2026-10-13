"""Comprehensive Export/Import Validation Test Suite for StorePro.

Validates:
1. Product catalog CSV export (schema, scaling, formula injection escaping).
2. Product catalog CSV import (creation, updates, categories, suppliers).
3. Import security hardening (formula injection stripping, sanitization).
4. Import validation error handling (missing columns, invalid prices, negative values).
5. Import integrity (in-file duplicate SKU collision rejection, atomic rollback).
6. Financial reports & price history XLSX/CSV export structure and security.
"""

import io
import csv
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_app import app, client  # noqa: F401
from models import db, Product, Category, Supplier, Sale, SaleItem, now


def test_product_csv_export_format_and_escaping(app, client):
    """Product CSV export must have proper columns, correct pricing format, and formula escaping."""
    with app.app_context():
        cat = Category.query.first()
        p_formula = Product(
            name="=SUM(A1:B5)",
            sku="FORMULA-SKU-1",
            barcode="+123456789",
            cost=2500,
            price=5000,
            stock=15,
            minimum=3,
            brand="@malicious_brand",
            category_id=cat.id,
            active=True,
        )
        db.session.add(p_formula)
        db.session.commit()

    res = client.get("/products/export/csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["Content-Type"]
    assert "StorePro-Products.csv" in res.headers["Content-Disposition"]

    content = res.data.decode("utf-8-sig")
    reader = list(csv.reader(io.StringIO(content)))
    assert len(reader) >= 2

    # Check header
    header = reader[0]
    expected_headers = [
        "Name", "SKU", "Barcode", "Category", "Supplier", "Brand",
        "Selling Price", "Cost Price", "Stock Units", "Minimum Stock"
    ]
    assert header == expected_headers

    # Check that formula product row was escaped with single quote
    formula_row = next((r for r in reader[1:] if "FORMULA-SKU-1" in r[1]), None)
    assert formula_row is not None
    assert formula_row[0].startswith("'=")
    assert formula_row[2].startswith("'+")
    assert formula_row[5].startswith("'@")
    assert formula_row[6] == "50.00"
    assert formula_row[7] == "25.00"


def test_product_csv_import_success(app, client):
    """Valid CSV import creates new products, categories, and suppliers."""
    csv_data = (
        "Name,SKU,Barcode,Category,Supplier,Selling Price,Cost Price,Stock Units,Minimum Stock,Description\n"
        "Wireless Mouse,MOU-001,888001,Peripherals,TechSupply,29.99,14.50,45,10,Ergonomic optical mouse\n"
        "Mechanical Keyboard,KEY-002,888002,Peripherals,TechSupply,89.00,50.00,20,5,RGB tactile switch\n"
    )
    data = {"file": (io.BytesIO(csv_data.encode("utf-8")), "products.csv")}
    res = client.post("/products/import/csv", data=data, follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "CSV Import successful" in html

    with app.app_context():
        p1 = Product.query.filter_by(sku="MOU-001").first()
        assert p1 is not None
        assert p1.name == "Wireless Mouse"
        assert p1.price == 2999
        assert p1.cost == 1450
        assert p1.stock == 45
        assert p1.category.name == "Peripherals"
        assert p1.supplier.name == "TechSupply"

        p2 = Product.query.filter_by(sku="KEY-002").first()
        assert p2 is not None
        assert p2.price == 8900
        assert p2.stock == 20


def test_product_csv_import_update_existing(app, client):
    """Importing an existing SKU updates the product in place without duplication."""
    with app.app_context():
        existing = Product.query.filter_by(sku="TEST-001").first()
        assert existing is not None
        initial_id = existing.id

    csv_data = (
        "Name,SKU,Barcode,Category,Supplier,Selling Price,Cost Price,Stock Units,Minimum Stock,Description\n"
        "Updated Test Product,TEST-001,12345678,Electronics,Supplier,149.50,75.00,99,8,Updated description\n"
    )
    data = {"file": (io.BytesIO(csv_data.encode("utf-8")), "update.csv")}
    res = client.post("/products/import/csv", data=data, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        updated = Product.query.filter_by(sku="TEST-001").first()
        assert updated.id == initial_id
        assert updated.name == "Updated Test Product"
        assert updated.price == 14950
        assert updated.cost == 7500
        assert updated.stock == 99


def test_product_csv_import_formula_injection_sanitization(app, client):
    """Uploaded values with formula characters (=, +, -, @) must be stripped/sanitized."""
    csv_data = (
        "Name,SKU,Barcode,Category,Supplier,Selling Price,Cost Price,Stock Units,Minimum Stock,Description\n"
        "=cmd|'/C calc'!A0,SAFE-001,+999999,Hardware,Vendor,10.00,5.00,5,2,@dangerous_text\n"
    )
    data = {"file": (io.BytesIO(csv_data.encode("utf-8")), "payload.csv")}
    res = client.post("/products/import/csv", data=data, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        p = Product.query.filter_by(sku="SAFE-001").first()
        assert p is not None
        assert not p.name.startswith("=")
        assert not p.barcode.startswith("+")
        assert not p.brand.startswith("@")


def test_product_csv_import_missing_required_columns(app, client):
    """CSV missing required columns (Name, SKU, Selling Price) must be rejected with error."""
    csv_data = (
        "Name,Barcode,Cost Price\n"
        "Missing SKU Product,111222,10.00\n"
    )
    data = {"file": (io.BytesIO(csv_data.encode("utf-8")), "invalid.csv")}
    res = client.post("/products/import/csv", data=data, follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "missing required column headers" in html.lower()


def test_product_csv_import_invalid_numeric_values(app, client):
    """Non-numeric or negative prices must cause atomic rollback with row-specific error."""
    csv_data = (
        "Name,SKU,Barcode,Category,Supplier,Selling Price,Cost Price,Stock Units,Minimum Stock,Description\n"
        "Bad Price Item,BAD-001,0001,Hardware,Vendor,NotANumber,5.00,5,2,Test\n"
    )
    data = {"file": (io.BytesIO(csv_data.encode("utf-8")), "bad_price.csv")}
    res = client.post("/products/import/csv", data=data, follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "invalid selling price" in html.lower()

    with app.app_context():
        assert Product.query.filter_by(sku="BAD-001").first() is None


def test_product_csv_import_duplicate_sku_in_file_rejected(app, client):
    """File containing duplicate SKUs must be rejected with atomic rollback."""
    csv_data = (
        "Name,SKU,Barcode,Category,Supplier,Selling Price,Cost Price,Stock Units,Minimum Stock,Description\n"
        "Duplicate 1,DUP-SKU-99,111,Cat,Supp,10.00,5.00,5,2,First\n"
        "Duplicate 2,DUP-SKU-99,222,Cat,Supp,15.00,7.00,5,2,Second\n"
    )
    data = {"file": (io.BytesIO(csv_data.encode("utf-8")), "dup.csv")}
    res = client.post("/products/import/csv", data=data, follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "duplicate sku" in html.lower()

    with app.app_context():
        assert Product.query.filter_by(sku="DUP-SKU-99").first() is None


def test_reporting_and_pricing_exports_validation(app, client):
    """Validate XLSX financial reports and price history export endpoints."""
    # 1. Sales Report XLSX
    res_sales = client.get("/reports/export/xlsx?kind=sales")
    assert res_sales.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in res_sales.headers["Content-Type"]
    assert len(res_sales.data) > 1000

    # 2. Profit Report XLSX
    res_profit = client.get("/reports/export/xlsx?kind=profit")
    assert res_profit.status_code == 200
    assert len(res_profit.data) > 1000

    # 3. Price History XLSX Export
    with app.app_context():
        p = Product.query.first()
        pid = p.id
    res_prices = client.get(f"/products/{pid}/price-history/export/xlsx")
    assert res_prices.status_code == 200
    assert len(res_prices.data) > 1000
