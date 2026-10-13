"""Database-backed permission administration. Every mutation is audited."""

import hashlib
import re
from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    session,
    g,
    abort,
    current_app,
    redirect,
    url_for,
)
from models import (
    db,
    User,
    Role,
    Permission,
    RolePermission,
    UserPermissionGrant,
    UserPermissionDenial,
    EndpointPermission,
)
from services.permissions import resolve, ensure_recovery_operator, PUBLIC, PERSONAL
from services.core import audit

access = Blueprint("access", __name__)


def catalog_data():
    return [
        dict(id=p.id, key=p.key, name=p.name, category=p.category, action=p.action)
        for p in Permission.query.order_by(Permission.category, Permission.name)
    ]


def role_data(role):
    ids = sorted(
        r.permission_id for r in RolePermission.query.filter_by(role_id=role.id)
    )
    revision = hashlib.sha256(f"{role.id}:{role.name}:{ids}".encode()).hexdigest()
    return dict(id=role.id, name=role.name, permissions=ids, revision=revision)


def user_data(user):
    policy = resolve(user)
    return dict(
        id=user.id,
        name=user.name,
        role_id=user.role_id,
        version=user.version,
        active=user.active,
        **{k: sorted(v) for k, v in policy.items()},
    )


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description="A JSON object is required.")
    for key in ("permission_id", "role_id", "version"):
        if key in data and (type(data[key]) is not int or data[key] < 0):
            raise ValueError(f"{key} must be a nonnegative integer.")
    # Serialize policy edits so concurrent requests cannot overwrite newer policies.
    db.session.execute(db.text("BEGIN IMMEDIATE"))
    return data


def finish(message, users):
    db.session.flush()
    ensure_recovery_operator()
    for user in users:
        user.version += 1
    audit("Access policy changed", message)
    db.session.commit()
    if any(u.id == g.user.id for u in users):
        session["version"] = g.user.version
    g.pop("permission_keys", None)


@access.get("/settings/users/<int:uid>")
def editor(uid):
    user = db.get_or_404(User, uid)
    return render_template(
        "settings/permissions.html",
        title="User Permissions",
        person=user,
        policy=user_data(user),
        permissions=catalog_data(),
        roles=[role_data(r) for r in Role.query.order_by(Role.name)],
    )


@access.post("/api/users/<int:uid>/permissions")
def user_policy(uid):
    data = payload()
    user = db.get_or_404(User, uid)
    db.session.refresh(user)
    if data.get("version") != user.version:
        return jsonify(
            error="Permissions changed elsewhere. Refresh before editing."
        ), 409
    operation = data.get("operation")
    if operation == "role":
        if "role_id" not in data:
            raise ValueError("Select a role.")
        role = db.get_or_404(Role, data.get("role_id"))
        user.role_id = role.id
    elif operation == "reset":
        UserPermissionGrant.query.filter_by(user_id=uid).delete()
        UserPermissionDenial.query.filter_by(user_id=uid).delete()
    elif operation in ("grant", "deny", "remove"):
        if "permission_id" not in data:
            raise ValueError("Select a permission.")
        permission = db.get_or_404(Permission, data.get("permission_id"))
        for model in (UserPermissionGrant, UserPermissionDenial):
            model.query.filter_by(user_id=uid, permission_id=permission.id).delete()
        if operation != "remove":
            model = (
                UserPermissionGrant if operation == "grant" else UserPermissionDenial
            )
            db.session.add(model(user_id=uid, permission_id=permission.id))
    else:
        abort(400, description="Unknown permission operation.")
    finish(
        f"User {user.username}: {operation}; permission {data.get('permission_id', '')}",
        [user],
    )
    return jsonify(user_data(user))


@access.get("/settings/policies")
def policies_alias():
    """Backward-compatible alias redirecting /settings/policies to /settings/permissions."""
    return redirect(url_for("access.catalog"))


@access.route("/settings/permissions", methods=["GET", "POST"])
def catalog():
    if request.method == "GET":
        endpoints = sorted(
            {
                r.endpoint
                for r in current_app.url_map.iter_rules()
                if r.endpoint not in PUBLIC | PERSONAL
                and not r.endpoint.startswith("access.")
            }
        )
        return render_template(
            "settings/policies.html",
            title="Access Policies",
            permissions=catalog_data(),
            roles=[role_data(r) for r in Role.query.order_by(Role.name)],
            endpoints=endpoints,
            bindings=[
                dict(
                    endpoint=b.endpoint, method=b.method, permission_id=b.permission_id
                )
                for b in EndpointPermission.query.all()
            ],
        )
    data = payload()
    key = str(data.get("key", "")).strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}\.[a-z][a-z0-9_]{0,39}", key):
        raise ValueError("Use a permission key such as products.special_offer.")
    name, category = (
        str(data.get("name", "")).strip(),
        str(data.get("category", "")).strip(),
    )
    if not name or len(name) > 120 or not category or len(category) > 60:
        raise ValueError(
            "Enter a name (120 characters maximum) and category (60 maximum)."
        )
    db.session.add(
        Permission(key=key, name=name, category=category, action=key.split(".")[1])
    )
    audit("Create permission", key)
    db.session.commit()
    return jsonify(permissions=catalog_data()), 201


@access.post("/api/roles")
def roles():
    data = payload()
    name = str(data.get("name", "")).strip()
    if not name or len(name) > 50:
        raise ValueError("Role name must contain 1–50 characters.")
    role = Role(name=name)
    db.session.add(role)
    audit("Create role", name)
    db.session.commit()
    return jsonify(role_data(role)), 201


@access.post("/api/roles/<int:rid>/permissions")
def role_policy(rid):
    data = payload()
    role = db.get_or_404(Role, rid)
    if data.get("revision") != role_data(role)["revision"]:
        return jsonify(error="Role changed elsewhere. Refresh before editing."), 409
    ids = data.get("permissions")
    if not isinstance(ids, list) or any(type(i) is not int for i in ids):
        raise ValueError("Permissions must be a list of permission IDs.")
    available = {p.id for p in Permission.query.all()}
    if not set(ids).issubset(available):
        raise ValueError("Unknown permission.")
    RolePermission.query.filter_by(role_id=rid).delete()
    for pid in set(ids):
        db.session.add(RolePermission(role_id=rid, permission_id=pid))
    finish(
        f"Role {role.name}: {sorted(set(ids))}", User.query.filter_by(role_id=rid).all()
    )
    return jsonify(role_data(role))


@access.post("/api/permissions/bindings")
def bindings():
    data = payload()
    endpoint, method = data.get("endpoint"), data.get("method")
    valid = any(
        r.endpoint == endpoint and method in r.methods
        for r in current_app.url_map.iter_rules()
    )
    if (
        not valid
        or method not in ("GET", "POST")
        or endpoint in PUBLIC | PERSONAL
        or endpoint.startswith("access.")
    ):
        raise ValueError("Choose an existing business endpoint and supported method.")
    permission = db.get_or_404(Permission, data.get("permission_id"))
    key = (endpoint, method, permission.id)
    existing = db.session.get(EndpointPermission, key)
    if data.get("remove"):
        if existing:
            db.session.delete(existing)
    elif not existing:
        db.session.add(
            EndpointPermission(
                endpoint=endpoint, method=method, permission_id=permission.id
            )
        )
    audit(
        "Change endpoint policy",
        f"{endpoint} {method}: {permission.key}; remove={bool(data.get('remove'))}",
    )
    db.session.commit()
    return jsonify(ok=True)


@access.get("/backups")
def backups_page():
    from models import BackupLog

    logs = BackupLog.query.order_by(BackupLog.id.desc()).limit(20).all()
    return render_template(
        "settings/backups.html",
        title="Backup & Restore",
        backup_state=current_app.extensions["backups"].snapshot(),
        backup_logs=logs,
    )
