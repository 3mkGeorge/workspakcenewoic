"""Hybrid authorization: explicit denial > explicit grant > role assignment.

There is no administrator bypass. All application routes are checked centrally;
unknown business routes fail closed until assigned a database-backed policy.
"""

from flask import abort, g, request, has_request_context
from sqlalchemy import event, select
from models import (
    db,
    Role,
    User,
    Permission,
    RolePermission,
    UserPermissionGrant,
    UserPermissionDenial,
    EndpointPermission,
)

CATEGORIES = (
    "Dashboard",
    "Sales",
    "Products",
    "Inventory",
    "Purchases",
    "Customers",
    "Suppliers",
    "Reports",
    "Backups",
    "Settings",
    "Users",
)
ACTIONS = {
    "view": "View",
    "create": "Create",
    "edit": "Edit",
    "delete": "Delete",
    "export": "Export",
    "import": "Import",
    "approve": "Approve",
    "print": "Print",
    "refund": "Refund",
    "price_change": "Price Change",
    "stock_adjustment": "Stock Adjustment",
}
PUBLIC = {
    "static",
    "auth.setup",
    "auth.login",
    "backup_admin.recovery",
    "backup_admin.recovery_status",
    "healthz",
    "main.debug_crash",
}
PERSONAL = {"auth.logout", "admin.account", "main.search", "main.notifications"}
STATIC = {
    "main.dashboard": "dashboard.view",
    "transactions.sales": "sales.view",
    "transactions.sale_detail": "sales.view",
    "transactions.pickup_status": "sales.edit",
    "transactions.invoice": "sales.print",
    "transactions.purchases": "purchases.view",
    "transactions.purchase_form": "purchases.create",
    "catalog.delete_product": "products.delete",
    "catalog.customer_profile": "customers.view",
    "catalog.adjust": "inventory.stock_adjustment",
    "catalog.movements": "inventory.view",
    "pos.products": "products.view",
    "pos.shortcuts": "sales.view",
    "pos.customers": "customers.view",
    "pos.new_customer": "customers.create",
    "price_history.history": "products.view",
    "price_history.alerts": "products.edit",
    "price_history.export": "products.export",
    "product_media.list_images": "products.view",
    "product_media.preview": "products.view",
    "product_media.upload": "products.edit",
    "product_media.reorder": "products.edit",
    "product_media.make_primary": "products.edit",
    "product_media.delete": "products.edit",
    "product_media.replace": "products.edit",
    "categories.list_categories": "products.view",
    "categories.get_category": "products.view",
    "categories.create_category": "products.create",
    "catalog.api_create_supplier": "suppliers.create",
    "catalog.adjust_price": "products.price_change",
    "categories.update_category": "products.edit",
    "categories.merge_categories": "products.delete",
    "categories.delete_category": "products.delete",
    "categories.purge_category": "products.delete",
    "archive.list_archived": "inventory.view",
    "archive.archived_details": "inventory.view",
    "archive.restore_archived": "products.edit",
    "archive.delete_archived": "products.delete",
    "shipping.orders": "sales.view",
    "shipping.details": "sales.view",
    "shipping.label": "sales.view",
    "shipping.order_detail": "sales.view",
    "shipping.order_customer": "sales.view",
    "shipping.delete_order": "sales.delete",
    "orders_hub.hub": "sales.view",
    "shipping.last_address": "sales.view",
    "shipping.update_order": "sales.edit",
    "shipping.transition": "sales.edit",
    "reporting.reports": "reports.view",
    "admin.backup": "backups.create",
    "admin.download_backup": "backups.export",
    "admin.restore": "backups.approve",
    "admin.audit_logs": "settings.view",
    "backup_admin.status": "backups.view",
    "backup_admin.logs": "backups.view",
    "backup_admin.save_paths": "backups.edit",
    "backup_admin.test_paths": "backups.edit",
    "backup_admin.reset_defaults": "backups.edit",
    "access.editor": "users.view",
    "access.user_policy": "users.permissions",
    "access.catalog": "users.permissions",
    "access.policies_alias": "users.permissions",
    "access.roles": "users.permissions",
    "access.role_policy": "users.permissions",
    "access.bindings": "users.permissions",
    "access.backups_page": "backups.view",
    "admin.export_audit_logs": "settings.view",
    "admin.telemetry": "settings.view",
    "admin.run_maintenance": "settings.edit",
    "admin.verify_backups_now": "backups.approve",
    "website.page": "settings.view",
    "website.sync_now": "settings.edit",
    "website.publish": "products.edit",
    "catalog.export_products_csv": "products.export",
    "catalog.import_products_csv": "products.import",
}


def defaults(role, keys):
    if role == "Admin":
        return set(keys)
    if role == "Manager":
        return {
            k for k in keys if k.split(".")[0] not in {"settings", "users", "backups"}
        }
    if role == "Cashier":
        return {
            "dashboard.view",
            "sales.view",
            "sales.create",
            "sales.print",
            "products.view",
            "inventory.view",
            "purchases.view",
            "customers.view",
            "customers.create",
            "customers.edit",
            "suppliers.view",
        }
    return set()


def install_schema(connection):
    """Run inside the migration transaction; never reseed an existing policy."""
    from sqlalchemy.schema import CreateTable, CreateIndex
    from sqlalchemy.dialects.sqlite import dialect

    tables = {
        r[0]
        for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    fresh = "permissions" not in tables
    for model in (
        Permission,
        RolePermission,
        UserPermissionGrant,
        UserPermissionDenial,
        EndpointPermission,
    ):
        if model.__tablename__ not in tables:
            connection.execute(
                str(CreateTable(model.__table__).compile(dialect=dialect()))
            )
            for index in model.__table__.indexes:
                connection.execute(str(CreateIndex(index).compile(dialect=dialect())))
    if not fresh:
        return
    definitions = [
        (f"{c.lower()}.{a}", f"{label} {c}", c, a)
        for c in CATEGORIES
        for a, label in ACTIONS.items()
    ]
    definitions.append(
        ("users.permissions", "Manage Access Policies", "Users", "permissions")
    )
    connection.executemany(
        "INSERT INTO permissions(key,name,category,action) VALUES (?,?,?,?)",
        definitions,
    )
    permissions = dict(connection.execute("SELECT key,id FROM permissions"))
    for rid, name in (
        connection.execute("SELECT id,name FROM roles") if "roles" in tables else []
    ):
        connection.executemany(
            "INSERT INTO role_permissions(role_id,permission_id) VALUES (?,?)",
            [(rid, permissions[k]) for k in defaults(name, permissions)],
        )


def seed_empty_catalog():
    # Fresh databases are created by create_all; migrate the empty catalog explicitly.
    if Permission.query.first():
        return
    for category in CATEGORIES:
        for action, label in ACTIONS.items():
            db.session.add(
                Permission(
                    key=f"{category.lower()}.{action}",
                    name=f"{label} {category}",
                    category=category,
                    action=action,
                )
            )
    db.session.add(
        Permission(
            key="users.permissions",
            name="Manage Access Policies",
            category="Users",
            action="permissions",
        )
    )
    db.session.flush()
    rows = {p.key: p.id for p in Permission.query.all()}
    for role in Role.query.all():
        for key in defaults(role.name, rows):
            if not db.session.get(RolePermission, (role.id, rows[key])):
                db.session.add(RolePermission(role_id=role.id, permission_id=rows[key]))
    db.session.commit()


@event.listens_for(Role, "after_insert")
def new_role_defaults(mapper, connection, role):
    rows = dict(connection.execute(select(Permission.key, Permission.id)).all())
    values = [
        {"role_id": role.id, "permission_id": rows[k]}
        for k in defaults(role.name, rows)
    ]
    if values:
        connection.execute(RolePermission.__table__.insert(), values)


def resolve(user):
    if not user or not user.active:
        return {"role": set(), "grants": set(), "denials": set(), "effective": set()}

    def keys(model, condition):
        return set(
            db.session.scalars(
                select(Permission.key)
                .join(model, model.permission_id == Permission.id)
                .where(condition)
            )
        )

    role = keys(RolePermission, RolePermission.role_id == user.role_id)
    grants = keys(UserPermissionGrant, UserPermissionGrant.user_id == user.id)
    denials = keys(UserPermissionDenial, UserPermissionDenial.user_id == user.id)
    return {
        "role": role,
        "grants": grants,
        "denials": denials,
        "effective": (role | grants) - denials,
    }


def can(key, user=None):
    if user is not None:
        return key in resolve(user)["effective"]
    if not has_request_context() or not getattr(g, "user", None):
        return False
    if not hasattr(g, "permission_keys"):
        g.permission_keys = resolve(g.user)["effective"]
    return key in g.permission_keys


def require(key):
    if not can(key):
        abort(403, description=f"Permission required: {key}")


def required_action():
    endpoint = request.endpoint
    args = request.view_args or {}
    if endpoint in STATIC:
        return STATIC[endpoint]
    if endpoint == "catalog.products":
        return "inventory.view" if request.path == "/inventory" else "products.view"
    if endpoint == "catalog.product_form":
        return "products.edit" if args.get("pid") else "products.create"
    if endpoint == "transactions.sale_form":
        return "sales.edit" if args.get("sid") else "sales.create"
    if endpoint == "transactions.sale_action":
        action = args.get("action")
        return "sales." + action if action in ("refund", "delete") else None
    if endpoint == "transactions.purchase_action":
        return {
            "receive": "purchases.approve",
            "process": "purchases.edit",
            "cancel": "purchases.delete",
        }.get(args.get("action"))
    if endpoint in (
        "catalog.contacts",
        "catalog.save_contact",
        "catalog.delete_contact",
    ):
        category = args.get("kind")
        if category not in ("customers", "suppliers", "categories"):
            abort(404)
        category = "products" if category == "categories" else category
        action = (
            "view"
            if endpoint == "catalog.contacts"
            else "delete"
            if endpoint == "catalog.delete_contact"
            else "edit"
            if request.form.get("id")
            else "create"
        )
        return category + "." + action
    if endpoint in ("pos.quote", "pos.save"):
        payload = request.get_json(silent=True)
        return (
            "sales.edit"
            if isinstance(payload, dict) and payload.get("sale_id") is not None
            else "sales.create"
        )
    if endpoint == "reporting.export":
        category = request.args.get("kind", "sales")
        if category == "profit":
            category = "reports"
        if category == "shipping":
            category = "sales"
        if category not in {
            "sales",
            "purchases",
            "inventory",
            "products",
            "customers",
            "suppliers",
            "reports",
        }:
            abort(400)
        return category + ".export"
    if endpoint == "admin.settings_page":
        return "settings.edit" if request.method == "POST" else "settings.view"
    if endpoint == "admin.users":
        return (
            "users.view"
            if request.method == "GET"
            else "users.edit"
            if request.form.get("id")
            else "users.create"
        )
    if endpoint == "website.listing":
        return "products.edit" if request.method == "POST" else "products.view"
    if endpoint == "admin.expenses":
        return "reports.create" if request.method == "POST" else "reports.view"
    return None


def enforce_request():
    if request.endpoint in PUBLIC or request.endpoint is None:
        return
    if request.endpoint in PERSONAL:
        return  # Own-account operations; search/notifications filter each data source.
    key = required_action()
    method = "GET" if request.method == "HEAD" else request.method
    extra = list(
        db.session.scalars(
            select(Permission.key)
            .join(EndpointPermission)
            .where(
                EndpointPermission.endpoint == request.endpoint,
                EndpointPermission.method == method,
            )
        )
    )
    if key is None and not extra:
        abort(403, description="This action has no access policy.")
    for required in ([key] if key else []) + extra:
        require(required)


def ensure_recovery_operator():
    # Prevent an accidental permanent lockout, independently of role names.
    for user in User.query.filter_by(active=True).all():
        if {"users.permissions", "backups.approve"}.issubset(
            resolve(user)["effective"]
        ):
            return
    raise ValueError(
        "Keep at least one active user with Manage Access Policies and Approve Backups for recovery."
    )


def guard_user_management(target, role=None):
    if can("users.permissions"):
        return
    own = resolve(g.user)["effective"]
    target_keys = set()
    if target:
        target_keys = set(
            db.session.scalars(
                select(Permission.key)
                .join(RolePermission)
                .where(RolePermission.role_id == target.role_id)
            )
        )
        target_keys |= set(
            db.session.scalars(
                select(Permission.key)
                .join(UserPermissionGrant)
                .where(UserPermissionGrant.user_id == target.id)
            )
        )
        target_keys -= set(
            db.session.scalars(
                select(Permission.key)
                .join(UserPermissionDenial)
                .where(UserPermissionDenial.user_id == target.id)
            )
        )
    if target and not target_keys.issubset(own):
        abort(
            403,
            description="Manage Access Policies is required to manage a more privileged account.",
        )
    if role:
        keys = set(
            db.session.scalars(
                select(Permission.key)
                .join(RolePermission)
                .where(RolePermission.role_id == role.id)
            )
        )
        if not keys.issubset(own):
            abort(403, description="You cannot assign privileges you do not hold.")
