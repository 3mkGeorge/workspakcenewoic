"""Archived Products Center: list/restore/permanent-delete, incl. aliases."""

from test_app import app, client  # noqa: F401
from models import AuditLog, InventoryMovement, Product, db


def _archive(app, pid=1, actor="Admin"):
    with app.app_context():
        product = db.session.get(Product, pid)
        product.active = False
        db.session.add(
            AuditLog(
                user_id=1,
                actor=actor,
                action="Archive product",
                details=product.sku,
            )
        )
        db.session.commit()
        return product.id, product.sku


def test_list_shows_only_archived_with_attribution(app, client):
    assert client.get("/api/archived").json == {
        "total": 0,
        "currency": "EGP",
        "products": [],
    }
    pid, sku = _archive(app)
    for url in ("/api/archived", "/api/products/archived"):
        data = client.get(url).json
        assert data["total"] == 1, url
        (row,) = data["products"]
        assert row["id"] == pid and row["status"] == "ARCHIVED"
        assert row["archived_by"] == "Admin"
        assert row["sku"] == sku and row["stock"] == 10
    with app.app_context():
        assert Product.query.filter_by(active=False).count() == 1


def test_search_filter_sort(app, client):
    _archive(app)
    assert client.get("/api/products/archived?q=TEST-001").json["total"] == 1
    assert client.get("/api/products/archived?q=no-such-thing").json["total"] == 0
    assert client.get("/api/products/archived?q=12345678").json["total"] == 1
    assert client.get("/api/products/archived?category_id=1").json["total"] == 1
    assert client.get("/api/products/archived?category_id=999").json["total"] == 0
    assert client.get("/api/products/archived?supplier_id=1").json["total"] == 1
    for sort in ("newest", "oldest", "name"):
        assert (
            client.get(f"/api/products/archived?sort={sort}").json["total"] == 1
        )


def test_inventory_page_wires_center(client):
    html = client.get("/inventory").data.decode()
    for token in (
        "archived-products-btn",
        "archivedProductsModal",
        "Archived Products",
        "Manage products that have been archived.",
        "Products you archive will appear here.",
        "archived.js",
        "product-details-backdrop",
        "arch-delete-confirm",
        "arch-search",
    ):
        assert token in html, token


def test_restore_flow(app, client):
    pid, _sku = _archive(app)
    response = client.post(f"/api/products/{pid}/restore", json={})
    assert response.status_code == 200, response.json
    with app.app_context():
        assert db.session.get(Product, pid).active is True
        assert Product.query.filter_by(active=False).count() == 0
    assert client.get("/api/products/archived").json["total"] == 0
    blocked = client.post(f"/api/products/{pid}/restore", json={})
    assert blocked.status_code == 400


def test_permanent_delete_blocked_then_allowed(app, client):
    pid, _sku = _archive(app)
    with app.app_context():
        db.session.add(
            InventoryMovement(
                product_id=pid,
                quantity=-1,
                balance=9,
                cost=5000,
                kind="Damaged Items",
                reference="TEST",
                user_id=1,
            )
        )
        db.session.commit()
    blocked = client.delete(f"/api/products/{pid}/permanent")
    assert blocked.status_code == 400, blocked.json
    assert "inventory movement" in blocked.json["error"]
    with app.app_context():
        InventoryMovement.query.filter_by(product_id=pid).delete()
        db.session.commit()
    response = client.delete(f"/api/products/{pid}/permanent")
    assert response.status_code == 200, response.json
    with app.app_context():
        assert db.session.get(Product, pid) is None


def test_archive_permissions(client):
    client.post("/logout")
    assert client.get("/api/products/archived").status_code == 401
    client.post(
        "/login", data={"username": "cashier", "password": "test-password-123"}
    )
    assert client.get("/api/products/archived").status_code == 200
    assert client.post("/api/products/1/restore", json={}).status_code == 403
    assert client.delete("/api/products/1/permanent").status_code == 403
