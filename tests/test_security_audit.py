"""Comprehensive Automated Security Audit & Attack Vector Validation Suite.

Tests authorization enforcement, privilege escalation defenses, XSS escaping,
SQL injection immunities, and backup restore attack vectors (Zip Slip,
decompression bombs, malformed manifests).
"""

import io
import json
import zipfile
import pytest
from test_app import app, client  # noqa: F401
from models import db, User, Role, Product, Customer, Sale, Category, Supplier, UserPermissionDenial, Permission
from services.permissions import can, resolve


def test_unauthenticated_access_blocked(app):
    """Protected business routes must reject or redirect unauthenticated requests."""
    unauth_client = app.test_client()
    protected_urls = [
        "/",
        "/sales",
        "/products",
        "/inventory",
        "/inventory/adjust",
        "/purchases",
        "/settings",
        "/customers",
        "/suppliers",
        "/reports",
        "/api/pos/products",
    ]
    for url in protected_urls:
        res = unauth_client.get(url)
        if url.startswith("/api/"):
            assert res.status_code == 401, f"{url} allowed unauthenticated API access"
        else:
            assert res.status_code in (302, 401), f"{url} did not redirect unauthenticated request"
            if res.status_code == 302:
                assert "/login" in res.headers["Location"]


def test_cashier_privilege_escalation_blocked(app):
    """Cashier role must be strictly forbidden from administrative and configuration surfaces."""
    cashier_client = app.test_client()
    # Log in as cashier created in test_app fixture
    res_login = cashier_client.post("/login", data={"username": "cashier", "password": "test-password-123"})
    assert res_login.status_code == 302

    admin_get_routes = [
        "/settings",
        "/settings/users",
        "/settings/permissions",
    ]
    for route in admin_get_routes:
        res = cashier_client.get(route)
        assert res.status_code == 403, f"Cashier should not access {route}, got {res.status_code}"

    admin_post_routes = [
        "/settings/backup",
        "/settings/restore",
    ]
    for route in admin_post_routes:
        res = cashier_client.post(route)
        assert res.status_code == 403, f"Cashier should not POST {route}, got {res.status_code}"


def test_explicit_denial_beats_role_grant(app):
    """Verify hybrid authorization: explicit UserPermissionDenial overrides role grant."""
    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        perm = Permission.query.filter_by(key="products.delete").first()
        assert can("products.delete", admin) is True

        # Explicitly deny delete permission to this admin
        denial = UserPermissionDenial(user_id=admin.id, permission_id=perm.id)
        db.session.add(denial)
        db.session.commit()

        # Should now be denied
        assert can("products.delete", admin) is False

        # Cleanup
        db.session.delete(denial)
        db.session.commit()


def test_xss_payload_escaped_in_html(client, app):
    """XSS payloads in product names and customer names must be escaped, never rendered raw."""
    client.post("/login", data={"username": "admin", "password": "test-password-123"})

    payload_xss = '<script>alert("XSS-ATTACK")</script>'
    payload_img = '<img src="x" onerror="alert(1)">'

    with app.app_context():
        cat = Category.query.first()
        p = Product(
            name=f"Clean Name {payload_xss}",
            sku="XSS-SKU-001",
            category_id=cat.id,
            cost=1000,
            price=2000,
            stock=10,
            active=True,
        )
        c = Customer(
            name=f"Customer {payload_img}",
            phone="01000000000",
            active=True,
        )
        db.session.add_all([p, c])
        db.session.commit()

    res = client.get("/products")
    assert res.status_code == 200
    assert '<script>alert("XSS-ATTACK")</script>' not in res.text
    assert "&lt;script&gt;alert(&#34;XSS-ATTACK&#34;)&lt;/script&gt;" in res.text or "&lt;script&gt;" in res.text

    res_cust = client.get("/customers")
    assert res_cust.status_code == 200
    assert '<img src="x" onerror="alert(1)">' not in res_cust.text
    assert "&lt;img" in res_cust.text


def test_sql_injection_immunities(client):
    """SQL injection payloads in search and query parameters must be safely parameterized."""
    client.post("/login", data={"username": "admin", "password": "test-password-123"})

    sqli_payloads = [
        "' OR '1'='1",
        "'; DROP TABLE products; --",
        "admin'--",
        "1 UNION SELECT 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 --",
    ]

    for payload in sqli_payloads:
        # Search route
        res = client.get(f"/search?q={payload}")
        assert res.status_code == 200

        # Catalog filtering
        res_cat = client.get(f"/products?q={payload}&category_id={payload}")
        assert res_cat.status_code in (200, 400)

        # Reports filtering
        res_rep = client.get(f"/reports?kind=sales&from=2026-01-01&to=2026-10-01&customer_id={payload}")
        assert res_rep.status_code in (200, 400)


def test_backup_restore_zip_slip_rejected(tmp_path):
    """Backups with Zip Slip paths (e.g. ../../etc/passwd) must be rejected by archive verification."""
    from services.dual_backup import inspect_archive

    slip_zip = tmp_path / "slip.zip"
    with zipfile.ZipFile(slip_zip, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": "StorePro", "version": 1}))
        z.writestr("store.db", b"fake db")
        z.writestr("../../../malicious_file.txt", b"evil contents")

    with pytest.raises(ValueError, match="Unsafe archive member|Invalid backup members"):
        inspect_archive(slip_zip, full=False)


def test_backup_restore_unwhitelisted_executable_rejected(client, tmp_path):
    """Backups with executable files (.exe, .sh, .py) must be rejected."""
    from services.dual_backup import inspect_archive

    exe_zip = tmp_path / "exe.zip"
    with zipfile.ZipFile(exe_zip, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": "StorePro", "version": 1}))
        z.writestr("store.db", b"fake db")
        z.writestr("payload.exe", b"MZ\x90\x00...")

    with pytest.raises(ValueError, match="Unsafe archive member|Invalid backup members"):
        inspect_archive(exe_zip, full=False)

    # Also verify that restore with wrong password is immediately rejected with 400
    res = client.post(
        "/settings/restore",
        data={
            "password": "wrong-password",
            "confirm": "RESTORE",
        },
    )
    assert res.status_code == 400


def test_excel_formula_injection_sanitization(client, app):
    """Reports export must sanitize cells starting with =, +, -, @ to prevent spreadsheet command execution."""
    client.post("/login", data={"username": "admin", "password": "test-password-123"})

    # Add a product with a formula injection name
    with app.app_context():
        cat = Category.query.first()
        p = Product(
            name="=cmd|'/C calc'!A0",
            sku="FORMULA-001",
            category_id=cat.id,
            cost=1000,
            price=2000,
            stock=5,
            active=True,
        )
        db.session.add(p)
        db.session.commit()

    res = client.get("/reports/export/xlsx?kind=inventory")
    assert res.status_code == 200
    # Content must be binary Excel
    assert res.headers["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    
    # Load workbook and check cell value
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(res.data))
    sheet = wb.active
    values = [cell.value for row in sheet.iter_rows() for cell in row if cell.value]
    # In reporting.py line 88: if v.startswith(("=", "+", "-", "@")): row[i] = "'" + v
    # Ensure formula injection was neutralized with single quote prefix
    assert any(str(v).startswith("'=") for v in values), "Formula injection was not sanitized with single quote prefix"
