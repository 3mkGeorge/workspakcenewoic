import time
from collections import defaultdict
from flask import (
    Blueprint,
    g,
    render_template,
    request,
    redirect,
    url_for,
    session,
    current_app,
    flash,
)
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Role, now
from services.core import required, audit


def landing():
    from services.permissions import can

    return next(
        (
            url
            for key, url in [
                ("dashboard.view", "/"),
                ("sales.view", "/sales"),
                ("products.view", "/products"),
                ("inventory.view", "/inventory"),
                ("purchases.view", "/purchases"),
                ("customers.view", "/customers"),
                ("suppliers.view", "/suppliers"),
                ("reports.view", "/reports"),
                ("backups.view", "/backups"),
                ("users.view", "/settings/users"),
                ("settings.view", "/settings"),
            ]
            if can(key)
        ),
        "/account",
    )


auth = Blueprint("auth", __name__)
attempts = defaultdict(list)


def password(value):
    if len(value or "") < 12 or len(value) > 128:
        raise ValueError("Use a password with 12 to 128 characters.")
    return generate_password_hash(value)


@auth.route("/setup", methods=["GET", "POST"])
def setup():
    if User.query.first():
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        roles = [Role(name=n) for n in ("Admin", "Manager", "Cashier")]
        db.session.add_all(roles)
        db.session.flush()
        user = User(
            name=required(request.form.get("name"), "Name", 100),
            username=required(request.form.get("username"), "Username", 80).lower(),
            password_hash=password(request.form.get("password")),
            role_id=roles[0].id,
        )
        db.session.add(user)
        audit("Initial setup", "Administrator created")
        db.session.commit()
        flash("Your administrator account is ready. Please sign in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth.html", setup=True)


@auth.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(landing())
    if request.method == "POST":
        raw_username = request.form.get("username", "")
        username = raw_username.strip().lower() if isinstance(raw_username, str) else ""
        key = f"{request.remote_addr}:{username}"
        attempts[key] = [v for v in attempts[key] if time.monotonic() - v < 300]
        if len(attempts[key]) >= 8:
            return render_template(
                "auth.html",
                error="Too many attempts. Wait five minutes before trying again.",
            ), 429
        attempts[key].append(time.monotonic())
        user = User.query.filter_by(username=username).first()
        valid = check_password_hash(
            user.password_hash
            if user
            else generate_password_hash("unavailable-account"),
            request.form.get("password", ""),
        )
        if user and user.active and valid:
            session.clear()
            session.update(
                user_id=user.id,
                version=user.version,
                epoch=current_app.config["AUTH_EPOCH"],
                last_seen=now().timestamp(),
            )
            g.user = user
            audit("Login", "Local session started")
            db.session.commit()
            attempts.pop(key, None)
            return redirect(landing())
        return render_template(
            "auth.html", error="Incorrect username or password."
        ), 401
    return render_template("auth.html")


@auth.post("/logout")
def logout():
    audit("Logout", "Local session ended")
    db.session.commit()
    session.clear()
    return redirect(url_for("auth.login"))
