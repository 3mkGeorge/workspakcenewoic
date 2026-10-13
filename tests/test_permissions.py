from test_app import app, client
from models import (
    db,
    User,
    Permission,
    RolePermission,
    UserPermissionGrant,
    UserPermissionDenial,
)
from services.permissions import resolve, can


def permission(app, key):
    with app.app_context():
        return Permission.query.filter_by(key=key).one().id


def change(app, client, key, operation, uid=3):
    with app.app_context():
        version = db.session.get(User, uid).version
    return client.post(
        f"/api/users/{uid}/permissions",
        json=dict(
            operation=operation, permission_id=permission(app, key), version=version
        ),
    )


def login(app, name="cashier"):
    c = app.test_client()
    assert (
        c.post(
            "/login", data={"username": name, "password": "test-password-123"}
        ).status_code
        == 302
    )
    return c


def test_editor_pages(client):
    for url in ["/settings/users/3", "/settings/permissions", "/backups"]:
        assert client.get(url).status_code == 200


def test_hybrid_example(app, client):
    assert change(app, client, "reports.view", "grant").status_code == 200
    assert change(app, client, "sales.export", "grant").status_code == 200
    assert change(app, client, "sales.refund", "deny").status_code == 200
    c = login(app)
    assert c.get("/reports").status_code == 200
    assert c.get("/reports/export/xlsx?kind=sales").status_code == 200
    assert c.post("/sales/1/refund").status_code == 403
    with app.app_context():
        result = resolve(db.session.get(User, 3))
        assert {
            "sales.create",
            "sales.print",
            "reports.view",
            "sales.export",
        } <= result["effective"]
        assert "sales.refund" not in result["effective"]


def test_denial_beats_both_and_admin(app, client):
    pid = permission(app, "products.view")
    with app.app_context():
        db.session.add(UserPermissionGrant(user_id=1, permission_id=pid))
        db.session.add(UserPermissionDenial(user_id=1, permission_id=pid))
        db.session.commit()
        assert not can("products.view", db.session.get(User, 1))
        assert not can("not.registered", db.session.get(User, 1))
    assert client.get("/products").status_code == 403
    assert client.get("/api/pos/products").status_code == 403
    assert b"Test Product" not in client.get("/search?q=Test").data


def test_reset_remove_conflict_and_revocation(app, client):
    c = login(app)
    response = change(app, client, "reports.view", "grant")
    assert response.status_code == 200
    assert c.get("/reports").status_code == 302  # invalidated older session
    old = response.json["version"]
    assert change(app, client, "reports.view", "remove").status_code == 200
    assert (
        client.post(
            "/api/users/3/permissions", json={"version": old, "operation": "reset"}
        ).status_code
        == 409
    )
    assert change(app, client, "sales.create", "deny").status_code == 200
    response = change(app, client, "reports.view", "reset")
    assert response.status_code == 200
    assert response.json["grants"] == response.json["denials"] == []


def test_cannot_lock_out_last_operator(app, client):
    assert change(app, client, "users.permissions", "deny", 1).status_code == 400
    assert change(app, client, "backups.approve", "deny", 1).status_code == 400
    assert client.get("/settings/permissions").status_code == 200


def test_unprivileged_policy_calls(app, client):
    c = login(app)
    assert c.get("/settings/users/1").status_code == 403
    for path in [
        "/api/users/1/permissions",
        "/api/roles",
        "/api/roles/1/permissions",
        "/api/permissions/bindings",
        "/settings/permissions",
    ]:
        assert c.post(path, json={}).status_code == 403


def test_future_permission_binding(app, client):
    response = client.post(
        "/settings/permissions",
        json={
            "key": "products.review",
            "name": "Review Products",
            "category": "Products",
        },
    )
    assert response.status_code == 201
    pid = permission(app, "products.review")
    assert (
        client.post(
            "/api/permissions/bindings",
            json={
                "endpoint": "catalog.products",
                "method": "GET",
                "permission_id": pid,
            },
        ).status_code
        == 200
    )
    assert client.get("/products").status_code == 403  # admin has no implicit grant
    assert change(app, client, "products.review", "grant", 1).status_code == 200
    assert client.get("/products").status_code == 200
    assert (
        client.post(
            "/api/permissions/bindings",
            json={
                "endpoint": "access.user_policy",
                "method": "POST",
                "permission_id": pid,
            },
        ).status_code
        == 400
    )


def test_custom_role_and_overrides(app, client):
    response = client.post("/api/roles", json={"name": "Auditor"})
    assert response.status_code == 201
    role = response.json
    assert not role["permissions"]
    response = client.post(
        f"/api/roles/{role['id']}/permissions",
        json={
            "revision": role["revision"],
            "permissions": [permission(app, "reports.view")],
        },
    )
    assert response.status_code == 200
    change(app, client, "reports.view", "deny")
    with app.app_context():
        version = db.session.get(User, 3).version
    response = client.post(
        "/api/users/3/permissions",
        json={"version": version, "operation": "role", "role_id": role["id"]},
    )
    assert response.status_code == 200
    assert "reports.view" in response.json["role"]
    assert "reports.view" not in response.json["effective"]


def test_self_policy_session_remains_valid(app, client):
    assert change(app, client, "sales.refund", "deny", 1).status_code == 200
    assert client.get("/settings/users/1").status_code == 200
    assert client.post("/sales/1/refund").status_code == 403


def test_price_change_requires_specific_permission(app, client):
    change(app, client, "products.price_change", "deny", 1)
    response = client.post(
        "/products/1/edit",
        data={
            "name": "Test Product",
            "sku": "TEST-001",
            "barcode": "12345678",
            "category_id": "1",
            "supplier_id": "1",
            "price": "120",
            "cost": "50",
            "minimum": "5",
        },
    )
    assert response.status_code == 403
    with app.app_context():
        from models import Product

        assert db.session.get(Product, 1).price == 10000


def test_migration_preserves_existing_policies(app, client):
    from services.migrations import upgrade_sqlite

    assert change(app, client, "products.delete", "deny", 1).status_code == 200
    with app.app_context():
        path = db.engine.url.database
        before = resolve(db.session.get(User, 1))
        db.session.remove()
        upgrade_sqlite(path)
        upgrade_sqlite(path)
        assert resolve(db.session.get(User, 1)) == before


def test_csrf_and_malformed_policies(app, client):
    assert (
        client.post(
            "/api/users/3/permissions", json={"operation": "role", "role_id": []}
        ).status_code
        == 400
    )
    app.config["WTF_CSRF_ENABLED"] = True
    assert (
        client.post(
            "/api/users/3/permissions", json={"operation": "reset", "version": 1}
        ).status_code
        == 400
    )


def test_delegated_user_editor_cannot_escalate(app, client):
    assert change(app, client, "users.edit", "grant").status_code == 200
    c = login(app)
    response = c.post(
        "/settings/users",
        data={
            "id": "1",
            "role_id": "1",
            "name": "Admin",
            "username": "admin",
            "active": "1",
            "password": "new-password-123",
        },
    )
    assert response.status_code == 403


def test_denied_backup_settings_and_receiving(app, client):
    assert change(app, client, "backups.edit", "deny", 1).status_code == 200
    from services.core import DEFAULTS

    data = DEFAULTS.copy()
    data["backup_retention"] = "20"
    assert client.post("/settings", data=data).status_code == 403
    assert change(app, client, "purchases.approve", "deny", 1).status_code == 200
    assert client.post("/purchases/1/receive").status_code == 403
